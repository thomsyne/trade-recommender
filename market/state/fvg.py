"""Three-candle imbalance (FVG) proxy.

A formal three-candle proxy, not proof of institutional imbalance. Over three
consecutive registered completed candles of one granularity (no mixing across
granularities): a *bullish* gap exists iff candle 1's high is strictly below
candle 3's low; a *bearish* gap iff candle 1's low is strictly above candle 3's
high. Equality is no gap. The middle candle must displace in the gap direction
with a body of at least ``g*ATR``. The gap has deterministic boundaries; fill
progress and full fill/invalidation are tracked from the subsequent candles.
Spread-normalized qualification is reported unavailable when no spread is
supplied — the price facts are retained (design §7.4).
"""

from decimal import Decimal

from market.state.canonical import format_decimal

FVG_V = "fvg-v1"
FVG_DISPLACEMENT_ATR = Decimal("1.0")  # g: middle-candle body threshold
FVG_EXPIRY_BARS = 50  # candles after creation before an unfilled gap expires


def _iso(value):
    from datetime import UTC

    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _unavailable(reason):
    return {"state": "unavailable", "version": FVG_V, "reason_code": reason}


def find_fvgs(bars, atr, pip_size, displacement=FVG_DISPLACEMENT_ATR):
    """Return all three-candle FVG proxies in ``bars`` with fill state."""
    if atr is None or atr == 0:
        return _unavailable("atr_unavailable")
    if len(bars) < 3:
        return _unavailable("insufficient_history")
    gaps = []
    for i in range(len(bars) - 2):
        c1, c2, c3 = bars[i], bars[i + 1], bars[i + 2]
        if c1.high < c3.low:
            direction, gap_low, gap_high = "bullish", c1.high, c3.low
            displaced = c2.close > c2.open
        elif c1.low > c3.high:
            direction, gap_low, gap_high = "bearish", c3.high, c1.low
            displaced = c2.close < c2.open
        else:
            continue  # equality or overlap = no gap
        body = abs(c2.close - c2.open)
        if not displaced or body < displacement * atr:
            continue
        raw_gap = gap_high - gap_low
        following = bars[i + 3 :]
        gaps.append(
            {
                "direction": direction,
                "created_at": _iso(c3.timestamp),
                "gap_low": format_decimal(gap_low),
                "gap_high": format_decimal(gap_high),
                "raw_gap": format_decimal(raw_gap),
                "gap_atr": format_decimal(raw_gap / atr),
                "gap_pips": format_decimal(raw_gap / pip_size, Decimal("0.1")),
                "spread_normalized": {"state": "unavailable", "reason_code": "spread_unavailable"},
                **_fill_state(direction, gap_low, gap_high, raw_gap, following),
            }
        )
    return {"state": "available", "version": FVG_V, "fvgs": gaps}


def _fill_state(direction, gap_low, gap_high, raw_gap, following):
    """Partial-fill percentage and full-fill/invalidation from later candles.

    A bullish gap fills downward (price returns into it from above); a bearish
    gap fills upward. Full fill is a completed close through the far boundary."""
    if not following:
        return {
            "partial_fill_pct": "0.0",
            "full_fill": False,
            "invalidated": False,
            "expired": False,
        }
    if direction == "bullish":
        deepest = min(bar.low for bar in following)
        penetrated = gap_high - max(min(deepest, gap_high), gap_low)
        full = any(bar.close <= gap_low for bar in following)
    else:
        deepest = max(bar.high for bar in following)
        penetrated = min(max(deepest, gap_low), gap_high) - gap_low
        full = any(bar.close >= gap_high for bar in following)
    pct = (penetrated / raw_gap) * Decimal(100) if raw_gap else Decimal(0)
    # Expiry: an unfilled gap older than FVG_EXPIRY_BARS candles is expired.
    # (Deterministic internal-swing-break invalidation is a documented deferral,
    # design §7.4.)
    expired = not full and len(following) > FVG_EXPIRY_BARS
    return {
        "partial_fill_pct": format_decimal(pct, Decimal("0.1")),
        "full_fill": full,
        "invalidated": full,
        "expired": expired,
    }
