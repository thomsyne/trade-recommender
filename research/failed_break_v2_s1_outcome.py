"""Fail-closed, return-blind acceptance of the single persistent v2 S1 outcome."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal

from django.apps import apps
from django.db import connection, transaction
from django.db.models import Count

from research.failed_break_services import evidence_hash
from research.failed_break_v2_s0_governance import (
    select_persistent_v2_s0_evidence,
)
from research.failed_break_v2_s1 import DEVELOPMENT_END, DEVELOPMENT_START
from research.failed_break_v2_s1_governance import (
    ARTIFACT_SHA256 as RUNNER_ARTIFACT_SHA256,
)
from research.failed_break_v2_s1_governance import (
    EXECUTION_ARTIFACT_SHA256,
    EXECUTION_POLICY_SHA256,
    ROOT,
    canonical_bytes,
    canonical_hash,
    inspect_v2_s1_execution_authorization,
)

ARTIFACT_PATH = ROOT / "docs/strategy/failed-break/v2/s1-outcome-acceptance-v2.json"
ARTIFACT_SHA256 = "5760dd2dd60a2d6a6087b5116b085a8a3774db1512962af0622bc0e3eeed93d5"
ACCEPTANCE_SELF_SHA256 = "5f1497b7e47da958469d8b8c13d2608243e7a0f811eb30f54f4d5fe65f2bbcab"
SCHEMA = "failed-break-v2-s1-outcome-acceptance-v1"
IDENTITY = "failed-break-v2-s1-outcome-acceptance-v1"
REPOSITORY_BASELINE = "3b787839b149b48ebd309c5d94c85b59cd769824"
JOB_IDENTITY = "failed-break-signal-count-s1-v2"
PROJECTION_SHA256 = "5aab5a0e20eae00c6984a7740d9df5d14f0c575b3b0a997b66e055818d66e714"
CONFIGURATION_SHA256 = "cff541256f9d2138260e2b7ebe04d44ff3e2ddaa0ddeafd5f0058c69af13f08b"
REPORT_SHA256 = "02ce750ee803881a06877a0474cea94f6f04e63439f979041fb294569ae2af2a"
EXECUTION_LOG_SHA256 = "92959422e56f89616cdfa6494a5ddbaaa5fc28e5a785a7bc06b96e76b66e51b5"
V1_AGGREGATE_SHA256 = "dc7df52c3502644dc850d6cec865db977a8604b6d871bc8e9f6ec8d477e91a45"

AUTHORITY = {
    "provider_production_or_deployment": False,
    "promotion_or_live_trading": False,
    "return_blind_geometry_implementation": False,
    "returns_or_backtesting": False,
    "v2_s1_outcome": "ACCEPTED",
}
OPERATIONAL_ANCHORS = {
    "dataset_version_id": 3,
    "job_run_id": 5,
    "s0_job_run_id": 4,
    "strategy_version_id": 2,
}
EXPECTED_ROW_COUNTS = {
    "research_analysisrun": 344_817,
    "research_entryeligibilityevaluation": 752,
    "research_jobrun": 1,
    "research_level": 17_935,
    "research_levellifecycleevent": 17_901,
    "research_setupevent": 868,
    "research_setuplevelattribution": 1_213,
    "research_setuptransition": 1_620,
}
EXPECTED_TOTAL_INSERTED_ROWS = 385_107
EXPECTED_INVENTORY_TOTALS = {"D": 17_412, "H1": 344_817, "W": 2_826}
EXPECTED_APPLICATION_COUNTS_SHA256 = (
    "5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097"
)
EXPECTED_APPLICATION_STATE_SHA256 = (
    "6f6100f12f80c0fd49f0208368ddaf6fb23e4df07e693000da19b5c47580c2c1"
)
EXPECTED_INVENTORY_EVIDENCE_SHA256 = (
    "e6b0611a9c2547fe4079be394362570915f26f1ceaf6f268dfd8239f0162a0c1"
)
EXPECTED_STORED_EVIDENCE_SHA256 = "785b4ae600565776da1506bbf08a3866b6161cededf90080381485256aa4e958"
EXPECTED_V1_EVIDENCE_SHA256 = "fbb3437c75fcdedcfa23b6f235f2e7dc5de9413a3a7eba4db54d6c0cf02c2a0d"
EXPECTED_CURRENT_TOTALS = {
    "research_analysisrun": 689_484,
    "research_entryeligibilityevaluation": 1_513,
    "research_jobrun": 5,
    "research_level": 35_097,
    "research_levellifecycleevent": 35_029,
    "research_setupevent": 1_723,
    "research_setuplevelattribution": 2_398,
    "research_setuptransition": 3_236,
    "research_strategyparametermanifest": 2,
    "research_strategyversion": 2,
}
EXPECTED_V1_DIGESTS = {
    "research_analysisrun_v1": "dff5a9f74a6e3b17c24670769cf3c24582fc7794258ec000a6d40f513793ade7",
    "research_entryeligibilityevaluation_v1": (
        "cc75fea7fed6cc7d1223bdb3dc759d5a653ccd3e7a12bc0e54cb375dac666344"
    ),
    "research_jobrun_v1": "329429bba7e6f5979b984bf9b7682b94a979365599c945ab7873b8a78cc735e5",
    "research_level_v1": "5d6a84069ef1a236af5267672eb222995b49daad5f1061255930adeebcd4c00d",
    "research_levellifecycleevent_v1": (
        "cb2046fcce191ef9d240b1186d4c9605e01edb36c04b4b5ef0d454de00a46602"
    ),
    "research_setupevent_v1": "db20250012cc5fed2853e353dfc10041c4f4db672847f628a9d5113dcc9c345d",
    "research_setuplevelattribution_v1": (
        "8f36d1aae3a01eb5cc1d2c8f367d819f1f10c71692673011bf0415d3fd59a8a5"
    ),
    "research_setuptransition_v1": (
        "be9800cb35ad489beb99e39b4ddc50303092876d5b28b587fba9158346c9725e"
    ),
}

FORBIDDEN_APPLICATION_TABLES = {
    "forecasts_backtest": 0,
    "forecasts_experimentassessment": 0,
    "forecasts_experimentassessmentattempt": 0,
    "forecasts_forecastresolution": 0,
    "forecasts_paperlifecycleevent": 0,
    "forecasts_papertradecostassessment": 0,
    "forecasts_papertradeentry": 0,
    "forecasts_papertraderesult": 0,
    "forecasts_promotionrecord": 0,
    "forecasts_recommendationresolution": 0,
    "forecasts_reviewinterpretation": 0,
}


class V2S1OutcomeRefusal(ValueError):
    """The accepted v2 S1 outcome did not reconstruct exactly."""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _table_hash(rows: list[dict]) -> str:
    return canonical_hash(rows)


def load_v2_s1_outcome_acceptance() -> dict:
    """Load only the committed canonical outcome; no path or environment override exists."""

    try:
        raw = ARTIFACT_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ARTIFACT_SHA256:
            raise V2S1OutcomeRefusal("v2 S1 outcome artifact digest mismatch")
        artifact = json.loads(raw)
        if canonical_bytes(artifact) + b"\n" != raw:
            raise V2S1OutcomeRefusal("v2 S1 outcome artifact bytes are not canonical")
        body = dict(artifact)
        claimed = body.pop("acceptance_sha256", None)
        if claimed != ACCEPTANCE_SELF_SHA256 or canonical_hash(body) != claimed:
            raise V2S1OutcomeRefusal("v2 S1 outcome artifact self-hash mismatch")
        authorization = inspect_v2_s1_execution_authorization()
        if (
            artifact.get("schema") != SCHEMA
            or artifact.get("identity") != IDENTITY
            or artifact.get("repository_baseline") != REPOSITORY_BASELINE
            or artifact.get("status") != "ACCEPTED_RETURN_BLIND_V2_S1_EVIDENCE"
            or artifact.get("authority") != AUTHORITY
            or artifact.get("operational_anchors") != OPERATIONAL_ANCHORS
            or artifact.get("accepted_delta", {}).get("per_table") != EXPECTED_ROW_COUNTS
            or artifact.get("accepted_delta", {}).get("total_inserted_rows")
            != EXPECTED_TOTAL_INSERTED_ROWS
            or artifact.get("execution", {}).get("job_identity") != JOB_IDENTITY
            or artifact.get("execution", {}).get("authorization_artifact_sha256")
            != EXECUTION_ARTIFACT_SHA256
            or artifact.get("execution", {}).get("authorization_self_sha256")
            != EXECUTION_POLICY_SHA256
            or artifact.get("execution", {}).get("projection_sha256") != PROJECTION_SHA256
            or artifact.get("execution", {}).get("configuration_sha256") != CONFIGURATION_SHA256
            or artifact.get("execution", {}).get("report_sha256") != REPORT_SHA256
            or artifact.get("bindings") != authorization["bindings"]
            or artifact.get("inventory", {}).get("totals") != EXPECTED_INVENTORY_TOTALS
            or artifact.get("v1_preservation", {}).get("aggregate_sha256") != V1_AGGREGATE_SHA256
            or artifact.get("v1_preservation", {}).get("digests") != EXPECTED_V1_DIGESTS
            or artifact.get("application_state", {}).get("counts_sha256")
            != EXPECTED_APPLICATION_COUNTS_SHA256
            or artifact.get("application_state", {}).get("current_totals")
            != EXPECTED_CURRENT_TOTALS
            or canonical_hash(artifact.get("application_state"))
            != EXPECTED_APPLICATION_STATE_SHA256
            or canonical_hash(artifact.get("inventory")) != EXPECTED_INVENTORY_EVIDENCE_SHA256
            or canonical_hash(artifact.get("stored_evidence")) != EXPECTED_STORED_EVIDENCE_SHA256
            or canonical_hash(artifact.get("v1_preservation")) != EXPECTED_V1_EVIDENCE_SHA256
            or artifact.get("operational_corroboration", {}).get("execution_log_sha256")
            != EXECUTION_LOG_SHA256
        ):
            raise V2S1OutcomeRefusal("v2 S1 outcome acceptance identity changed")
        return artifact
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise V2S1OutcomeRefusal("invalid committed v2 S1 outcome artifact") from error


def select_persistent_v2_s1_evidence():
    """Select S0, dataset, strategy and S1 through governed semantic identities."""

    from research.models import JobRun

    artifact = load_v2_s1_outcome_acceptance()
    s0_job, dataset, strategy = select_persistent_v2_s0_evidence()
    execution = artifact["execution"]
    jobs = JobRun.objects.filter(
        job_name=execution["job_identity"],
        strategy_version=strategy,
        dataset_version=dataset,
        config_hash=execution["configuration_sha256"],
        status="succeeded",
    )
    if jobs.count() != 1:
        raise V2S1OutcomeRefusal("v2 S1 JobRun evidence is missing or duplicated")
    job = jobs.get()
    if (
        job.job_name != JOB_IDENTITY
        or job.strategy_version_id != strategy.pk
        or job.dataset_version_id != dataset.pk
        or job.config_hash != CONFIGURATION_SHA256
        or job.status != "succeeded"
    ):
        raise V2S1OutcomeRefusal("v1 or alternate JobRun cannot substitute for v2 S1")
    return job, s0_job, dataset, strategy


def _application_state() -> dict:
    labels = {"dashboard", "forecasts", "market", "operations", "research"}
    counts = {
        model._meta.db_table: model.objects.count()
        for model in apps.get_models()
        if model._meta.app_label in labels
    }
    for table, expected in FORBIDDEN_APPLICATION_TABLES.items():
        if table in counts and counts[table] != expected:
            raise V2S1OutcomeRefusal(f"forbidden outcome state exists in {table}")
    current_totals = {
        table: counts[table]
        for table in (
            "research_analysisrun",
            "research_entryeligibilityevaluation",
            "research_jobrun",
            "research_level",
            "research_levellifecycleevent",
            "research_setupevent",
            "research_setuplevelattribution",
            "research_setuptransition",
            "research_strategyparametermanifest",
            "research_strategyversion",
        )
    }
    return {
        "counts_sha256": canonical_hash(counts),
        "current_totals": current_totals,
        "forbidden_rows": 0,
    }


def _v1_digests() -> dict:
    queries = {
        "research_jobrun_v1": (
            "SELECT * FROM research_jobrun WHERE strategy_version_id=1 ORDER BY id"
        ),
        "research_analysisrun_v1": (
            "SELECT * FROM research_analysisrun WHERE strategy_version_id=1 ORDER BY id"
        ),
        "research_level_v1": (
            "SELECT * FROM research_level WHERE strategy_version_id=1 ORDER BY id"
        ),
        "research_levellifecycleevent_v1": (
            "SELECT e.* FROM research_levellifecycleevent e "
            "JOIN research_level l ON l.id=e.level_id "
            "WHERE l.strategy_version_id=1 ORDER BY e.id"
        ),
        "research_setupevent_v1": (
            "SELECT * FROM research_setupevent WHERE strategy_version_id=1 ORDER BY id"
        ),
        "research_setuplevelattribution_v1": (
            "SELECT a.* FROM research_setuplevelattribution a "
            "JOIN research_setupevent s ON s.id=a.setup_id "
            "WHERE s.strategy_version_id=1 ORDER BY a.id"
        ),
        "research_setuptransition_v1": (
            "SELECT * FROM research_setuptransition WHERE strategy_version_id=1 ORDER BY id"
        ),
        "research_entryeligibilityevaluation_v1": (
            "SELECT e.* FROM research_entryeligibilityevaluation e "
            "JOIN research_setupevent s ON s.id=e.setup_id "
            "WHERE s.strategy_version_id=1 ORDER BY e.id"
        ),
    }
    digests = {}
    with connection.cursor() as cursor:
        # The accepted historical digests were produced by psql in the
        # America/Toronto server timezone. Freeze that display convention so
        # Django's UTC connection default cannot alter COPY's canonical bytes.
        cursor.execute("SET LOCAL TIME ZONE 'America/Toronto'")
        for label, query in queries.items():
            digest = hashlib.sha256()
            with cursor.copy(f"COPY ({query}) TO STDOUT WITH (FORMAT csv)") as copy:
                for block in copy:
                    digest.update(block)
            digests[label] = digest.hexdigest()
    lines = "".join(f"{digest}  {label}\n" for label, digest in digests.items()).encode()
    return {"aggregate_sha256": hashlib.sha256(lines).hexdigest(), "digests": digests}


def _inventory_evidence(dataset) -> dict:
    from market.models import Candle, CandleConflict, HistoricalTimestampObservation, Instrument
    from market.services import candle_completion

    contract = dataset.registration.data_contract
    instruments = list(Instrument.objects.filter(code__in=artifact_instruments()).order_by("code"))
    if [instrument.code for instrument in instruments] != artifact_instruments():
        raise V2S1OutcomeRefusal("frozen instrument membership changed")
    result = {}
    integrity = Counter()
    for instrument in instruments:
        observations = list(
            HistoricalTimestampObservation.objects.filter(
                inventory__chunk__plan__registration__id=contract.discovery_registration_id,
                inventory__chunk__instrument=instrument,
            )
            .values_list(
                "inventory__chunk__granularity",
                "timestamp",
                "complete",
                "bid_present",
                "ask_present",
                "inventory__accepted_attempt__ingestion_run__status",
                "inventory__chunk__plan__sealed_at",
                "id",
            )
            .order_by("inventory__chunk__granularity", "timestamp", "id")
        )
        inventory = defaultdict(list)
        inventory_keys = []
        for granularity, timestamp, complete, bid, ask, run_status, sealed_at, _pk in observations:
            inventory[granularity].append(timestamp)
            inventory_keys.append((granularity, timestamp))
            integrity["invalid_inventory"] += not (
                granularity in {"D", "H1", "W"}
                and complete
                and bid
                and ask
                and run_status == "succeeded"
                and sealed_at is not None
            )
        candles = list(
            Candle.objects.filter(dataset_version=dataset, instrument=instrument)
            .values_list(
                "granularity",
                "timestamp",
                "complete",
                "ingestion_run__status",
                "ingestion_run__historical_attempt__attempt_number",
                "ingestion_run__historical_attempt__chunk__discovery_inventory_id",
                "id",
            )
            .order_by("granularity", "timestamp", "id")
        )
        candle_keys = []
        for granularity, timestamp, complete, run_status, attempt, inventory_id, _pk in candles:
            candle_keys.append((granularity, timestamp))
            integrity["invalid_candles"] += not (
                granularity in {"D", "H1", "W"}
                and complete
                and run_status == "succeeded"
                and attempt == 1
                and inventory_id is not None
            )
        integrity["duplicate_inventory"] += len(inventory_keys) - len(set(inventory_keys))
        integrity["duplicate_candles"] += len(candle_keys) - len(set(candle_keys))
        integrity["membership_mismatches"] += inventory_keys != candle_keys
        counts = {granularity: len(inventory[granularity]) for granularity in ("D", "H1", "W")}
        hashes = {
            granularity: hashlib.sha256(
                json.dumps(
                    [timestamp.isoformat() for timestamp in inventory[granularity]],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            for granularity in ("D", "H1", "W")
        }
        h1_completions = [
            candle_completion(timestamp, "H1", contract) for timestamp in inventory["H1"]
        ]
        result[instrument.code] = {
            "counts": counts,
            "h1_completion_membership_sha256": hashlib.sha256(
                json.dumps(
                    [timestamp.isoformat() for timestamp in h1_completions],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "timestamp_membership_sha256": hashes,
        }
    integrity["conflicts"] = CandleConflict.objects.filter(dataset_version=dataset).count()
    totals = {
        granularity: sum(row["counts"][granularity] for row in result.values())
        for granularity in ("D", "H1", "W")
    }
    return {"instruments": result, "integrity": dict(sorted(integrity.items())), "totals": totals}


def artifact_instruments() -> list[str]:
    return ["AUD_USD", "EUR_GBP", "EUR_USD", "GBP_USD", "USD_CAD", "USD_JPY"]


def _stored_evidence(job, dataset, strategy) -> dict:
    from research.models import (
        AnalysisRun,
        EntryEligibilityEvaluation,
        Level,
        LevelLifecycleEvent,
        SetupEvent,
        SetupLevelAttribution,
        SetupTransition,
    )

    setups = list(
        SetupEvent.objects.filter(dataset_version=dataset, strategy_version=strategy)
        .select_related("instrument")
        .order_by("sweep_h1_timestamp", "instrument__code", "evidence_hash")
    )
    setup_keys = defaultdict(list)
    for setup in setups:
        setup_keys[(setup.instrument_id, setup.sweep_h1_timestamp)].append(setup.evidence_hash)

    analysis_rows = []
    analysis_members = defaultdict(list)
    analysis_hash_mismatches = 0
    for row in (
        AnalysisRun.objects.filter(dataset_version=dataset, strategy_version=strategy)
        .select_related("instrument")
        .order_by("completed_h1_timestamp", "instrument__code")
    ):
        keys = setup_keys.get((row.instrument_id, row.completed_h1_timestamp), [])
        phase = (
            "DEVELOPMENT"
            if DEVELOPMENT_START <= row.completed_h1_timestamp < DEVELOPMENT_END
            else "WARMUP"
        )
        expected_hash = evidence_hash(
            {
                "completed_h1_timestamp": row.completed_h1_timestamp.isoformat(),
                "result": row.result,
                "setup_keys": keys,
                "phase": phase,
            }
        )
        analysis_hash_mismatches += row.evidence_hash != expected_hash
        analysis_members[row.instrument.code].append(row.completed_h1_timestamp)
        analysis_rows.append(
            {
                "completed_at": row.completed_h1_timestamp.isoformat(),
                "dataset_manifest_sha256": dataset.manifest_sha256,
                "detector_identity": row.detector_version,
                "evidence_hash": row.evidence_hash,
                "instrument": row.instrument.code,
                "result": row.result,
                "setup_keys": keys,
                "strategy_content_sha256": strategy.content_hash,
            }
        )

    lifecycle_by_level = defaultdict(list)
    lifecycle_rows = []
    lifecycle_hash_mismatches = 0
    for row in (
        LevelLifecycleEvent.objects.filter(
            level__dataset_version=dataset,
            level__strategy_version=strategy,
        )
        .select_related("level")
        .order_by("id")
    ):
        lifecycle_by_level[row.level_id].append(row)
        lifecycle_hash_mismatches += row.evidence_hash != evidence_hash(row.evidence)
        lifecycle_rows.append(
            {
                "effective_at": row.effective_at.isoformat(),
                "evidence": row.evidence,
                "evidence_hash": row.evidence_hash,
                "level_stable_key": row.level.stable_key,
                "state": row.state,
            }
        )

    level_rows = []
    projection_levels = []
    for row in (
        Level.objects.filter(dataset_version=dataset, strategy_version=strategy)
        .select_related("instrument")
        .order_by("instrument__code", "activated_at", "stable_key")
    ):
        events = lifecycle_by_level[row.id]
        level_rows.append(
            {
                "activated_at": row.activated_at.isoformat(),
                "atr_at_activation": str(row.atr_at_activation),
                "central_price": str(row.central_price),
                "dataset_manifest_sha256": dataset.manifest_sha256,
                "expires_at": _iso(row.expires_at),
                "family": row.family,
                "instrument": row.instrument.code,
                "role": row.role,
                "source_candle_timestamp": row.source_candle_timestamp.isoformat(),
                "source_timeframe": row.source_timeframe,
                "stable_key": row.stable_key,
                "strategy_content_sha256": strategy.content_hash,
                "zone_lower": str(row.zone_lower),
                "zone_upper": str(row.zone_upper),
            }
        )
        projection_levels.append(
            {
                "instrument": row.instrument.code,
                "stable_key": row.stable_key,
                "state": events[-1].state if events else "active",
                "lifecycle_hashes": [event.evidence_hash for event in events],
            }
        )

    attribution_by_setup = defaultdict(list)
    attribution_rows = []
    cross_strategy_attributions = 0
    for row in (
        SetupLevelAttribution.objects.filter(
            setup__dataset_version=dataset,
            setup__strategy_version=strategy,
        )
        .select_related("setup", "level")
        .order_by("id")
    ):
        attribution_by_setup[row.setup_id].append(row.level.stable_key)
        cross_strategy_attributions += (
            row.level.dataset_version_id != dataset.pk
            or row.level.strategy_version_id != strategy.pk
        )
        attribution_rows.append(
            {
                "level_stable_key": row.level.stable_key,
                "setup_evidence_hash": row.setup.evidence_hash,
            }
        )

    confirmations = {}
    transition_rows = []
    transition_hash_mismatches = 0
    cross_strategy_transitions = 0
    for row in (
        SetupTransition.objects.filter(dataset_version=dataset, strategy_version=strategy)
        .select_related("setup")
        .order_by("id")
    ):
        transition_hash_mismatches += row.evidence_hash != evidence_hash(row.evidence)
        cross_strategy_transitions += (
            row.setup.dataset_version_id != dataset.pk
            or row.setup.strategy_version_id != strategy.pk
            or row.job_run_id != job.pk
        )
        if row.from_state == "TRIGGER_PENDING" and row.book_identity == "":
            confirmations[row.setup_id] = row
        transition_rows.append(
            {
                "book_identity": row.book_identity,
                "dataset_manifest_sha256": dataset.manifest_sha256,
                "decision_at": row.decision_at.isoformat(),
                "effective_at": row.effective_at.isoformat(),
                "evidence": row.evidence,
                "evidence_hash": row.evidence_hash,
                "execution_identity": row.execution_identity,
                "from_state": row.from_state,
                "job_identity": job.job_name,
                "reason": row.reason,
                "setup_evidence_hash": row.setup.evidence_hash,
                "strategy_content_sha256": strategy.content_hash,
                "to_state": row.to_state,
            }
        )

    evaluations_by_setup = defaultdict(list)
    evaluation_rows = []
    evaluation_hash_mismatches = 0
    cross_strategy_evaluations = 0
    entry_status = Counter()
    for row in (
        EntryEligibilityEvaluation.objects.filter(
            setup__dataset_version=dataset,
            setup__strategy_version=strategy,
        )
        .select_related("setup", "target_level")
        .order_by("id")
    ):
        evaluation_hash_mismatches += row.evidence_hash != evidence_hash(row.evidence)
        cross_strategy_evaluations += bool(
            row.target_level_id
            and (
                row.target_level.dataset_version_id != dataset.pk
                or row.target_level.strategy_version_id != strategy.pk
                or row.target_level.stable_key != row.target_stable_key
            )
        )
        entry_status[row.decision] += 1
        projection_row = {
            "book": row.book_identity,
            "decision": row.decision,
            "evidence_hash": row.evidence_hash,
        }
        evaluations_by_setup[row.setup_id].append(projection_row)
        evaluation_rows.append(
            {
                "book_identity": row.book_identity,
                "conversion_effective_at": _iso(row.conversion_effective_at),
                "conversion_identity": row.conversion_identity,
                "conversion_rate_to_cad": _decimal(row.conversion_rate_to_cad),
                "decision": row.decision,
                "entry_price": _decimal(row.entry_price),
                "entry_timestamp": _iso(row.entry_timestamp),
                "evidence": row.evidence,
                "evidence_hash": row.evidence_hash,
                "reward_risk": _decimal(row.reward_risk),
                "risk_per_unit_cad": _decimal(row.risk_per_unit_cad),
                "risk_per_unit_quote": _decimal(row.risk_per_unit_quote),
                "setup_evidence_hash": row.setup.evidence_hash,
                "stop_price": _decimal(row.stop_price),
                "target_price": _decimal(row.target_price),
                "target_stable_key": row.target_stable_key,
                "terminal_reason": row.terminal_reason,
            }
        )

    setup_rows = []
    projection_setups = []
    setup_hash_mismatches = 0
    attribution_mismatches = 0
    direction = Counter()
    confirmation_status = Counter()
    book_membership = Counter()
    for row in setups:
        expected_hash = evidence_hash(
            {
                "sweep": row.sweep_evidence,
                "bias": row.bias_evidence,
                "provisional_swing": row.provisional_swing_evidence,
                "threshold": row.threshold_evidence,
            }
        )
        setup_hash_mismatches += row.evidence_hash != expected_hash
        attributed = attribution_by_setup[row.id]
        attribution_mismatches += len(attributed) != len(row.attribution_keys) or set(
            attributed
        ) != set(row.attribution_keys)
        confirmation = confirmations.get(row.id)
        direction[row.direction] += 1
        confirmation_status[confirmation.to_state if confirmation else "MISSING"] += 1
        books = tuple(item["book"] for item in evaluations_by_setup[row.id])
        book_membership["|".join(books) if books else "NONE"] += 1
        setup_rows.append(
            {
                "attribution_keys": row.attribution_keys,
                "bias_evidence": row.bias_evidence,
                "dataset_manifest_sha256": dataset.manifest_sha256,
                "detector_identity": row.detector_version,
                "direction": row.direction,
                "evidence_hash": row.evidence_hash,
                "initial_state": row.initial_state,
                "instrument": row.instrument.code,
                "provisional_swing_evidence": row.provisional_swing_evidence,
                "strategy_content_sha256": strategy.content_hash,
                "sweep_evidence": row.sweep_evidence,
                "sweep_h1_timestamp": row.sweep_h1_timestamp.isoformat(),
                "threshold_evidence": row.threshold_evidence,
            }
        )
        projection_setups.append(
            {
                "instrument": row.instrument.code,
                "logical_key": row.evidence_hash,
                "attribution_keys": list(row.attribution_keys),
                "confirmation_hash": confirmation.evidence_hash if confirmation else None,
                "censored_sha256": None,
                "evaluations": evaluations_by_setup[row.id],
            }
        )

    job_rows = [
        {
            "as_of": job.as_of.isoformat(),
            "config_hash": job.config_hash,
            "dataset_manifest_sha256": dataset.manifest_sha256,
            "evidence": job.evidence,
            "idempotency_key": job.idempotency_key,
            "job_name": job.job_name,
            "status": job.status,
            "strategy_content_sha256": strategy.content_hash,
        }
    ]
    tables = {
        "research_analysisrun": analysis_rows,
        "research_entryeligibilityevaluation": evaluation_rows,
        "research_jobrun": job_rows,
        "research_level": level_rows,
        "research_levellifecycleevent": lifecycle_rows,
        "research_setupevent": setup_rows,
        "research_setuplevelattribution": attribution_rows,
        "research_setuptransition": transition_rows,
    }
    per_table = {
        table: {"rows": len(rows), "sha256": _table_hash(rows)}
        for table, rows in sorted(tables.items())
    }
    projection = {
        "analyses": [
            {
                "instrument": row["instrument"],
                "completed_at": row["completed_at"],
                "result": row["result"],
                "setup_keys": row["setup_keys"],
                "evidence_hash": row["evidence_hash"],
            }
            for row in analysis_rows
        ],
        "levels": projection_levels,
        "setups": projection_setups,
    }
    report = job.evidence.get("report", {})
    report_body = {key: value for key, value in report.items() if key != "report_sha256"}
    configuration = job.evidence.get("configuration")
    duplicates = {
        "analysis": AnalysisRun.objects.filter(dataset_version=dataset, strategy_version=strategy)
        .values("instrument_id", "completed_h1_timestamp", "detector_version", "dataset_version_id")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .count(),
        "attribution": SetupLevelAttribution.objects.filter(
            setup__dataset_version=dataset, setup__strategy_version=strategy
        )
        .values("setup_id", "level_id")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .count(),
        "evaluation": EntryEligibilityEvaluation.objects.filter(
            setup__dataset_version=dataset, setup__strategy_version=strategy
        )
        .values("setup_id", "book_identity")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .count(),
        "level": Level.objects.filter(dataset_version=dataset, strategy_version=strategy)
        .values("stable_key")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .count(),
        "setup": SetupEvent.objects.filter(dataset_version=dataset, strategy_version=strategy)
        .values(
            "instrument_id",
            "direction",
            "sweep_h1_timestamp",
            "detector_version",
            "dataset_version_id",
        )
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .count(),
        "transition": SetupTransition.objects.filter(
            dataset_version=dataset, strategy_version=strategy
        )
        .values("setup_id", "from_state", "book_identity")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .count(),
    }
    integrity = {
        "analysis_evidence_hash_mismatches": analysis_hash_mismatches,
        "attribution_mismatches": attribution_mismatches,
        "cross_strategy_attributions": cross_strategy_attributions,
        "cross_strategy_evaluations": cross_strategy_evaluations,
        "cross_strategy_transitions": cross_strategy_transitions,
        "duplicate_groups": duplicates,
        "evaluation_evidence_hash_mismatches": evaluation_hash_mismatches,
        "lifecycle_evidence_hash_mismatches": lifecycle_hash_mismatches,
        "setup_evidence_hash_mismatches": setup_hash_mismatches,
        "setups_without_confirmation": len(setups) - len(confirmations),
        "transition_evidence_hash_mismatches": transition_hash_mismatches,
    }
    distributions = {
        "entry_evaluation_status": dict(sorted(entry_status.items())),
        "setup_book_membership": dict(sorted(book_membership.items())),
        "setup_confirmation_status": dict(sorted(confirmation_status.items())),
        "setup_direction": dict(sorted(direction.items())),
    }
    hashes = {
        "configuration_sha256": canonical_hash(configuration),
        "projection_sha256": canonical_hash(projection),
        "report_sha256": canonical_hash(report_body),
    }
    analysis_membership = {
        instrument: {
            "count": len(timestamps),
            "timestamp_membership_sha256": hashlib.sha256(
                json.dumps(
                    [timestamp.isoformat() for timestamp in timestamps],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        }
        for instrument, timestamps in sorted(analysis_members.items())
    }
    return {
        "aggregate_evidence_sha256": canonical_hash(per_table),
        "analysis_membership": analysis_membership,
        "data_quality": report.get("data_quality"),
        "distributions": distributions,
        "hashes": hashes,
        "integrity": integrity,
        "per_table": per_table,
    }


def reconstruct_v2_s1_outcome(*, job, dataset, strategy) -> dict:
    stored = _stored_evidence(job, dataset, strategy)
    inventory = _inventory_evidence(dataset)
    return {
        "application_state": _application_state(),
        "inventory": inventory,
        "stored_evidence": stored,
        "v1_preservation": _v1_digests(),
    }


def _all_zero(value) -> bool:
    if isinstance(value, dict):
        return all(_all_zero(item) for item in value.values())
    return value == 0


def verify_reconstructed_v2_s1_outcome(reconstructed: dict, artifact: dict) -> None:
    if reconstructed.get("application_state") != artifact.get("application_state"):
        raise V2S1OutcomeRefusal("application table state changed")
    if reconstructed.get("inventory") != artifact.get("inventory"):
        raise V2S1OutcomeRefusal("sealed inventory membership changed")
    if reconstructed.get("v1_preservation") != artifact.get("v1_preservation"):
        raise V2S1OutcomeRefusal("v1 evidence changed")
    stored = reconstructed.get("stored_evidence", {})
    if stored != artifact.get("stored_evidence"):
        raise V2S1OutcomeRefusal("v2 S1 stored evidence changed")
    if {table: row["rows"] for table, row in stored.get("per_table", {}).items()} != (
        artifact.get("accepted_delta", {}).get("per_table")
    ):
        raise V2S1OutcomeRefusal("v2 S1 row counts changed")
    if stored.get("hashes") != {
        "configuration_sha256": CONFIGURATION_SHA256,
        "projection_sha256": PROJECTION_SHA256,
        "report_sha256": REPORT_SHA256,
    }:
        raise V2S1OutcomeRefusal("v2 S1 configuration, projection, or report changed")
    if not _all_zero(stored.get("integrity", {})):
        raise V2S1OutcomeRefusal("v2 S1 evidence is duplicate, orphaned, crossed, or altered")
    if not _all_zero(reconstructed.get("inventory", {}).get("integrity", {})):
        raise V2S1OutcomeRefusal("sealed inventory is incomplete, invalid, or conflicting")
    inventory_instruments = reconstructed["inventory"]["instruments"]
    expected_analysis_membership = {
        instrument: {
            "count": evidence["counts"]["H1"],
            "timestamp_membership_sha256": evidence["h1_completion_membership_sha256"],
        }
        for instrument, evidence in inventory_instruments.items()
    }
    if stored.get("analysis_membership") != expected_analysis_membership:
        raise V2S1OutcomeRefusal("H1 analysis membership differs from sealed inventory")
    if stored.get("data_quality") != {"analysis_data_incomplete": 0, "cancelled": 0}:
        raise V2S1OutcomeRefusal("v2 S1 contains unresolved data-quality evidence")


def build_v2_s1_outcome_candidate(*, job, s0_job, dataset, strategy) -> dict:
    authorization = inspect_v2_s1_execution_authorization()
    reconstructed = reconstruct_v2_s1_outcome(job=job, dataset=dataset, strategy=strategy)
    return {
        "accepted_delta": {
            "every_other_application_table": 0,
            "per_table": EXPECTED_ROW_COUNTS,
            "total_inserted_rows": EXPECTED_TOTAL_INSERTED_ROWS,
        },
        "application_state": reconstructed["application_state"],
        "authority": AUTHORITY,
        "bindings": authorization["bindings"],
        "execution": {
            "authorization_artifact_sha256": EXECUTION_ARTIFACT_SHA256,
            "authorization_self_sha256": EXECUTION_POLICY_SHA256,
            "configuration_sha256": CONFIGURATION_SHA256,
            "job_identity": JOB_IDENTITY,
            "projection_sha256": PROJECTION_SHA256,
            "report_sha256": REPORT_SHA256,
            "runner_artifact_sha256": RUNNER_ARTIFACT_SHA256,
        },
        "identity": IDENTITY,
        "inventory": reconstructed["inventory"],
        "operational_anchors": {
            "dataset_version_id": dataset.pk,
            "job_run_id": job.pk,
            "s0_job_run_id": s0_job.pk,
            "strategy_version_id": strategy.pk,
        },
        "operational_corroboration": {
            "execution_log_primary_authority": False,
            "execution_log_sha256": EXECUTION_LOG_SHA256,
        },
        "repository_baseline": REPOSITORY_BASELINE,
        "schema": SCHEMA,
        "status": "ACCEPTED_RETURN_BLIND_V2_S1_EVIDENCE",
        "stored_evidence": reconstructed["stored_evidence"],
        "v1_preservation": reconstructed["v1_preservation"],
    }


def verify_persistent_v2_s1_outcome() -> dict:
    if connection.vendor != "postgresql":
        raise V2S1OutcomeRefusal("persistent v2 S1 acceptance requires PostgreSQL")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != "trade_recommender_research":
                raise V2S1OutcomeRefusal("v2 S1 acceptance targeted the wrong database")
        artifact = load_v2_s1_outcome_acceptance()
        job, _s0_job, dataset, strategy = select_persistent_v2_s1_evidence()
        reconstructed = reconstruct_v2_s1_outcome(job=job, dataset=dataset, strategy=strategy)
        verify_reconstructed_v2_s1_outcome(reconstructed, artifact)
        # The semantic selector is primary. The recorded key is only a final audit anchor.
        if job.pk != artifact["operational_anchors"]["job_run_id"]:
            raise V2S1OutcomeRefusal("v2 S1 operational anchor changed")
        return artifact


def v2_s1_outcome_readiness() -> dict:
    artifact = load_v2_s1_outcome_acceptance()
    return {
        "status": "V2_S1_ACCEPTED_LATER_STAGES_SEPARATELY_UNAUTHORIZED",
        "artifact_sha256": ARTIFACT_SHA256,
        "acceptance_sha256": artifact["acceptance_sha256"],
        "v2_s1_outcome": "ACCEPTED",
        "repeat_v2_s1_execution": False,
        "return_blind_geometry_implementation": False,
        "returns_or_backtesting": False,
        "promotion_or_live_trading": False,
    }
