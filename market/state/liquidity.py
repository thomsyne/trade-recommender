"""Liquidity and price-action proxies (sweep/reclaim and acceptance).

Mechanically defined, honestly labelled proxies over the eligible candle list.
A *sweep* is a wick through a reference level (by at least ``s*ATR``) whose body
does not close beyond it, followed within a small window by a completed close
back on the origin side — a rejection of visible liquidity, not proof of order
flow. An *acceptance* is a completed close through the level that is not
reclaimed within the window; wick breach and close acceptance are always
mutually distinguishable. Reference levels are the nearest confirmed swing
extremes (the visible liquidity pools). Definitions/thresholds: design §7.3.
No output here selects a trade.
"""

from datetime import datetime
from decimal import Decimal

from market.state.canonical import format_decimal
from market.state.features import (
    ATR_PERIOD,
    SWING_LEFT,
    SWING_RIGHT,
    _by_kind,
    atr_at_index,
    confirmed_swings,
    contiguous,
)
from market.state.structure import _zone_id

SWEEP_V = "sweep-v1"
ACCEPTANCE_V = "acceptance-v1"

SWEEP_DEPTH_ATR = Decimal("0.1")  # s: minimum wick penetration
RECLAIM_WINDOW = 3  # t: bars allowed for the reclaim / acceptance test


def _utc():
    from datetime import UTC

    return UTC


def _iso(value):
    return value.astimezone(_utc()).isoformat(timespec="microseconds")


def _unavailable(version, reason):
    return {"state": "unavailable", "version": version, "reason_code": reason}


def detect_sweep(
    bars,
    atr,
    level,
    side,
    *,
    level_id,
    depth=SWEEP_DEPTH_ATR,
    window=RECLAIM_WINDOW,
    atr_history=None,
):
    """Latest wick-through-and-reclaim of ``level`` from ``side`` ('above'/'below').

    ``bars`` should begin at (or after) the reference level's formation so a
    breach that predates the level is not counted."""
    latest = None
    for i, bar in enumerate(bars):
        event_atr = atr if atr_history is None else atr_history.get(bar.timestamp)
        if not event_atr:
            continue
        margin = depth * event_atr
        if side == "above":
            breached = bar.high >= level + margin and bar.close <= level
            penetration = bar.high - level
        else:
            breached = bar.low <= level - margin and bar.close >= level
            penetration = level - bar.low
        if not breached:
            continue
        for j in range(i, min(i + window + 1, len(bars))):
            if not contiguous(bars[i : j + 1]):
                break
            reclaimed = bars[j].close < level if side == "above" else bars[j].close > level
            if reclaimed:
                reclaim_distance = (
                    level - bars[j].close if side == "above" else bars[j].close - level
                )
                latest = {
                    "level": format_decimal(level),
                    "level_id": level_id,
                    "side": side,
                    "first_breach": _iso(bar.timestamp),
                    "formed_at": _iso(bar.end or bar.timestamp),
                    "reclaim_close": _iso(bars[j].end or bars[j].timestamp),
                    "available_at": _iso(max(b.available_at for b in bars[i : j + 1])),
                    "sweep_depth_atr": format_decimal(penetration / event_atr),
                    "reclaim_distance_atr": format_decimal(reclaim_distance / event_atr),
                    "reclaim_bars": j - i,
                }
                break
    return latest


def detect_acceptance(bars, atr, level, side, *, level_id, window=RECLAIM_WINDOW):
    """Latest completed close beyond ``level`` that is not reclaimed within ``window``.

    Acceptance is only declared once the full confirmation window has elapsed with
    no reclaim: a close beyond the level with fewer than ``window`` subsequent
    bars is still pending, not accepted."""
    latest = None
    for i, bar in enumerate(bars):
        accepted = bar.close > level if side == "above" else bar.close < level
        if not accepted:
            continue
        if len(bars) - 1 - i < window:
            continue  # confirmation window has not matured -> pending, not accepted
        if not contiguous(bars[i : i + window + 1]):
            continue
        reclaimed = any(
            (bars[j].close < level if side == "above" else bars[j].close > level)
            for j in range(i + 1, min(i + window + 1, len(bars)))
        )
        if not reclaimed:
            latest = {
                "level": format_decimal(level),
                "level_id": level_id,
                "side": side,
                "acceptance_close": _iso(bar.end or bar.timestamp),
                "available_at": _iso(max(b.available_at for b in bars[i : i + window + 1])),
            }
    return latest


def liquidity_context(bars, atr, instrument_code, timeframe):
    """Sweep and acceptance proxies against the nearest confirmed swing extremes.

    Each level is only tested against bars at or after it formed, so a breach
    that predates the level is not counted."""
    atr_history = {bar.timestamp: atr_at_index(bars, i) for i, bar in enumerate(bars)}
    if not any(atr_history.values()):
        return _unavailable(SWEEP_V, "atr_unavailable")
    swings = confirmed_swings(bars)
    highs = _by_kind(swings, "high")
    lows = _by_kind(swings, "low")
    if not highs and not lows:
        return _unavailable(SWEEP_V, "insufficient_history")
    result = {"state": "available", "version": SWEEP_V}
    if highs:
        pivot = highs[-1]
        available_at = max(
            b.available_at
            for b in bars[max(0, pivot.index - SWING_LEFT) : pivot.index + SWING_RIGHT + 1]
        )
        after = bars[pivot.index + SWING_RIGHT + 1 :]
        level_id = _zone_id(pivot.price, pivot.price, instrument_code, timeframe)
        result["resistance_level"] = format_decimal(pivot.price)
        result["sweep_above"] = detect_sweep(
            after, atr, pivot.price, "above", level_id=level_id, atr_history=atr_history
        )
        result["acceptance_above"] = detect_acceptance(
            after, atr, pivot.price, "above", level_id=level_id
        )
        for name in ("sweep_above", "acceptance_above"):
            if result[name]:
                result[name]["available_at"] = _iso(
                    max(available_at, datetime.fromisoformat(result[name]["available_at"]))
                )
    if lows:
        pivot = lows[-1]
        available_at = max(
            b.available_at
            for b in bars[max(0, pivot.index - SWING_LEFT) : pivot.index + SWING_RIGHT + 1]
        )
        after = bars[pivot.index + SWING_RIGHT + 1 :]
        level_id = _zone_id(pivot.price, pivot.price, instrument_code, timeframe)
        result["support_level"] = format_decimal(pivot.price)
        result["sweep_below"] = detect_sweep(
            after, atr, pivot.price, "below", level_id=level_id, atr_history=atr_history
        )
        result["acceptance_below"] = detect_acceptance(
            after, atr, pivot.price, "below", level_id=level_id
        )
        for name in ("sweep_below", "acceptance_below"):
            if result[name]:
                result[name]["available_at"] = _iso(
                    max(available_at, datetime.fromisoformat(result[name]["available_at"]))
                )
    for name in ("sweep_above", "sweep_below"):
        event = result.get(name)
        if event:
            index = next(
                i for i, b in enumerate(bars) if _iso(b.timestamp) == event["first_breach"]
            )
            event["available_at"] = _iso(
                max(
                    datetime.fromisoformat(event["available_at"]),
                    *(b.available_at for b in bars[max(0, index - ATR_PERIOD) : index + 1]),
                )
            )
    return result
