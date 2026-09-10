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
from market.state.features import (
    ATR_PERIOD,
    SWING_LEFT,
    SWING_RIGHT,
    _iso,
    atr_at_index,
    confirmed_swings,
    contiguous,
)

ZONE_V = "zone-v1"
EQUAL_LEVELS_V = "equal-levels-v1"
SD_CANDIDATE_V = "sd-candidate-v1"
CONSOLIDATION_V = "consolidation-v1"
PRIOR_EXTREME_V = "prior-extreme-v1"

ZONE_CLUSTER_ATR = Decimal("0.25")  # c: swing merge distance / test-exit margin
ZONE_EXPIRY_INTERVALS = 200  # reachable within every registered descriptor lookback
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
    """Separate approaches to [low, high] over ``bars`` (which must begin at the
    zone's formation). Consecutive candles inside count once; a new test requires
    leaving the zone by at least ``margin`` (``>=``, the exact threshold) and
    returning."""
    count = 0
    inside = False
    for bar in bars:
        touching = bar.low <= high and bar.high >= low
        if touching:
            if not inside:
                count += 1
                inside = True
        elif bar.high <= low - margin or bar.low >= high + margin:
            inside = False
    return count


def support_resistance_zones(bars, atr, instrument_code, timeframe, cluster=ZONE_CLUSTER_ATR):
    if not contiguous(bars):
        return _unavailable(ZONE_V, "missing_registered_interval")
    swings = confirmed_swings(bars)
    if not swings:
        return _unavailable(ZONE_V, "insufficient_history")
    # Each edge uses both pivots' confirmation-time ATRs. Later volatility cannot
    # merge old pivots into a new band without any new structural evidence.
    margins = {}
    for swing in swings:
        at_confirmation = atr if atr is not None else atr_at_index(bars, swing.index + SWING_RIGHT)
        if at_confirmation:
            margins[swing] = cluster * at_confirmation
    if not margins:
        return _unavailable(ZONE_V, "atr_unavailable")
    clusters = []
    for swing in sorted(margins, key=lambda s: (s.kind, s.price, s.index)):
        previous = clusters[-1][-1] if clusters else None
        if (
            previous is not None
            and previous.kind == swing.kind
            and swing.price - previous.price <= min(margins[swing], margins[previous])
        ):
            clusters[-1].append(swing)
        else:
            clusters.append([swing])
    zones = []
    for cluster_members in clusters:
        margin = min(margins[m] for m in cluster_members)
        prices = [m.price for m in cluster_members]
        low, high = min(prices), max(prices)
        earliest = min(m.index for m in cluster_members)
        age = (len(bars) - 1) - earliest
        confirmed = max(m.index for m in cluster_members) + SWING_RIGHT
        dependencies = {
            i
            for m in cluster_members
            for i in range(
                max(0, min(m.index - SWING_LEFT, m.index + SWING_RIGHT - ATR_PERIOD)),
                m.index + SWING_RIGHT + 1,
            )
        }
        available_at = max(bars[i].available_at for i in dependencies)
        since_formation = [
            b
            for b in bars[confirmed + 1 : earliest + ZONE_EXPIRY_INTERVALS + 1]
            if b.timestamp >= available_at
        ]
        kinds = {m.kind for m in cluster_members}
        invalidation_index = next(
            (
                i
                for i, bar in enumerate(since_formation)
                if ("high" in kinds and bar.close >= high + margin)
                or ("low" in kinds and bar.close <= low - margin)
            ),
            None,
        )
        invalidated = invalidation_index is not None
        tested = since_formation[:invalidation_index] if invalidated else since_formation
        zones.append(
            {
                "zone_id": identity_digest(
                    [
                        _zone_id(low, high, instrument_code, timeframe),
                        [
                            [_iso(m.timestamp), m.kind, bars[m.index].content_sha256]
                            for m in sorted(cluster_members)
                        ],
                    ]
                ),
                "range_low": format_decimal(low),
                "range_high": format_decimal(high),
                "member_count": len(cluster_members),
                "margin_price": format_decimal(margin),
                "formed_at": _iso(bars[earliest].end or bars[earliest].timestamp),
                "available_at": _iso(available_at),
                "age_intervals": age,
                "distinct_tests": _zone_test_count(tested, low, high, margin),
                "invalidated": invalidated,
                "expired": age > ZONE_EXPIRY_INTERVALS,
            }
        )
    zones.sort(key=lambda z: (z["range_low"], z["range_high"]))
    return {"state": "available", "version": ZONE_V, "cluster_atr": str(cluster), "zones": zones}


