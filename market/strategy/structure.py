"""Versioned Phase4 structure hypotheses, never subjective confluence."""

from datetime import datetime
from decimal import Decimal as D
from decimal import localcontext

from market.strategy.contracts import Unavailable
from market.strategy.setups import atr, candidate


def _block(inputs, timeframe):
    return inputs.payload.get("granularities", {}).get(timeframe, {})


def _trend(inputs, timeframe):
    fact = _block(inputs, timeframe).get("higher_timeframe", {}).get("trend", {})
    if fact.get("state") == "available" and fact.get("version") == "trend-v1":
        return fact.get("classification")
    return None


def _continuation(rejection, signal, direction):
    return signal.close > rejection.high if direction == 1 else signal.close < rejection.low


def pullback(inputs, timeframe):
    if timeframe not in ("M15", "H1"):
        raise ValueError("unsupported_pullback_interval")
    strategy = f"pullback-{timeframe.lower()}-v1"
    bars = inputs.series(timeframe)
    volatility = atr(bars)
    if volatility is None:
        return Unavailable(strategy, "signal_atr_unavailable")
    rejection, signal = bars[-2:]
    trend = _trend(inputs, "D")
    if trend not in ("uptrend", "downtrend") or trend != _trend(inputs, "H4"):
        return Unavailable(strategy, "htf_alignment_unavailable")
    if any(
        not inputs.series(g) or max(b.available_at for b in inputs.series(g)) > rejection.timestamp
        for g in ("D", "H4")
    ):
        return Unavailable(strategy, "htf_not_available_before_rejection")
    direction = 1 if trend == "uptrend" else -1
    zones = _block(inputs, "H4").get("structure", {}).get("support_resistance_zones", {})
    if zones.get("state") != "available" or zones.get("version") != "zone-v1":
        return Unavailable(strategy, "qualified_zone_unavailable")
    with localcontext() as ctx:
        ctx.prec = 34
        for zone in sorted(zones.get("zones", ()), key=lambda z: z["zone_id"]):
            if (
                zone.get("invalidated") is not False
                or zone.get("expired") is not False
                or zone.get("distinct_tests", 0) < 2
                or zone.get("age_intervals", 201) > 200
                or datetime.fromisoformat(zone["available_at"]) > rejection.timestamp
            ):
                continue
            low, high = D(zone["range_low"]), D(zone["range_high"])
            # Full overlap is necessary; a candle wholly beyond a zone is not a touch.
            touched = rejection.low <= high and rejection.high >= low
            reclaimed = rejection.close > high if direction == 1 else rejection.close < low
            if touched and reclaimed and _continuation(rejection, signal, direction):
                stop = (
                    low - D("0.25") * volatility
                    if direction == 1
                    else high + D("0.25") * volatility
                )
                return candidate(
                    strategy,
                    signal,
                    direction,
                    stop,
                    available_at=max(b.available_at for b in bars[-15:]),
                    evidence=(zone["zone_id"], rejection.content_sha256),
                )
        return Unavailable(strategy, "no_qualified_pullback")


def range_reversion(inputs):
    strategy = "range-m15-v1"
    bars = inputs.series("M15")
    volatility = atr(bars)
    if volatility is None or _trend(inputs, "D") != "range":
        return Unavailable(strategy, "sideways_regime_unavailable")
    consolidation = _block(inputs, "H4").get("structure", {}).get("consolidation", {})
    if (
        consolidation.get("state") != "available"
        or consolidation.get("version") != "consolidation-v1"
        or consolidation.get("in_consolidation") is not True
    ):
        return Unavailable(strategy, "range_or_breakout_unavailable")
    rejection, signal = bars[-2:]
    low, high = D(consolidation["range_low"]), D(consolidation["range_high"])
    raw = range_geometry(signal, rejection, low, high, volatility)
    if isinstance(raw, Unavailable):
        return raw
    # Descriptor0.12.0 cannot attest known-safe or attested-empty event coverage.
    # Do not create a fictitious override for a readiness gate missing in the source.
    return Unavailable(strategy, "event_expansion_clearance_unavailable")


def range_geometry(signal, rejection, low, high, volatility):
    """Price-only hypothesis; range_reversion separately enforces readiness."""
    strategy = "range-m15-v1"
    with localcontext() as ctx:
        ctx.prec = 34
        if high <= low:
            return Unavailable(strategy, "zero_range")
        lower, upper = low + (high - low) / 10, high - (high - low) / 10
        long = rejection.low <= lower < rejection.close and rejection.high >= low
        short = rejection.high >= upper > rejection.close and rejection.low <= high
        if long == short:
            return Unavailable(strategy, "not_a_unique_range_edge")
        direction = 1 if long else -1
        if not _continuation(rejection, signal, direction):
            return Unavailable(strategy, "range_continuation_unavailable")
        boundary = low if long else high
        return candidate(
            strategy,
            signal,
            direction,
            boundary - direction * D("0.25") * volatility,
            target=(low + high) / 2,
        )


def failed_break(inputs, *, continuation=False):
    strategy = "phase5-acceptance-continuation-v1" if continuation else "phase5-sweep-reversal-v1"
    bars = inputs.series("M15")
    volatility = atr(bars)
    if volatility is None:
        return Unavailable(strategy, "signal_atr_unavailable")
    block = _block(inputs, "M15")
    liquidity = block.get("liquidity", {})
    bos = block.get("higher_timeframe", {}).get("break_of_structure", {})
    if (
        liquidity.get("state") != "available"
        or liquidity.get("version") != "sweep-v2"
        or bos.get("state") != "available"
        or bos.get("version") != "bos-v1"
        or bos.get("broken") is not True
    ):
        return Unavailable(strategy, "confirmed_structure_unavailable")
    signal = bars[-1]
    matches = []
    with localcontext() as ctx:
        ctx.prec = 34
        for side in ("above", "below"):
            event = liquidity.get(f"{'acceptance' if continuation else 'sweep'}_{side}")
            if not event or event.get("status") != "confirmed":
                continue
            direction = (1 if side == "above" else -1) * (1 if continuation else -1)
            if (
                bos.get("direction") != ("up" if direction == 1 else "down")
                or datetime.fromisoformat(event["confirmation_available_at"]) > signal.timestamp
            ):
                continue
            if continuation:
                boundary = D(event["level"])
            else:
                breach, confirmation = (
                    datetime.fromisoformat(event["breach_at"]),
                    datetime.fromisoformat(event["confirmation_at"]),
                )
                excursion = [b for b in bars if breach <= b.end <= confirmation]
                if not excursion:
                    continue
                boundary = (
                    min(b.low for b in excursion)
                    if direction == 1
                    else max(b.high for b in excursion)
                )
            matches.append(
                candidate(
                    strategy,
                    signal,
                    direction,
                    boundary - direction * D("0.25") * volatility,
                    available_at=max(b.available_at for b in bars),
                    evidence=(event["level_id"],),
                )
            )
    return (
        matches[0]
        if len(matches) == 1
        else Unavailable(strategy, "no_unique_confirmed_failed_break")
    )
