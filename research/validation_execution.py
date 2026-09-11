"""Preregistered regular-session retrospective diagnostics, never broker fills."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal as D

from market.quality import NEW_YORK, registered_successor
from market.state.canonical import identity_digest
from market.strategy.contracts import arithmetic


def unavailable(reason):
    return {"state": "unavailable", "reason": reason}


def crosses_rollover(start, end):
    day = start.astimezone(NEW_YORK).date()
    while day <= end.astimezone(NEW_YORK).date():
        at = datetime.combine(day, time(17), NEW_YORK).astimezone(UTC)
        if start <= at <= end:
            return True
        day += timedelta(days=1)
    return False


@arithmetic
def conversion(currency, at, data):
    """CAD per quote, mid/credit/debit rates using a completed contemporaneous bar."""
    if currency == "CAD":
        return D(1), D(1), D(1), ("CAD_identity",)
    paths = {
        "USD": (),
        "EUR": (("EUR_USD", False),),
        "GBP": (("GBP_USD", False),),
        "AUD": (("AUD_USD", False),),
        "NZD": (("NZD_USD", False),),
        "JPY": (("USD_JPY", True),),
        "CHF": (("USD_CHF", True),),
    }
    if currency not in paths:
        return None
    mid, credit, debit, evidence = D(1), D(1), D(1), []
    for pair, inverse in paths[currency] + (("USD_CAD", False),):
        series = data.get(pair)
        bars = series.before(at, 1) if series else ()
        if not bars or bars[-1].end != at:
            return None
        bar = bars[-1]
        row = series.by_start[bar.timestamp][1]
        bid, ask = D(row["bid_close"]), D(row["ask_close"])
        if not 0 < bid <= ask:
            return None
        midpoint = (bid + ask) / 2
        mid *= 1 / midpoint if inverse else midpoint
        credit *= 1 / ask if inverse else bid
        debit *= 1 / bid if inverse else ask
        evidence.append(bar.content_sha256)
    return mid, credit, debit, tuple(evidence)


@arithmetic
def simulate(setup, instrument, series, conversions, registration, scenario):
    """Same adverse price geometry, separately attributed retrospective cost clocks."""
    if scenario not in registration["scenarios"]:
        raise ValueError("unregistered_scenario")
    direction = setup["direction"]
    reference, stop, target = (D(setup[name]) for name in ("reference", "stop", "target"))
    entry_at, exit_at, signal_start, available_at, expiry = (
        datetime.fromisoformat(setup[name])
        for name in ("entry_at", "exit_at", "signal_start", "available_at", "expires_at")
    )
    granularity = setup["granularity"]
    limit = setup["strategy"] == "fast-mr-h1-v1"
    if scenario == "extra_interval_latency":
        entry_at = registered_successor(entry_at, granularity)
        if entry_at > expiry or entry_at >= exit_at:
            return unavailable("extra_latency_expired")
    if exit_at > datetime(2025, 1, 6, tzinfo=UTC):
        return unavailable("sealed_outcome_horizon")
    expected = registered_successor(signal_start, granularity)
    while expected < entry_at:
        if expected not in series.by_start:
            return unavailable("pre_entry_interval_gap")
        expected = registered_successor(expected, granularity)
    if entry_at not in series.by_start:
        return unavailable("next_interval_missing")
    first, first_row = series.by_start[entry_at]
    entry_spread = D(first_row["ask_open"]) - D(first_row["bid_open"])
    if entry_spread <= 0:
        return unavailable("spread_unavailable")
    slip_multiple = D(registration["slippage_spreads_per_side"][scenario])
    entry_slippage = entry_spread * slip_multiple
    entry_charge = entry_spread / 2
    entry_mid = first.open
    if limit:
        quote_open = first.open + direction * entry_spread / 2
        quote_edge = (first.low if direction == 1 else first.high) + direction * entry_spread / 2
        if direction * (quote_open - reference) > 0:
            return unavailable(
                "limit_intrabar_fill_unavailable"
                if direction * (quote_edge - reference) <= 0
                else "limit_expired_unfilled"
            )
        if direction * (first.open - stop) <= 0:
            return unavailable("limit_gap_beyond_invalidation")
        entry_mid = reference - direction * entry_spread / 2
        entry_slippage = D(0)
    elif (
        direction * (entry_mid + direction * (entry_charge + entry_slippage) - stop) <= 0
        or direction * (target - entry_mid - direction * (entry_charge + entry_slippage)) <= 0
    ):
        return unavailable("entry_gap_outside_geometry")
    quote_currency = instrument.split("_")[1]
    sizing = conversion(quote_currency, available_at, conversions)
    if sizing is None:
        return unavailable("decision_conversion_unavailable")
    equity = D(registration["research_equity_CAD"])
    units = min(
        equity * D(registration["risk_fraction"]) / (abs(reference - stop) * sizing[0]),
        equity / (reference * sizing[0]),
    )
    # Preserve Phase5 fast-MR high-vol baseline reduction, never above baseline.
    if limit and "high_vol_half" in setup.get("evidence", ()):
        units /= 2
    consumed = []
    cursor = entry_at
    while cursor < exit_at:
        item = series.by_start.get(cursor)
        if item is None:
            return unavailable("outcome_interval_gap")
        bar, row = item
        if crosses_rollover(entry_at, bar.end):
            return unavailable("genuine_financing_rollover_unavailable")
        consumed.append(bar.content_sha256)
        adverse, favorable = (bar.low, bar.high) if direction == 1 else (bar.high, bar.low)
        if direction * (bar.open - stop) <= 0:
            price, reason, kind = bar.open, "stop_gap", "open"
        elif direction * (adverse - stop) <= 0:
            price, reason, kind = stop, "stop_adverse_path", "proxy"
        elif direction * (favorable - target) >= 0:
            price, reason, kind = target, "target_no_improvement", "proxy"
        elif bar.end >= exit_at:
            price, reason, kind = bar.close, "time_stop", "close"
        else:
            cursor = registered_successor(cursor, granularity)
            continue
        open_spread, close_spread = (
            D(row["ask_open"]) - D(row["bid_open"]),
            D(row["ask_close"]) - D(row["bid_close"]),
        )
        exit_spread = (
            max(open_spread, close_spread)
            if kind == "proxy"
            else (open_spread if kind == "open" else close_spread)
        )
        if exit_spread <= 0:
            return unavailable("exit_spread_unavailable")
        rate = conversion(quote_currency, bar.end, conversions)
        if rate is None:
            return unavailable("exit_conversion_unavailable")
        gross_quote = direction * (price - entry_mid) * units
        spread_quote = (entry_charge + exit_spread / 2) * units
        slippage_quote = (entry_slippage + exit_spread * slip_multiple) * units
        gross = gross_quote * rate[0]
        spread, slippage = spread_quote * rate[0], slippage_quote * rate[0]
        commission = 2 * D(registration["commission_CAD_per_base_side"][scenario]) * units
        after_quote = gross_quote - spread_quote - slippage_quote
        conversion_cost = after_quote * (rate[0] - (rate[1] if after_quote >= 0 else rate[2]))
        net = gross - spread - slippage - commission - conversion_cost
        body = {
            "state": "modeled",
            "reason": reason,
            "direction": direction,
            "entered_at": entry_at.isoformat(),
            "exited_at": bar.end.isoformat(),
            "units": str(units),
            "gross_CAD": str(gross),
            "spread_CAD": str(spread),
            "commission_CAD": str(commission),
            "slippage_CAD": str(slippage),
            "financing_CAD": "0",
            "financing_basis": "no_rollover_touched",
            "conversion_CAD": str(conversion_cost),
            "net_CAD": str(net),
            "net_account_return": str(net / equity),
            "holding_seconds": int((bar.end - entry_at).total_seconds()),
            "turnover_CAD": str(units * (entry_mid + price) * rate[0]),
            "registration_sha256": identity_digest(registration),
            "outcome_evidence": consumed,
            "conversion_evidence": list(sizing[3] + rate[3]),
            "execution_model": "phase55/regular-session-retrospective-v1",
            "phase5_price_model": "adverse-limit-h1-v1" if limit else "adverse-next-interval-v1",
            "limitations": [
                "exceptional_session_vintages_missing",
                "not_executable_fill",
                "modeled_commission_slippage_conversion",
            ],
        }
        body["identity"] = identity_digest(
            {"setup": setup, "instrument": instrument, "scenario": scenario, "result": body}
        )
        return body
    return unavailable("outcome_horizon_unavailable")
