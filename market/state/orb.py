"""Opening-range (ORB) features from the completed first M15 candle.

An ORB does not exist until the first M15 interval of the session completes and
becomes available; a missing opening candle is reported unavailable and the next
M15 candle is never substituted (design §7.4). Outputs: ORH/ORL, range size and
its ATR- and spread-normalized forms, the first completed close outside the
range (breakout) distinct from a wick-only breach, and a simple retest/failure
state. No output selects a trade.
"""

from market.state.canonical import format_decimal
from market.state.features import contiguous

ORB_V = "orb-v1"


def _iso(value):
    from datetime import UTC

    return value.astimezone(UTC).isoformat(timespec="microseconds")


def opening_range(opening_bar, session_bars, atr, spread, *, session_name, local_open, tzinfo):
    """Build the ORB feature. ``opening_bar`` is the completed first M15 candle;
    ``session_bars`` are the later completed M15 candles of the same session."""
    if not contiguous([opening_bar, *session_bars]):
        return orb_unavailable("missing_registered_interval", session_name=session_name)
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
        "formed_at": _iso(opening_bar.end or opening_bar.timestamp),
        "available_at": _iso(opening_bar.available_at),
        "utc_start": _iso(opening_bar.timestamp),
        "utc_end": _iso(opening_bar.end or opening_bar.timestamp),
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
    breakout_bar = None
    breakout_index = None
    wick_only = False
    for i, bar in enumerate(session_bars):
        if breakout is None:
            if bar.close > orh:
                breakout, breakout_bar, breakout_index = "up", bar, i
            elif bar.close < orl:
                breakout, breakout_bar, breakout_index = "down", bar, i
            elif bar.high > orh or bar.low < orl:
                wick_only = True  # pierced without a completed close outside
    state = {"breakout": breakout, "wick_only_breach": wick_only}
    if breakout is not None:
        boundary = orh if breakout == "up" else orl
        # breakout_at is the breakout candle's completion (formation time), not its
        # start, so the historical event fact is stamped at the right instant.
        state["breakout_at"] = _iso(breakout_bar.end or breakout_bar.timestamp)
        state["breakout_available_at"] = _iso(breakout_bar.available_at)
        state["breakout_spread"] = (
            {"state": "available", "value": format_decimal(breakout_bar.spread)}
            if breakout_bar.spread is not None and breakout_bar.spread > 0
            else {"state": "unavailable", "reason_code": "spread_unavailable"}
        )
        after = session_bars[breakout_index + 1 :]
        failed = False
        retest = False
        for bar in after:
            if (breakout == "up" and bar.close <= orh) or (breakout == "down" and bar.close >= orl):
                failed = True
                state["failed_at"] = _iso(bar.available_at)
                break  # terminal for this breakout; no implicit renewed breakout
            elif breakout == "up" and bar.low <= boundary and bar.close > orh:
                retest = True  # returned to the broken boundary but held beyond it
                state.setdefault("retest_at", _iso(bar.available_at))
            elif breakout == "down" and bar.high >= boundary and bar.close < orl:
                retest = True
                state.setdefault("retest_at", _iso(bar.available_at))
        state["failed"] = failed
        state["retest"] = retest
    return state


def orb_unavailable(reason, *, session_name):
    return {
        "state": "unavailable",
        "version": ORB_V,
        "session": session_name,
        "reason_code": reason,
    }
