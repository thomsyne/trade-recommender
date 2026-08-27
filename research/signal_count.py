"""Return-blind Phase 2A signal-count boundaries.

This module deliberately does not import the strategy or execution code.  It is the
only market-data projection intended for S0/S1 entry-open use.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal
from zoneinfo import ZoneInfo

from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from market.models import (
    Candle,
    DatasetVersion,
    IngestionRun,
    Instrument,
    dataset_manifest_sha256,
)
from market.quality import (
    expected_candle_timestamps,
    final_registered_completion_before,
    registered_candle_completion,
)
from market.services import RequiredCandleRange, assert_dataset_window_usable
from research.models import (
    AnalysisRun,
    EntryEligibilityEvaluation,
    JobRun,
    Level,
    LevelLifecycleEvent,
    LevelProximityEvent,
    SetupEvent,
    SetupLevelAttribution,
    SetupTransition,
    StrategyVersion,
)

SIGNAL_COUNT_IDENTITY = "failed-break-signal-count-v1"
S0_JOB_NAME = "failed-break-signal-count-s0"
S1_DETECTOR_JOB_NAME = "failed-break-signal-count-s1-detector"
PARTITION_BOUNDARY_CENSOR_RULE = "development-sweep-three-h1-plus-entry-v1"
PHASE1_MANIFEST_SHA256 = "f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882"
FROZEN_INSTRUMENTS = frozenset({"EUR_USD", "GBP_USD", "EUR_GBP", "USD_CAD", "USD_JPY", "AUD_USD"})
S1_GRANULARITIES = frozenset({"W", "D", "H1"})
DEVELOPMENT_START = datetime(2010, 1, 1, tzinfo=ZoneInfo("America/New_York"))
DEVELOPMENT_END = datetime(2019, 1, 1, tzinfo=ZoneInfo("America/New_York"))
WARMUP_CANDLES = {"W": 1, "D": 220, "H1": 14}
PIPETTES = {
    code: Decimal("0.001") if code == "USD_JPY" else Decimal("0.00001")
    for code in FROZEN_INSTRUMENTS
}
M1_ESTIMATED_BYTES_PER_ROW = 256
COMBINED_BOOK = "failed-break-any-level-deduplicated-v1"
FAMILY_BOOKS = {
    Level.Family.WEEKLY: "failed-break-weekly-extreme-v1",
    Level.Family.DAILY_SWING: "failed-break-daily-swing-v1",
    Level.Family.BREAKOUT: "failed-break-breakout-flip-v1",
}
ENTRY_FIELDS = frozenset({"timestamp", "bid_open", "ask_open"})
FORBIDDEN_FIELD_PARTS = frozenset(
    {
        "high",
        "low",
        "close",
        "volume",
        "m1",
        "later",
        "exit",
        "pnl",
        "profit",
        "loss",
        "return",
        "outcome",
        "win_rate",
        "payoff",
        "drawdown",
        "excursion",
    }
)
S0_COUNT_FIELDS = frozenset({"observations"})
S0_COVERAGE_FIELDS = frozenset(
    {
        "dataset_id",
        "dataset_manifest_sha256",
        "strategy_version_id",
        "strategy_content_hash",
        "registered_identities",
        "as_of",
        "row_counts",
        "missingness",
        "spread_ceilings",
        "spread_distribution_hashes",
    }
)
S1_COUNT_FIELDS = frozenset(
    {
        "levels_active",
        "levels_invalidated",
        "levels_expired",
        "levels_superseded",
        "levels_consumed",
        "proximity_approaching",
        "proximity_touched",
        "sweeps",
        "attributions",
        "confirmations",
        "setup_invalidated",
        "setup_expired",
        "setup_cancelled_data_quality",
        "still_trigger_pending",
        "partition_boundary_censored",
        "partition_boundary_purged",
        "physical_setups_processed",
        "eligibility_evaluations_processed",
        "entry_eligible",
        "missed_fill",
        "blocked_session",
        "blocked_spread",
        "no_target",
        "insufficient_reward",
        "cancelled_data_quality",
    }
)
S1_COVERAGE_FIELDS = frozenset(
    {
        "dataset_id",
        "strategy_version_id",
        "s0_report_sha256",
        "detector_job_id",
        "detector_report_sha256",
        "partition_boundary_censor_rule",
        "as_of",
        "bounded",
        "complete",
        "maximum_setups",
        "entry_projections_read",
        "by_pair",
        "by_confirmation_year",
        "by_direction",
        "by_level_family",
        "by_session",
        "by_strategy_identity",
        "physical_event_overlap",
        "attribution_multiplicity",
        "issuance_date_clusters",
        "issuance_week_clusters",
        "shared_currency_clusters",
        "simultaneous_requests",
        "maximum_horizon_concurrency",
        "data_quality_coverage",
        "spread_coverage",
        "proposed_m1_windows",
    }
)
S1_EVALUATION_FIELDS = (
    "setup_id",
    "setup__instrument_id",
    "book_identity",
    "decision",
    "entry_timestamp",
)


class ReturnBlindViolation(ValueError):
    """Raised before a forbidden price or outcome can be accessed."""


@dataclass(frozen=True, slots=True)
class EntryProjection:
    timestamp: datetime
    bid_open: Decimal
    ask_open: Decimal


def read_entry_projection(
    *, dataset_id: int, instrument_id: int, theoretical_entry_timestamp, as_of, fields=ENTRY_FIELDS
) -> EntryProjection:
    """Project only an admitted, completed H1 entry open from one dataset."""
    requested = frozenset(fields)
    if requested != ENTRY_FIELDS:
        raise ReturnBlindViolation(
            "entry projection must request exactly timestamp, bid_open, ask_open"
        )
    if as_of < theoretical_entry_timestamp + timedelta(hours=1):
        raise ReturnBlindViolation("entry H1 candle has not completed as of the requested time")

    dataset = DatasetVersion.objects.get(pk=dataset_id)
    assert_dataset_window_usable(
        dataset,
        instrument_id,
        (
            RequiredCandleRange(
                "H1",
                theoretical_entry_timestamp,
                theoretical_entry_timestamp + timedelta(hours=1),
            ),
        ),
        as_of,
    )

    row = (
        Candle.objects.filter(
            dataset_version_id=dataset_id,
            instrument_id=instrument_id,
            granularity="H1",
            timestamp=theoretical_entry_timestamp,
            complete=True,
            ingestion_run__dataset_version_id=dataset_id,
            ingestion_run__status=IngestionRun.Status.SUCCEEDED,
        )
        .values(*sorted(ENTRY_FIELDS))
        .get()
    )
    return EntryProjection(row["timestamp"], row["bid_open"], row["ask_open"])


def enforce_price_cutoff(*, row_timestamp, theoretical_entry_timestamp, granularity="H1") -> None:
    """Fail closed before any non-H1 or post-entry row is considered."""
    if granularity != "H1":
        raise ReturnBlindViolation("signal count permits no non-H1 price data")
    if row_timestamp > theoretical_entry_timestamp:
        raise ReturnBlindViolation("price rows after theoretical entry are forbidden")


def _assert_return_blind(value, path="output") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_").replace(" ", "_")
            proposed_m1_count = path == "output.coverage" and normalized == "proposed_m1_windows"
            if not proposed_m1_count and any(part in normalized for part in FORBIDDEN_FIELD_PARTS):
                raise ReturnBlindViolation(f"forbidden signal-count output field: {path}.{key}")
            _assert_return_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_return_blind(child, f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class SignalCountOutput:
    identity: str
    stage: str
    counts: Mapping[str, int]
    coverage: Mapping[str, object]
    configuration_sha256: str
    report_sha256: str = field(init=False)

    def __post_init__(self):
        if self.identity != SIGNAL_COUNT_IDENTITY or self.stage not in {"S0", "S1"}:
            raise ValueError("unregistered signal-count identity or stage")
        expected_counts = S0_COUNT_FIELDS if self.stage == "S0" else S1_COUNT_FIELDS
        expected_coverage = S0_COVERAGE_FIELDS if self.stage == "S0" else S1_COVERAGE_FIELDS
        if set(self.counts) != expected_counts or set(self.coverage) != expected_coverage:
            raise ReturnBlindViolation("signal-count output does not match the registered schema")
        if any(type(value) is not int or value < 0 for value in self.counts.values()):
            raise ReturnBlindViolation("signal-count values must be non-negative integers")
        object.__setattr__(
            self,
            "report_sha256",
            stable_hash(
                {
                    "identity": self.identity,
                    "stage": self.stage,
                    "counts": self.counts,
                    "coverage": self.coverage,
                    "configuration_sha256": self.configuration_sha256,
                }
            ),
        )
        _assert_return_blind(asdict(self))

    def as_dict(self):
        return asdict(self)


def stable_hash(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def generate_spread_ceilings(
    spreads: Mapping[str, Iterable[Decimal]], pipettes: Mapping[str, Decimal]
) -> dict[str, Decimal]:
    """Return deterministic absolute nearest-rank p99 ceilings from opening spreads."""
    ceilings = {}
    for group, observations in sorted(spreads.items()):
        ordered = sorted(Decimal(value) for value in observations)
        pipette = Decimal(pipettes.get(group, 0))
        if not ordered or ordered[0] < 0 or pipette <= 0:
            raise ValueError(f"{group} requires non-negative spread observations")
        percentile = ordered[math.ceil(Decimal("0.99") * len(ordered)) - 1]
        ceilings[group] = (percentile / pipette).to_integral_value(rounding=ROUND_CEILING) * pipette
    return ceilings


def _declared_required_ranges(dataset):
    raw_ranges = dataset.manifest.get("required_ranges")
    if not isinstance(raw_ranges, list) or not raw_ranges:
        raise ReturnBlindViolation("dataset manifest must declare bounded required_ranges")
    grouped = {}
    for item in raw_ranges:
        try:
            instrument = str(item["instrument"])
            granularity = str(item["granularity"])
            start = parse_datetime(item["start"])
            end = parse_datetime(item["end"])
        except (KeyError, TypeError, ValueError) as error:
            raise ReturnBlindViolation("invalid dataset required_ranges declaration") from error
        if (
            start is None
            or end is None
            or not timezone.is_aware(start)
            or not timezone.is_aware(end)
        ):
            raise ReturnBlindViolation("dataset required_ranges timestamps must be timezone-aware")
        grouped.setdefault(instrument, []).append(RequiredCandleRange(granularity, start, end))
    return grouped


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_dataset_contract(dataset, strategy, as_of):
    if dataset.manifest_sha256 != dataset_manifest_sha256(dataset.manifest):
        raise ReturnBlindViolation("dataset manifest SHA-256 does not match canonical JSON")
    if (
        strategy.content_hash != PHASE1_MANIFEST_SHA256
        or set(strategy.pair_metadata.get("instruments", ())) != FROZEN_INSTRUMENTS
    ):
        raise ReturnBlindViolation("S1 requires the approved frozen six-instrument strategy")
    manifest = dataset.manifest
    if (
        manifest.get("strategy_manifest_sha256") != PHASE1_MANIFEST_SHA256
        or set(manifest.get("instruments", ())) != FROZEN_INSTRUMENTS
        or manifest.get("partition")
        != {"name": "development", "start_year": 2010, "end_year": 2018}
    ):
        raise ReturnBlindViolation("dataset manifest does not match the frozen S1 universe")
    grouped = _declared_required_ranges(dataset)
    if set(grouped) != FROZEN_INSTRUMENTS:
        raise ReturnBlindViolation("S1 required_ranges must contain all six instruments")
    development_start = DEVELOPMENT_START.astimezone(DEVELOPMENT_START.tzinfo)
    for instrument, ranges in grouped.items():
        if (
            len(ranges) != len(S1_GRANULARITIES)
            or {required.granularity for required in ranges} != S1_GRANULARITIES
        ):
            raise ReturnBlindViolation(
                f"{instrument} must declare exactly one W, D and H1 S1 range"
            )
        for required in ranges:
            try:
                expected = expected_candle_timestamps(
                    required.start, required.end, required.granularity
                )
            except ValueError as error:
                raise ReturnBlindViolation(str(error)) from error
            warmup = sum(
                registered_candle_completion(timestamp, required.granularity) <= development_start
                for timestamp in expected
            )
            legal_end = final_registered_completion_before(DEVELOPMENT_END, required.granularity)
            if warmup < WARMUP_CANDLES[required.granularity] or required.end != legal_end:
                raise ReturnBlindViolation(
                    f"{instrument} {required.granularity} range lacks development or warm-up coverage"
                )
            if required.end > as_of:
                raise ReturnBlindViolation(
                    "signal-count as_of precedes required development coverage"
                )
    return grouped


def _persist_signal_count_job(*, output, configuration, job_name, strategy, dataset, as_of):
    values = {
        "job_name": job_name,
        "strategy_version": strategy,
        "dataset_version": dataset,
        "config_hash": output.configuration_sha256,
        "as_of": as_of,
        "status": JobRun.Status.SUCCEEDED,
        "evidence": {"configuration": configuration, "report": output.as_dict()},
    }
    job, created = JobRun.objects.get_or_create(
        idempotency_key=(
            f"{output.stage.lower()}:{strategy.pk}:{dataset.pk}:{output.configuration_sha256}"
        ),
        defaults=values,
    )
    if not created and any(getattr(job, name) != value for name, value in values.items()):
        raise ValueError(f"{output.stage} run key resolved to different immutable content")
    return job


def _session_label(timestamp):
    london = time(8) <= timestamp.astimezone(ZoneInfo("Europe/London")).time() < time(17)
    new_york = time(8) <= timestamp.astimezone(ZoneInfo("America/New_York")).time() < time(17)
    if london and new_york:
        return "london_new_york_overlap"
    if london:
        return "london"
    if new_york:
        return "new_york"
    return "outside_registered_union"


def _registered_identities(strategy):
    return {
        "data": strategy.data_identity,
        "detector": strategy.detector_version,
        "event_policy": strategy.event_identity,
        "execution": strategy.execution_identity,
        "cost": strategy.cost_identity,
        "portfolio": strategy.portfolio_identity,
        "signal_count": SIGNAL_COUNT_IDENTITY,
    }


def run_s0(
    *, dataset_id: int, strategy_version_id: int, maximum_observations: int, as_of
) -> tuple[SignalCountOutput, JobRun]:
    """Freeze bounded development opening-spread evidence without accessing trade records."""
    if maximum_observations < 1:
        raise ValueError("maximum_observations must be positive")
    if not timezone.is_aware(as_of):
        raise ValueError("as_of must be timezone-aware")
    dataset = DatasetVersion.objects.get(pk=dataset_id)
    strategy = StrategyVersion.objects.get(pk=strategy_version_id)
    ranges_by_instrument = _validate_dataset_contract(dataset, strategy, as_of)
    instruments = {
        instrument.code: instrument
        for instrument in Instrument.objects.filter(code__in=ranges_by_instrument)
    }
    if set(instruments) != FROZEN_INSTRUMENTS:
        raise ReturnBlindViolation("frozen S0 instrument registry is incomplete")

    row_counts = {}
    missingness = {}
    development_ranges_by_instrument = {}
    for code, ranges in ranges_by_instrument.items():
        instrument = instruments[code]
        development_ranges = tuple(development_candle_range(required) for required in ranges)
        development_ranges_by_instrument[code] = development_ranges
        assert_dataset_window_usable(dataset, instrument, development_ranges, as_of)
        row_counts[code] = {}
        missingness[code] = {}
        for required in development_ranges:
            expected = len(
                expected_candle_timestamps(required.start, required.end, required.granularity)
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
                raise ReturnBlindViolation("S0 row-count audit found incomplete dataset coverage")

    development_start = DEVELOPMENT_START.astimezone(UTC)
    development_end = DEVELOPMENT_END.astimezone(UTC)
    opening_queries = []
    for code, ranges in development_ranges_by_instrument.items():
        h1_range = next(required for required in ranges if required.granularity == "H1")
        timestamps = tuple(
            timestamp
            for timestamp in expected_candle_timestamps(
                h1_range.start, h1_range.end, h1_range.granularity
            )
            if development_start <= registered_candle_completion(timestamp, "H1") < development_end
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
            ).values("instrument__code", "timestamp", "bid_open", "ask_open")
        )
    if sum(query.count() for query in opening_queries) > maximum_observations:
        raise ReturnBlindViolation("S0 observation bound would truncate the registered audit")

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
    for query in opening_queries:
        for row in query.iterator(chunk_size=10_000):
            label = _session_label(row["timestamp"])
            spread = row["ask_open"] - row["bid_open"]
            group = f"{row['instrument__code']}/{label}"
            distributions[group].append(spread)
            if label != "outside_registered_union":
                pair_spreads[row["instrument__code"]].append(spread)
    ceilings = generate_spread_ceilings(pair_spreads, PIPETTES)
    distribution_hashes = {
        group: stable_hash([str(value) for value in sorted(values)])
        for group, values in sorted(distributions.items())
    }
    observations = sum(len(values) for values in pair_spreads.values())
    configuration = {
        "identity": SIGNAL_COUNT_IDENTITY,
        "stage": "S0",
        "dataset_id": dataset.pk,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "strategy_version_id": strategy.pk,
        "strategy_content_hash": strategy.content_hash,
        "registered_identities": _registered_identities(strategy),
        "as_of": as_of.isoformat(),
        "maximum_observations": maximum_observations,
    }
    output = SignalCountOutput(
        SIGNAL_COUNT_IDENTITY,
        "S0",
        {"observations": observations},
        {
            "dataset_id": dataset.pk,
            "dataset_manifest_sha256": dataset.manifest_sha256,
            "strategy_version_id": strategy.pk,
            "strategy_content_hash": strategy.content_hash,
            "registered_identities": _registered_identities(strategy),
            "as_of": as_of.isoformat(),
            "row_counts": row_counts,
            "missingness": missingness,
            "spread_ceilings": {key: str(value) for key, value in ceilings.items()},
            "spread_distribution_hashes": distribution_hashes,
        },
        stable_hash(configuration),
    )
    job = _persist_signal_count_job(
        output=output,
        configuration=configuration,
        job_name=S0_JOB_NAME,
        strategy=strategy,
        dataset=dataset,
        as_of=as_of,
    )
    return output, job


def _validated_s0_job(*, s0_job_id, dataset, strategy):
    job = JobRun.objects.filter(
        pk=s0_job_id,
        job_name=S0_JOB_NAME,
        strategy_version=strategy,
        dataset_version=dataset,
        status=JobRun.Status.SUCCEEDED,
    ).first()
    if not job or set(job.evidence) != {"configuration", "report"}:
        raise ReturnBlindViolation("S1 requires a genuine immutable S0 audit")
    configuration = job.evidence["configuration"]
    report = job.evidence["report"]
    try:
        reconstructed = SignalCountOutput(
            report["identity"],
            report["stage"],
            report["counts"],
            report["coverage"],
            report["configuration_sha256"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ReturnBlindViolation("stored S0 report is not canonical") from error
    coverage = reconstructed.coverage
    expected_configuration_fields = {
        "identity",
        "stage",
        "dataset_id",
        "dataset_manifest_sha256",
        "strategy_version_id",
        "strategy_content_hash",
        "registered_identities",
        "as_of",
        "maximum_observations",
    }
    row_counts = coverage.get("row_counts", {})
    missingness = coverage.get("missingness", {})
    spread_ceilings = coverage.get("spread_ceilings", {})
    distribution_hashes = coverage.get("spread_distribution_hashes", {})
    range_maps_valid = all(
        isinstance(value, Mapping)
        and set(value) == FROZEN_INSTRUMENTS
        and all(
            isinstance(granularities, Mapping) and set(granularities) == S1_GRANULARITIES
            for granularities in value.values()
        )
        for value in (row_counts, missingness)
    )
    try:
        ceilings_valid = set(spread_ceilings) == FROZEN_INSTRUMENTS and all(
            Decimal(value) >= 0 for value in spread_ceilings.values()
        )
    except (TypeError, ValueError):
        ceilings_valid = False
    if (
        reconstructed.as_dict() != report
        or reconstructed.report_sha256 != report.get("report_sha256")
        or set(configuration) != expected_configuration_fields
        or configuration.get("identity") != SIGNAL_COUNT_IDENTITY
        or configuration.get("stage") != "S0"
        or stable_hash(configuration) != job.config_hash
        or reconstructed.configuration_sha256 != job.config_hash
        or configuration.get("dataset_id") != dataset.pk
        or configuration.get("dataset_manifest_sha256") != dataset.manifest_sha256
        or configuration.get("strategy_version_id") != strategy.pk
        or configuration.get("strategy_content_hash") != strategy.content_hash
        or configuration.get("registered_identities") != _registered_identities(strategy)
        or configuration.get("as_of") != job.as_of.isoformat()
        or type(configuration.get("maximum_observations")) is not int
        or configuration["maximum_observations"] < reconstructed.counts["observations"]
        or coverage.get("dataset_id") != dataset.pk
        or coverage.get("dataset_manifest_sha256") != dataset.manifest_sha256
        or coverage.get("strategy_version_id") != strategy.pk
        or coverage.get("strategy_content_hash") != strategy.content_hash
        or coverage.get("registered_identities") != _registered_identities(strategy)
        or coverage.get("as_of") != job.as_of.isoformat()
        or not range_maps_valid
        or any(
            type(value) is not int or value < 0
            for granularities in row_counts.values()
            for value in granularities.values()
        )
        or any(
            value != 0 for granularities in missingness.values() for value in granularities.values()
        )
        or not ceilings_valid
        or any(not _is_sha256(value) for value in distribution_hashes.values())
        or not distribution_hashes
    ):
        raise ReturnBlindViolation("stored S0 audit hashes or identities do not verify")
    return reconstructed


def _validate_s1_contract(dataset, strategy, as_of, s0_job_id):
    grouped = _validate_dataset_contract(dataset, strategy, as_of)
    s0_output = _validated_s0_job(
        s0_job_id=s0_job_id,
        dataset=dataset,
        strategy=strategy,
    )
    return grouped, s0_output


def expected_analysis_keys(ranges_by_instrument):
    keys = []
    development_start = DEVELOPMENT_START.astimezone(UTC)
    development_end = DEVELOPMENT_END.astimezone(UTC)
    for code, ranges in sorted(ranges_by_instrument.items()):
        h1_range = next(required for required in ranges if required.granularity == "H1")
        keys.extend(
            (code, registered_candle_completion(timestamp, "H1").isoformat())
            for timestamp in expected_candle_timestamps(
                h1_range.start, h1_range.end, h1_range.granularity
            )
            if development_start <= registered_candle_completion(timestamp, "H1") < development_end
        )
    return tuple(keys)


def development_candle_range(required):
    """Restrict a declared range to candles completed strictly inside development."""
    timestamps = tuple(
        timestamp
        for timestamp in expected_candle_timestamps(
            required.start, required.end, required.granularity
        )
        if registered_candle_completion(timestamp, required.granularity)
        < DEVELOPMENT_END.astimezone(UTC)
    )
    if not timestamps:
        raise ReturnBlindViolation("declared range has no pre-boundary candles")
    return RequiredCandleRange(
        required.granularity,
        timestamps[0],
        registered_candle_completion(timestamps[-1], required.granularity),
    )


def _validate_detector_coverage(
    *,
    detector_job_id,
    dataset,
    strategy,
    ranges_by_instrument,
    s0_job_id,
    s0_report_sha256,
    as_of,
):
    expected = expected_analysis_keys(ranges_by_instrument)
    expected_hash = stable_hash(expected)
    job = JobRun.objects.filter(
        pk=detector_job_id,
        job_name=S1_DETECTOR_JOB_NAME,
        strategy_version=strategy,
        dataset_version=dataset,
        status=JobRun.Status.SUCCEEDED,
    ).first()
    if not job or set(job.evidence) != {"configuration", "report"}:
        raise ReturnBlindViolation("S1 requires its registered detector JobRun")
    configuration = job.evidence["configuration"]
    report = job.evidence["report"]
    report_body = {key: value for key, value in report.items() if key != "report_sha256"}
    censored_evidence = report.get("partition_boundary_censored")
    if (
        set(configuration)
        != {
            "identity",
            "dataset_id",
            "dataset_manifest_sha256",
            "strategy_version_id",
            "strategy_content_hash",
            "detector_version",
            "partition_boundary_censor_rule",
            "s0_job_id",
            "s0_report_sha256",
            "as_of",
        }
        or configuration.get("identity") != S1_DETECTOR_JOB_NAME
        or configuration.get("dataset_id") != dataset.pk
        or configuration.get("dataset_manifest_sha256") != dataset.manifest_sha256
        or configuration.get("strategy_version_id") != strategy.pk
        or configuration.get("strategy_content_hash") != strategy.content_hash
        or configuration.get("detector_version") != strategy.detector_version
        or configuration.get("partition_boundary_censor_rule") != PARTITION_BOUNDARY_CENSOR_RULE
        or configuration.get("s0_job_id") != s0_job_id
        or configuration.get("s0_report_sha256") != s0_report_sha256
        or configuration.get("as_of") != as_of.isoformat()
        or configuration.get("as_of") != job.as_of.isoformat()
        or stable_hash(configuration) != job.config_hash
        or set(report)
        != {
            "report_sha256",
            "expected_analysis_count",
            "expected_analysis_sha256",
            "observed_analysis_count",
            "observed_analysis_sha256",
            "partition_boundary_censored",
            "partition_boundary_censored_sha256",
        }
        or report.get("report_sha256") != stable_hash(report_body)
        or report.get("expected_analysis_count") != len(expected)
        or report.get("expected_analysis_sha256") != expected_hash
        or not isinstance(censored_evidence, list)
        or any(not isinstance(row, Mapping) for row in censored_evidence)
        or censored_evidence != sorted(censored_evidence, key=lambda row: row.get("setup_id", -1))
        or report.get("partition_boundary_censored_sha256") != stable_hash(censored_evidence)
    ):
        raise ReturnBlindViolation("S1 detector audit hashes or identities do not verify")

    observed_rows = list(
        AnalysisRun.objects.filter(
            dataset_version=dataset,
            detector_version=strategy.detector_version,
            instrument__code__in=FROZEN_INSTRUMENTS,
            completed_h1_timestamp__gte=DEVELOPMENT_START.astimezone(UTC),
            completed_h1_timestamp__lt=DEVELOPMENT_END.astimezone(UTC),
        ).values_list("instrument__code", "completed_h1_timestamp", "result")
    )
    observed = tuple(sorted((code, timestamp.isoformat()) for code, timestamp, _ in observed_rows))
    if (
        observed != expected
        or report.get("observed_analysis_count") != len(observed)
        or report.get("observed_analysis_sha256") != stable_hash(observed)
        or any(result == AnalysisRun.Result.DATA_INCOMPLETE for _, _, result in observed_rows)
    ):
        raise ReturnBlindViolation("S1 detector analysis coverage is incomplete or unresolved")

    setup_rows = list(
        SetupEvent.objects.filter(
            dataset_version=dataset,
            strategy_version=strategy,
            sweep_h1_timestamp__gte=DEVELOPMENT_START.astimezone(UTC),
            sweep_h1_timestamp__lt=DEVELOPMENT_END.astimezone(UTC),
        ).values("pk", "sweep_h1_timestamp")
    )
    expected_censored = sorted(
        (
            evidence
            for row in setup_rows
            if (
                evidence := partition_boundary_censorship(
                    setup_id=row["pk"], sweep_timestamp=row["sweep_h1_timestamp"]
                )
            )
        ),
        key=lambda row: row["setup_id"],
    )
    censored_ids = {row["setup_id"] for row in expected_censored}
    transitioned_censored_ids = set(
        SetupTransition.objects.filter(
            setup_id__in=censored_ids,
            book_identity="",
        ).values_list("setup_id", flat=True)
    )
    if censored_evidence != expected_censored or transitioned_censored_ids:
        raise ReturnBlindViolation("S1 detector partition censorship evidence does not verify")
    return job, report["report_sha256"]


def _s1_evaluation_queryset(setup_ids):
    return (
        EntryEligibilityEvaluation.objects.filter(setup_id__in=setup_ids)
        .order_by("setup__sweep_h1_timestamp", "setup_id", "book_identity")
        .values(*S1_EVALUATION_FIELDS)
    )


def _next_registered_h1_open(timestamp):
    local = timestamp.astimezone(ZoneInfo("America/New_York"))
    if local.weekday() == 4 and local.time() == time(17):
        return (local + timedelta(days=2)).replace(hour=17).astimezone(timestamp.tzinfo)
    return timestamp


def _partition_boundary_lifecycle_horizon(sweep_timestamp):
    completion = sweep_timestamp
    for _ in range(3):
        confirmation_open = _next_registered_h1_open(completion)
        completion = registered_candle_completion(confirmation_open, "H1")
    latest_confirmation_completion = completion
    entry_open = _next_registered_h1_open(latest_confirmation_completion)
    entry_evidence_completion = registered_candle_completion(entry_open, "H1")
    return latest_confirmation_completion, entry_evidence_completion


def partition_boundary_censorship(*, setup_id, sweep_timestamp):
    """Return canonical timestamp-only evidence when development cannot observe a setup."""
    latest_confirmation_completion, entry_evidence_completion = (
        _partition_boundary_lifecycle_horizon(sweep_timestamp)
    )
    if entry_evidence_completion < DEVELOPMENT_END.astimezone(UTC):
        return None
    body = {
        "setup_id": setup_id,
        "sweep_timestamp": sweep_timestamp.isoformat(),
        "rule": PARTITION_BOUNDARY_CENSOR_RULE,
        "partition_boundary": DEVELOPMENT_END.astimezone(UTC).isoformat(),
        "latest_confirmation_completion": latest_confirmation_completion.isoformat(),
        "entry_evidence_completion": entry_evidence_completion.isoformat(),
    }
    return {**body, "evidence_sha256": stable_hash(body)}


def _maximum_horizon_end(entry_timestamp):
    local = entry_timestamp.astimezone(ZoneInfo("America/New_York"))
    day = local.date()
    completions = 0
    while completions < 10:
        candidate = datetime.combine(day, time(17), tzinfo=local.tzinfo)
        if candidate > local and candidate.weekday() < 5:
            completions += 1
            last_completion = candidate
        day += timedelta(days=1)
    return _next_registered_h1_open(last_completion.astimezone(entry_timestamp.tzinfo))


def _cluster_summary(counter):
    sizes = Counter(counter.values())
    return {
        "clusters": len(counter),
        "members": sum(counter.values()),
        "maximum_size": max(counter.values(), default=0),
        "multi_member_clusters": sum(size > 1 for size in counter.values()),
        "size_distribution": {str(size): count for size, count in sorted(sizes.items())},
    }


def _maximum_concurrency(entries):
    changes = []
    for timestamp in entries:
        changes.append((timestamp, 1))
        changes.append((_maximum_horizon_end(timestamp), -1))
    active = 0
    peak = 0
    for _, delta in sorted(changes, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    return {"entry_requests": len(entries), "peak_requests": peak}


def _analysis_data_incomplete_count(dataset, strategy):
    return AnalysisRun.objects.filter(
        dataset_version=dataset,
        detector_version=strategy.detector_version,
        instrument__code__in=FROZEN_INSTRUMENTS,
        completed_h1_timestamp__gte=DEVELOPMENT_START.astimezone(UTC),
        completed_h1_timestamp__lt=DEVELOPMENT_END.astimezone(UTC),
        result=AnalysisRun.Result.DATA_INCOMPLETE,
    ).count()


def run_s1(
    *,
    dataset_id: int,
    strategy_version_id: int,
    s0_job_id: int,
    detector_job_id: int,
    maximum_setups: int,
    as_of,
) -> SignalCountOutput:
    """Count bounded persisted eligibility facts without importing post-entry execution code."""
    if maximum_setups < 1:
        raise ValueError("maximum_setups must be positive")
    if not timezone.is_aware(as_of):
        raise ValueError("as_of must be timezone-aware")
    dataset = DatasetVersion.objects.get(pk=dataset_id)
    strategy = StrategyVersion.objects.get(pk=strategy_version_id)
    ranges_by_instrument, s0_output = _validate_s1_contract(dataset, strategy, as_of, s0_job_id)
    s0_report_sha256 = s0_output.report_sha256
    instruments_by_code = {
        instrument.code: instrument
        for instrument in Instrument.objects.filter(code__in=ranges_by_instrument)
    }
    if set(instruments_by_code) != set(ranges_by_instrument):
        raise ReturnBlindViolation("dataset required_ranges references an unknown instrument")
    for code, ranges in ranges_by_instrument.items():
        assert_dataset_window_usable(
            dataset,
            instruments_by_code[code],
            tuple(development_candle_range(required) for required in ranges),
            as_of,
        )
    detector_job, detector_report_sha256 = _validate_detector_coverage(
        detector_job_id=detector_job_id,
        dataset=dataset,
        strategy=strategy,
        ranges_by_instrument=ranges_by_instrument,
        s0_job_id=s0_job_id,
        s0_report_sha256=s0_report_sha256,
        as_of=as_of,
    )
    detector_evidence = getattr(detector_job, "evidence", {})
    censored_setup_ids = frozenset(
        row["setup_id"]
        for row in detector_evidence.get("report", {}).get("partition_boundary_censored", ())
    )
    ranges_by_instrument_id = {
        instruments_by_code[code].pk: ranges for code, ranges in ranges_by_instrument.items()
    }

    development_start = DEVELOPMENT_START.astimezone(UTC)
    development_end = DEVELOPMENT_END.astimezone(UTC)
    global_transition = SetupTransition.objects.filter(setup_id=OuterRef("pk"), book_identity="")
    pending = (
        SetupEvent.objects.filter(
            dataset_version=dataset,
            strategy_version=strategy,
            sweep_h1_timestamp__gte=development_start,
            sweep_h1_timestamp__lt=development_end,
        )
        .annotate(has_global_transition=Exists(global_transition))
        .filter(has_global_transition=False)
    )
    pending_ids = set(pending.values_list("pk", flat=True))
    if pending_ids != set(censored_setup_ids):
        raise ReturnBlindViolation(
            "S1 lifecycle is incomplete: trigger-pending setups do not match immutable "
            "partition censorship evidence"
        )

    confirmations = []
    purged = 0
    confirmation_rows = (
        SetupTransition.objects.filter(
            setup__dataset_version=dataset,
            setup__strategy_version=strategy,
            book_identity="",
            from_state=SetupTransition.State.TRIGGER_PENDING,
            to_state=SetupTransition.State.CONFIRMED,
            effective_at__gte=development_start,
            effective_at__lt=development_end,
        )
        .order_by("effective_at", "setup_id")
        .values("setup_id", "effective_at")
    )
    for confirmation in confirmation_rows.iterator(chunk_size=10_000):
        entry_timestamp = _next_registered_h1_open(confirmation["effective_at"])
        if _maximum_horizon_end(entry_timestamp) >= development_end:
            purged += 1
            continue
        confirmations.append(confirmation)
        if len(confirmations) > maximum_setups:
            raise ReturnBlindViolation(
                "S1 maximum_setups would truncate the complete development report"
            )
    setup_ids = [row["setup_id"] for row in confirmations]
    development_setup_ids = list(
        SetupEvent.objects.filter(
            dataset_version=dataset,
            strategy_version=strategy,
            sweep_h1_timestamp__gte=development_start,
            sweep_h1_timestamp__lt=development_end,
        ).values_list("pk", flat=True)
    )
    confirmation_by_setup = {row["setup_id"]: row["effective_at"] for row in confirmations}
    setups = {
        row["pk"]: row
        for row in SetupEvent.objects.filter(pk__in=setup_ids).values(
            "pk",
            "instrument_id",
            "instrument__code",
            "instrument__base_currency",
            "instrument__quote_currency",
            "direction",
        )
    }
    attribution_rows = list(
        SetupLevelAttribution.objects.filter(setup_id__in=setup_ids).values(
            "setup_id", "level_id", "level__family"
        )
    )
    raw_attribution_count = SetupLevelAttribution.objects.filter(
        setup_id__in=development_setup_ids
    ).count()
    attributions_by_setup = {setup_id: [] for setup_id in setup_ids}
    for attribution in attribution_rows:
        attributions_by_setup[attribution["setup_id"]].append(attribution)

    evaluations = list(_s1_evaluation_queryset(setup_ids))
    evaluations_by_setup = {setup_id: [] for setup_id in setup_ids}
    for evaluation in evaluations:
        evaluations_by_setup[evaluation["setup_id"]].append(evaluation)
    entry_transitions = list(
        SetupTransition.objects.filter(
            setup_id__in=setup_ids,
            from_state=SetupTransition.State.CONFIRMED,
        ).values("setup_id", "book_identity", "to_state", "effective_at")
    )
    transitions_by_key = {
        (transition["setup_id"], transition["book_identity"]): transition
        for transition in entry_transitions
    }
    for setup_id in setup_ids:
        families = {row["level__family"] for row in attributions_by_setup[setup_id]}
        expected_books = {COMBINED_BOOK, *(FAMILY_BOOKS[family] for family in families)}
        actual_books = {row["book_identity"] for row in evaluations_by_setup[setup_id]}
        if not families or actual_books != expected_books:
            raise ReturnBlindViolation("S1 setup/book eligibility lifecycle is incomplete")
        for evaluation in evaluations_by_setup[setup_id]:
            transition = transitions_by_key.get((setup_id, evaluation["book_identity"]))
            if not transition or transition["to_state"] != evaluation["decision"]:
                raise ReturnBlindViolation("S1 eligibility transition ledger is incomplete")

    counts = {field: 0 for field in S1_COUNT_FIELDS}
    counts["physical_setups_processed"] = len(setup_ids)
    counts["sweeps"] = len(development_setup_ids)
    counts["confirmations"] = len(setup_ids)
    counts["partition_boundary_censored"] = len(censored_setup_ids)
    counts["partition_boundary_purged"] = purged
    counts["attributions"] = raw_attribution_count
    projections_read = 0
    projected_entries = set()
    decision_fields = {
        EntryEligibilityEvaluation.Decision.ENTRY_PENDING: "entry_eligible",
        EntryEligibilityEvaluation.Decision.MISSED_FILL: "missed_fill",
        EntryEligibilityEvaluation.Decision.BLOCKED_SESSION: "blocked_session",
        EntryEligibilityEvaluation.Decision.BLOCKED_SPREAD: "blocked_spread",
        EntryEligibilityEvaluation.Decision.NO_TARGET: "no_target",
        EntryEligibilityEvaluation.Decision.INSUFFICIENT_REWARD: "insufficient_reward",
        EntryEligibilityEvaluation.Decision.CANCELLED_DATA_QUALITY: "cancelled_data_quality",
    }
    by_pair = Counter()
    by_year = Counter()
    by_direction = Counter()
    by_family = Counter()
    multiplicity = Counter()
    issuance_dates = Counter()
    issuance_weeks = Counter()
    for setup_id in setup_ids:
        setup = setups[setup_id]
        confirmation_local = confirmation_by_setup[setup_id].astimezone(
            ZoneInfo("America/New_York")
        )
        by_pair[setup["instrument__code"]] += 1
        by_year[str(confirmation_local.year)] += 1
        by_direction[setup["direction"]] += 1
        families = {row["level__family"] for row in attributions_by_setup[setup_id]}
        for family in families:
            by_family[family] += 1
        multiplicity[str(len(attributions_by_setup[setup_id]))] += 1
        issuance_dates[confirmation_local.date().isoformat()] += 1
        iso_year, iso_week, _ = confirmation_local.isocalendar()
        issuance_weeks[f"{iso_year}-W{iso_week:02d}"] += 1

    by_session = Counter()
    by_book = Counter()
    simultaneous = Counter()
    simultaneous_by_book = {}
    shared_currency = Counter()
    eligible_entries = []
    eligible_entries_by_book = {}
    for evaluation in evaluations:
        counts["eligibility_evaluations_processed"] += 1
        counts[decision_fields[evaluation["decision"]]] += 1
        transition = transitions_by_key[(evaluation["setup_id"], evaluation["book_identity"])]
        by_session[_session_label(transition["effective_at"])] += 1
        by_book[evaluation["book_identity"]] += 1
        if evaluation["decision"] == EntryEligibilityEvaluation.Decision.ENTRY_PENDING:
            projection_key = (
                evaluation["setup__instrument_id"],
                evaluation["entry_timestamp"],
            )
            entry_ranges = ranges_by_instrument_id.get(evaluation["setup__instrument_id"], ())
            if not any(
                required.granularity == "H1"
                and required.start <= evaluation["entry_timestamp"]
                and evaluation["entry_timestamp"] + timedelta(hours=1) <= required.end
                for required in entry_ranges
            ):
                raise ReturnBlindViolation("entry projection is outside the frozen S1 range")
            if projection_key not in projected_entries:
                read_entry_projection(
                    dataset_id=dataset.pk,
                    instrument_id=evaluation["setup__instrument_id"],
                    theoretical_entry_timestamp=evaluation["entry_timestamp"],
                    as_of=evaluation["entry_timestamp"] + timedelta(hours=1),
                )
                projected_entries.add(projection_key)
                projections_read += 1
            entry_timestamp = evaluation["entry_timestamp"]
            eligible_entries.append(entry_timestamp)
            eligible_entries_by_book.setdefault(evaluation["book_identity"], []).append(
                entry_timestamp
            )
            simultaneous[entry_timestamp.isoformat()] += 1
            simultaneous_by_book.setdefault(evaluation["book_identity"], Counter())[
                entry_timestamp.isoformat()
            ] += 1
            setup = setups[evaluation["setup_id"]]
            base_side = "long" if setup["direction"] == SetupEvent.Direction.LONG else "short"
            quote_side = "short" if base_side == "long" else "long"
            shared_currency[
                f"{evaluation['book_identity']}|{entry_timestamp.isoformat()}|"
                f"{base_side}:{setup['instrument__base_currency']}"
            ] += 1
            shared_currency[
                f"{evaluation['book_identity']}|{entry_timestamp.isoformat()}|"
                f"{quote_side}:{setup['instrument__quote_currency']}"
            ] += 1

    development_levels = list(
        Level.objects.filter(
            dataset_version=dataset,
            strategy_version=strategy,
            activated_at__lt=development_end,
        ).values_list("pk", flat=True)
    )
    latest_level_state = {}
    for event in (
        LevelLifecycleEvent.objects.filter(
            level_id__in=development_levels,
            effective_at__lt=development_end,
        )
        .order_by("effective_at", "pk")
        .values("level_id", "state")
    ):
        latest_level_state[event["level_id"]] = event["state"]
    counts["levels_active"] = sum(
        level_id not in latest_level_state for level_id in development_levels
    )
    counts["levels_invalidated"] = sum(
        state == LevelLifecycleEvent.State.INVALIDATED for state in latest_level_state.values()
    )
    counts["levels_expired"] = sum(
        state == LevelLifecycleEvent.State.EXPIRED for state in latest_level_state.values()
    )
    counts["levels_superseded"] = sum(
        state
        in {
            LevelLifecycleEvent.State.SUPERSEDED,
            LevelLifecycleEvent.State.SUPERSEDED_BY_FLIP,
        }
        for state in latest_level_state.values()
    )
    counts["levels_consumed"] = (
        SetupLevelAttribution.objects.filter(
            setup__dataset_version=dataset,
            setup__strategy_version=strategy,
            setup__sweep_h1_timestamp__gte=development_start,
            setup__sweep_h1_timestamp__lt=development_end,
        )
        .values("level_id")
        .distinct()
        .count()
    )
    proximity = Counter(
        LevelProximityEvent.objects.filter(
            level__dataset_version=dataset,
            level__strategy_version=strategy,
            observed_at__gte=development_start,
            observed_at__lt=development_end,
        ).values_list("kind", flat=True)
    )
    counts["proximity_approaching"] = proximity[LevelProximityEvent.Kind.APPROACHING]
    counts["proximity_touched"] = proximity[LevelProximityEvent.Kind.TOUCHED]
    setup_terminal = Counter(
        SetupTransition.objects.filter(
            setup__dataset_version=dataset,
            setup__strategy_version=strategy,
            book_identity="",
            setup__sweep_h1_timestamp__gte=development_start,
            setup__sweep_h1_timestamp__lt=development_end,
        ).values_list("to_state", flat=True)
    )
    counts["setup_invalidated"] = setup_terminal[SetupTransition.State.INVALIDATED]
    counts["setup_expired"] = setup_terminal[SetupTransition.State.EXPIRED]
    counts["setup_cancelled_data_quality"] = setup_terminal[
        SetupTransition.State.CANCELLED_DATA_QUALITY
    ]
    counts["still_trigger_pending"] = 0

    analysis_data_incomplete = _analysis_data_incomplete_count(dataset, strategy)
    spread_checks = (
        len(evaluations)
        - counts["cancelled_data_quality"]
        - counts["blocked_session"]
        - counts["missed_fill"]
    )
    unique_m1_windows = len(projected_entries)
    configuration = {
        "dataset_id": dataset.pk,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "strategy_version_id": strategy.pk,
        "strategy_content_hash": strategy.content_hash,
        "s0_job_id": s0_job_id,
        "s0_report_sha256": s0_report_sha256,
        "detector_job_id": detector_job.pk,
        "detector_report_sha256": detector_report_sha256,
        "partition_boundary_censor_rule": PARTITION_BOUNDARY_CENSOR_RULE,
        "maximum_setups": maximum_setups,
        "as_of": as_of.isoformat(),
    }
    output = SignalCountOutput(
        SIGNAL_COUNT_IDENTITY,
        "S1",
        counts,
        {
            "dataset_id": dataset.pk,
            "strategy_version_id": strategy.pk,
            "s0_report_sha256": s0_report_sha256,
            "detector_job_id": detector_job.pk,
            "detector_report_sha256": detector_report_sha256,
            "partition_boundary_censor_rule": PARTITION_BOUNDARY_CENSOR_RULE,
            "as_of": as_of.isoformat(),
            "bounded": True,
            "complete": True,
            "maximum_setups": maximum_setups,
            "entry_projections_read": projections_read,
            "by_pair": dict(sorted(by_pair.items())),
            "by_confirmation_year": dict(sorted(by_year.items())),
            "by_direction": dict(sorted(by_direction.items())),
            "by_level_family": dict(sorted(by_family.items())),
            "by_session": dict(sorted(by_session.items())),
            "by_strategy_identity": dict(sorted(by_book.items())),
            "physical_event_overlap": {
                "multiple_attributions": sum(
                    len(rows) > 1 for rows in attributions_by_setup.values()
                ),
                "multiple_families": sum(
                    len({row["level__family"] for row in rows}) > 1
                    for rows in attributions_by_setup.values()
                ),
            },
            "attribution_multiplicity": dict(sorted(multiplicity.items())),
            "issuance_date_clusters": _cluster_summary(issuance_dates),
            "issuance_week_clusters": _cluster_summary(issuance_weeks),
            "shared_currency_clusters": _cluster_summary(shared_currency),
            "simultaneous_requests": {
                "all_books": _cluster_summary(simultaneous),
                "by_strategy_identity": {
                    book: _cluster_summary(clusters)
                    for book, clusters in sorted(simultaneous_by_book.items())
                },
            },
            "maximum_horizon_concurrency": {
                "all_books": _maximum_concurrency(eligible_entries),
                "by_strategy_identity": {
                    book: _maximum_concurrency(entries)
                    for book, entries in sorted(eligible_entries_by_book.items())
                },
            },
            "data_quality_coverage": {
                "analysis_data_incomplete": analysis_data_incomplete,
                "cancelled_setups": counts["setup_cancelled_data_quality"],
                "cancelled_eligibility": counts["cancelled_data_quality"],
                "manifest_missing_candles": sum(
                    sum(values.values()) for values in s0_output.coverage["missingness"].values()
                ),
            },
            "spread_coverage": {
                "s0_opening_observations": s0_output.counts["observations"],
                "eligibility_checks": spread_checks,
                "blocked": counts["blocked_spread"],
                "passed": spread_checks - counts["blocked_spread"],
            },
            "proposed_m1_windows": {
                "entry_windows": unique_m1_windows,
                "minute_rows": unique_m1_windows * 60,
                "estimated_bytes_per_minute_row": M1_ESTIMATED_BYTES_PER_ROW,
                "estimated_bytes": unique_m1_windows * 60 * M1_ESTIMATED_BYTES_PER_ROW,
                "additional_ordering_windows_deferred": True,
            },
        },
        stable_hash(configuration),
    )
    _persist_signal_count_job(
        output=output,
        configuration=configuration,
        job_name="failed-break-signal-count-s1",
        strategy=strategy,
        dataset=dataset,
        as_of=as_of,
    )
    return output
