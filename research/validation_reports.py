"""Deterministic, separately attributed diagnostics. Never an acceptance authority."""

import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from market.state.canonical import canonical_json, identity_digest
from market.strategy.contracts import arithmetic
from research.validation_registration import DEVELOPMENT_SPLIT, SCENARIOS, Catalog

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


def iso_week(at):
    year, week, _ = datetime.fromisoformat(at).isocalendar()
    return f"{year}-W{week:02d}"


def effective_weeks(trades):
    parent = {}

    def root(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            key = parent[key]
        return key

    for trade in trades:
        start, end = map(datetime.fromisoformat, (trade["entered_at"], trade["exited_at"]))
        cursor = start
        weeks = {iso_week(start.isoformat()), iso_week(end.isoformat())}
        while cursor < end:
            weeks.add(iso_week(cursor.isoformat()))
            cursor += timedelta(days=1)
        roots = sorted(root(w) for w in weeks)
        for item in roots[1:]:
            parent[root(item)] = root(roots[0])
    return len({root(k) for k in parent}), sorted(parent)


@arithmetic
def summarize(rows, scenario, *, accounts=1):
    states, reasons = Counter(), Counter()
    trades, weekly, by_pair, by_month, sides = (
        [],
        defaultdict(lambda: D(0)),
        defaultdict(lambda: D(0)),
        defaultdict(lambda: D(0)),
        defaultdict(lambda: D(0)),
    )
    totals = {key: D(0) for key in MONEY}
    strata = {}
    count = 0
    for row in rows:
        count += 1
        result = row["scenarios"][scenario]
        states[result["state"]] += 1
        if result["state"] == "unavailable":
            reasons[result["reason"]] += 1
        if result["state"] != "modeled":
            continue
        trade = {
            **result,
            "instrument": row["instrument"],
            "session": row["session"],
            "opportunity": row["opportunity"],
        }
        trades.append(trade)
        for group in (
            "long" if trade["direction"] == 1 else "short",
            row.get("volatility_stratum", "unavailable"),
        ):
            item = strata.setdefault(group, {"trades": 0, **{key: D(0) for key in MONEY}})
            item["trades"] += 1
            for key in MONEY:
                item[key] += D(trade[key])
        for key in MONEY:
            totals[key] += D(trade[key])
        net = D(trade["net_CAD"])
        weekly[iso_week(trade["exited_at"])] += net
        by_pair[row["instrument"]] += net
        by_month[trade["exited_at"][:7]] += net
        sides["long" if trade["direction"] == 1 else "short"] += net
    trades.sort(key=lambda t: (t["exited_at"], t["instrument"], t["identity"]))
    equity, peak, drawdown = D(0), D(0), D(0)
    for trade in trades:
        equity += D(trade["net_CAD"])
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    effective, active = effective_weeks(trades)
    weekly_values = sorted(weekly.values())
    concentration = {}
    for name, group in (("instrument", by_pair), ("UTC_month", by_month)):
        denominator = sum((abs(v) for v in group.values()), D(0))
        concentration[name] = (
            str(max(abs(v) for v in group.values()) / denominator) if denominator else None
        )
    halves = []
    for first in (True, False):
        subset = [t for t in trades if (t["opportunity"] < DEVELOPMENT_SPLIT) == first]
        halves.append(
            {
                "trades": len(subset),
                "effective_weeks": effective_weeks(subset)[0],
                "net_CAD": str(sum((D(t["net_CAD"]) for t in subset), D(0))) if subset else None,
            }
        )
    concurrent_peak, currency_overlap = 0, 0
    pending = []
    for trade in sorted(trades, key=lambda t: (t["entered_at"], t["instrument"])):
        pending = [t for t in pending if t["exited_at"] > trade["entered_at"]]
        currency_overlap += sum(
            bool(set(t["instrument"].split("_")) & set(trade["instrument"].split("_")))
            for t in pending
        )
        pending.append(trade)
        concurrent_peak = max(concurrent_peak, len(pending))
    return {
        "planned_opportunities": count,
        "eligible_opportunities": count - states["unavailable"],
        "trades": len(trades),
        "states": dict(sorted(states.items())),
        "unavailable_reasons": dict(sorted(reasons.items())),
        "active_UTC_ISO_weeks": active,
        "effective_week_units": effective,
        "usable_instruments": len(by_pair),
        "money": {key: str(value) if trades else None for key, value in totals.items()},
        "diagnostic_net_account_return": str(totals["net_CAD"] / (D(100000) * accounts))
        if trades
        else None,
        "full_population_net_account_return": None
        if states["unavailable"]
        else (str(totals["net_CAD"] / (D(100000) * accounts)) if trades else "0"),
        "realized_drawdown_CAD": str(drawdown) if trades else None,
        "worst_week_CAD": str(min(weekly_values)) if weekly_values else None,
        "weekly_lower_5pct_CAD": str(weekly_values[(len(weekly_values) - 1) // 20])
        if weekly_values
        else None,
        "weekly_net_CAD": {key: str(value) for key, value in sorted(weekly.items())},
        "long_short_net_CAD": {key: str(value) for key, value in sorted(sides.items())},
        "concentration": concentration,
        "halves": halves,
        "remove_best_instrument_net_CAD": str(totals["net_CAD"] - max(by_pair.values()))
        if by_pair
        else None,
        "remove_best_month_net_CAD": str(totals["net_CAD"] - max(by_month.values()))
        if by_month
        else None,
        "holding_seconds_total": sum(t["holding_seconds"] for t in trades),
        "concurrent_positions_peak": concurrent_peak,
        "overlapping_currency_trade_pairs": currency_overlap,
        "side_and_volatility_strata": {
            group: {key: value if key == "trades" else str(value) for key, value in item.items()}
            for group, item in sorted(strata.items())
        },
        "high_vol_rule": "decision_daily_price_sigma_gt_1.5_times_prior_sigma_no_filter",
        "event_strata": {
            "state": "unavailable",
            "reason": "event_vintages_missing",
        },
        "integrity_clean": False,
        "limitations": [
            "exceptional_session_vintages_missing",
            "retrospective_model_not_broker_observed",
            "realized_not_mark_to_market_drawdown",
        ],
    }


@arithmetic
def paired_increment(candidate, comparator, scenario):
    def index(rows):
        result = {}
        for row in rows:
            key = row["instrument"], row["session"], row["opportunity"]
            if key in result:
                raise ValueError("duplicate_paired_opportunity")
            result[key] = row["scenarios"][scenario]
        return result

    left, right = index(candidate), index(comparator)
    weekly, matched, unavailable = defaultdict(lambda: D(0)), 0, 0
    for key in sorted(left.keys() | right.keys()):
        a, b = left.get(key), right.get(key)
        if (
            not a
            or not b
            or a["state"] not in {"modeled", "no_setup"}
            or b["state"] not in {"modeled", "no_setup"}
        ):
            unavailable += 1
            continue
        matched += 1
        weekly[iso_week(key[2])] += (D(a["net_CAD"]) if a["state"] == "modeled" else D(0)) - (
            D(b["net_CAD"]) if b["state"] == "modeled" else D(0)
        )
    return {
        "matched_opportunities": matched,
        "unavailable_or_unmatched": unavailable,
        "paired_UTC_week_increment_CAD": {k: str(v) for k, v in sorted(weekly.items())},
        "total_increment_CAD": str(sum(weekly.values(), D(0))) if matched else None,
        "retention_eligible": False,
    }


def report(catalog, registration_id, strategy, instrument, *, baseline=None):
    """Certifying boundary: no caller rows, account counts, periods or labels."""
    return next(_verified_reports(catalog, registration_id, [(strategy, instrument, baseline)]))


@arithmetic
def overlay_rows(rows, overlay):
    """A paired view of immutable baseline opportunities, not new trade selection."""
    output = []
    for row in rows:
        risk = row["overlays"][overlay]
        multiplier = D(risk["multiplier"]) if risk["multiplier"] is not None else None
        if multiplier is not None and (not multiplier.is_finite() or not 0 <= multiplier <= 1):
            raise ValueError("overlay_exceeds_baseline")
        scenarios = {}
        for name, result in row["scenarios"].items():
            if overlay == "macro-risk-v1":
                current = {"state": "unavailable", "reason": risk["reason"]}
            elif result["state"] != "modeled":
                current = result
            elif multiplier is None:
                current = {"state": "unavailable", "reason": risk["reason"]}
            elif multiplier == 0:
                current = {"state": "no_setup", "reason": "risk_paused_baseline_opportunity"}
            else:
                current = {
                    **result,
                    **{
                        key: str(D(result[key]) * multiplier)
                        for key in MONEY + ("units", "net_account_return")
                    },
                }
                current["identity"] = identity_digest(
                    {"baseline": result["identity"], "overlay": overlay, "risk": risk}
                )
            scenarios[name] = current
        output.append(
            {
                **row,
                "strategy": overlay,
                "baseline_identity": row["strategy"],
                "scenarios": scenarios,
                "evaluation_identity": identity_digest(
                    {"baseline": row["evaluation_identity"], "overlay": overlay, "risk": risk}
                ),
            }
        )
    return output


def development_proposal(body, registration):
    baseline = body["scenarios"]["baseline"]

    def positive(value):
        return None if value is None else D(value) > 0

    gates = {
        "integrity_clean": baseline["integrity_clean"],
        "complete_opportunity_evidence": baseline["states"].get("unavailable", 0) == 0,
        "minimum_weeks": baseline["effective_week_units"] >= registration["min_effective_weeks"],
        "minimum_opportunities": baseline["eligible_opportunities"]
        >= registration["min_opportunities"],
        "minimum_trades": baseline["trades"] >= registration["min_trades"],
        "minimum_instruments": baseline["usable_instruments"]
        >= registration["minimum_instruments"],
        "positive_net": positive(baseline["money"]["net_CAD"]),
        "positive_adverse": positive(body["scenarios"]["adverse_cost"]["money"]["net_CAD"]),
        "positive_extra_latency": positive(
            body["scenarios"]["extra_interval_latency"]["money"]["net_CAD"]
        ),
        "positive_without_best_instrument": positive(baseline["remove_best_instrument_net_CAD"]),
        "positive_without_best_month": positive(baseline["remove_best_month_net_CAD"]),
    }
    for scenario, result in body["scenarios"].items():
        gates[f"complete_{scenario}"] = result["states"].get("unavailable", 0) == 0
    for index, half in enumerate(baseline["halves"]):
        gates[f"half_{index + 1}_weeks"] = half["effective_weeks"] >= registration["min_half_weeks"]
        gates[f"half_{index + 1}_positive"] = positive(half["net_CAD"])
    for name, value in baseline["concentration"].items():
        gates[f"{name}_not_concentrated"] = (
            None
            if value is None
            else D(value) <= D(registration["maximum_absolute_net_concentration"])
        )
    paired = body.get("paired_comparator")
    if paired:
        gates["paired_coverage_complete"] = all(
            p["unavailable_or_unmatched"] == 0 for p in paired.values()
        )
        if body["strategy"].startswith("orb-m15-fvg"):
            for scenario, value in paired.items():
                gates[f"positive_paired_{scenario}"] = positive(value["total_increment_CAD"])
    evidence = (
        "integrity_clean",
        "complete_opportunity_evidence",
        "minimum_weeks",
        "minimum_opportunities",
        "minimum_trades",
        "minimum_instruments",
        "half_1_weeks",
        "half_2_weeks",
    )
    if (
        any(gates[k] is not True for k in evidence)
        or any(not gates[f"complete_{s}"] for s in body["scenarios"])
        or gates.get("paired_coverage_complete") is False
        or any(v is None for v in gates.values())
    ):
        proposal = "inconclusive"
    elif not all(gates.values()):
        proposal = "reject"
    else:
        proposal = "candidate_for_independent_review_not_retained"
    return {
        "proposal": proposal,
        "development_gates": gates,
        "holdout_gate": "sealed_not_evaluated",
        "retention": "not_authorized",
    }


def saved_rows(catalog, registration_id, strategy, instrument, *, overlay=None):
    rows, _, _ = catalog.verify_chain(registration_id, strategy, instrument)
    yield from overlay_rows(rows, overlay) if overlay else rows


def _verified_reports(catalog, registration_id, requests):
    from research.validation_batch import OVERLAYS, timeframe

    if type(catalog) is not Catalog:
        raise ValueError("verified_catalog_required")
    registration = catalog.load(registration_id)
    needed = set()
    for strategy, instrument, baseline in requests:
        if strategy not in registration["strategies"] or instrument not in [
            *registration["instruments"],
            "aggregate",
        ]:
            raise ValueError("unregistered_report_population")
        if (strategy in OVERLAYS) != (baseline is not None) or baseline in OVERLAYS:
            raise ValueError("report_overlay_requires_separate_baseline")
        source = baseline or strategy
        if source not in registration["strategies"]:
            raise ValueError("report_baseline_unregistered")
        population = registration["instruments"] if instrument == "aggregate" else [instrument]
        for pair in population:
            needed.add((source, pair))
            if not baseline and source.startswith("orb-m15-fvg"):
                needed.add((source.replace("orb-m15-fvg", "orb-m15-confirmed"), pair))
    # Preloading is internal and goes through exactly the same complete causal
    # verification as focused publication. No selected-row API can mint claims.
    verified, bindings, shared = {}, {}, {}
    for source, pair in sorted(needed):
        rows, _, terminal = catalog.verify_chain(registration_id, source, pair)
        # Only after full-body verification: omit unused decision payloads and
        # intern identical immutable views to bound a twelve-pair M15 report.
        for row in rows:
            row.pop("decision")
            for field in ("scenarios", "overlays"):
                value = row[field]
                row[field] = shared.setdefault(canonical_json(value), value)
        verified[source, pair] = rows
        bindings[source, pair] = {
            "strategy": source,
            "instrument": pair,
            "terminal_checkpoint_sha256": terminal,
            "daily_checkpoints": (
                datetime.fromisoformat(registration["development"][1])
                - datetime.fromisoformat(registration["development"][0])
            ).days,
        }
    for strategy, instrument, baseline in requests:
        source = baseline or strategy
        population = registration["instruments"] if instrument == "aggregate" else [instrument]

        def rows(overlay=None, comparator=source):
            for pair in population:
                values = verified[comparator, pair]
                yield from overlay_rows(values, overlay) if overlay else values

        body = {
            "schema": registration["report_schema"],
            "registration": registration_id,
            "strategy": strategy,
            "instrument": instrument,
            "session": source.split(":")[1] if ":" in source else "regular_fx",
            "timeframe": timeframe(source),
            "baseline_identity": baseline,
            "original_definition_revision": 2,
            "validation_revision": registration["revision"],
            "mode": registration["mode"],
            "account_allocation": {
                "independent_CAD_accounts": len(population),
                "equity_each": registration["research_equity_CAD"],
            },
            "period": "development",
            "period_bounds": registration["development"],
            "checkpoint_bindings": [bindings[source, p] for p in population],
            "scenarios": {
                s: summarize(rows(strategy if baseline else None), s, accounts=len(population))
                for s in SCENARIOS
            },
            "reason": "integrity_evidence_incomplete_holdout_sealed",
            "holdout": "sealed_not_evaluated",
            "activation": "forbidden",
        }
        if baseline:
            body["paired_comparator"] = {
                s: paired_increment(rows(strategy), rows(), s) for s in SCENARIOS
            }
        elif strategy.startswith("orb-m15-fvg"):
            confirmed = strategy.replace("orb-m15-fvg", "orb-m15-confirmed")
            body["comparator_checkpoint_bindings"] = [bindings[confirmed, p] for p in population]
            body["paired_comparator"] = {
                s: paired_increment(rows(), rows(comparator=confirmed), s) for s in SCENARIOS
            }
        else:
            body["paired_comparator"] = None
        body.update(development_proposal(body, registration))
        body["identity"] = identity_digest(body)
        yield body


def export_population(catalog, registration_id, source, destination):
    """Bounded one-baseline batch: twelve instruments plus aggregate, five views."""
    from research.validation_batch import OVERLAYS

    registration = catalog.load(registration_id)
    if source not in registration["strategies"] or source in OVERLAYS:
        raise ValueError("report_baseline_unregistered")
    requests = [
        (s, p, source if s in OVERLAYS else None)
        for s in (source, *OVERLAYS)
        for p in (*registration["instruments"], "aggregate")
    ]
    return [
        _publish_report(body, destination)
        for body in _verified_reports(catalog, registration_id, requests)
    ]


def export_report(catalog, registration_id, strategy, instrument, destination, *, baseline=None):
    return _publish_report(
        report(catalog, registration_id, strategy, instrument, baseline=baseline), destination
    )


def _publish_report(body, destination):
    directory = Path(destination)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for suffix, text in (("json", canonical_json(body) + "\n"), ("txt", plain_english(body))):
        path = directory / f"{body['identity']}.{suffix}"
        publish_immutable(path, text)
    return body["identity"]


def publish_immutable(path, text):
    # A crash can leave an unpublished temporary file, never a partially published
    # report. Concurrent identical publishers converge; differing bytes refuse.
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=".phase55-report-"
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        try:
            os.link(handle.name, path)
        except FileExistsError:
            if path.read_text() != text:
                raise ValueError("immutable_report_conflict") from None


def plain_english(body):
    lines = [
        f"{body['strategy']} / {body['instrument']} / {body['session']}: {body['proposal']}.",
        f"Original definition revision 2; validation revision {body['validation_revision']}; "
        f"paired baseline: {body['baseline_identity']}.",
        f"Registration: {body['registration']}; period: development; null means unavailable.",
        "Model-based retrospective only. Exceptional-session evidence is missing; "
        "integrity-clean retention is blocked. Holdout remains sealed. Not trading approval.",
    ]
    for scenario in SCENARIOS:
        result = body["scenarios"][scenario]
        lines.extend(
            (
                f"\nScenario {scenario}: {result['planned_opportunities']} planned opportunities; "
                f"{result['eligible_opportunities']} eligible; {result['trades']} modeled trades.",
                f"Opportunity states: {canonical_json(result['states'])}.",
                f"Exact unavailable reasons and counts: {canonical_json(result['unavailable_reasons'])}.",
                f"Gross, separate costs, net and turnover in CAD: {canonical_json(result['money'])}.",
                f"Diagnostic account return: {result['diagnostic_net_account_return']}; "
                f"full-population return: {result['full_population_net_account_return']}.",
                f"Active UTC ISO weeks: {canonical_json(result['active_UTC_ISO_weeks'])}; "
                f"effective dependence units: {result['effective_week_units']}.",
                f"Realized (not mark-to-market) drawdown CAD: {result['realized_drawdown_CAD']}; "
                f"worst week: {result['worst_week_CAD']}; lower 5% weekly tail: {result['weekly_lower_5pct_CAD']}.",
                f"Chronological halves: {canonical_json(result['halves'])}.",
                f"Long/short net CAD: {canonical_json(result['long_short_net_CAD'])}; "
                f"side/high-volatility strata: {canonical_json(result['side_and_volatility_strata'])}.",
                f"Absolute-net concentration: {canonical_json(result['concentration'])}; "
                f"net without best instrument: {result['remove_best_instrument_net_CAD']}; "
                f"net without best UTC month: {result['remove_best_month_net_CAD']}.",
                f"Total holding seconds: {result['holding_seconds_total']}; "
                f"peak concurrent positions: {result['concurrent_positions_peak']}; "
                f"overlapping-currency trade pairs: {result['overlapping_currency_trade_pairs']}.",
                "Event-period evidence is unavailable: event_vintages_missing.",
            )
        )
    lines.append(f"Matched comparators: {canonical_json(body.get('paired_comparator'))}.")
    lines.append(f"Development gates: {canonical_json(body.get('development_gates'))}.")
    return "\n".join(lines) + "\n"