def _local_extrema(bars, kind):
    """Local highs/lows using non-strict comparison, so adjacent EQUAL highs/lows
    (which the strict swing rule rejects) are still surfaced as levels."""
    prices = []
    for i in range(1, len(bars) - 1):
        if kind == "high":
            if bars[i].high >= bars[i - 1].high and bars[i].high >= bars[i + 1].high:
                prices.append(bars[i].high)
        elif bars[i].low <= bars[i - 1].low and bars[i].low <= bars[i + 1].low:
            prices.append(bars[i].low)
    return prices


def equal_levels(bars, atr, tolerance=EQUAL_LEVEL_ATR):
    if atr is None or atr == 0:
        return _unavailable(EQUAL_LEVELS_V, "atr_unavailable")
    if len(bars) < 3:
        return _unavailable(EQUAL_LEVELS_V, "insufficient_history")
    if not contiguous(bars):
        return _unavailable(EQUAL_LEVELS_V, "missing_registered_interval")
    margin = tolerance * atr
    result = {"state": "available", "version": EQUAL_LEVELS_V}
    for kind, name in (("high", "equal_highs"), ("low", "equal_lows")):
        prices = _local_extrema(bars, kind)
        groups = []
        if prices:
            for cluster in _single_linkage(prices, lambda p: p, margin):
                if len(cluster) >= 2:
                    groups.append(
                        {
                            "count": len(cluster),
                            "low": format_decimal(min(cluster)),
                            "high": format_decimal(max(cluster)),
                        }
                    )
        result[name] = groups
    return result


def displacement_candidates(bars, atr=None, threshold=DISPLACEMENT_ATR):
    """Origin candle bodies of displacement legs, as named supply/demand proxy
    candidates (bearish displacement -> supply candidate; bullish -> demand)."""
    candidates = []
    has_history = False
    for i in range(len(bars) - 1):
        bar = bars[i]
        event_atr = atr if atr is not None else atr_at_index(bars, i)
        if not event_atr or not contiguous(bars[i : i + 2]):
            continue
        has_history = True
        body = abs(bar.close - bar.open)
        if body < threshold * event_atr:
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
                "body_atr": format_decimal(body / event_atr),
                "timestamp": bar.timestamp.astimezone(_utc()).isoformat(timespec="microseconds"),
                "formed_at": _iso(bar.end or bar.timestamp),
                "available_at": _iso(
                    max(b.available_at for b in bars[max(0, i - ATR_PERIOD) : i + 2])
                ),
            }
        )
    if not has_history:
        return _unavailable(SD_CANDIDATE_V, "atr_unavailable")
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
    if not contiguous(base + tail):
        return _unavailable(CONSOLIDATION_V, "missing_registered_interval")
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
        failed = False
        retest = False
        for bar in after:
            if (breakout == "up" and bar.close <= high) or (
                breakout == "down" and bar.close >= low
            ):
                failed = True
                result["failed_at"] = _iso(bar.available_at)
                break
            elif breakout == "up" and bar.low <= boundary and bar.close > high:
                # Touched the broken boundary from above but held beyond it.
                retest = True
                result.setdefault("retest_at", _iso(bar.available_at))
            elif breakout == "down" and bar.high >= boundary and bar.close < low:
                retest = True
                result.setdefault("retest_at", _iso(bar.available_at))
        result["failed"] = failed
        result["retest"] = retest
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
        "support_resistance_zones": support_resistance_zones(
            bars, None, instrument_code, timeframe
        ),
        "equal_levels": equal_levels(bars, atr),
        "displacement_candidates": displacement_candidates(bars),
        "consolidation": consolidation_state(bars, atr),
    }
