"""One read-only S1 geometry projection; no candle/exit/outcome reader.

The live entry point has fixed research connection and exact query/field
allowlists. Offline reconstruction consumes the committed projection artifact.
Allocation below is a fixed-equity maximum-horizon diagnostic, NOT execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from statistics import NormalDist
from time import perf_counter
from zoneinfo import ZoneInfo

from research.s2_policy import (
    ACCEPTED_JOBS,
    CANDIDATE_POLICY_SHA256,
    COMBINED_BOOK,
    PolicyRefusal,
    digest,
    load_candidate_policy,
)

CANDIDATE_COMMIT = "cfe9d19eef2f76bec2328098be77f68bf3103320"
PROJECTION_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs/strategy/failed-break/v1/s2-geometry-projection-v1.json"
)
PROJECTION_FILE_SHA256 = "4749633ac8c3f28e977e7697ba9f1b9d32425de84afde183a2d0fd98e4c7b27b"
PROJECTION_SHA256 = "af2f0d6e2e865dcdc8d9825c039d5df650059e717cd09fad92b0f41ff72a8fb7"
NY = ZoneInfo("America/New_York")
DEVELOPMENT_END = datetime(2019, 1, 1, 5, tzinfo=UTC)
FAMILY_BOOKS = {
    "PREVIOUS_WEEKLY_EXTREME": "failed-break-weekly-extreme-v1",
    "CONFIRMED_DAILY_SWING": "failed-break-daily-swing-v1",
    "TWENTY_SESSION_BREAKOUT_FLIP": "failed-break-breakout-flip-v1",
}
BOOKS = tuple(sorted((COMBINED_BOOK, *FAMILY_BOOKS.values())))
GEOMETRY_MDE_SIGMA_GRID = ("0.5", "1.0", "1.5")

# Every selected expression has a named allowlisted output. No SELECT *,
# arbitrary table, arbitrary predicate or free-form SQL is accepted by the reader.
QUERIES = {
    "isolation": (
        ("database", "read_only", "isolation", "server_address"),
        "SELECT current_database() AS database, current_setting('transaction_read_only') AS read_only, "
        "current_setting('transaction_isolation') AS isolation, inet_server_addr() AS server_address",
        1,
    ),
    "jobs": (
        ("id", "job_name", "status", "config_hash", "report_sha256", "dataset_id", "strategy_id"),
        "SELECT id, job_name, status, config_hash, evidence->'report'->>'report_sha256' AS report_sha256, "
        "dataset_version_id AS dataset_id, strategy_version_id AS strategy_id "
        "FROM research_jobrun WHERE id IN (1,2,3) ORDER BY id",
        3,
    ),
    "lineage": (
        (
            "dataset_id",
            "dataset_version",
            "dataset_manifest_sha256",
            "dataset_contract_sha256",
            "registration_configuration_sha256",
            "registration_report_sha256",
            "contract_id",
            "contract_identity",
            "contract_sha256",
            "inventory_sha256",
            "plan_identity",
            "plan_contract_id",
            "plan_contract_sha256",
            "registration_contract_id",
            "registration_inventory_sha256",
            "discovery_sealed",
        ),
        "SELECT d.id AS dataset_id, d.version AS dataset_version, d.manifest_sha256 AS dataset_manifest_sha256, "
        "d.data_contract_sha256 AS dataset_contract_sha256, r.configuration_sha256 AS registration_configuration_sha256, "
        "r.report_sha256 AS registration_report_sha256, c.id AS contract_id, c.identity AS contract_identity, "
        "c.sha256 AS contract_sha256, c.global_semantic_inventory_sha256 AS inventory_sha256, "
        "p.identity AS plan_identity, p.data_contract_id AS plan_contract_id, "
        "p.data_contract_sha256 AS plan_contract_sha256, r.data_contract_id AS registration_contract_id, "
        "r.global_semantic_inventory_sha256 AS registration_inventory_sha256, "
        "dp.sealed_at IS NOT NULL AS discovery_sealed "
        "FROM market_datasetversion d JOIN market_datasetregistration r ON r.dataset_version_id=d.id "
        "JOIN market_historicaldatasetplan p ON p.id=r.plan_id "
        "JOIN market_historicaldatacontract c ON c.id=p.data_contract_id "
        "JOIN market_historicaldiscoveryregistration dr ON dr.id=c.discovery_registration_id "
        "JOIN market_historicaldiscoveryplan dp ON dp.id=dr.plan_id WHERE d.id=3",
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
            "job_id",
        ),
        "SELECT e.id AS evaluation_id, s.id AS setup_id, e.book_identity AS book, e.entry_timestamp AS entry_at, "
        "e.risk_per_unit_cad::text AS risk_per_unit_cad, e.evidence_hash AS evaluation_hash, "
        "i.id AS instrument_id, i.code AS instrument, i.base_currency AS base, i.quote_currency AS quote, "
        "s.direction, s.sweep_h1_timestamp AS sweep_at, s.detector_version AS detector, "
        "s.dataset_version_id AS dataset_id, s.strategy_version_id AS strategy_id, s.evidence_hash AS setup_hash, "
        "t.effective_at AS confirmation_at, t.evidence_hash AS confirmation_hash, t.job_run_id AS job_id "
        "FROM research_entryeligibilityevaluation e JOIN research_setupevent s ON s.id=e.setup_id "
        "JOIN market_instrument i ON i.id=s.instrument_id JOIN research_setuptransition t ON t.setup_id=s.id "
        "AND t.book_identity='' AND t.from_state='TRIGGER_PENDING' AND t.to_state='CONFIRMED' "
        "WHERE s.dataset_version_id=3 AND s.strategy_version_id=1 AND e.decision='ENTRY_PENDING' "
        "AND t.effective_at >= '2010-01-01T05:00:00Z' AND t.effective_at < '2019-01-01T05:00:00Z' "
        "ORDER BY e.entry_timestamp, s.id, e.book_identity",
        206,
    ),
    "attributions": (
        ("setup_id", "level_key", "family", "activated_at", "dataset_id", "strategy_id"),
        "SELECT a.setup_id, l.stable_key AS level_key, l.family, l.activated_at, "
        "l.dataset_version_id AS dataset_id, l.strategy_version_id AS strategy_id "
        "FROM research_setuplevelattribution a JOIN research_level l ON l.id=a.level_id "
        "JOIN research_setupevent s ON s.id=a.setup_id WHERE s.dataset_version_id=3 AND s.strategy_version_id=1 "
        "AND EXISTS(SELECT 1 FROM research_entryeligibilityevaluation e WHERE e.setup_id=s.id "
        "AND e.decision='ENTRY_PENDING') ORDER BY a.setup_id, l.stable_key",
        500,
    ),
    "inventory": (
        ("instrument_id", "granularity", "timestamps"),
        "SELECT ch.instrument_id, ch.granularity, array_agg(o.timestamp ORDER BY o.timestamp) AS timestamps "
        "FROM market_historicaltimestampobservation o "
        "JOIN market_historicaltimestampinventory inv ON inv.id=o.inventory_id "
        "JOIN market_historicaldiscoverychunk ch ON ch.id=inv.chunk_id "
        "JOIN market_historicaldiscoveryregistration dr ON dr.plan_id=ch.plan_id "
        "JOIN market_historicaldatacontract c ON c.discovery_registration_id=dr.id "
        "WHERE c.id=2 AND ch.granularity IN ('D','H1') "
        "GROUP BY ch.instrument_id, ch.granularity ORDER BY ch.instrument_id,ch.granularity",
        12,
    ),
}


def require(condition, message):
    if not condition:
        raise PolicyRefusal(message)


def read_allowed(cursor, name, fields):
    require(name in QUERIES, "query not allowlisted")
    allowed, sql, limit = QUERIES[name]
    require(tuple(fields) == allowed, "exact field allowlist required; additional fields refused")
    cursor.execute(sql)
    require(
        tuple(column.name for column in cursor.description) == allowed, "database projection drift"
    )
    rows = cursor.fetchmany(limit + 1)
    require(len(rows) <= limit, "projection row bound exceeded")
    return [dict(zip(allowed, row, strict=True)) for row in rows]


def timestamp(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    require(
        isinstance(result, datetime) and result.utcoffset() is not None, "aware timestamp required"
    )
    return result.astimezone(UTC)


def stamp(value):
    return timestamp(value).isoformat()


def daily_completion(value):
    # Exact existing market.quality.registered_candle_completion D semantics;
    # do not invent weekday membership or extend closures with synthetic bars.
    return (timestamp(value).astimezone(NY) + timedelta(days=1)).astimezone(UTC)


def session(value):
    value = timestamp(value)
    london = time(8) <= value.astimezone(ZoneInfo("Europe/London")).time() < time(17)
    new_york = time(8) <= value.astimezone(NY).time() < time(17)
    require(london or new_york, "accepted eligible event outside governed session")
    return "london_new_york_overlap" if london and new_york else "london" if london else "new_york"


def entry_week(value):
    local = timestamp(value).astimezone(NY)
    year, week, _ = local.isocalendar()
    return f"{year}-W{week:02d}"


def cluster_summary(groups):
    groups = {key: sorted(values) for key, values in sorted(groups.items())}
    sizes = {key: len(values) for key, values in groups.items()}
    n = sum(sizes.values())
    squared = sum(size * size for size in sizes.values())
    effective = Fraction(n * n, squared) if squared else Fraction(0)
    return {
        "membership_sha256": digest(groups),
        "sizes": sizes,
        "raw_count": len(groups),
        "event_count": n,
        "kish_exact": str(effective),
        "kish_decimal": format(float(effective), ".10f"),
    }


def factor_clusters(events):
    """S2-04: transitive shared currency, same NY entry week, unique events."""
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
            groups[f"{week}|{digest(sorted(component))}"] = component
    return cluster_summary(groups)


def geometry(events):
    dates, weeks, simultaneous = defaultdict(list), defaultdict(list), defaultdict(list)
    edges = []
    for event in events:
        key, entry = event["physical_key"], timestamp(event["entry_at"])
        dates[entry.astimezone(NY).date().isoformat()].append(key)
        weeks[entry_week(entry)].append(key)
        simultaneous[stamp(entry)].append(key)
    ordered = sorted(events, key=lambda e: (e["entry_at"], e["physical_key"]))
    for index, a in enumerate(ordered):
        for b in ordered[index + 1 :]:
            if timestamp(b["entry_at"]) <= timestamp(a["horizon_at"]):
                edges.append([a["physical_key"], b["physical_key"]])
    points = sorted({timestamp(e["entry_at"]) for e in events})
    return {
        "entry_dates": cluster_summary(dates),
        "entry_weeks": cluster_summary(weeks),
        "shared_factors": factor_clusters(events),
        "simultaneous": cluster_summary(simultaneous),
        "maximum_horizon_overlap_edges": edges,
        "half_open_peak": max(
            (
                sum(timestamp(e["entry_at"]) <= t < timestamp(e["horizon_at"]) for e in events)
                for t in points
            ),
            default=0,
        ),
        "allocation_phase_peak": max(
            (
                sum(timestamp(e["entry_at"]) <= t <= timestamp(e["horizon_at"]) for e in events)
                for t in points
            ),
            default=0,
        ),
        "overlap_semantics": "Maximum-horizon potential overlap only; at equal boundary allocate before scheduled release",
    }


def buckets(event):
    base_side, quote_side = ("long", "short") if event["direction"] == "long" else ("short", "long")
    return (f"{base_side}:{event['base']}", f"{quote_side}:{event['quote']}")


def capacity_diagnostic(events):
    """Fixed 10k equity, max horizon, no marks or early exits: NOT actual survival."""
    with localcontext() as context:
        context.prec = 38
        grouped = defaultdict(list)
        for event in events:
            grouped[event["entry_at"]].append(event)
        open_rows, results = [], []
        for at, group in sorted(grouped.items()):
            # Preserve specification phase ordering: equal-time scheduled
            # exits release capacity only AFTER new allocations.
            open_rows = [row for row in open_rows if row["horizon_at"] >= at]
            remaining = max(
                Decimal(0), Decimal(100) - sum((row["risk"] for row in open_rows), Decimal(0))
            )
            used = defaultdict(Decimal)
            requests = Counter()
            for row in open_rows:
                for bucket in row["buckets"]:
                    used[bucket] += row["risk"]
            for event in group:
                requests.update(buckets(event))
            fraction = min(
                [Decimal(1), remaining / (Decimal(25) * len(group))]
                + [
                    max(Decimal(0), Decimal(50) - used[bucket]) / (Decimal(25) * count)
                    for bucket, count in requests.items()
                ]
            )
            for event in sorted(group, key=lambda e: e["physical_key"]):
                unit_risk = Decimal(event["risk_per_unit_cad"])
                require(unit_risk.is_finite() and unit_risk > 0, "invalid pre-entry CAD unit risk")
                units = (Decimal(25) * fraction / unit_risk).to_integral_value(rounding=ROUND_FLOOR)
                risk = units * unit_risk
                row = {
                    "physical_key": event["physical_key"],
                    "entry_at": at,
                    "common_fraction": str(fraction),
                    "units": int(units),
                    "planned_risk_cad": str(risk),
                }
                results.append(row)
                if units > 0:
                    open_rows.append(
                        {"risk": risk, "horizon_at": event["horizon_at"], "buckets": buckets(event)}
                    )
        return {
            "kind": "FIXED_EQUITY_MAXIMUM_HORIZON_DIAGNOSTIC_NOT_ACTUAL_SURVIVAL",
            "equity_cad": "10000",
            "risk_per_request_cad": "25",
            "aggregate_cap_cad": "100",
            "bucket_cap_cad": "50",
            "unit_step": "1",
            "rows": results,
            "positive_unit_events": sum(row["units"] > 0 for row in results),
            "zero_unit_events": sum(row["units"] == 0 for row in results),
            "actual_allocated_count": None,
            "actual_resolved_allocated_count": None,
            "not_a_bound_on_actual_survival": True,
        }


def concentration(events, weights=None):
    totals = {
        kind: defaultdict(Fraction)
        for kind in ("pair", "year", "direction", "session", "family", "currency_direction")
    }
    weights = weights or {event["physical_key"]: Fraction(1) for event in events}
    denominator = sum(weights.values(), Fraction(0))
    for event in events:
        weight = weights.get(event["physical_key"], Fraction(0))
        for field, key in (
            ("pair", event["instrument"]),
            ("year", str(timestamp(event["entry_at"]).astimezone(NY).year)),
            ("direction", event["direction"]),
            ("session", session(event["entry_at"])),
        ):
            totals[field][key] += weight
        for family in event["families"]:
            totals["family"][family] += weight / len(event["families"])
        for bucket in buckets(event):
            totals["currency_direction"][bucket] += weight
    return {
        kind: {
            key: {
                "exact": str(value / (denominator * (2 if kind == "currency_direction" else 1))),
                "decimal": format(
                    float(value / (denominator * (2 if kind == "currency_direction" else 1))),
                    ".10f",
                ),
            }
            for key, value in sorted(values.items())
        }
        if denominator
        else {}
        for kind, values in totals.items()
    }


def detectable_effect(n_effective):
    n = float(Fraction(n_effective))
    multiplier = NormalDist().inv_cdf(0.975) + NormalDist().inv_cdf(0.80)
    return {
        str(sigma): format(multiplier * sigma / n**0.5, ".10f") if n > 0 else None
        for sigma in (0.5, 1.0, 1.5)
    }


def floors(book, events, geo, policy):
    thresholds = policy["decision_ledger"][3]["recommendation"]
    final = policy["accepted_job_evidence"][2]["evidence"]["report"]
    n = len(events)
    known = {
        "minimum_included_confirmed_physical_setups": final["coverage"]["by_strategy_identity"][
            book
        ],
        "minimum_entry_eligible_physical_events": n,
        "minimum_nonempty_entry_date_clusters": geo["entry_dates"]["raw_count"],
        "minimum_nonempty_entry_week_clusters": geo["entry_weeks"]["raw_count"],
        "minimum_kish_entry_week_clusters": geo["entry_weeks"]["kish_exact"],
        "minimum_kish_shared_factor_clusters": geo["shared_factors"]["kish_exact"],
        "observation_calendar_days": (datetime(2019, 1, 1) - datetime(2010, 1, 1)).days,
        "required_registered_coverage_fraction": "1",
    }
    result = {
        field: {
            "threshold": thresholds[field],
            "observed": value,
            "status": "SATISFIED"
            if Fraction(value) >= Fraction(str(thresholds[field]))
            else "FAILED",
        }
        for field, value in known.items()
    }
    result["required_registered_coverage_fraction"]["basis"] = (
        "Accepted S0/S1 registered coverage only; no exit evidence coverage claim"
    )
    for field in ("minimum_resolved_allocated_physical_trades", "minimum_paired_physical_events"):
        result[field] = {
            "threshold": thresholds[field],
            "observed": None,
            "cohort_upper_bound": n,
            "status": "FAILED" if n < thresholds[field] else "UNKNOWABLE",
            "reason": "No outcome/resolution/comparator evidence authorized; never substitute capacity diagnostic",
        }
    result["maximum_unresolved_data_count"] = {
        "threshold": 0,
        "s1_observed": 0,
        "observed": None,
        "status": "UNKNOWABLE",
        "reason": "S1 clean; future execution evidence uninspected",
    }
    return result


def build_report(events, policy):
    books = {}
    for book in BOOKS:
        rows = [event for event in events if book in event["books"]]
        geo = geometry(rows)
        capacity = capacity_diagnostic(rows)
        positive = {row["physical_key"] for row in capacity["rows"] if row["units"] > 0}
        proxy_events = [event for event in rows if event["physical_key"] in positive]
        proxy_geo = geometry(proxy_events)
        weights = {
            row["physical_key"]: Fraction(row["planned_risk_cad"]) for row in capacity["rows"]
        }
        books[book] = {
            "eligible_physical_count": len(rows),
            "geometry": geo,
            "capacity_diagnostic": capacity,
            "eligible_request_concentration": concentration(rows),
            "capacity_diagnostic_risk_weighted_concentration": concentration(rows, weights),
            "actual_resolved_risk_weighted_concentration": None,
            "mde_R_eligible_geometry": {
                "raw_event_count": detectable_effect(len(rows)),
                "entry_week_kish": detectable_effect(geo["entry_weeks"]["kish_exact"]),
                "shared_factor_kish": detectable_effect(geo["shared_factors"]["kish_exact"]),
            },
            "capacity_diagnostic_effective_counts": {
                "week": proxy_geo["entry_weeks"]["kish_exact"],
                "factor": proxy_geo["shared_factors"]["kish_exact"],
            },
            "mde_R_capacity_diagnostic": {
                "entry_week_kish": detectable_effect(proxy_geo["entry_weeks"]["kish_exact"]),
                "shared_factor_kish": detectable_effect(proxy_geo["shared_factors"]["kish_exact"]),
            },
            "s2_04_floors": floors(book, rows, geo, policy),
        }
    return {
        "books": books,
        "shared_factor_definition": "Connected components within New York ISO entry week, edge if either currency is shared; transitive, ignore direction/book, unique physical events",
        "singleton_408_shared_currency_statistic": "NON_AUTHORITATIVE_NOT_INDEPENDENCE_EVIDENCE",
        "confirmed_setup_kish": "PROHIBITED_SUBSTITUTE_FOR_TRADE_LEVEL_EFFECTIVE_SAMPLE_SIZE",
        "mde_method": "(z_0.975+z_0.80)*hypothetical_sigma/sqrt(Kish); 95% two-sided normal design, 80% power; not empirical power; residual temporal/factor dependence may reduce true effective N",
        "sigma_R": list(GEOMETRY_MDE_SIGMA_GRID),
        "sigma_grid_governance": {
            "interchangeable_with_s2_03": False,
            "observed_return_selection_or_reinterpretation": "PROHIBITED",
            "overrides_s2_03": False,
            "promotion_authority": False,
            "purpose": "RETURN_BLIND_GEOMETRY_MDE_DIAGNOSTIC",
            "sigma_R": list(GEOMETRY_MDE_SIGMA_GRID),
        },
        "resolved_allocated_physical_trades": None,
        "resolved_count_status": "UNKNOWABLE_WITHOUT_FORBIDDEN_EXIT_EVIDENCE",
        "actual_allocation_status": "UNKNOWABLE_WITHOUT_MARKED_EQUITY_AND_EARLIER_EXITS",
        "recommendation": {
            "choice": "B",
            "effective": False,
            "text": "Recommend a separately authorized exploratory-only freeze with promotion permanently prohibited regardless of outcomes; do not activate it here",
            "reason": "90 dependent eligible physical events cannot establish confirmatory adequacy at 0.20R across all return-blind geometry/MDE diagnostic points; allocation/resolution and comparator floors remain unknown. The 0.20R practical-effect target is unconditionally immutable after the return-blind geometry became known.",
        },
    }


def prepare_source(raw, policy):
    for name, rows in raw.items():
        allowed = set(QUERIES[name][0])
        require(all(set(row) == allowed for row in rows), "additional source field refused")
    require(set(raw) == set(QUERIES), "incomplete read-only source bundle")
    isolation = raw["isolation"]
    require(
        isolation
        == [
            {
                "database": "trade_recommender_research",
                "read_only": "on",
                "isolation": "repeatable read",
                "server_address": None,
            }
        ],
        "research isolation failed",
    )
    require(len(raw["jobs"]) == 3, "accepted jobs missing")
    for row in raw["jobs"]:
        require(row["id"] in ACCEPTED_JOBS, "unaccepted job")
        name, config, report = ACCEPTED_JOBS[row["id"]]
        require(
            row
            == {
                "id": row["id"],
                "job_name": name,
                "status": "succeeded",
                "config_hash": config,
                "report_sha256": report,
                "dataset_id": 3,
                "strategy_id": 1,
            },
            "accepted S1 job identity changed",
        )
    require(len(raw["lineage"]) == 1, "successor registration absent or duplicated")
    lineage = raw["lineage"][0]
    config = policy["accepted_job_evidence"][2]["evidence"]["configuration"]
    require(
        lineage["dataset_id"] == 3
        and lineage["dataset_version"] == "phase-2b1r-v2"
        and lineage["contract_id"]
        == lineage["plan_contract_id"]
        == lineage["registration_contract_id"]
        == 2
        and lineage["contract_identity"]
        == lineage["plan_identity"]
        == policy["lineage"]["effective_data_identity"]
        and lineage["contract_sha256"]
        == lineage["dataset_contract_sha256"]
        == lineage["plan_contract_sha256"]
        == config["historical_data_contract_sha256"]
        and lineage["inventory_sha256"]
        == lineage["registration_inventory_sha256"]
        == config["global_semantic_inventory_sha256"]
        and lineage["dataset_manifest_sha256"] == config["dataset_manifest_sha256"]
        and lineage["registration_configuration_sha256"]
        == policy["lineage"]["registration_configuration_sha256"]
        and lineage["registration_report_sha256"] == policy["lineage"]["registration_report_sha256"]
        and lineage["discovery_sealed"] is True,
        "successor relational governance mismatch",
    )
    series = {}
    series_hashes = {}
    for row in raw["inventory"]:
        key = (row["instrument_id"], row["granularity"])
        values = tuple(timestamp(value) for value in row["timestamps"])
        require(
            key not in series and values and tuple(sorted(set(values))) == values,
            "conflicting sealed timestamps",
        )
        series[key] = values
        series_hashes[f"{key[0]}/{key[1]}"] = digest([stamp(value) for value in values])
    require(len(series) == 12, "six D/H1 inventories required")
    require(
        sum(len(values) for values in series.values()) <= 365055, "sealed timestamp bound exceeded"
    )
    daily_ends = {
        key: tuple(daily_completion(value) for value in values)
        for key, values in series.items()
        if key[1] == "D"
    }
    evaluations = defaultdict(list)
    for row in raw["evaluations"]:
        evaluations[row["setup_id"]].append(row)
    require(
        len(raw["evaluations"]) == 206 and len(evaluations) == 91,
        "unpurged S1 eligible ledger changed",
    )
    attributes = defaultdict(list)
    for row in raw["attributions"]:
        require(
            row["setup_id"] in evaluations and row["dataset_id"] == 3 and row["strategy_id"] == 1,
            "attribution lineage mismatch",
        )
        attributes[row["setup_id"]].append(row)
    events, purged = [], []
    witnesses = {}
    for setup_id, rows in sorted(evaluations.items()):
        first = rows[0]
        for row in rows:
            require(
                # Accepted detector leaves job_run unset; summary is created
                # afterward. Preserve this exact lineage, never repair S1.
                row["dataset_id"] == 3 and row["strategy_id"] == 1 and row["job_id"] is None,
                "S1 event lineage mismatch",
            )
            require(
                all(
                    row[field] == first[field]
                    for field in (
                        "entry_at",
                        "instrument",
                        "base",
                        "quote",
                        "direction",
                        "sweep_at",
                        "detector",
                        "setup_hash",
                        "confirmation_at",
                        "confirmation_hash",
                        "risk_per_unit_cad",
                    )
                ),
                "book geometry conflicts",
            )
        require(
            len({row["book"] for row in rows}) == len(rows)
            and any(row["book"] == COMBINED_BOOK for row in rows),
            "duplicate or missing combined book",
        )
        require(
            first["instrument"] == f"{first['base']}_{first['quote']}"
            and first["direction"] in {"long", "short"}
            and first["detector"] == "failed-break-detector-v1",
            "physical identity invalid",
        )
        attrs = attributes[setup_id]
        require(
            attrs and len({a["level_key"] for a in attrs}) == len(attrs),
            "missing/duplicate level attribution",
        )
        require(
            all(
                timestamp(a["activated_at"]) <= timestamp(first["sweep_at"]) - timedelta(hours=1)
                for a in attrs
            ),
            "non-pre-existing attributed level",
        )
        families = sorted({a["family"] for a in attrs})
        expected_books = {COMBINED_BOOK, *(FAMILY_BOOKS[family] for family in families)}
        require(
            {row["book"] for row in rows} == expected_books,
            "eligible book memberships do not match families",
        )
        entry = timestamp(first["entry_at"])
        confirmation = timestamp(first["confirmation_at"])
        h1 = series[(first["instrument_id"], "H1")]
        daily = series[(first["instrument_id"], "D")]
        ends = daily_ends[(first["instrument_id"], "D")]
        entry_index = bisect_left(h1, confirmation)
        require(
            entry_index < len(h1) and h1[entry_index] == entry,
            "entry not first sealed H1 successor",
        )
        start = bisect_right(ends, entry)
        selected = daily[start : start + 10]
        tenth = ends[start + 9] if start + 9 < len(ends) else None
        end_index = bisect_left(h1, tenth) if tenth else len(h1)
        horizon = h1[end_index] if end_index < len(h1) else None
        witnesses[str(setup_id)] = {
            "daily_starts": [stamp(value) for value in selected],
            "prior_daily_start": stamp(daily[start - 1]) if start else None,
            "first_entry_open": stamp(h1[entry_index]),
            "prior_entry_open": stamp(h1[entry_index - 1]) if entry_index else None,
            "horizon_at": stamp(horizon) if horizon else None,
            "prior_horizon_open": stamp(h1[end_index - 1])
            if end_index and end_index <= len(h1)
            else None,
        }
        if horizon is None or horizon >= DEVELOPMENT_END:
            purged.append(
                {
                    "setup_id": setup_id,
                    "evaluations": len(rows),
                    "entry_at": stamp(entry),
                    "reason": "INCOMPLETE_OR_BOUNDARY_TEN_SESSION_HORIZON",
                }
            )
            continue
        natural_key = [
            first["instrument"],
            first["direction"],
            stamp(first["sweep_at"]),
            first["detector"],
            "phase-2b1r-v2",
        ]
        events.append(
            {
                "setup_id": setup_id,
                "physical_key": digest(natural_key),
                "natural_key": natural_key,
                "instrument": first["instrument"],
                "base": first["base"],
                "quote": first["quote"],
                "direction": first["direction"],
                "entry_at": stamp(entry),
                "confirmation_at": stamp(confirmation),
                "risk_per_unit_cad": first["risk_per_unit_cad"],
                "horizon_at": stamp(horizon),
                "books": sorted(expected_books),
                "families": families,
                "setup_evidence_hash": first["setup_hash"],
                "confirmation_evidence_hash": first["confirmation_hash"],
                "evaluations": [
                    {
                        "id": row["evaluation_id"],
                        "book": row["book"],
                        "evidence_hash": row["evaluation_hash"],
                    }
                    for row in sorted(rows, key=lambda r: r["book"])
                ],
            }
        )
    events.sort(key=lambda event: (event["entry_at"], event["physical_key"]))
    require(
        len(events) == len({e["physical_key"] for e in events}) == 90
        and sum(len(e["books"]) for e in events) == 204
        and len(purged) == 1
        and purged[0]["setup_id"] == 596
        and purged[0]["evaluations"] == 2,
        "accepted 90/204 cohort and boundary purge did not reconstruct",
    )
    # Persist only the exact allowed pre-entry row projections and compact
    # timestamp witnesses. Full preloaded inventory is discarded after hashing.
    source = {name: rows for name, rows in raw.items() if name != "inventory"}
    source["inventory_series_sha256"] = series_hashes
    source["timestamp_witnesses"] = witnesses
    return events, purged, source


def json_value(value):
    if isinstance(value, datetime):
        return stamp(value)
    raise TypeError(type(value).__name__)


def read_once():
    """Explicitly authorized one-shot research READ ONLY transaction, no retries."""
    import psycopg

    started = perf_counter()
    policy = load_candidate_policy()
    with psycopg.connect(
        dbname="trade_recommender_research",
        user="trade_recommender",
        host="/tmp",
        password="",
        passfile="/dev/null",
        connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=60000 -c lock_timeout=2000",
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            try:
                raw = {"isolation": read_allowed(cursor, "isolation", QUERIES["isolation"][0])}
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
                    "research read-only socket isolation failed before evidence access",
                )
                for name, (fields, _sql, _limit) in QUERIES.items():
                    if name != "isolation":
                        raw[name] = read_allowed(cursor, name, fields)
            finally:
                cursor.execute("ROLLBACK")
    events, purged, source = prepare_source(raw, policy)
    report = build_report(events, policy)
    expected = policy["accepted_job_evidence"][2]["evidence"]["report"]["coverage"]
    for book, row in report["books"].items():
        require(
            row["eligible_physical_count"]
            == expected["simultaneous_requests"]["by_strategy_identity"][book]["members"],
            "S1 book count changed",
        )
        require(
            row["geometry"]["half_open_peak"]
            == expected["maximum_horizon_concurrency"]["by_strategy_identity"][book][
                "peak_requests"
            ],
            "S1 horizon concurrency changed",
        )
    source = json.loads(json.dumps(source, default=json_value))
    body = {
        "schema": "failed-break-s2-return-blind-geometry-v1",
        "candidate_commit": CANDIDATE_COMMIT,
        "candidate_policy_sha256": policy["policy_sha256"],
        "dataset_id": 3,
        "strategy_id": 1,
        "s1_report_sha256": ACCEPTED_JOBS[3][2],
        "authorization_effective": False,
        "source_projection": source,
        "source_projection_sha256": digest(source),
        "query_contract": {
            name: {
                "fields": list(fields),
                "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
                "max_rows": limit,
            }
            for name, (fields, sql, limit) in QUERIES.items()
        },
        "events": events,
        "event_set_sha256": digest(events),
        "purged": purged,
        "report": report,
        "report_sha256": digest(report),
        "isolation": {
            "transaction": "READ ONLY REPEATABLE READ ROLLED BACK",
            "provider_access": False,
            "candle_table_access": False,
            "outcome_access": False,
            "persistent_writes": False,
            "s0_s1_rerun": False,
            "s2_activation": False,
        },
    }
    body["projection_sha256"] = digest(body)
    return {"artifact": body, "elapsed_seconds": round(perf_counter() - started, 6)}


def verify_committed():
    """Offline only: rebuild the entire count/geometry report from fixed inputs.

    Witness adjacency was checked against complete sealed timestamp sequences
    during capture. Compact witnesses and whole-series hashes retain that claim;
    this verifier does not re-query the database or claim to rehash its inventory.
    """
    raw = PROJECTION_PATH.read_bytes()
    require(
        hashlib.sha256(raw).hexdigest() == PROJECTION_FILE_SHA256, "projection file digest changed"
    )
    artifact = json.loads(raw)
    require(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode() + b"\n" == raw,
        "noncanonical projection",
    )
    body = dict(artifact)
    require(
        body.pop("projection_sha256") == PROJECTION_SHA256 == digest(body),
        "projection self-hash changed",
    )
    policy = load_candidate_policy()
    require(
        artifact["candidate_commit"] == CANDIDATE_COMMIT
        and artifact["candidate_policy_sha256"]
        == policy["policy_sha256"]
        == CANDIDATE_POLICY_SHA256
        and artifact["authorization_effective"] is False,
        "candidate/authority mismatch",
    )
    source = artifact["source_projection"]
    require(
        digest(source) == artifact["source_projection_sha256"], "source projection hash mismatch"
    )
    require(
        set(source)
        == (set(QUERIES) - {"inventory"}) | {"timestamp_witnesses", "inventory_series_sha256"},
        "source schema drift",
    )
    for name in set(QUERIES) - {"inventory"}:
        require(
            all(set(row) == set(QUERIES[name][0]) for row in source[name]),
            "source field allowlist drift",
        )
    for name, (fields, query, limit) in QUERIES.items():
        require(
            artifact["query_contract"][name]
            == {
                "fields": list(fields),
                "sql_sha256": hashlib.sha256(query.encode()).hexdigest(),
                "max_rows": limit,
            },
            "query contract changed",
        )

    grouped = defaultdict(list)
    for row in source["evaluations"]:
        grouped[row["setup_id"]].append(row)
    attrs = defaultdict(list)
    for row in source["attributions"]:
        attrs[row["setup_id"]].append(row)
    require(len(grouped) == 91 and len(source["evaluations"]) == 206, "source cohort mismatch")
    require(
        {event["setup_id"] for event in artifact["events"]} == set(grouped) - {596},
        "wrong purged cohort",
    )
    require(
        artifact["purged"][0]["setup_id"] == 596 and artifact["purged"][0]["evaluations"] == 2,
        "purge mismatch",
    )
    for event in artifact["events"]:
        rows = grouped[event["setup_id"]]
        row = rows[0]
        require(
            all(
                r["job_id"] is None and r["dataset_id"] == 3 and r["strategy_id"] == 1 for r in rows
            ),
            "nullable S1 lineage changed",
        )
        for field in ("instrument", "direction", "base", "quote", "risk_per_unit_cad"):
            require(
                all(event[field] == r[field] for r in rows), f"event geometry mismatch: {field}"
            )
        require(
            event["natural_key"]
            == [
                row["instrument"],
                row["direction"],
                row["sweep_at"],
                row["detector"],
                "phase-2b1r-v2",
            ]
            and event["physical_key"] == digest(event["natural_key"]),
            "physical identity mismatch",
        )
        require(
            event["entry_at"] == row["entry_at"]
            and event["confirmation_at"] == row["confirmation_at"]
            and event["setup_evidence_hash"] == row["setup_hash"]
            and event["confirmation_evidence_hash"] == row["confirmation_hash"],
            "event timestamp/evidence mismatch",
        )
        require(
            event["books"] == sorted(r["book"] for r in rows)
            and event["families"] == sorted({r["family"] for r in attrs[event["setup_id"]]})
            and event["evaluations"]
            == [
                {"id": r["evaluation_id"], "book": r["book"], "evidence_hash": r["evaluation_hash"]}
                for r in sorted(rows, key=lambda r: r["book"])
            ],
            "book membership mismatch",
        )
        witness = source["timestamp_witnesses"][str(event["setup_id"])]
        starts = tuple(timestamp(value) for value in witness["daily_starts"])
        require(
            len(starts) == 10 and tuple(sorted(set(starts))) == starts,
            "ten-session witness invalid",
        )
        entry = timestamp(event["entry_at"])
        require(
            all(daily_completion(value) > entry for value in starts)
            and (
                witness["prior_daily_start"] is None
                or daily_completion(witness["prior_daily_start"]) <= entry
            ),
            "entry-containing session counting mismatch",
        )
        require(
            witness["first_entry_open"] == event["entry_at"]
            and (
                witness["prior_entry_open"] is None
                or timestamp(witness["prior_entry_open"]) < timestamp(event["confirmation_at"])
            )
            and entry >= timestamp(event["confirmation_at"]),
            "sealed entry successor witness mismatch",
        )
        require(
            witness["horizon_at"] == event["horizon_at"]
            and daily_completion(starts[-1]) <= timestamp(event["horizon_at"]) < DEVELOPMENT_END
            and (
                witness["prior_horizon_open"] is None
                or timestamp(witness["prior_horizon_open"]) < daily_completion(starts[-1])
            ),
            "horizon successor witness mismatch",
        )
    require(digest(artifact["events"]) == artifact["event_set_sha256"], "event set hash mismatch")
    rebuilt = build_report(artifact["events"], policy)
    require(
        rebuilt == artifact["report"] and digest(rebuilt) == artifact["report_sha256"],
        "geometry report does not reconstruct",
    )
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--read-research-once", action="store_true")
    mode.add_argument("--verify-committed", action="store_true")
    args = parser.parse_args()
    if args.verify_committed:
        artifact = verify_committed()
        print(
            json.dumps(
                {
                    "verified": True,
                    "projection_sha256": artifact["projection_sha256"],
                    "events": len(artifact["events"]),
                    "recommendation": artifact["report"]["recommendation"],
                    "database_access": False,
                },
                sort_keys=True,
            )
        )
    else:
        print(json.dumps(read_once(), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
