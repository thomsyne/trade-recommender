"""Read-only publication reconciliation, never price replay or certification.

This module deliberately does not import Catalog, batch, acquisition, strategy
evaluation or simulation. Inputs are completed development report artifacts.
An audit receipt describes checks performed; it does not mint report identities.
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext
from pathlib import Path

from market.state.canonical import canonical_json, identity_digest

OVERLAYS = ("fixed-risk-v1", "ewma-risk-v1", "garch-t-risk-v1", "macro-risk-v1")
MONEY = (
    "gross_CAD",
    "spread_CAD",
    "commission_CAD",
    "slippage_CAD",
    "financing_CAD",
    "conversion_CAD",
    "net_CAD",
    "turnover_CAD",
)
SCENARIOS = ("baseline", "adverse_cost", "extra_interval_latency")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def key(body):
    return body["strategy"], body["instrument"], body["baseline_identity"]


def timeframe(source):
    if source in {"ewmac-d-v1", "breakout-d-v1", "carry-readiness-v1"}:
        return "D"
    return "H1" if source in {"fast-mr-h1-v1", "pullback-h1-v1"} else "M15"


def expected_grid(registration):
    return {
        (view, pair, base if view in OVERLAYS else None)
        for base in registration["strategies"]
        if base not in OVERLAYS
        for view in (base, *OVERLAYS)
        for pair in (*registration["instruments"], "aggregate")
    }


def read_reports(directory):
    reports = {}
    for path in sorted(Path(directory).glob("*.json")):
        raw = path.read_text()
        body = json.loads(raw)
        require(key(body) not in reports, "duplicate_attribution")
        require(raw == canonical_json(body) + "\n", "noncanonical_report")
        require(
            path.stem
            == body["identity"]
            == identity_digest({k: v for k, v in body.items() if k != "identity"}),
            "report_identity",
        )
        reports[key(body)] = body
    return reports


def check_gates(body, registration):
    baseline = body["scenarios"]["baseline"]
    expected = {
        "integrity_clean": baseline["integrity_clean"],
        "complete_opportunity_evidence": not baseline["states"].get("unavailable", 0),
    }
    for gate, field, threshold in (
        ("minimum_weeks", "effective_week_units", "min_effective_weeks"),
        ("minimum_opportunities", "eligible_opportunities", "min_opportunities"),
        ("minimum_trades", "trades", "min_trades"),
        ("minimum_instruments", "usable_instruments", "minimum_instruments"),
    ):
        expected[gate] = baseline[field] >= registration[threshold]
    for gate, value in (
        ("positive_net", baseline["money"]["net_CAD"]),
        ("positive_adverse", body["scenarios"]["adverse_cost"]["money"]["net_CAD"]),
        ("positive_extra_latency", body["scenarios"]["extra_interval_latency"]["money"]["net_CAD"]),
        ("positive_without_best_instrument", baseline["remove_best_instrument_net_CAD"]),
        ("positive_without_best_month", baseline["remove_best_month_net_CAD"]),
    ):
        expected[gate] = None if value is None else D(value) > 0
    for scenario, result in body["scenarios"].items():
        expected["complete_" + scenario] = not result["states"].get("unavailable", 0)
    for i, half in enumerate(baseline["halves"], 1):
        expected[f"half_{i}_weeks"] = half["effective_weeks"] >= registration["min_half_weeks"]
        expected[f"half_{i}_positive"] = None if half["net_CAD"] is None else D(half["net_CAD"]) > 0
    for name, value in baseline["concentration"].items():
        expected[name + "_not_concentrated"] = (
            None
            if value is None
            else D(value) <= D(registration["maximum_absolute_net_concentration"])
        )
    if body["paired_comparator"]:
        expected["paired_coverage_complete"] = all(
            p["unavailable_or_unmatched"] == 0 for p in body["paired_comparator"].values()
        )
        if body["strategy"].startswith("orb-m15-fvg"):
            for scenario, paired in body["paired_comparator"].items():
                value = paired["total_increment_CAD"]
                expected["positive_paired_" + scenario] = None if value is None else D(value) > 0
    require(body["development_gates"] == expected, "threshold_gate_mismatch")


def check_population(reports, frozen):
    registration = frozen["body"]
    require(frozen["identity"] == identity_digest(registration), "registration_identity")
    require(set(reports) == expected_grid(registration), "incomplete_or_extra_grid")
    a, b = map(datetime.fromisoformat, registration["development"])
    require(b <= datetime.fromisoformat("2025-01-06T00:00:00+00:00"), "sealed_period")
    weekdays = sum((a + timedelta(days=i)).weekday() < 5 for i in range((b - a).days))
    for (strategy, instrument, baseline), body in reports.items():
        source = baseline or strategy
        population = registration["instruments"] if instrument == "aggregate" else [instrument]
        require(body["registration"] == frozen["identity"], "wrong_registration")
        require(body["schema"] == registration["report_schema"], "report_schema")
        require(
            body["validation_revision"] == registration["revision"]
            and body["original_definition_revision"] == 2,
            "report_era",
        )
        require(
            body["period"] == "development"
            and body["period_bounds"] == registration["development"],
            "report_period",
        )
        require(
            body["session"] == (source.split(":")[1] if ":" in source else "regular_fx")
            and body["timeframe"] == timeframe(source),
            "report_session_timeframe",
        )
        require(
            body["mode"] == registration["mode"]
            and body["activation"] == "forbidden"
            and body["holdout"] == body["holdout_gate"] == "sealed_not_evaluated"
            and body["retention"] == "not_authorized",
            "report_boundary",
        )
        require(
            body["account_allocation"]
            == {
                "independent_CAD_accounts": len(population),
                "equity_each": registration["research_equity_CAD"],
            },
            "account_denominator",
        )
        require(set(body["scenarios"]) == set(SCENARIOS), "scenario_population")
        bindings = body["checkpoint_bindings"]
        require(
            [p["instrument"] for p in bindings] == population
            and all(
                p["strategy"] == source and p["daily_checkpoints"] == (b - a).days for p in bindings
            ),
            "checkpoint_population",
        )
        comparator = baseline or (
            source.replace("fvg", "confirmed") if source.startswith("orb-m15-fvg") else None
        )
        require(bool(body["paired_comparator"]) == bool(comparator), "comparator_presence")
        if comparator and not baseline:
            expected = reports[comparator, instrument, None]["checkpoint_bindings"]
            require(body["comparator_checkpoint_bindings"] == expected, "same_session_comparator")
        factor = (
            1
            if ":" in source or timeframe(source) == "D"
            else (24 if timeframe(source) == "H1" else 96)
        )
        for result in body["scenarios"].values():
            require(
                result["planned_opportunities"] == weekdays * factor * len(population),
                "planned_population",
            )
            require(
                sum(result["states"].values()) == result["planned_opportunities"],
                "state_population",
            )
            require(
                set(result["states"]) <= {"modeled", "unavailable", "occupied", "no_setup"},
                "state_schema",
            )
            require(result["trades"] == result["states"].get("modeled", 0), "trade_count")
            require(
                sum(result["unavailable_reasons"].values())
                == result["states"].get("unavailable", 0),
                "missing_population",
            )
            require(
                result["eligible_opportunities"]
                == result["planned_opportunities"] - result["states"].get("unavailable", 0),
                "eligible_denominator",
            )
            require(
                result["integrity_clean"] is False
                and result["event_strata"]
                == {"state": "unavailable", "reason": "event_vintages_missing"},
                "integrity_claim",
            )
            require(
                result["limitations"]
                == [
                    "exceptional_session_vintages_missing",
                    "retrospective_model_not_broker_observed",
                    "realized_not_mark_to_market_drawdown",
                ],
                "report_limitations",
            )
            if result["states"].get("unavailable", 0):
                require(
                    result["full_population_net_account_return"] is None,
                    "incomplete_population_return",
                )
            require(set(result["money"]) == set(MONEY), "money_schema")
            for field, value in result["money"].items():
                require((value is None) == (result["trades"] == 0), "missing_money")
                if value is not None:
                    require(D(value).is_finite(), "nonfinite_money")
                    if field not in {"gross_CAD", "net_CAD"}:
                        require(D(value) >= 0, "negative_cost")
            require(
                sum(h["trades"] for h in result["halves"]) == result["trades"], "half_population"
            )
        # The frozen evidence-first rule makes every incomplete-integrity report
        # inconclusive even if economic gates are negative. This is not a pass.
        require(
            body["proposal"] == "inconclusive"
            and body["development_gates"]["integrity_clean"] is False,
            "unsupported_disposition",
        )
        check_gates(body, registration)


def numeric_equal(actual, expected, terms, scale):
    """Bound only Decimal34 summation rounding, not economic differences.

    For n rounded additions, each partial sum is bounded by the sum of absolute
    inputs S. Half an ulp at S bounds each rounding; allow n+1 operations and
    both the published and independently regrouped sums. No fixed epsilon.
    """
    with localcontext() as ctx:
        ctx.prec = 80
        error = abs(D(actual) - expected)
        bound = D(terms + 1) * D(10) ** (scale.adjusted() - 33) if scale else D(0)
        require(error <= bound, "aggregate_numeric_mismatch")
        return error


def check_aggregates(reports, registration):
    checks, rounding = 0, []
    with localcontext() as ctx:
        ctx.prec = 80
        for (strategy, instrument, baseline), body in sorted(reports.items(), key=str):
            if instrument != "aggregate":
                continue
            leaves = [reports[strategy, p, baseline] for p in registration["instruments"]]
            for scenario, total in body["scenarios"].items():
                children = [r["scenarios"][scenario] for r in leaves]
                for field in (
                    "planned_opportunities",
                    "eligible_opportunities",
                    "trades",
                    "holding_seconds_total",
                    "usable_instruments",
                ):
                    require(
                        total[field] == sum(r[field] for r in children), "aggregate_count_" + field
                    )
                for field in ("states", "unavailable_reasons"):
                    values = Counter()
                    for row in children:
                        values.update(row[field])
                    require(dict(values) == total[field], "aggregate_" + field)
                require(
                    total["active_UTC_ISO_weeks"]
                    == sorted({w for r in children for w in r["active_UTC_ISO_weeks"]}),
                    "aggregate_week_union",
                )
                for field in MONEY:
                    values = [
                        D(r["money"][field]) for r in children if r["money"][field] is not None
                    ]
                    if not values:
                        require(total["money"][field] is None, "aggregate_missing_money")
                        continue
                    error = numeric_equal(
                        total["money"][field],
                        sum(values),
                        total["trades"] * 2,
                        sum(map(abs, values)),
                    )
                    if error:
                        rounding.append(
                            {
                                "report": body["identity"],
                                "scenario": scenario,
                                "field": field,
                                "exact_leaf_sum_delta": str(error),
                            }
                        )
                    checks += 1
                for field in ("weekly_net_CAD", "long_short_net_CAD"):
                    groups = {g for r in children for g in r[field]}
                    require(set(total[field]) == groups, "aggregate_group_population")
                    for group in groups:
                        values = [D(r[field][group]) for r in children if group in r[field]]
                        numeric_equal(
                            total[field][group],
                            sum(values),
                            total["trades"] * 2,
                            sum(map(abs, values)),
                        )
                        checks += 1
                for index, half in enumerate(total["halves"]):
                    require(
                        half["trades"] == sum(r["halves"][index]["trades"] for r in children),
                        "aggregate_half_count",
                    )
                    values = [
                        D(r["halves"][index]["net_CAD"])
                        for r in children
                        if r["halves"][index]["net_CAD"] is not None
                    ]
                    if values:
                        numeric_equal(
                            half["net_CAD"], sum(values), half["trades"] * 2, sum(map(abs, values))
                        )
                    else:
                        require(half["net_CAD"] is None, "aggregate_half_missing")
                if body["paired_comparator"]:
                    paired = body["paired_comparator"][scenario]
                    parts = [r["paired_comparator"][scenario] for r in leaves]
                    for field in ("matched_opportunities", "unavailable_or_unmatched"):
                        require(paired[field] == sum(r[field] for r in parts), "paired_population")
                    field = "paired_UTC_week_increment_CAD"
                    groups = {g for r in parts for g in r[field]}
                    require(set(paired[field]) == groups, "paired_week_population")
                    for group in groups:
                        values = [D(r[field][group]) for r in parts if group in r[field]]
                        numeric_equal(
                            paired[field][group],
                            sum(values),
                            paired["matched_opportunities"] * 2,
                            sum(map(abs, values)),
                        )
                        checks += 1
    return {"numeric_groups_checked": checks, "nonzero_rounding_deltas": rounding}


def differences(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(a.keys() | b.keys()):
            yield from differences(a.get(k), b.get(k), path + "/" + k)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from differences(x, y, path + "/" + str(i))
    elif a != b:
        yield {"path": path, "before": a, "after": b}


def reconcile(directory, previous, frozen):
    current = read_reports(directory)
    check_population(current, frozen)
    accounting = check_aggregates(current, frozen["body"])
    old = read_reports(previous)
    require(set(old) == set(current), "prior_comparison_population")
    transitions = []
    for k in sorted(current, key=str):
        a, b = old[k], current[k]
        changes = [
            d
            for field in ("scenarios", "paired_comparator", "proposal", "development_gates")
            for d in differences(a[field], b[field], "/" + field)
        ]
        transitions.append(
            {
                "strategy": k[0],
                "instrument": k[1],
                "baseline": k[2],
                "prior_report": a["identity"],
                "report": b["identity"],
                "before": a["proposal"],
                "after": b["proposal"],
                "changes": changes,
            }
        )
    return {
        "schema": "phase55/report-reconciliation-observation-v1",
        "registration": frozen["identity"],
        "report_count": len(current),
        "aggregate_count": sum(k[1] == "aggregate" for k in current),
        "accounting": accounting,
        "transitions": transitions,
        "scope": "report_grid_leaf_aggregate_and_revision2_delta_only_not_checkpoint_semantic_closure",
        "holdout": "not_accessed",
        "acceptance": "not_authorized",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("previous", type=Path)
    parser.add_argument("registration", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = reconcile(args.directory, args.previous, json.loads(args.registration.read_text()))
    raw = canonical_json(result) + "\n"
    with args.output.open("x") as handle:
        handle.write(raw)
    args.output.chmod(0o600)
    print(
        canonical_json(
            {
                "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "reports": result["report_count"],
                "aggregates": result["aggregate_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
