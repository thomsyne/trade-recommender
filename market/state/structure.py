"""Support/resistance, structure and prior-period extremes.

Pure, causal functions over the eligible candle list (plus the granularity's
current ATR for normalization). Zones are volatility-normalized clusters of
confirmed swings with deterministic identities that never depend on database row
ids or calculation order; a "test" counts a separate approach, not each candle
that rests inside a zone. Supply/demand are named proxy *candidates* derived from
observable displacement — no claim of resting orders. Definitions and thresholds
are fixed in docs/phase4/design.md §7.2; no threshold here selects a trade.
"""

from decimal import Decimal

from market.state.canonical import format_decimal, identity_digest
from market.state.features import confirmed_swings

ZONE_V = "zone-v1"
EQUAL_LEVELS_V = "equal-levels-v1"
SD_CANDIDATE_V = "sd-candidate-v1"
CONSOLIDATION_V = "consolidation-v1"
PRIOR_EXTREME_V = "prior-extreme-v1"

ZONE_CLUSTER_ATR = Decimal("0.25")  # c: swing merge distance / test-exit margin
EQUAL_LEVEL_ATR = Decimal("0.1")  # e: equal/clustered level distance
DISPLACEMENT_ATR = Decimal("1.5")  # d: displacement body threshold
CONSOLIDATION_ATR = Decimal("1.5")  # r: consolidation range ceiling
CONSOLIDATION_WINDOW = 20
FAILED_BREAKOUT_BARS = 3  # f: bars to reclaim before a breakout is "failed"


def _unavailable(version, reason):
    return {"state": "unavailable", "version": version, "reason_code": reason}


def _zone_id(low, high, instrument_code, timeframe):
    # Identity binds the version, instrument, timeframe and rounded boundaries
    # (design §7.2) — never a database row id or calculation order — so the same
    # price band on different instruments or timeframes does not collide.
    return identity_digest(
        [ZONE_V, instrument_code, timeframe, format_decimal(low), format_decimal(high)]
    )


def _single_linkage(points, key, margin):
    """Single-linkage clusters of ``points`` sorted by ``key`` within ``margin``."""
    ordered = sorted(points, key=key)
    clusters = [[ordered[0]]]
    for point in ordered[1:]:
        if key(point) - key(clusters[-1][-1]) <= margin:
            clusters[-1].append(point)
        else:
            clusters.append([point])
    return clusters


def _zone_test_count(bars, low, high, margin):
    """Separate approaches to [low, high]. Consecutive candles inside count once;
    a new test requires leaving the zone by at least ``margin`` and returning."""
    count = 0
    inside = False
    for bar in bars:
        touching = bar.low <= high and bar.high >= low
        if touching:
            if not inside:
                count += 1
                inside = True
        elif bar.high < low - margin or bar.low > high + margin:
            inside = False
    return count


def support_resistance_zones(bars, atr, instrument_code, timeframe, cluster=ZONE_CLUSTER_ATR):
    if atr is None or atr == 0:
        return _unavailable(ZONE_V, "atr_unavailable")
    swings = confirmed_swings(bars)
    if not swings:
        return _unavailable(ZONE_V, "insufficient_history")
    margin = cluster * atr
    zones = []
    for cluster_members in _single_linkage(swings, lambda s: s.price, margin):
        prices = [m.price for m in cluster_members]
        low, high = min(prices), max(prices)
        earliest = min(m.index for m in cluster_members)
        zones.append(
            {
                "zone_id": _zone_id(low, high, instrument_code, timeframe),
                "range_low": format_decimal(low),
                "range_high": format_decimal(high),
                "member_count": len(cluster_members),
                "age_intervals": (len(bars) - 1) - earliest,
                "distinct_tests": _zone_test_count(bars, low, high, margin),
            }
        )
    zones.sort(key=lambda z: (z["range_low"], z["range_high"]))
    return {"state": "available", "version": ZONE_V, "cluster_atr": str(cluster), "zones": zones}


def equal_levels(bars, atr, tolerance=EQUAL_LEVEL_ATR):
    if atr is None or atr == 0:
        return _unavailable(EQUAL_LEVELS_V, "atr_unavailable")
    swings = confirmed_swings(bars)
    if not swings:
        return _unavailable(EQUAL_LEVELS_V, "insufficient_history")
    margin = tolerance * atr
    result = {"state": "available", "version": EQUAL_LEVELS_V}
    for kind, name in (("high", "equal_highs"), ("low", "equal_lows")):
        members = [s for s in swings if s.kind == kind]
        groups = []
        if members:
            for cluster in _single_linkage(members, lambda s: s.price, margin):
                if len(cluster) >= 2:
                    groups.append(
                        {
                            "count": len(cluster),
                            "low": format_decimal(min(m.price for m in cluster)),
                            "high": format_decimal(max(m.price for m in cluster)),
                        }
                    )
        result[name] = groups
    return result


