"""Return-blind v2 S1 geometry projection and fixed-path verifier.

The live path reads only accepted S1 identities, pre-entry setup metadata, and
sealed D/H1 timestamps. It never selects candle prices, outcomes, or returns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from time import perf_counter

from market.quality import registered_candle_completion
from research.s2_geometry import (
    capacity_diagnostic,
    cluster_summary,
    concentration,
    detectable_effect,
    entry_week,
    session,
    stamp,
    timestamp,
)
from research.s2_geometry import (
    geometry as established_geometry,
)
from research.s2_policy import COMBINED_BOOK

REPOSITORY_BASELINE = "f6b498b187d433058e32b2c004be26ce882f71f5"
SCHEMA = "failed-break-v2-s1-return-blind-geometry-v1"
IDENTITY = "failed-break-v2-s1-geometry-v1"
S1_ACCEPTANCE_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs/strategy/failed-break/v2/s1-outcome-acceptance-v2.json"
)
S1_ACCEPTANCE_FILE_SHA256 = "5760dd2dd60a2d6a6087b5116b085a8a3774db1512962af0622bc0e3eeed93d5"
S1_ACCEPTANCE_SELF_SHA256 = "5f1497b7e47da958469d8b8c13d2608243e7a0f811eb30f54f4d5fe65f2bbcab"
S1_AGGREGATE_EVIDENCE_SHA256 = "4fd959c4185034599f9eee803d476aa7249fb995d2560325071b3fc4dbb5c2d1"
S1_PROJECTION_SHA256 = "5aab5a0e20eae00c6984a7740d9df5d14f0c575b3b0a997b66e055818d66e714"
S1_CONFIGURATION_SHA256 = "cff541256f9d2138260e2b7ebe04d44ff3e2ddaa0ddeafd5f0058c69af13f08b"
S1_REPORT_SHA256 = "02ce750ee803881a06877a0474cea94f6f04e63439f979041fb294569ae2af2a"

ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent / "docs/strategy/failed-break/v2/s1-geometry-v2.json"
)
REPORT_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs/strategy/failed-break/v2/s1-geometry-decision-report.md"
)
ARTIFACT_FILE_SHA256 = "b3bc76fa4ac226793a24f11a9a65f9b549e7231ace11e399f6d81c1599e41fdc"
ARTIFACT_SELF_SHA256 = "a3c2f7e3f3f7d722228233c158b51eaa296557daf0c19860c79848a788ffc140"
DECISION_REPORT_FILE_SHA256 = "63cc1be510e2de520c8f2f21a5c0982f4e6768d8e36f6688b7c7499558b521cf"

DATASET_NAME = "failed-break-provider-observed-historical"
DATASET_VERSION = "phase-2b1r-v2"
DATA_IDENTITY = "oanda-ba-ny17-friday-provider-observed-v2"
DATASET_MANIFEST_SHA256 = "11da094fc7ca6a30e946be33523757d7ab559a9ad1951c9142e8969539930014"
CONTRACT_SHA256 = "d630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c"
INVENTORY_SHA256 = "f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427"
REGISTRATION_CONFIGURATION_SHA256 = (
    "dc12d05ba149b01ec2f5ed4228d64622bc675b58c7d790fe676d2b46370d18e2"
)
REGISTRATION_REPORT_SHA256 = "871ba55669da47577c6eb65c46bf8fb86ba6aef73fe7dd322ff37c67b3f280c2"
STRATEGY_VERSION = "failed-break-phase-1-admission-correction-v2"
DETECTOR_IDENTITY = "failed-break-detector-v2-admission-correction"
STRATEGY_CONTENT_SHA256 = "3b9188749c10581d7518e25838a2cb65704d1329e7ebe3061cd7fe4b82115861"
S1_JOB_IDENTITY = "failed-break-signal-count-s1-v2"
DEVELOPMENT_START = datetime(2010, 1, 1, 5, tzinfo=UTC)
DEVELOPMENT_END = datetime(2019, 1, 1, 5, tzinfo=UTC)
TARGET_EFFECT_R = Fraction(1, 5)
CALENDAR_MONTHS = 108

FAMILY_BOOKS = {
    "PREVIOUS_WEEKLY_EXTREME": "failed-break-weekly-extreme-v1",
    "CONFIRMED_DAILY_SWING": "failed-break-daily-swing-v1",
    "TWENTY_SESSION_BREAKOUT_FLIP": "failed-break-breakout-flip-v1",
}
BOOKS = tuple(sorted((COMBINED_BOOK, *FAMILY_BOOKS.values())))
REFERENCE_S2_04_FLOORS = {
    "minimum_included_confirmed_physical_setups": 100,
    "minimum_entry_eligible_physical_events": 50,
    "minimum_resolved_allocated_physical_trades": 50,
    "minimum_paired_physical_events": 30,
    "minimum_nonempty_entry_date_clusters": 40,
    "minimum_nonempty_entry_week_clusters": 30,
    "minimum_kish_entry_week_clusters": "30",
    "minimum_kish_shared_factor_clusters": "20",
    "observation_calendar_days": 1095,
    "required_registered_coverage_fraction": "1",
    "maximum_unresolved_data_count": 0,
}
V1_SUMMARY = {
    "book_memberships": 204,
    "physical_events": 90,
    "nonempty_entry_dates": 81,
    "entry_week_clusters": 73,
    "entry_week_kish": "2025/34",
    "shared_factor_clusters": 74,
    "shared_factor_kish": "4050/67",
    "maximum_horizon_concurrency": 5,
}


class V2GeometryRefusal(ValueError):
    """Fail-closed geometry or artifact refusal."""


def require(condition, message):
    if not condition:
        raise V2GeometryRefusal(message)


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_s1_acceptance() -> dict:
    raw = S1_ACCEPTANCE_PATH.read_bytes()
    require(
        hashlib.sha256(raw).hexdigest() == S1_ACCEPTANCE_FILE_SHA256, "S1 acceptance file drift"
    )
    artifact = json.loads(raw)
    require(canonical_bytes(artifact) + b"\n" == raw, "S1 acceptance is not canonical")
    body = dict(artifact)
    require(
        body.pop("acceptance_sha256", None) == S1_ACCEPTANCE_SELF_SHA256 == digest(body),
        "S1 acceptance self-hash drift",
    )
    require(
        artifact["stored_evidence"]["aggregate_evidence_sha256"] == S1_AGGREGATE_EVIDENCE_SHA256
        and artifact["stored_evidence"]["hashes"]
        == {
            "configuration_sha256": S1_CONFIGURATION_SHA256,
            "projection_sha256": S1_PROJECTION_SHA256,
            "report_sha256": S1_REPORT_SHA256,
        },
        "S1 accepted evidence pins changed",
    )
    bindings = artifact["bindings"]
    require(
        bindings["dataset"]["name"] == DATASET_NAME
        and bindings["dataset"]["version"] == DATASET_VERSION
        and bindings["dataset"]["effective_data_identity"] == DATA_IDENTITY
        and bindings["dataset"]["manifest_sha256"] == DATASET_MANIFEST_SHA256
        and bindings["dataset"]["contract_sha256"] == CONTRACT_SHA256
        and bindings["dataset"]["global_semantic_inventory_sha256"] == INVENTORY_SHA256
        and bindings["strategy"]["identity"] == STRATEGY_VERSION
        and bindings["strategy"]["detector_identity"] == DETECTOR_IDENTITY
        and bindings["strategy"]["content_sha256"] == STRATEGY_CONTENT_SHA256,
        "accepted v2 dataset or strategy identity changed",
    )
    require(
        artifact["authority"]
        == {
            "promotion_or_live_trading": False,
            "provider_production_or_deployment": False,
            "return_blind_geometry_implementation": False,
            "returns_or_backtesting": False,
            "v2_s1_outcome": "ACCEPTED",
        },
        "source S1 authority changed",
    )
    return artifact


# Every query has an exact output allowlist and hard row bound. No caller may
# provide SQL, table names, predicates, or additional projected fields.
QUERIES = {
    "isolation": (
        ("database", "read_only", "isolation", "server_address"),
        "SELECT current_database() AS database, current_setting('transaction_read_only') AS read_only, "
        "current_setting('transaction_isolation') AS isolation, inet_server_addr() AS server_address",
        1,
    ),
    "job": (
        (
            "job_id",
            "job_name",
            "status",
            "config_hash",
            "report_sha256",
            "projection_sha256",
            "confirmed",
            "included_confirmed",
            "entry_pending",
            "dataset_id",
            "dataset_name",
            "dataset_version",
            "dataset_manifest_sha256",
            "dataset_contract_sha256",
            "strategy_id",
            "strategy_version",
            "detector",
            "data_identity",
            "strategy_content_sha256",
        ),
        "SELECT j.id AS job_id,j.job_name,j.status,j.config_hash,"
        "j.evidence->'report'->>'report_sha256' AS report_sha256,"
        "j.evidence->'report'->>'canonical_evidence_sha256' AS projection_sha256,"
        "(j.evidence->'report'->'setup_counts'->>'confirmed')::integer AS confirmed,"
        "(j.evidence->'report'->'setup_counts'->>'included_confirmed')::integer AS included_confirmed,"
        "(j.evidence->'report'->'setup_counts'->'eligibility_decisions'->>'ENTRY_PENDING')::integer AS entry_pending,"
        "d.id AS dataset_id,d.name AS dataset_name,d.version AS dataset_version,"
        "d.manifest_sha256 AS dataset_manifest_sha256,d.data_contract_sha256 AS dataset_contract_sha256,"
        "sv.id AS strategy_id,sv.version AS strategy_version,sv.detector_version AS detector,"
        "sv.data_identity,sv.content_hash AS strategy_content_sha256 "
        "FROM research_jobrun j JOIN market_datasetversion d ON d.id=j.dataset_version_id "
        "JOIN research_strategyversion sv ON sv.id=j.strategy_version_id "
        "WHERE j.job_name='failed-break-signal-count-s1-v2' "
        "AND d.version='phase-2b1r-v2' AND sv.version='failed-break-phase-1-admission-correction-v2'",
        1,
    ),
    "lineage": (
        (
            "contract_id",
            "contract_identity",
            "contract_sha256",
            "inventory_sha256",
            "plan_identity",
            "plan_contract_id",
            "registration_contract_id",
            "registration_configuration_sha256",
            "registration_report_sha256",
            "registration_inventory_sha256",
            "discovery_sealed",
        ),
        "SELECT c.id AS contract_id,c.identity AS contract_identity,c.sha256 AS contract_sha256,"
        "c.global_semantic_inventory_sha256 AS inventory_sha256,p.identity AS plan_identity,"
        "p.data_contract_id AS plan_contract_id,r.data_contract_id AS registration_contract_id,"
        "r.configuration_sha256 AS registration_configuration_sha256,r.report_sha256 AS registration_report_sha256,"
        "r.global_semantic_inventory_sha256 AS registration_inventory_sha256,"
        "dp.sealed_at IS NOT NULL AS discovery_sealed "
        "FROM market_datasetversion d JOIN market_datasetregistration r ON r.dataset_version_id=d.id "
        "JOIN market_historicaldatasetplan p ON p.id=r.plan_id "
        "JOIN market_historicaldatacontract c ON c.id=p.data_contract_id "
        "JOIN market_historicaldiscoveryregistration dr ON dr.id=c.discovery_registration_id "
        "JOIN market_historicaldiscoveryplan dp ON dp.id=dr.plan_id "
        "WHERE d.version='phase-2b1r-v2'",
        1,
    ),
    "evaluations": (
        (
            "evaluation_id",
            "setup_id",
            "book",
            "entry_at",
            "risk_per_unit_cad",
            "evaluation_hash",
            "instrument_id",
            "instrument",
            "base",
            "quote",
            "direction",
            "sweep_at",
            "detector",
            "dataset_id",
            "strategy_id",
            "setup_hash",
            "confirmation_at",
            "confirmation_hash",
            "confirmation_job_id",
            "eligibility_transition_hash",
            "eligibility_job_id",
        ),
        "SELECT e.id AS evaluation_id,s.id AS setup_id,e.book_identity AS book,e.entry_timestamp AS entry_at,"
        "e.risk_per_unit_cad::text AS risk_per_unit_cad,e.evidence_hash AS evaluation_hash,"
        "i.id AS instrument_id,i.code AS instrument,i.base_currency AS base,i.quote_currency AS quote,"
        "s.direction,s.sweep_h1_timestamp AS sweep_at,s.detector_version AS detector,"
        "s.dataset_version_id AS dataset_id,s.strategy_version_id AS strategy_id,s.evidence_hash AS setup_hash,"
        "c.effective_at AS confirmation_at,c.evidence_hash AS confirmation_hash,c.job_run_id AS confirmation_job_id,"
        "t.evidence_hash AS eligibility_transition_hash,t.job_run_id AS eligibility_job_id "
        "FROM research_entryeligibilityevaluation e JOIN research_setupevent s ON s.id=e.setup_id "
        "JOIN market_instrument i ON i.id=s.instrument_id "
        "JOIN research_strategyversion sv ON sv.id=s.strategy_version_id "
        "JOIN market_datasetversion d ON d.id=s.dataset_version_id "
        "JOIN research_setuptransition c ON c.setup_id=s.id AND c.book_identity='' "
        "AND c.from_state='TRIGGER_PENDING' AND c.to_state='CONFIRMED' "
        "JOIN research_setuptransition t ON t.setup_id=s.id AND t.book_identity=e.book_identity "
        "AND t.from_state='CONFIRMED' AND t.to_state=e.decision "
        "WHERE e.decision='ENTRY_PENDING' AND d.version='phase-2b1r-v2' "
        "AND sv.version='failed-break-phase-1-admission-correction-v2' "
        "ORDER BY e.entry_timestamp,s.id,e.book_identity",
        188,
    ),
    "entry_attributions": (
        ("setup_id", "level_key", "family", "activated_at", "dataset_id", "strategy_id"),
        "SELECT a.setup_id,l.stable_key AS level_key,l.family,l.activated_at,"
        "l.dataset_version_id AS dataset_id,l.strategy_version_id AS strategy_id "
        "FROM research_setuplevelattribution a JOIN research_level l ON l.id=a.level_id "
        "JOIN research_setupevent s ON s.id=a.setup_id "
        "JOIN research_strategyversion sv ON sv.id=s.strategy_version_id "
        "JOIN market_datasetversion d ON d.id=s.dataset_version_id "
        "WHERE d.version='phase-2b1r-v2' AND sv.version='failed-break-phase-1-admission-correction-v2' "
        "AND EXISTS(SELECT 1 FROM research_entryeligibilityevaluation e "
        "WHERE e.setup_id=s.id AND e.decision='ENTRY_PENDING') ORDER BY a.setup_id,l.stable_key",
        1213,
    ),
    "confirmed": (
        (
            "setup_id",
            "instrument_id",
            "instrument",
            "direction",
            "sweep_at",
            "detector",
            "dataset_id",
            "strategy_id",
            "setup_hash",
            "confirmation_at",
            "confirmation_hash",
            "job_id",
        ),
        "SELECT s.id AS setup_id,i.id AS instrument_id,i.code AS instrument,s.direction,"
        "s.sweep_h1_timestamp AS sweep_at,s.detector_version AS detector,"
        "s.dataset_version_id AS dataset_id,s.strategy_version_id AS strategy_id,s.evidence_hash AS setup_hash,"
        "t.effective_at AS confirmation_at,t.evidence_hash AS confirmation_hash,t.job_run_id AS job_id "
        "FROM research_setupevent s JOIN market_instrument i ON i.id=s.instrument_id "
        "JOIN research_strategyversion sv ON sv.id=s.strategy_version_id "
        "JOIN market_datasetversion d ON d.id=s.dataset_version_id "
        "JOIN research_setuptransition t ON t.setup_id=s.id AND t.book_identity='' "
        "AND t.from_state='TRIGGER_PENDING' AND t.to_state='CONFIRMED' "
        "WHERE d.version='phase-2b1r-v2' AND sv.version='failed-break-phase-1-admission-correction-v2' "
        "ORDER BY s.id",
        314,
    ),
    "confirmed_attributions": (
        ("setup_id", "level_key", "family", "activated_at", "dataset_id", "strategy_id"),
        "SELECT a.setup_id,l.stable_key AS level_key,l.family,l.activated_at,"
        "l.dataset_version_id AS dataset_id,l.strategy_version_id AS strategy_id "
        "FROM research_setuplevelattribution a JOIN research_level l ON l.id=a.level_id "
        "JOIN research_setupevent s ON s.id=a.setup_id "
        "JOIN research_strategyversion sv ON sv.id=s.strategy_version_id "
        "JOIN market_datasetversion d ON d.id=s.dataset_version_id "
        "WHERE d.version='phase-2b1r-v2' AND sv.version='failed-break-phase-1-admission-correction-v2' "
        "AND EXISTS(SELECT 1 FROM research_setuptransition t WHERE t.setup_id=s.id "
        "AND t.book_identity='' AND t.from_state='TRIGGER_PENDING' AND t.to_state='CONFIRMED') "
        "ORDER BY a.setup_id,l.stable_key",
        1213,
    ),
    "inventory": (
        ("instrument_id", "granularity", "timestamps"),
        "SELECT ch.instrument_id,ch.granularity,array_agg(o.timestamp ORDER BY o.timestamp) AS timestamps "
        "FROM market_historicaltimestampobservation o "
        "JOIN market_historicaltimestampinventory inv ON inv.id=o.inventory_id "
        "JOIN market_historicaldiscoverychunk ch ON ch.id=inv.chunk_id "
        "JOIN market_historicaldiscoveryregistration dr ON dr.plan_id=ch.plan_id "
        "JOIN market_historicaldatacontract c ON c.discovery_registration_id=dr.id "
        "WHERE c.identity='oanda-ba-ny17-friday-provider-observed-v2' "
        "AND ch.granularity IN ('D','H1') GROUP BY ch.instrument_id,ch.granularity "
        "ORDER BY ch.instrument_id,ch.granularity",
        12,
    ),
}


def read_allowed(cursor, name, fields):
    require(name in QUERIES, "query not allowlisted")
    allowed, sql, limit = QUERIES[name]
    require(tuple(fields) == allowed, "exact field allowlist required")
    cursor.execute(sql)
    require(
        tuple(column.name for column in cursor.description) == allowed, "database projection drift"
    )
    rows = cursor.fetchmany(limit + 1)
    require(len(rows) <= limit, f"{name} row bound exceeded")
    return [dict(zip(allowed, row, strict=True)) for row in rows]


def _factor_groups(events):
    by_week = defaultdict(list)
    for event in events:
        by_week[entry_week(event["entry_at"])].append(event)
    groups = {}
    for week, rows in sorted(by_week.items()):
        remaining = {row["physical_key"]: row for row in rows}
        while remaining:
            first = remaining.pop(min(remaining))
            component = [first["physical_key"]]
            currencies = {first["base"], first["quote"]}
            changed = True
            while changed:
                changed = False
                for key, row in list(remaining.items()):
                    if currencies & {row["base"], row["quote"]}:
                        component.append(key)
                        currencies.update((row["base"], row["quote"]))
                        remaining.pop(key)
                        changed = True
            groups[f"{week}|{digest(sorted(component))}"] = sorted(component)
    return dict(sorted(groups.items()))


def geometry_with_assignments(events):
    weeks = defaultdict(list)
    simultaneous = defaultdict(list)
    for event in events:
        key = event["physical_key"]
        entry = timestamp(event["entry_at"])
        weeks[entry_week(entry)].append(key)
        simultaneous[stamp(entry)].append(key)
    # The date definition is New York in the established implementation.
    established = established_geometry(events)
    assignments = {
        "entry_dates": _groups_from_summary(established["entry_dates"], events, "date"),
        "entry_weeks": {key: sorted(value) for key, value in sorted(weeks.items())},
        "shared_factors": _factor_groups(events),
        "simultaneous": {key: sorted(value) for key, value in sorted(simultaneous.items())},
    }
    for name in assignments:
        require(cluster_summary(assignments[name]) == established[name], f"{name} definition drift")
    return {**established, "cluster_assignments": assignments}


def _groups_from_summary(summary, events, kind):
    require(kind == "date", "unsupported cluster group")
    result = defaultdict(list)
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    for event in events:
        result[timestamp(event["entry_at"]).astimezone(ny).date().isoformat()].append(
            event["physical_key"]
        )
    groups = {key: sorted(value) for key, value in sorted(result.items())}
    require(cluster_summary(groups) == summary, "entry date definition drift")
    return groups


def _horizon(entry_at, daily, hourly):
    completions = tuple(registered_candle_completion(value, "D") for value in daily)
    start = bisect_right(completions, entry_at)
    if start + 9 >= len(completions):
        return None, (), None
    selected = daily[start : start + 10]
    tenth_completion = completions[start + 9]
    index = bisect_left(hourly, tenth_completion)
    return (
        hourly[index] if index < len(hourly) else None,
        selected,
        hourly[index - 1] if index else None,
    )


def _counter(values):
    return dict(sorted(Counter(values).items()))


def _ratio(value, denominator):
    fraction = Fraction(value, denominator) if denominator else Fraction(0)
    return {"exact": str(fraction), "decimal": format(float(fraction), ".10f")}


def _max_concentration(events, geometry, book_memberships):
    physical = {
        "instrument": _counter(event["instrument"] for event in events),
        "direction": _counter(event["direction"] for event in events),
        "session": _counter(session(event["entry_at"]) for event in events),
        "year": _counter(str(timestamp(event["entry_at"]).year) for event in events),
    }
    result = {}
    for name, counts in physical.items():
        key, value = max(counts.items(), key=lambda row: (row[1], row[0]))
        result[name] = {"key": key, "count": value, **_ratio(value, len(events))}
    book_key, book_value = max(book_memberships.items(), key=lambda row: (row[1], row[0]))
    result["book"] = {
        "key": book_key,
        "count": book_value,
        **_ratio(book_value, sum(book_memberships.values())),
    }
    for name in ("entry_weeks", "shared_factors"):
        key, value = max(geometry[name]["sizes"].items(), key=lambda row: (row[1], row[0]))
        result[name] = {"key": key, "count": value, **_ratio(value, len(events))}
    return result


def _floor_result(book, events, geometry, confirmed_coverage):
    known = {
        "minimum_included_confirmed_physical_setups": confirmed_coverage[book],
        "minimum_entry_eligible_physical_events": len(events),
        "minimum_nonempty_entry_date_clusters": geometry["entry_dates"]["raw_count"],
        "minimum_nonempty_entry_week_clusters": geometry["entry_weeks"]["raw_count"],
        "minimum_kish_entry_week_clusters": geometry["entry_weeks"]["kish_exact"],
        "minimum_kish_shared_factor_clusters": geometry["shared_factors"]["kish_exact"],
        "observation_calendar_days": (DEVELOPMENT_END - DEVELOPMENT_START).days,
        "required_registered_coverage_fraction": "1",
    }
    result = {
        field: {
            "threshold": REFERENCE_S2_04_FLOORS[field],
            "observed": value,
            "status": "SATISFIED"
            if Fraction(str(value)) >= Fraction(str(REFERENCE_S2_04_FLOORS[field]))
            else "FAILED",
        }
        for field, value in known.items()
    }
    for field in (
        "minimum_resolved_allocated_physical_trades",
        "minimum_paired_physical_events",
    ):
        threshold = REFERENCE_S2_04_FLOORS[field]
        result[field] = {
            "threshold": threshold,
            "observed": None,
            "cohort_upper_bound": len(events),
            "status": "FAILED" if len(events) < threshold else "UNKNOWABLE",
            "reason": "Outcome, resolution, and comparator evidence are unauthorized",
        }
    result["maximum_unresolved_data_count"] = {
        "threshold": 0,
        "s1_observed": 0,
        "observed": None,
        "status": "UNKNOWABLE",
        "reason": "Accepted S1 is clean; later execution evidence does not exist",
    }
    return result


def _mde(geometry, event_count):
    week = geometry["entry_weeks"]["kish_exact"]
    factor = geometry["shared_factors"]["kish_exact"]
    effective = min(Fraction(week), Fraction(factor))
    values = {
        "raw_event_count": detectable_effect(event_count),
        "entry_week_kish": detectable_effect(week),
        "shared_factor_kish": detectable_effect(factor),
        "conservative_effective_n": str(effective),
        "conservative_mde_R": detectable_effect(str(effective)),
    }
    values["target_0_20R_adequacy"] = {
        sigma: "ADEQUATE" if Fraction(value) <= TARGET_EFFECT_R else "INADEQUATE"
        for sigma, value in values["conservative_mde_R"].items()
    }
    return values


def _capacity_summary(events):
    full = capacity_diagnostic(events)
    rows = full.pop("rows")
    return {
        **full,
        "rows": len(rows),
        "rows_sha256": digest(rows),
        "zero_unit_physical_keys": sorted(row["physical_key"] for row in rows if row["units"] == 0),
    }


def _semantic_core(event):
    return tuple(event["natural_key"][:3])


def _v1_comparison(events, report):
    from research.s2_geometry import verify_committed

    v1 = verify_committed()
    v1_events = v1["events"]
    v1_cores = {_semantic_core(event) for event in v1_events}
    v2_cores = {_semantic_core(event) for event in events}
    geometry = report["books"][COMBINED_BOOK]["geometry"]
    v2_summary = {
        "book_memberships": sum(len(event["books"]) for event in events),
        "physical_events": len(events),
        "nonempty_entry_dates": geometry["entry_dates"]["raw_count"],
        "entry_week_clusters": geometry["entry_weeks"]["raw_count"],
        "entry_week_kish": geometry["entry_weeks"]["kish_exact"],
        "shared_factor_clusters": geometry["shared_factors"]["raw_count"],
        "shared_factor_kish": geometry["shared_factors"]["kish_exact"],
        "maximum_horizon_concurrency": geometry["allocation_phase_peak"],
    }
    return {
        "v1": V1_SUMMARY,
        "v2": v2_summary,
        "numeric_delta": {
            key: v2_summary[key] - V1_SUMMARY[key]
            for key in (
                "book_memberships",
                "physical_events",
                "nonempty_entry_dates",
                "entry_week_clusters",
                "shared_factor_clusters",
                "maximum_horizon_concurrency",
            )
        },
        "semantic_event_overlap": len(v1_cores & v2_cores),
        "v1_only_semantic_events": [list(value) for value in sorted(v1_cores - v2_cores)],
        "v2_only_semantic_events": [list(value) for value in sorted(v2_cores - v1_cores)],
        "unchanged_geometry_definitions": [
            "physical-event identity and book collapse",
            "New York entry date and ISO week",
            "transitive shared-currency factor clusters within entry week",
            "Kish effective count",
            "sealed ten-provider-D-session maximum horizon",
            "concentration and MDE formulas",
        ],
        "governed_detector_semantic_changes": [
            "Every sealed D/W member is admitted independently of H1 coincidence",
            "Supporting swing remains valid from pivot availability exclusive through confirmation inclusive unless strictly breached",
        ],
        "causal_limit": "Geometry identifies the changed cohort exactly; it does not infer a per-event counterfactual attribution between the two corrected detector rules",
    }


def build_report(events, confirmed_coverage):
    books = {}
    for book in BOOKS:
        rows = [event for event in events if book in event["books"]]
        geometry = (
            geometry_with_assignments(rows) if book == COMBINED_BOOK else established_geometry(rows)
        )
        capacity = _capacity_summary(rows)
        books[book] = {
            "eligible_physical_count": len(rows),
            "geometry": geometry,
            "capacity_diagnostic": capacity,
            "eligible_concentration": concentration(rows),
            "mde": _mde(geometry, len(rows)),
            "reference_s2_04_floors": _floor_result(book, rows, geometry, confirmed_coverage),
        }
    combined = books[COMBINED_BOOK]
    book_counts = _counter(book for event in events for book in event["books"])
    family_counts = _counter(family for event in events for family in event["families"])
    distributions = {
        "instrument": _counter(event["instrument"] for event in events),
        "direction": _counter(event["direction"] for event in events),
        "session": _counter(session(event["entry_at"]) for event in events),
        "book_identity": book_counts,
        "strategy_family": family_counts,
        "calendar_year": _counter(str(timestamp(event["entry_at"]).year) for event in events),
        "book_multiplicity": _counter(str(len(event["books"])) for event in events),
    }
    frequency = Fraction(len(events), CALENDAR_MONTHS)
    objective = {
        "equity_cad": "10000",
        "monthly_objective_cad": ["800", "1000"],
        "calendar_months": CALENDAR_MONTHS,
        "potential_events_per_month_exact": str(frequency),
        "potential_events_per_month_decimal": format(float(frequency), ".10f"),
        "risk_per_request_cad": "25",
        "optimistic_required_R_per_potential_event": {
            "800": format(float(Fraction(800, 25) / frequency), ".10f"),
            "1000": format(float(Fraction(1000, 25) / frequency), ".10f"),
        },
        "conclusion": "STRUCTURALLY_UNREALISTIC_BEFORE_OUTCOMES; fewer than one potential event per month requires extraordinary average R even before costs, capacity blocks, or losses",
    }
    report = {
        "books": books,
        "distributions": distributions,
        "maximum_concentration": _max_concentration(events, combined["geometry"], book_counts),
        "confirmed_coverage": confirmed_coverage,
        "physical_events": len(events),
        "book_memberships": sum(book_counts.values()),
        "nonempty_entry_dates": combined["geometry"]["entry_dates"]["raw_count"],
        "return_blind_fixed_equity_diagnostic": objective,
        "shared_factor_definition": "Connected components within New York ISO entry week, linked by either shared currency; transitive, direction/book ignored, unique physical events",
        "mde_method": "(z_0.975+z_0.80)*hypothetical_sigma/sqrt(n_eff); 95% two-sided normal design and 80% power",
        "geometry_mde_sigma_R": ["0.5", "1.0", "1.5"],
        "target_effect_R": "0.20",
        "combined_confirmatory_adequacy": combined["mde"]["target_0_20R_adequacy"],
        "confirmatory_adequacy_across_all_scenarios": False,
        "exploratory_returns_sample_assessment": "SUFFICIENT_ONLY_FOR_SEPARATELY_AUTHORIZED_DESCRIPTIVE_EXPLORATION; NOT_CONFIRMATORY_AND_NEVER_PROMOTION_AUTHORITY",
        "recommendation": {
            "choice": "REMAIN_EXPLORATORY_ONLY",
            "effective": False,
            "text": "Any later v2 return policy should remain exploratory-only with permanent non-promotion; this geometry does not authorize it",
        },
        "reference_floor_governance": "V1 S2-04 thresholds are comparison diagnostics only; they are not adopted or activated for v2",
        "actual_resolved_allocated_physical_trades": None,
        "actual_returns_or_outcomes": None,
    }
    report["v1_v2_comparison"] = _v1_comparison(events, report)
    return report


def _jsonable(value):
    if isinstance(value, datetime):
        return stamp(value)
    raise TypeError(type(value).__name__)


def _normalize(value):
    return json.loads(json.dumps(value, default=_jsonable))


def prepare_source(raw, acceptance):
    require(set(raw) == set(QUERIES), "incomplete source query bundle")
    for name, rows in raw.items():
        require(all(set(row) == set(QUERIES[name][0]) for row in rows), "source field drift")
    require(
        raw["isolation"]
        == [
            {
                "database": "trade_recommender_research",
                "read_only": "on",
                "isolation": "repeatable read",
                "server_address": None,
            }
        ],
        "research read-only socket isolation failed",
    )
    require(len(raw["job"]) == 1, "accepted v2 S1 job missing or duplicated")
    job = raw["job"][0]
    require(
        job
        == {
            "job_id": acceptance["operational_anchors"]["job_run_id"],
            "job_name": S1_JOB_IDENTITY,
            "status": "succeeded",
            "config_hash": S1_CONFIGURATION_SHA256,
            "report_sha256": S1_REPORT_SHA256,
            "projection_sha256": S1_PROJECTION_SHA256,
            "confirmed": 314,
            "included_confirmed": 313,
            "entry_pending": 188,
            "dataset_id": acceptance["bindings"]["dataset"]["operational_id"],
            "dataset_name": DATASET_NAME,
            "dataset_version": DATASET_VERSION,
            "dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
            "dataset_contract_sha256": CONTRACT_SHA256,
            "strategy_id": acceptance["bindings"]["strategy"]["operational_id"],
            "strategy_version": STRATEGY_VERSION,
            "detector": DETECTOR_IDENTITY,
            "data_identity": DATA_IDENTITY,
            "strategy_content_sha256": STRATEGY_CONTENT_SHA256,
        },
        "accepted v2 S1 job identity changed",
    )
    require(
        raw["lineage"]
        == [
            {
                "contract_id": 2,
                "contract_identity": DATA_IDENTITY,
                "contract_sha256": CONTRACT_SHA256,
                "inventory_sha256": INVENTORY_SHA256,
                "plan_identity": DATA_IDENTITY,
                "plan_contract_id": 2,
                "registration_contract_id": 2,
                "registration_configuration_sha256": REGISTRATION_CONFIGURATION_SHA256,
                "registration_report_sha256": REGISTRATION_REPORT_SHA256,
                "registration_inventory_sha256": INVENTORY_SHA256,
                "discovery_sealed": True,
            }
        ],
        "registered successor lineage changed",
    )
    series = {}
    series_hashes = {}
    for row in raw["inventory"]:
        key = (row["instrument_id"], row["granularity"])
        values = tuple(timestamp(value) for value in row["timestamps"])
        require(
            key not in series and values == tuple(sorted(set(values))), "sealed inventory conflict"
        )
        series[key] = values
        series_hashes[f"{key[0]}/{key[1]}"] = digest([stamp(value) for value in values])
    require(len(series) == 12, "six D/H1 sealed inventories required")
    accepted_inventory = acceptance["inventory"]["instruments"]
    instrument_codes = {row["instrument_id"]: row["instrument"] for row in raw["confirmed"]}
    for (instrument_id, granularity), values in series.items():
        code = instrument_codes[instrument_id]
        require(
            len(values) == accepted_inventory[code]["counts"][granularity]
            and digest([stamp(value) for value in values])
            == accepted_inventory[code]["timestamp_membership_sha256"][granularity],
            "sealed inventory differs from accepted S1 evidence",
        )

    confirmed_attrs = defaultdict(list)
    for row in raw["confirmed_attributions"]:
        confirmed_attrs[row["setup_id"]].append(row)
    confirmed_coverage = Counter()
    boundary_purged = []
    for row in raw["confirmed"]:
        require(
            row["detector"] == DETECTOR_IDENTITY
            and row["dataset_id"] == job["dataset_id"]
            and row["strategy_id"] == job["strategy_id"]
            and row["job_id"] == job["job_id"],
            "confirmed setup lineage changed",
        )
        attrs = confirmed_attrs[row["setup_id"]]
        require(
            attrs and len({item["level_key"] for item in attrs}) == len(attrs),
            "confirmed attribution drift",
        )
        families = sorted({item["family"] for item in attrs})
        require(set(families) <= set(FAMILY_BOOKS), "unknown level family")
        books = {COMBINED_BOOK, *(FAMILY_BOOKS[family] for family in families)}
        hourly = series[(row["instrument_id"], "H1")]
        daily = series[(row["instrument_id"], "D")]
        entry_index = bisect_left(hourly, timestamp(row["confirmation_at"]))
        require(entry_index < len(hourly), "confirmed setup lacks sealed H1 successor")
        entry = hourly[entry_index]
        horizon, _, _ = _horizon(entry, daily, hourly)
        if horizon is None or horizon >= DEVELOPMENT_END:
            boundary_purged.append(row["setup_id"])
        else:
            confirmed_coverage.update(books)
    require(
        len(raw["confirmed"]) == job["confirmed"]
        and confirmed_coverage[COMBINED_BOOK] == job["included_confirmed"]
        and len(boundary_purged) == 1,
        "confirmed coverage or boundary purge changed",
    )

    entry_attrs = defaultdict(list)
    for row in raw["entry_attributions"]:
        entry_attrs[row["setup_id"]].append(row)
    grouped = defaultdict(list)
    for row in raw["evaluations"]:
        grouped[row["setup_id"]].append(row)
    require(len(raw["evaluations"]) == 188 and len(grouped) == 83, "83/188 cohort changed")
    events = []
    purged_events = []
    witnesses = {}
    for setup_id, rows in sorted(grouped.items()):
        first = rows[0]
        invariant = (
            "entry_at",
            "risk_per_unit_cad",
            "instrument_id",
            "instrument",
            "base",
            "quote",
            "direction",
            "sweep_at",
            "detector",
            "dataset_id",
            "strategy_id",
            "setup_hash",
            "confirmation_at",
            "confirmation_hash",
            "confirmation_job_id",
        )
        require(
            all(all(row[field] == first[field] for field in invariant) for row in rows),
            "book geometry conflict",
        )
        require(
            first["detector"] == DETECTOR_IDENTITY
            and first["dataset_id"] == job["dataset_id"]
            and first["strategy_id"] == job["strategy_id"]
            and first["confirmation_job_id"] == job["job_id"]
            and all(row["eligibility_job_id"] == job["job_id"] for row in rows),
            "entry evidence lineage changed",
        )
        attrs = entry_attrs[setup_id]
        require(
            attrs and len({item["level_key"] for item in attrs}) == len(attrs),
            "entry attribution drift",
        )
        require(
            all(
                item["dataset_id"] == job["dataset_id"]
                and item["strategy_id"] == job["strategy_id"]
                and timestamp(item["activated_at"])
                <= timestamp(first["sweep_at"]) - timedelta(hours=1)
                for item in attrs
            ),
            "entry attribution lineage or timing changed",
        )
        families = sorted({item["family"] for item in attrs})
        expected_books = {COMBINED_BOOK, *(FAMILY_BOOKS[family] for family in families)}
        require(
            {row["book"] for row in rows} == expected_books and len(rows) == len(expected_books),
            "book membership does not match attributed families",
        )
        hourly = series[(first["instrument_id"], "H1")]
        daily = series[(first["instrument_id"], "D")]
        confirmation = timestamp(first["confirmation_at"])
        entry = timestamp(first["entry_at"])
        entry_index = bisect_left(hourly, confirmation)
        require(
            entry_index < len(hourly) and hourly[entry_index] == entry,
            "entry is not first sealed H1 successor",
        )
        horizon, selected_daily, prior_horizon = _horizon(entry, daily, hourly)
        natural_key = [
            first["instrument"],
            first["direction"],
            stamp(first["sweep_at"]),
            DETECTOR_IDENTITY,
            DATASET_VERSION,
        ]
        event = {
            "setup_id": setup_id,
            "physical_key": digest(natural_key),
            "natural_key": natural_key,
            "instrument": first["instrument"],
            "base": first["base"],
            "quote": first["quote"],
            "direction": first["direction"],
            "entry_at": stamp(entry),
            "confirmation_at": stamp(confirmation),
            "horizon_at": stamp(horizon) if horizon else None,
            "risk_per_unit_cad": first["risk_per_unit_cad"],
            "books": sorted(expected_books),
            "families": families,
            "setup_evidence_hash": first["setup_hash"],
            "confirmation_evidence_hash": first["confirmation_hash"],
            "evaluations": [
                {
                    "id": row["evaluation_id"],
                    "book": row["book"],
                    "evidence_hash": row["evaluation_hash"],
                    "transition_evidence_hash": row["eligibility_transition_hash"],
                }
                for row in sorted(rows, key=lambda value: value["book"])
            ],
        }
        if horizon is None or horizon >= DEVELOPMENT_END:
            purged_events.append(
                {
                    **event,
                    "purge_reason": "TEN_SESSION_HORIZON_CROSSES_DEVELOPMENT_BOUNDARY",
                }
            )
        else:
            events.append(event)
        completions = [registered_candle_completion(value, "D") for value in selected_daily]
        witnesses[str(setup_id)] = {
            "daily_starts": [stamp(value) for value in selected_daily],
            "daily_completions": [stamp(value) for value in completions],
            "prior_entry_open": stamp(hourly[entry_index - 1]) if entry_index else None,
            "entry_open": stamp(entry),
            "prior_horizon_open": stamp(prior_horizon) if prior_horizon else None,
            "horizon_open": stamp(horizon) if horizon else None,
        }
    events.sort(key=lambda event: (event["entry_at"], event["physical_key"]))
    purged_events.sort(key=lambda event: (event["entry_at"], event["physical_key"]))
    require(
        len(events) + len(purged_events) == 83
        and len({event["physical_key"] for event in [*events, *purged_events]}) == 83
        and sum(len(event["books"]) for event in [*events, *purged_events]) == 188
        and len(purged_events) == 1
        and purged_events[0]["setup_id"] in boundary_purged,
        "physical-event collapse changed",
    )
    source_hashes = {name: digest(_normalize(rows)) for name, rows in raw.items()}
    source = {
        "query_row_counts": {name: len(rows) for name, rows in raw.items()},
        "query_result_sha256": source_hashes,
        "inventory_series_sha256": series_hashes,
        "timestamp_witnesses": witnesses,
        "confirmed_coverage": dict(sorted(confirmed_coverage.items())),
        "boundary_purged_setup_ids": boundary_purged,
    }
    return events, purged_events, source


def build_artifact(raw):
    acceptance = load_s1_acceptance()
    events, purged_events, source = prepare_source(raw, acceptance)
    report = build_report(events, source["confirmed_coverage"])
    memberships = [[event["physical_key"], book] for event in events for book in event["books"]]
    source_memberships = [
        [event["physical_key"], book]
        for event in [*events, *purged_events]
        for book in event["books"]
    ]
    body = {
        "schema": SCHEMA,
        "identity": IDENTITY,
        "repository_baseline": REPOSITORY_BASELINE,
        "source_s1_acceptance": {
            "artifact_sha256": S1_ACCEPTANCE_FILE_SHA256,
            "self_sha256": S1_ACCEPTANCE_SELF_SHA256,
            "aggregate_evidence_sha256": S1_AGGREGATE_EVIDENCE_SHA256,
            "projection_sha256": S1_PROJECTION_SHA256,
            "configuration_sha256": S1_CONFIGURATION_SHA256,
            "report_sha256": S1_REPORT_SHA256,
        },
        "bindings": acceptance["bindings"],
        "query_contract": {
            name: {
                "fields": list(fields),
                "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
                "max_rows": limit,
            }
            for name, (fields, sql, limit) in QUERIES.items()
        },
        "source_projection": source,
        "source_projection_sha256": digest(source),
        "events": events,
        "event_set_sha256": digest(events),
        "memberships_sha256": digest(memberships),
        "source_memberships_sha256": digest(source_memberships),
        "purged_events": purged_events,
        "purged_event_set_sha256": digest(purged_events),
        "source_entry_pending_evaluations": 188,
        "source_physical_events": 83,
        "report": report,
        "report_sha256": digest(report),
        "return_blindness": {
            "allowed": [
                "semantic identities",
                "row status",
                "pre-entry timestamps",
                "pre-entry CAD unit risk",
                "sealed D/H1 timestamp membership",
            ],
            "forbidden": [
                "candle prices",
                "post-entry candle paths",
                "stop or target outcomes",
                "trade exits",
                "wins or losses",
                "returns or P&L",
                "drawdown",
                "paper trades",
                "backtests",
                "provider data",
            ],
            "candle_table_access": False,
            "outcome_or_return_access": False,
            "persistent_database_writes": False,
        },
        "authority": {
            "return_blind_geometry_analysis": "COMPLETED",
            "effective_s2_policy": False,
            "return_execution": False,
            "backtesting": False,
            "promotion_or_live_trading": False,
            "provider_production_or_deployment": False,
        },
    }
    body["geometry_sha256"] = digest(body)
    return body


def read_research_once():
    """One bounded, explicitly read-only projection; callers may compare two runs."""
    import psycopg

    started = perf_counter()
    load_s1_acceptance()
    with psycopg.connect(
        dbname="trade_recommender_research",
        user="trade_recommender",
        host="/tmp",
        password="",
        passfile="/dev/null",
        connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=60000 -c lock_timeout=2000 -c application_name=v2_s1_geometry",
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            try:
                raw = {
                    name: read_allowed(cursor, name, fields)
                    for name, (fields, _sql, _limit) in QUERIES.items()
                }
            finally:
                cursor.execute("ROLLBACK")
    artifact = build_artifact(raw)
    return {"artifact": artifact, "elapsed_seconds": round(perf_counter() - started, 6)}


def _verify_artifact_bytes(raw, expected_file_sha256):
    require(
        hashlib.sha256(raw).hexdigest() == expected_file_sha256,
        "geometry artifact file digest changed",
    )
    artifact = json.loads(raw)
    require(canonical_bytes(artifact) + b"\n" == raw, "geometry artifact is not canonical")
    body = dict(artifact)
    require(
        body.pop("geometry_sha256", None) == ARTIFACT_SELF_SHA256 == digest(body),
        "geometry self-hash changed",
    )
    return artifact


def verify_committed():
    acceptance = load_s1_acceptance()
    artifact = _verify_artifact_bytes(ARTIFACT_PATH.read_bytes(), ARTIFACT_FILE_SHA256)
    require(
        artifact["schema"] == SCHEMA and artifact["identity"] == IDENTITY,
        "geometry identity changed",
    )
    require(artifact["repository_baseline"] == REPOSITORY_BASELINE, "geometry baseline changed")
    require(artifact["bindings"] == acceptance["bindings"], "accepted bindings changed")
    require(
        artifact["source_s1_acceptance"]
        == {
            "artifact_sha256": S1_ACCEPTANCE_FILE_SHA256,
            "self_sha256": S1_ACCEPTANCE_SELF_SHA256,
            "aggregate_evidence_sha256": S1_AGGREGATE_EVIDENCE_SHA256,
            "projection_sha256": S1_PROJECTION_SHA256,
            "configuration_sha256": S1_CONFIGURATION_SHA256,
            "report_sha256": S1_REPORT_SHA256,
        },
        "source S1 pins changed",
    )
    for name, (fields, sql, limit) in QUERIES.items():
        require(
            artifact["query_contract"][name]
            == {
                "fields": list(fields),
                "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
                "max_rows": limit,
            },
            "query contract changed",
        )
    events = artifact["events"]
    purged = artifact["purged_events"]
    require(
        len(events) + len(purged) == artifact["source_physical_events"] == 83
        and artifact["source_entry_pending_evaluations"] == 188
        and digest(events) == artifact["event_set_sha256"]
        and digest(purged) == artifact["purged_event_set_sha256"],
        "event set changed",
    )
    require(
        len({event["physical_key"] for event in [*events, *purged]}) == 83
        and all(
            event["physical_key"] == digest(event["natural_key"]) for event in [*events, *purged]
        ),
        "physical identities changed",
    )
    memberships = [[event["physical_key"], book] for event in events for book in event["books"]]
    require(digest(memberships) == artifact["memberships_sha256"], "book memberships changed")
    source_memberships = [
        [event["physical_key"], book] for event in [*events, *purged] for book in event["books"]
    ]
    require(
        len(source_memberships) == 188
        and digest(source_memberships) == artifact["source_memberships_sha256"],
        "source book memberships changed",
    )
    rebuilt = build_report(events, artifact["source_projection"]["confirmed_coverage"])
    require(
        rebuilt == artifact["report"] and digest(rebuilt) == artifact["report_sha256"],
        "geometry report changed",
    )
    require(
        digest(artifact["source_projection"]) == artifact["source_projection_sha256"],
        "source projection changed",
    )
    require(
        artifact["authority"]
        == {
            "return_blind_geometry_analysis": "COMPLETED",
            "effective_s2_policy": False,
            "return_execution": False,
            "backtesting": False,
            "promotion_or_live_trading": False,
            "provider_production_or_deployment": False,
        },
        "geometry authority changed",
    )
    require(
        hashlib.sha256(REPORT_PATH.read_bytes()).hexdigest() == DECISION_REPORT_FILE_SHA256,
        "geometry decision report changed",
    )
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--read-research-once", action="store_true")
    mode.add_argument("--verify-committed", action="store_true")
    args = parser.parse_args()
    if args.read_research_once:
        print(json.dumps(read_research_once(), sort_keys=True, separators=(",", ":")))
    else:
        artifact = verify_committed()
        print(
            json.dumps(
                {
                    "verified": True,
                    "artifact_sha256": ARTIFACT_FILE_SHA256,
                    "geometry_sha256": artifact["geometry_sha256"],
                    "events": len(artifact["events"]),
                    "memberships": sum(len(event["books"]) for event in artifact["events"]),
                    "return_execution": False,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
