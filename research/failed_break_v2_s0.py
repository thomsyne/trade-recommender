"""Return-blind S0 preparation for the forward-only failed-break v2 strategy.

This module deliberately owns no S1 path.  It reuses the accepted S0
calculation primitives without changing the v1 implementation or treating the
accepted v1 JobRun as v2 evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from django.db import transaction
from django.db.models import Q

from market.models import Candle, DatasetVersion, IngestionRun, Instrument
from market.provider_observed_acquisition import REPLACEMENT_REGISTRATION_IDENTITY
from market.services import assert_dataset_window_usable, candle_completion
from research.failed_break_detector_v2 import validate_registered_successor
from research.failed_break_detector_v2_governance import (
    ARTIFACT_SHA256 as DETECTOR_ARTIFACT_SHA256,
)
from research.failed_break_detector_v2_governance import (
    load_v2_policy,
)
from research.models import JobRun, StrategyDefinition, StrategyParameterManifest, StrategyVersion
from research.provider_observed import contract_for_dataset, inventory_timestamps, inventory_window
from research.signal_count import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    FROZEN_INSTRUMENTS,
    PHASE1_MANIFEST_SHA256,
    PHASE1_SPEC_SHA256,
    PIPETTES,
    _session_label,
    _validate_dataset_contract,
    development_candle_range,
    generate_spread_ceilings,
    stable_hash,
)

V2_S0_IDENTITY = "failed-break-return-blind-s0-v2"
V2_S0_CONFIGURATION_IDENTITY = "failed-break-v2-s0-configuration-v1"
V2_S0_REPORT_IDENTITY = "failed-break-v2-s0-report-v1"
V2_S0_JOB_NAME = "failed-break-signal-count-s0-v2"
V2_S0_STRATEGY_DEFINITION = "top-down-failed-break-continuation"
V2_S0_DATASET_ID = 3
V2_S0_AS_OF = datetime(2019, 1, 1, 4, tzinfo=UTC)
V2_S0_MAXIMUM_OBSERVATIONS = 1_000_000
V2_S0_PRICE_FIELDS = frozenset({"instrument__code", "timestamp", "bid_open", "ask_open"})


class V2S0Error(ValueError):
    """The v2 S0 preregistration, evidence, or execution boundary failed closed."""


@dataclass(frozen=True, slots=True)
class V2S0Output:
    identity: str
    stage: str
    numerical_evidence: dict
    configuration_sha256: str
    report_sha256: str = field(init=False)

    def __post_init__(self):
        if self.identity != V2_S0_REPORT_IDENTITY or self.stage != "S0":
            raise V2S0Error("v2 S0 report identity changed")
        object.__setattr__(
            self,
            "report_sha256",
            stable_hash(
                {
                    "identity": self.identity,
                    "stage": self.stage,
                    "numerical_evidence": self.numerical_evidence,
                    "configuration_sha256": self.configuration_sha256,
                }
            ),
        )

    def as_dict(self) -> dict:
        return asdict(self)


def _strategy_values(preregistration: dict) -> dict:
    strategy = preregistration["strategy"]
    return {
        "version": strategy["identity"],
        "detector_version": strategy["detector_identity"],
        "data_identity": strategy["data_identity"],
        "event_identity": strategy["event_identity"],
        "execution_identity": strategy["execution_identity"],
        "cost_identity": strategy["cost_identity"],
        "portfolio_identity": strategy["portfolio_identity"],
        "pair_metadata": strategy["pair_metadata"],
        "timeframe_metadata": strategy["timeframe_metadata"],
        "content_hash": strategy["content_sha256"],
    }


def validate_v2_strategy(strategy: StrategyVersion, preregistration: dict) -> None:
    if strategy.definition.key != V2_S0_STRATEGY_DEFINITION:
        raise V2S0Error("v2 S0 strategy definition changed")
    expected = _strategy_values(preregistration)
    if any(getattr(strategy, field) != value for field, value in expected.items()):
        raise V2S0Error("v2 S0 strategy identity or content changed")
    try:
        parameter = strategy.strategyparametermanifest
    except StrategyParameterManifest.DoesNotExist as error:
        raise V2S0Error("v2 S0 strategy parameter binding is missing") from error
    if (
        parameter.payload != load_v2_policy()
        or parameter.sha256 != DETECTOR_ARTIFACT_SHA256
        or parameter.phase1_spec_hash != PHASE1_SPEC_SHA256
        or parameter.phase1_manifest_hash != PHASE1_MANIFEST_SHA256
    ):
        raise V2S0Error("v2 S0 strategy parameter binding changed")


def _create_v2_strategy(preregistration: dict) -> StrategyVersion:
    definition = StrategyDefinition.objects.filter(key=V2_S0_STRATEGY_DEFINITION).get()
    expected = _strategy_values(preregistration)
    collisions = StrategyVersion.objects.filter(
        Q(definition=definition, version=expected["version"])
        | Q(content_hash=expected["content_hash"])
    )
    if collisions.exists():
        raise V2S0Error("pre-existing v2 strategy state makes the S0 operation non-pristine")
    strategy = StrategyVersion.objects.create(definition=definition, **expected)
    StrategyParameterManifest.objects.create(
        strategy_version=strategy,
        payload=load_v2_policy(),
        sha256=DETECTOR_ARTIFACT_SHA256,
        phase1_spec_hash=PHASE1_SPEC_SHA256,
        phase1_manifest_hash=PHASE1_MANIFEST_SHA256,
    )
    return strategy


def validate_v2_s0_prerequisites(
    *, dataset: DatasetVersion, strategy: StrategyVersion, as_of: datetime
) -> tuple[dict, object, dict]:
    from research.failed_break_v2_s0_governance import load_v2_s0_preregistration

    preregistration = load_v2_s0_preregistration()
    if as_of != V2_S0_AS_OF:
        raise V2S0Error("v2 S0 as-of changed")
    if dataset.pk != V2_S0_DATASET_ID:
        raise V2S0Error("v2 S0 requires accepted dataset id 3")
    contract = contract_for_dataset(dataset)
    if contract is None:
        raise V2S0Error("v2 S0 requires the accepted provider-observed contract")
    try:
        validate_registered_successor(dataset, contract)
    except ValueError as error:
        raise V2S0Error("v2 S0 dataset or registration identity changed") from error

    dataset_binding = preregistration["dataset"]
    registration = dataset.registration
    if (
        dataset.name != dataset_binding["name"]
        or dataset.version != dataset_binding["version"]
        or dataset.manifest_sha256 != dataset_binding["manifest_sha256"]
        or contract.identity != dataset_binding["effective_data_identity"]
        or contract.sha256 != dataset_binding["contract_sha256"]
        or contract.global_semantic_inventory_sha256
        != dataset_binding["global_semantic_inventory_sha256"]
        or registration.configuration_sha256 != dataset_binding["registration_configuration_sha256"]
        or registration.report_sha256 != dataset_binding["registration_report_sha256"]
        or preregistration["registration_identity"] != REPLACEMENT_REGISTRATION_IDENTITY
    ):
        raise V2S0Error("v2 S0 preregistered dataset binding changed")

    lineage = preregistration["immutable_v1_data_lineage"]
    lineage_strategy = contract.strategy_version
    if (
        lineage_strategy.version != lineage["strategy_identity"]
        or lineage_strategy.detector_version != lineage["detector_identity"]
        or lineage_strategy.content_hash != lineage["strategy_content_sha256"]
        or lineage_strategy.data_identity != lineage["strategy_data_identity"]
        or strategy.pk == lineage_strategy.pk
    ):
        raise V2S0Error("immutable dataset lineage no longer resolves to the accepted v1 strategy")
    validate_v2_strategy(strategy, preregistration)
    ranges = _validate_dataset_contract(dataset, lineage_strategy, as_of)
    return ranges, contract, preregistration


def derive_v2_s0_numerical_evidence(
    *,
    dataset: DatasetVersion,
    ranges_by_instrument: dict,
    contract,
    as_of: datetime,
    maximum_observations: int,
) -> dict:
    """Independently derive S0 values using only sealed membership and H1 opens."""
    if as_of != V2_S0_AS_OF or maximum_observations != V2_S0_MAXIMUM_OBSERVATIONS:
        raise V2S0Error("v2 S0 execution bounds changed")
    instruments = {
        instrument.code: instrument
        for instrument in Instrument.objects.filter(code__in=ranges_by_instrument)
    }
    if set(instruments) != FROZEN_INSTRUMENTS:
        raise V2S0Error("v2 S0 instrument registry is incomplete")

    row_counts: dict[str, dict[str, int]] = {}
    missingness: dict[str, dict[str, int]] = {}
    development_ranges_by_instrument = {}
    for code, ranges in ranges_by_instrument.items():
        instrument = instruments[code]
        development_ranges = tuple(
            development_candle_range(required, contract=contract, instrument=code)
            for required in ranges
        )
        development_ranges_by_instrument[code] = development_ranges
        assert_dataset_window_usable(dataset, instrument, development_ranges, as_of)
        row_counts[code] = {}
        missingness[code] = {}
        for required in development_ranges:
            expected = len(
                inventory_window(contract, code, required.granularity, required.start, required.end)
            )
            observed = Candle.objects.filter(
                dataset_version=dataset,
                instrument=instrument,
                granularity=required.granularity,
                timestamp__gte=required.start,
                timestamp__lt=required.end,
                complete=True,
                ingestion_run__dataset_version=dataset,
                ingestion_run__status=IngestionRun.Status.SUCCEEDED,
            ).count()
            row_counts[code][required.granularity] = observed
            missingness[code][required.granularity] = expected - observed
            if observed != expected:
                raise V2S0Error("v2 S0 row-count audit found incomplete dataset coverage")

    development_start = DEVELOPMENT_START.astimezone(UTC)
    development_end = DEVELOPMENT_END.astimezone(UTC)
    opening_queries = []
    for code, ranges in development_ranges_by_instrument.items():
        h1_range = next(required for required in ranges if required.granularity == "H1")
        timestamps = tuple(
            timestamp
            for timestamp in inventory_window(contract, code, "H1", h1_range.start, h1_range.end)
            if development_start <= candle_completion(timestamp, "H1", contract) < development_end
        )
        opening_queries.append(
            Candle.objects.filter(
                dataset_version=dataset,
                instrument=instruments[code],
                granularity="H1",
                timestamp__in=timestamps,
                complete=True,
                ingestion_run__dataset_version=dataset,
                ingestion_run__status=IngestionRun.Status.SUCCEEDED,
            ).values(*sorted(V2_S0_PRICE_FIELDS))
        )
    if sum(query.count() for query in opening_queries) > maximum_observations:
        raise V2S0Error("v2 S0 observation bound would truncate the registered audit")

    pair_spreads = {code: [] for code in sorted(FROZEN_INSTRUMENTS)}
    distributions = {
        f"{code}/{label}": []
        for code in sorted(FROZEN_INSTRUMENTS)
        for label in (
            "london",
            "new_york",
            "london_new_york_overlap",
            "outside_registered_union",
        )
    }
    latest_contribution = None
    for query in opening_queries:
        for row in query.iterator(chunk_size=10_000):
            label = _session_label(row["timestamp"])
            spread = row["ask_open"] - row["bid_open"]
            distributions[f"{row['instrument__code']}/{label}"].append(spread)
            if label != "outside_registered_union":
                pair_spreads[row["instrument__code"]].append(spread)
                completed_at = candle_completion(row["timestamp"], "H1", contract)
                latest_contribution = (
                    max(latest_contribution, completed_at)
                    if latest_contribution is not None
                    else completed_at
                )
    if latest_contribution is None:
        raise V2S0Error("v2 S0 has no eligible development observations")

    warmup_counts = {
        code: {
            granularity: sum(
                candle_completion(timestamp, granularity, contract) < development_start
                for timestamp in inventory_timestamps(contract, code, granularity)
            )
            for granularity in ("D", "H1", "W")
        }
        for code in sorted(FROZEN_INSTRUMENTS)
    }
    observations = sum(len(values) for values in pair_spreads.values())
    ceilings = generate_spread_ceilings(pair_spreads, PIPETTES)
    evidence = {
        "as_of": as_of.isoformat(),
        "development_start": development_start.isoformat(),
        "development_end_exclusive": development_end.isoformat(),
        "latest_contribution": latest_contribution.isoformat(),
        "contribution_partition_counts": {
            "development": observations,
            "validation": 0,
            "holdout": 0,
            "future": 0,
        },
        "eligible_session_observations": observations,
        "coverage_counts": row_counts,
        "missingness": missingness,
        "warmup_counts": warmup_counts,
        "spread_ceilings": {code: str(value) for code, value in ceilings.items()},
        "spread_distribution_hashes": {
            group: stable_hash([str(value) for value in sorted(values)])
            for group, values in sorted(distributions.items())
        },
    }
    return evidence


def build_v2_s0_evidence(
    *, dataset: DatasetVersion, strategy: StrategyVersion, numerical_evidence: dict
) -> tuple[dict, V2S0Output]:
    from research.failed_break_v2_s0_governance import PREREG_ARTIFACT_SHA256

    contract = contract_for_dataset(dataset)
    registration = dataset.registration
    configuration = {
        "identity": V2_S0_CONFIGURATION_IDENTITY,
        "stage": "S0",
        "preregistration_artifact_sha256": PREREG_ARTIFACT_SHA256,
        "dataset_id": dataset.pk,
        "dataset_name": dataset.name,
        "dataset_version": dataset.version,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "contract_identity": contract.identity,
        "contract_sha256": contract.sha256,
        "global_semantic_inventory_sha256": contract.global_semantic_inventory_sha256,
        "registration_identity": REPLACEMENT_REGISTRATION_IDENTITY,
        "registration_configuration_sha256": registration.configuration_sha256,
        "registration_report_sha256": registration.report_sha256,
        "strategy_version_id": strategy.pk,
        "strategy_identity": strategy.version,
        "strategy_content_sha256": strategy.content_hash,
        "detector_identity": strategy.detector_version,
        "detector_artifact_sha256": DETECTOR_ARTIFACT_SHA256,
        "methodology_identity": V2_S0_IDENTITY,
        "as_of": V2_S0_AS_OF.isoformat(),
        "maximum_observations": V2_S0_MAXIMUM_OBSERVATIONS,
    }
    output = V2S0Output(
        identity=V2_S0_REPORT_IDENTITY,
        stage="S0",
        numerical_evidence=numerical_evidence,
        configuration_sha256=stable_hash(configuration),
    )
    return configuration, output


@transaction.atomic
def execute_v2_s0_once() -> tuple[V2S0Output, JobRun, StrategyVersion]:
    """Persist one new v2 strategy and S0 JobRun; never accept or authorize S1."""
    from research.failed_break_v2_s0_governance import load_v2_s0_preregistration

    preregistration = load_v2_s0_preregistration()
    if JobRun.objects.filter(job_name=V2_S0_JOB_NAME).exists():
        raise V2S0Error("v2 S0 already has persistent evidence; replay is prohibited")
    strategy = _create_v2_strategy(preregistration)
    dataset = DatasetVersion.objects.get(pk=V2_S0_DATASET_ID)
    ranges, contract, preregistration = validate_v2_s0_prerequisites(
        dataset=dataset,
        strategy=strategy,
        as_of=V2_S0_AS_OF,
    )
    numerical_evidence = derive_v2_s0_numerical_evidence(
        dataset=dataset,
        ranges_by_instrument=ranges,
        contract=contract,
        as_of=V2_S0_AS_OF,
        maximum_observations=V2_S0_MAXIMUM_OBSERVATIONS,
    )
    if numerical_evidence != preregistration["expected_numerical_evidence"]:
        raise V2S0Error("derived v2 S0 numerical evidence differs from preregistration")
    configuration, output = build_v2_s0_evidence(
        dataset=dataset,
        strategy=strategy,
        numerical_evidence=numerical_evidence,
    )
    job = JobRun.objects.create(
        job_name=V2_S0_JOB_NAME,
        strategy_version=strategy,
        dataset_version=dataset,
        config_hash=output.configuration_sha256,
        idempotency_key=(f"v2-s0:{strategy.pk}:{dataset.pk}:{output.configuration_sha256}"),
        as_of=V2_S0_AS_OF,
        status=JobRun.Status.SUCCEEDED,
        evidence={"configuration": configuration, "report": output.as_dict()},
    )
    return output, job, strategy
