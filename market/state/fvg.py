"""Three-candle imbalance (FVG) proxy.

A formal three-candle proxy, not proof of institutional imbalance. Over three
*registered-consecutive* completed candles of one granularity (no mixing across
granularities, no gap substitution): a *bullish* gap exists iff candle 1's high
is strictly below candle 3's low; a *bearish* gap iff candle 1's low is strictly
above candle 3's high. Equality is no gap. The middle candle must displace in the
gap direction with a body of at least ``g * ATR`` where the ATR is the value
*contemporaneous* with candle 3 (so appending later bars never re-qualifies a
past gap). The gap has deterministic boundaries; fill, expiry (evaluated within
the expiry window so a late fill cannot un-expire it) and internal-swing-break
invalidation are tracked from the subsequent candles. Spread-normalization uses
the candle-3 spread when available, else is reported unavailable (design §7.4).
"""

from decimal import Decimal

from market.state.canonical import format_decimal
from market.state.features import atr_at_index, bars_are_consecutive, confirmed_swings

FVG_V = "fvg-v1"
FVG_DISPLACEMENT_ATR = Decimal("1.0")  # g: middle-candle body threshold
FVG_EXPIRY_BARS = 50  # candles after creation within which a fill avoids expiry


def _iso(value):
    from datetime import UTC

    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _unavailable(reason):
    return {"state": "unavailable", "version": FVG_V, "reason_code": reason}


def find_fvgs(bars, pip_size, *, atr_override=None, displacement=FVG_DISPLACEMENT_ATR):
    """Return every three-candle FVG proxy in ``bars``.

    ``atr_override`` forces the ATR (unit-test hook); production passes ``None``
    so the contemporaneous ATR at candle 3 is used and a gap that cannot yet be
    ATR-qualified is simply not emitted.
    """
    if len(bars) < 3:
        return _unavailable("insufficient_history")
    gaps = []
    for i in range(len(bars) - 2):
        c1, c2, c3 = bars[i], bars[i + 1], bars[i + 2]
        if not (bars_are_consecutive(c1, c2) and bars_are_consecutive(c2, c3)):
            continue  # a missing registered interval is not a gap
        if c1.high < c3.low:
            direction, gap_low, gap_high = "bullish", c1.high, c3.low
            displaced = c2.close > c2.open
        elif c1.low > c3.high:
            direction, gap_low, gap_high = "bearish", c3.high, c1.low
            displaced = c2.close < c2.open
        else:
            continue  # equality or overlap = no gap
        atr = atr_override if atr_override is not None else atr_at_index(bars, i + 2)
        if atr is None or atr == 0:
            continue  # no contemporaneous ATR to qualify displacement against
        body = abs(c2.close - c2.open)
        if not displaced or body < displacement * atr:
            continue
        raw_gap = gap_high - gap_low
        following = bars[i + 3 :]
        gap = {
            "direction": direction,
            "created_at": _iso(c3.end or c3.timestamp),
            "gap_low": format_decimal(gap_low),
            "gap_high": format_decimal(gap_high),
            "raw_gap": format_decimal(raw_gap),
            "gap_atr": format_decimal(raw_gap / atr),
            "gap_pips": format_decimal(raw_gap / pip_size, Decimal("0.1")),
            "spread_normalized": _spread_normalized(raw_gap, c3.spread),
            **_fill_state(direction, gap_low, gap_high, raw_gap, following),
        }
        gaps.append(gap)
    return {"state": "available", "version": FVG_V, "fvgs": gaps}


def _spread_normalized(raw_gap, spread):
    if spread is None:
        return {"state": "unavailable", "reason_code": "spread_unavailable"}
    if spread == 0:
        return {"state": "unavailable", "reason_code": "spread_unavailable"}
    return {"state": "available", "value": format_decimal(raw_gap / spread)}


def _fill_state(direction, gap_low, gap_high, raw_gap, following):
    """Partial fill, full fill, expiry (window-bounded) and internal-swing-break.

    A bullish gap fills downward; a bearish gap fills upward. Full fill is a
    completed close through the far boundary. Expiry is decided within the first
    ``FVG_EXPIRY_BARS`` following candles, so a fill after the window cannot
    reset it. Internal-swing-break invalidation is a confirmed opposing swing in
    the following candles that is then broken by a completed close."""
    if not following:
        return {
            "partial_fill_pct": "0.0",
            "full_fill": False,
            "internal_swing_break": False,
            "invalidated": False,
            "expired": False,
        }
    if direction == "bullish":
        deepest = min(bar.low for bar in following)
        penetrated = gap_high - max(min(deepest, gap_high), gap_low)
        full = any(bar.close <= gap_low for bar in following)
        window_full = any(bar.close <= gap_low for bar in following[:FVG_EXPIRY_BARS])
    else:
        deepest = max(bar.high for bar in following)
        penetrated = min(max(deepest, gap_low), gap_high) - gap_low
        full = any(bar.close >= gap_high for bar in following)
        window_full = any(bar.close >= gap_high for bar in following[:FVG_EXPIRY_BARS])
    pct = (penetrated / raw_gap) * Decimal(100) if raw_gap else Decimal(0)
    expired = len(following) > FVG_EXPIRY_BARS and not window_full
    internal_break = _internal_swing_break(direction, following)
    return {
        "partial_fill_pct": format_decimal(pct, Decimal("0.1")),
        "full_fill": full,
        "internal_swing_break": internal_break,
        "invalidated": full or internal_break,
        "expired": expired,
    }


def _internal_swing_break(direction, following):
    swings = confirmed_swings(following)
    if direction == "bullish":
        for swing in (s for s in swings if s.kind == "low"):
            if any(
                following[j].close < swing.price for j in range(swing.index + 1, len(following))
            ):
                return True
    else:
        for swing in (s for s in swings if s.kind == "high"):
            if any(
                following[j].close > swing.price for j in range(swing.index + 1, len(following))
            ):
                return True
    return False