def displacement_candidates(bars, atr, threshold=DISPLACEMENT_ATR):
    """Origin candle bodies of displacement legs, as named supply/demand proxy
    candidates (bearish displacement -> supply candidate; bullish -> demand)."""
    if atr is None or atr == 0:
        return _unavailable(SD_CANDIDATE_V, "atr_unavailable")
    candidates = []
    for i in range(len(bars) - 1):
        bar = bars[i]
        body = abs(bar.close - bar.open)
        if body < threshold * atr:
            continue
        following = bars[i + 1]
        if bar.close > bar.open and following.close > bar.close:
            kind = "demand_candidate"
        elif bar.close < bar.open and following.close < bar.close:
            kind = "supply_candidate"
        else:
            continue
        origin_low = min(bar.open, bar.close)
        origin_high = max(bar.open, bar.close)
        candidates.append(
            {
                "kind": kind,
                "origin_low": format_decimal(origin_low),
                "origin_high": format_decimal(origin_high),
                "body_atr": format_decimal(body / atr),
                "timestamp": bar.timestamp.astimezone(_utc()).isoformat(timespec="microseconds"),
            }
        )
    return {"state": "available", "version": SD_CANDIDATE_V, "candidates": candidates}


def _utc():
    from datetime import UTC

    return UTC


def consolidation_state(
    bars,
    atr,
    ceiling=CONSOLIDATION_ATR,
    window=CONSOLIDATION_WINDOW,
    failed_bars=FAILED_BREAKOUT_BARS,
):
    """The most recent bounded consolidation and its breakout/retest/failed state.

    The consolidation range is measured over the ``window`` bars ending just
    before the last bar; the last bars are then examined for a completed close
    beyond a boundary (breakout), a retest of the broken boundary, and a
    reclaim back inside within ``failed_bars`` (a failed breakout)."""
    if atr is None or atr == 0:
        return _unavailable(CONSOLIDATION_V, "atr_unavailable")
    tail_len = failed_bars + 1
    if len(bars) < window + tail_len:
        return _unavailable(CONSOLIDATION_V, "insufficient_history")
    base = bars[-(window + tail_len) : -tail_len]
    tail = bars[-tail_len:]
    high = max(b.high for b in base)
    low = min(b.low for b in base)
    if high - low > ceiling * atr:
        return {"state": "available", "version": CONSOLIDATION_V, "in_consolidation": False}
    breakout = None
    breakout_index = None
    for index, bar in enumerate(tail):
        if bar.close > high:
            breakout, breakout_index = "up", index
            break
        if bar.close < low:
            breakout, breakout_index = "down", index
            break
    result = {
        "state": "available",
        "version": CONSOLIDATION_V,
        "in_consolidation": breakout is None,
        "range_low": format_decimal(low),
        "range_high": format_decimal(high),
    }
    if breakout is not None:
        after = tail[breakout_index + 1 :]
        boundary = high if breakout == "up" else low
        result["breakout"] = breakout
        # Retest: a later bar returns to touch the broken boundary.
        result["retest"] = any(bar.low <= boundary <= bar.high for bar in after)
        # Failed breakout: a later completed close back inside the range.
        result["failed"] = any(low <= bar.close <= high for bar in after)
    return result


def prior_period_extreme(period_bars):
    """High/low of a completed period from its (already period-scoped) bars."""
    if not period_bars:
        return _unavailable(PRIOR_EXTREME_V, "insufficient_history")
    return {
        "state": "available",
        "version": PRIOR_EXTREME_V,
        "high": format_decimal(max(b.high for b in period_bars)),
        "low": format_decimal(min(b.low for b in period_bars)),
    }


def structure_context(bars, atr, instrument_code, timeframe):
    """Assemble the structure block for one granularity."""
    return {
        "support_resistance_zones": support_resistance_zones(bars, atr, instrument_code, timeframe),
        "equal_levels": equal_levels(bars, atr),
        "displacement_candidates": displacement_candidates(bars, atr),
        "consolidation": consolidation_state(bars, atr),
    }
