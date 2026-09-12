"""Independent report arithmetic from persisted modeled results, not market data."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext

from research.validation_reconciliation import MONEY, OVERLAYS, SCENARIOS, numeric_equal, require


def week(at):
    y, w, _ = datetime.fromisoformat(at).isocalendar()
    return f"{y}-W{w:02d}"


def check_populations(reports, rows):
    """Count every stored decision and independently pair exact opportunities.

    Caller must supply only the development catalogs already checked by scan.
    This reducer neither loads market inputs nor certifies publication.
    """
    counters = defaultdict(Counter)
    reasons = defaultdict(Counter)
    pairs = defaultdict(
        lambda: {"matched": 0, "unmatched": 0, "weekly": defaultdict(lambda: D(0)), "scale": D(0)}
    )
    orb = {}

    def accumulate(k, result):
        counters[k][result["state"]] += 1
        if result["state"] == "unavailable":
            reasons[k][result["reason"]] += 1

    def paired(k, opportunity, left, right):
        bucket = pairs[k]
        if left["state"] not in {"modeled", "no_setup"} or right["state"] not in {
            "modeled",
            "no_setup",
        }:
            bucket["unmatched"] += 1
            return
        bucket["matched"] += 1
        a = D(left["net_CAD"]) if left["state"] == "modeled" else D(0)
        b = D(right["net_CAD"]) if right["state"] == "modeled" else D(0)
        bucket["weekly"][week(opportunity)] += a - b
        bucket["scale"] += abs(a) + abs(b)

    with localcontext() as ctx:
        ctx.prec = 80
        for row in rows:
            source, instrument, at = row["strategy"], row["instrument"], row["opportunity"]
            if source.startswith(("orb-m15-fvg", "orb-m15-confirmed")):
                k = source, instrument, row["session"], at
                require(k not in orb, "duplicate_paired_opportunity")
                orb[k] = row["scenarios"]
            for scenario, raw in row["scenarios"].items():
                for instrument_view in (instrument, "aggregate"):
                    accumulate((source, instrument_view, None, scenario), raw)
                for view in OVERLAYS:
                    risk = row["overlays"][view]
                    current = raw
                    if view == "macro-risk-v1" or (
                        raw["state"] == "modeled" and risk["multiplier"] is None
                    ):
                        current = {"state": "unavailable", "reason": risk["reason"]}
                    elif raw["state"] == "modeled":
                        m = D(risk["multiplier"])
                        require(0 <= m <= 1, "uncapped_overlay")
                        with localcontext() as numeric:
                            numeric.prec = 34
                            current = (
                                {"state": "modeled", "net_CAD": str(D(raw["net_CAD"]) * m)}
                                if m
                                else {"state": "no_setup"}
                            )
                    for instrument_view in (instrument, "aggregate"):
                        k = view, instrument_view, source, scenario
                        accumulate(k, current)
                        paired(k, at, current, raw)
        for (source, instrument, session, at), scenarios in orb.items():
            if not source.startswith("orb-m15-fvg"):
                continue
            comparator_key = source.replace("fvg", "confirmed"), instrument, session, at
            require(comparator_key in orb, "missing_same_session_comparator")
            for scenario, result in scenarios.items():
                for instrument_view in (instrument, "aggregate"):
                    paired(
                        (source, instrument_view, None, scenario),
                        at,
                        result,
                        orb[comparator_key][scenario],
                    )
        for key, report in reports.items():
            for scenario, result in report["scenarios"].items():
                k = (*key, scenario)
                require(dict(counters[k]) == result["states"], "persisted_states")
                require(
                    dict(reasons[k]) == result["unavailable_reasons"],
                    "persisted_unavailable_reasons",
                )
                if report["paired_comparator"]:
                    actual, expected = report["paired_comparator"][scenario], pairs[k]
                    require(
                        (actual["matched_opportunities"], actual["unavailable_or_unmatched"])
                        == (expected["matched"], expected["unmatched"]),
                        "exact_pair_population",
                    )
                    require(
                        set(actual["paired_UTC_week_increment_CAD"]) == set(expected["weekly"]),
                        "exact_pair_weeks",
                    )
                    for w, value in expected["weekly"].items():
                        numeric_equal(
                            actual["paired_UTC_week_increment_CAD"][w],
                            value,
                            expected["matched"] * 4,
                            expected["scale"],
                        )
                    if expected["matched"]:
                        numeric_equal(
                            actual["total_increment_CAD"],
                            sum(expected["weekly"].values()),
                            expected["matched"] * 4,
                            expected["scale"],
                        )
                    else:
                        require(actual["total_increment_CAD"] is None, "empty_pair_increment")
    return {
        "counted_scenario_views": len(counters),
        "paired_scenario_views": len(pairs),
        "orb_opportunity_keys": len(orb),
    }


def dependence(trades):
    components = []
    for trade in trades:
        start, end = map(datetime.fromisoformat, (trade["entered_at"], trade["exited_at"]))
        weeks = {week(end.isoformat())}
        while start <= end:
            weeks.add(week(start.isoformat()))
            start += timedelta(days=1)
        separate = []
        for component in components:
            if weeks & component:
                weeks |= component
            else:
                separate.append(component)
        components = [*separate, weeks]
    return len(components), sorted(set().union(*components)) if components else []


def trade_views(receipts):
    """Project only saved amounts using saved capped risk. Never refit a solver."""
    views = defaultdict(list)
    for receipt in receipts:
        for key, row in receipt["setup_rows"].items():
            source, pair, opportunity = key.split("|")
            for scenario, raw in row["scenarios"].items():
                if raw["state"] != "modeled":
                    continue
                for view in (source, *OVERLAYS):
                    if view == "macro-risk-v1":
                        continue
                    multiplier = row["overlays"][view]["multiplier"] if view in OVERLAYS else "1"
                    if multiplier is None or D(multiplier) == 0:
                        continue
                    require(0 < D(multiplier) <= 1, "uncapped_overlay")
                    result = {
                        **raw,
                        "instrument": pair,
                        "opportunity": opportunity,
                        "volatility_stratum": row["volatility_stratum"],
                    }
                    # Decimal34 is the registered projection arithmetic. These
                    # are existing checkpoint amounts, not new simulated outcomes.
                    with localcontext() as ctx:
                        ctx.prec = 34
                        for field in (*MONEY, "units", "net_account_return"):
                            result[field] = str(D(raw[field]) * D(multiplier))
                    baseline = source if view in OVERLAYS else None
                    views[view, pair, baseline, scenario].append(result)
                    views[view, "aggregate", baseline, scenario].append(result)
    return views


def check_metrics(reports, receipts, registration):
    views, checked = trade_views(receipts), 0
    with localcontext() as ctx:
        ctx.prec = 80
        for key, report in reports.items():
            for scenario in SCENARIOS:
                trades = views[(*key, scenario)]
                metric = report["scenarios"][scenario]
                require(len(trades) == metric["trades"], "persisted_trade_population")
                require(
                    sum(t["holding_seconds"] for t in trades) == metric["holding_seconds_total"],
                    "persisted_duration",
                )
                units, weeks = dependence(trades)
                require(
                    (units, weeks)
                    == (metric["effective_week_units"], metric["active_UTC_ISO_weeks"]),
                    "dependence_grouping",
                )
                if not trades:
                    checked += 1
                    continue
                n = len(trades)

                def total(field, values=trades):
                    return sum((D(t[field]) for t in values), D(0))

                scale = sum(abs(D(t["net_CAD"])) for t in trades)

                def compare(actual, expected, magnitude=scale):
                    numeric_equal(actual, expected, n * 4, magnitude)

                for field in MONEY:
                    compare(
                        metric["money"][field], total(field), sum(abs(D(t[field])) for t in trades)
                    )
                accounts = 12 if key[1] == "aggregate" else 1
                compare(
                    metric["diagnostic_net_account_return"],
                    total("net_CAD") / (D(registration["research_equity_CAD"]) * accounts),
                    scale / (D(registration["research_equity_CAD"]) * accounts),
                )
                weekly, sides, months, instruments = (defaultdict(lambda: D(0)) for _ in range(4))
                for t in trades:
                    amount = D(t["net_CAD"])
                    weekly[week(t["exited_at"])] += amount
                    sides["long" if t["direction"] == 1 else "short"] += amount
                    months[t["exited_at"][:7]] += amount
                    instruments[t["instrument"]] += amount
                require(len(instruments) == metric["usable_instruments"], "usable_instruments")
                for label, group in (("instrument", instruments), ("UTC_month", months)):
                    absolute = sum(map(abs, group.values()))
                    if absolute:
                        numeric_equal(
                            metric["concentration"][label],
                            max(map(abs, group.values())) / absolute,
                            n * 4,
                            D(1),
                        )
                    else:
                        require(
                            metric["concentration"][label] is None, "zero_concentration_denominator"
                        )
                expected_strata = {"long" if t["direction"] == 1 else "short" for t in trades} | {
                    t["volatility_stratum"] for t in trades
                }
                require(
                    set(metric["side_and_volatility_strata"]) == expected_strata,
                    "strata_population",
                )
                for label, stratum in metric["side_and_volatility_strata"].items():
                    selected = [
                        t
                        for t in trades
                        if label
                        in {"long" if t["direction"] == 1 else "short", t["volatility_stratum"]}
                    ]
                    require(stratum["trades"] == len(selected), "strata_count")
                    for field in MONEY:
                        numeric_equal(
                            stratum[field],
                            total(field, selected),
                            n * 4,
                            sum(abs(D(t[field])) for t in selected),
                        )
                for field, group in (("weekly_net_CAD", weekly), ("long_short_net_CAD", sides)):
                    require(set(metric[field]) == set(group), "persisted_group_population")
                    for item, value in group.items():
                        compare(metric[field][item], value)
                weekly_values = sorted(weekly.values())
                compare(metric["worst_week_CAD"], weekly_values[0])
                compare(
                    metric["weekly_lower_5pct_CAD"], weekly_values[(len(weekly_values) - 1) // 20]
                )
                compare(
                    metric["remove_best_month_net_CAD"], total("net_CAD") - max(months.values())
                )
                compare(
                    metric["remove_best_instrument_net_CAD"],
                    total("net_CAD") - max(instruments.values()),
                )
                for i, half in enumerate(metric["halves"]):
                    subset = [
                        t
                        for t in trades
                        if (t["opportunity"] < registration["development_split"]) == (i == 0)
                    ]
                    require(
                        (half["trades"], half["effective_weeks"])
                        == (len(subset), dependence(subset)[0]),
                        "half_dependence",
                    )
                    if subset:
                        compare(half["net_CAD"], total("net_CAD", subset))
                    else:
                        require(half["net_CAD"] is None, "empty_half")
                # One baseline cannot have overlapping positions on one pair.
                # Therefore exit/instrument ties do not require the opaque result
                # identity as a tiebreaker to recompute realized drawdown.
                require(
                    len({(t["exited_at"], t["instrument"]) for t in trades}) == n,
                    "ambiguous_drawdown_order",
                )
                equity, peak, dd = D(0), D(0), D(0)
                for t in sorted(trades, key=lambda t: (t["exited_at"], t["instrument"])):
                    equity += D(t["net_CAD"])
                    peak = max(peak, equity)
                    dd = max(dd, peak - equity)
                compare(metric["realized_drawdown_CAD"], dd)
                pending, peak, overlaps = [], 0, 0
                for t in sorted(trades, key=lambda t: (t["entered_at"], t["instrument"])):
                    pending = [p for p in pending if p["exited_at"] > t["entered_at"]]
                    overlaps += sum(
                        bool(set(p["instrument"].split("_")) & set(t["instrument"].split("_")))
                        for p in pending
                    )
                    pending.append(t)
                    peak = max(peak, len(pending))
                require(
                    (peak, overlaps)
                    == (
                        metric["concurrent_positions_peak"],
                        metric["overlapping_currency_trade_pairs"],
                    ),
                    "concurrent_currency_overlap",
                )
                checked += 1
    return {
        "scenario_views_checked": checked,
        "scope": "all_persisted_modeled_trade_amounts_dependence_halves_tails_drawdown_overlap",
    }
