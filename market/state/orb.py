"""Opening-range (ORB) features from the completed first M15 candle.

An ORB does not exist until the first M15 interval of the session completes and
becomes available; a missing opening candle is reported unavailable and the next
M15 candle is never substituted (design §7.4). Outputs: ORH/ORL, range size and
its ATR- and spread-normalized forms, the first completed close outside the
range (breakout) distinct from a wick-only breach, and a simple retest/failure
state. No output selects a trade.
"""

from market.state.canonical import format_decimal

ORB_V = "orb-v1"


def _iso(value):
    from datetime import UTC

    return value.astimezone(UTC).isoformat(timespec="microseconds")


def opening_range(opening_bar, session_bars, atr, spread, *, session_name, local_open, tzinfo):
    """Build the ORB feature. ``opening_bar`` is the completed first M15 candle;
    ``session_bars`` are the later completed M15 candles of the same session."""
    orh, orl = opening_bar.high, opening_bar.low
    range_size = orh - orl
    result = {
        "state": "available",
        "version": ORB_V,
        "session": session_name,
        "session_date": local_open.date().isoformat(),
        "timezone": str(tzinfo),
        "dst_offset": local_open.strftime("%z") or "+0000",
        "opening_candle": _iso(opening_bar.timestamp),
        "orh": format_decimal(orh),
        "orl": format_decimal(orl),
        "range_size": format_decimal(range_size),
    }
    if atr and atr != 0:
        result["range_atr"] = format_decimal(range_size / atr)
    else:
        result["range_atr"] = {"state": "unavailable", "reason_code": "atr_unavailable"}
    if spread and spread != 0:
        result["range_spread"] = format_decimal(range_size / spread)
    else:
        result["range_spread"] = {"state": "unavailable", "reason_code": "spread_unavailable"}
    result.update(_breakout_state(orh, orl, session_bars))
    return result


def _breakout_state(orh, orl, session_bars):
    breakout = None
    breakout_at = None
    wick_only = False
    for bar in session_bars:
        if breakout is None:
            if bar.close > orh:
                breakout, breakout_at = "up", bar.timestamp
            elif bar.close < orl:
                breakout, breakout_at = "down", bar.timestamp
            elif bar.high > orh or bar.low < orl:
                wick_only = True  # pierced without a completed close outside
    state = {"breakout": breakout, "wick_only_breach": wick_only}
    if breakout is not None:
        state["breakout_at"] = _iso(breakout_at)
        # Failure/invalidation: a later completed close back inside the range.
        after = [b for b in session_bars if b.timestamp > breakout_at]
        state["failed"] = any(orl <= b.close <= orh for b in after)
    return state


def orb_unavailable(reason, *, session_name):
    return {
        "state": "unavailable",
        "version": ORB_V,
        "session": session_name,
        "reason_code": reason,
    }
