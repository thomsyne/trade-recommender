"""Higher-timeframe descriptive features over an ordered eligible candle list.

Every function here is a pure function of a chronological ``list[Bar]`` of
midpoint OHLC (the eligible observations already selected causally by
``market.state.manifest``), so causality and confirmation delay are inherited:
a feature that needs right-hand confirmation bars is simply unavailable until
those bars are eligible at the cutoff. Each returns a result dict with an
explicit ``state`` (``available`` / ``unavailable``) — an unavailable feature is
never reported as a neutral or false value. All prices are formatted Decimal
strings; classifications use strict inequalities with ties handled explicitly.

Definitions, thresholds and versions are fixed in docs/phase4/design.md §7.1.
No threshold here selects a trade; these are observable descriptive facts only.
"""

from decimal import Decimal
from typing import NamedTuple

from market.state.canonical import format_decimal

# --- versions (bump when an algorithm changes; snapshots bind these) ----------
SWING_V = "swing-v1"
TREND_V = "trend-v1"
SEQUENCE_V = "swing-sequence-v1"
ATR_V = "atr-v1"
VOLATILITY_V = "volatility-v1"
VOL_REGIME_V = "vol-regime-v1"
EQUILIBRIUM_V = "equilibrium-v1"
PERSISTENCE_V = "persistence-v1"
BOS_V = "bos-v1"
CHOCH_V = "choch-v1"

# --- fixed parameters ---------------------------------------------------------
SWING_LEFT = 2
SWING_RIGHT = 2
ATR_PERIOD = 14
VOL_POPULATION = 100
VOL_MIN_POPULATION = 20
COMPRESSION_PCTL = Decimal("20")
EXPANSION_PCTL = Decimal("80")
PERSISTENCE_WINDOW = 20


class Bar(NamedTuple):
    timestamp: object  # aware UTC datetime (interval start)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    # Optional trailing fields set on the production path (compute); pure-function
    # unit tests may omit them. ``end`` is the registered interval completion —
    # two bars are registered-consecutive iff the earlier one's ``end`` equals the
    # later one's ``timestamp``. ``spread`` is ask-bid at the candle close.
    end: object = None
    spread: Decimal = None
    granularity: str = ""
    observed_at: object = None
    revision: int = 1
    content_sha256: str = ""

    @property
    def available_at(self):
        return max(self.end or self.timestamp, self.observed_at or self.timestamp)


def bars_are_consecutive(earlier, later):
    """Use registered succession, including the closed FX weekend."""
    if earlier.granularity and earlier.granularity == later.granularity:
        from market.quality import registered_successor

        if earlier.granularity == "M":
            from market.quality import NEW_YORK

            a, b = earlier.timestamp.astimezone(NEW_YORK), later.timestamp.astimezone(NEW_YORK)
            return b.year * 12 + b.month == a.year * 12 + a.month + 1
        return registered_successor(earlier.timestamp, earlier.granularity) == later.timestamp
    return earlier.end is None or earlier.end == later.timestamp


def contiguous(bars):
    return all(bars_are_consecutive(a, b) for a, b in zip(bars, bars[1:]))


class Swing(NamedTuple):
    index: int
    timestamp: object
    kind: str  # "high" | "low"
    price: Decimal


def _iso(value):
    from datetime import UTC

    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _unavailable(version, reason):
    return {"state": "unavailable", "version": version, "reason_code": reason}


# --- swings -------------------------------------------------------------------
def confirmed_swings(bars, left=SWING_LEFT, right=SWING_RIGHT):
    """Chronological confirmed swings. Strict inequalities: equal highs/lows do
    not confirm a swing (they are reported separately as equal levels). The last
    ``right`` bars can never be confirmed, which is the confirmation delay."""
    swings = []
    for i in range(left, len(bars) - right):
        span = bars[i - left : i + right + 1]
        # A swing is only confirmed over registered-consecutive candles: a gap
        # (missing interval) in the confirmation window disqualifies it, so an
        # observed position never substitutes for a registered neighbour.
        if any(not bars_are_consecutive(span[k], span[k + 1]) for k in range(len(span) - 1)):
            continue
        pivot = bars[i]
        window = bars[i - left : i] + bars[i + 1 : i + 1 + right]
        if all(pivot.high > b.high for b in window):
            swings.append(Swing(i, pivot.timestamp, "high", pivot.high))
        if all(pivot.low < b.low for b in window):
            swings.append(Swing(i, pivot.timestamp, "low", pivot.low))
    swings.sort(key=lambda s: (s.index, s.kind))
    return swings


def swing_feature(bars):
    swings = confirmed_swings(bars)
    if not swings:
        return _unavailable(SWING_V, "insufficient_history")
    return {
        "state": "available",
        "version": SWING_V,
        "left": SWING_LEFT,
        "right": SWING_RIGHT,
        "swings": [
            {
                "timestamp": _iso(s.timestamp),
                "kind": s.kind,
                "price": format_decimal(s.price),
                "formed_at": _iso(bars[s.index].end or s.timestamp),
                "available_at": _iso(
                    max(
                        b.available_at
                        for b in bars[s.index - SWING_LEFT : s.index + SWING_RIGHT + 1]
                    )
                ),
            }
            for s in swings
        ],
    }


# --- trend + sequence ---------------------------------------------------------
def _by_kind(swings, kind):
    return [s for s in swings if s.kind == kind]


def trend_feature(bars):
    if not contiguous(bars):
        return _unavailable(TREND_V, "missing_registered_interval")
    swings = confirmed_swings(bars)
    highs = _by_kind(swings, "high")
    lows = _by_kind(swings, "low")
    if len(highs) < 2 or len(lows) < 2:
        return _unavailable(TREND_V, "insufficient_history")
    higher_high = highs[-1].price > highs[-2].price
    higher_low = lows[-1].price > lows[-2].price
    lower_high = highs[-1].price < highs[-2].price
    lower_low = lows[-1].price < lows[-2].price
    if higher_high and higher_low:
        classification = "uptrend"
    elif lower_high and lower_low:
        classification = "downtrend"
    else:
        classification = "range"
    return {"state": "available", "version": TREND_V, "classification": classification}


def sequence_feature(bars):
    swings = confirmed_swings(bars)
    if len(swings) < 2:
        return _unavailable(SEQUENCE_V, "insufficient_history")
    labels = []
    last_by_kind = {}
    for s in swings:
        prev = last_by_kind.get(s.kind)
        if prev is None:
            label = "first_high" if s.kind == "high" else "first_low"
        elif s.price == prev.price:
            label = "equal_high" if s.kind == "high" else "equal_low"
        elif s.kind == "high":
            label = "higher_high" if s.price > prev.price else "lower_high"
        else:
            label = "higher_low" if s.price > prev.price else "lower_low"
        labels.append({"timestamp": _iso(s.timestamp), "label": label})
        last_by_kind[s.kind] = s
    return {"state": "available", "version": SEQUENCE_V, "sequence": labels}


# --- true range / ATR ---------------------------------------------------------
def _true_ranges(bars):
    ranges = []
    for i in range(1, len(bars)):
        if not bars_are_consecutive(bars[i - 1], bars[i]):
            ranges.append(None)
            continue
        prev_close = bars[i - 1].close
        high, low = bars[i].high, bars[i].low
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return ranges


def _atr_at(true_ranges, end_index, period):
    """ATR over the ``period`` true ranges ending at ``end_index`` (inclusive)."""
    if end_index + 1 < period:
        return None
    window = true_ranges[end_index - period + 1 : end_index + 1]
    if any(value is None for value in window):
        return None
    return sum(window) / period


def atr_feature(bars, period=ATR_PERIOD):
    true_ranges = _true_ranges(bars)
    atr = _atr_at(true_ranges, len(true_ranges) - 1, period) if true_ranges else None
    if atr is None:
        return _unavailable(ATR_V, "insufficient_history")
    return {
        "state": "available",
        "version": ATR_V,
        "period": period,
        "atr": format_decimal(atr),
    }


def _current_atr(bars, period=ATR_PERIOD):
    true_ranges = _true_ranges(bars)
    if not true_ranges:
        return None
    return _atr_at(true_ranges, len(true_ranges) - 1, period)


def atr_at_index(bars, index, period=ATR_PERIOD):
    """ATR evaluated using only bars up to and including ``index`` (contemporaneous).

    Historical event qualification (e.g. an FVG's displacement threshold) must use
    the ATR as it stood when the event formed, so appending later bars never
    changes a past fact."""
    true_ranges = _true_ranges(bars[max(0, index - period) : index + 1])
    if not true_ranges:
        return None
    return _atr_at(true_ranges, len(true_ranges) - 1, period)


def volatility_percentile_feature(
    bars, period=ATR_PERIOD, population=VOL_POPULATION, min_population=VOL_MIN_POPULATION
):
    """Percentile of the current ATR among the prior eligible ATR observations
    (strictly-smaller fraction). Uses only prior observations; records the
    population size and window."""
    true_ranges = _true_ranges(bars)
    current = _atr_at(true_ranges, len(true_ranges) - 1, period) if true_ranges else None
    if current is None:
        return _unavailable(VOLATILITY_V, "insufficient_history")
    prior = [_atr_at(true_ranges, end, period) for end in range(period - 1, len(true_ranges) - 1)]
    prior = [a for a in prior if a is not None][-population:]
    if len(prior) < min_population:
        return _unavailable(VOLATILITY_V, "insufficient_history")
    smaller = sum(1 for a in prior if a < current)
    percentile = (Decimal(smaller) / Decimal(len(prior))) * Decimal(100)
    return {
        "state": "available",
        "version": VOLATILITY_V,
        "atr": format_decimal(current),
        "percentile": format_decimal(percentile, Decimal("0.01")),
        "population": len(prior),
    }


def volatility_regime_feature(bars):
    percentile = volatility_percentile_feature(bars)
    if percentile["state"] != "available":
        return _unavailable(VOL_REGIME_V, percentile["reason_code"])
    value = Decimal(percentile["percentile"])
    if value < COMPRESSION_PCTL:
        regime = "compression"
    elif value > EXPANSION_PCTL:
        regime = "expansion"
    else:
        regime = "normal"
    return {"state": "available", "version": VOL_REGIME_V, "regime": regime}


# --- range / equilibrium / persistence ----------------------------------------
def equilibrium_feature(bars):
    swings = confirmed_swings(bars)
    highs = _by_kind(swings, "high")
    lows = _by_kind(swings, "low")
    if not highs or not lows:
        return _unavailable(EQUILIBRIUM_V, "insufficient_history")
    high = highs[-1].price
    low = lows[-1].price
    midpoint = (high + low) / 2
    close = bars[-1].close
    result = {
        "state": "available",
        "version": EQUILIBRIUM_V,
        "range_low": format_decimal(low),
        "range_high": format_decimal(high),
        "midpoint": format_decimal(midpoint),
        "distance_price": format_decimal(close - midpoint),
    }
    atr = _current_atr(bars)
    if atr and atr != 0:
        result["distance_atr"] = format_decimal((close - midpoint) / atr)
    else:
        result["distance_atr_state"] = "unavailable"
        result["distance_atr_reason"] = "atr_unavailable"
    return result


def persistence_feature(bars, window=PERSISTENCE_WINDOW):
    equilibrium = equilibrium_feature(bars)
    if equilibrium["state"] != "available":
        return _unavailable(PERSISTENCE_V, equilibrium["reason_code"])
    midpoint = Decimal(equilibrium["midpoint"])
    recent = bars[-window:]
    if not contiguous(recent):
        return _unavailable(PERSISTENCE_V, "missing_registered_interval")
    count = 0
    side = None
    for bar in reversed(recent):
        bar_side = "above" if bar.close > midpoint else "below" if bar.close < midpoint else "at"
        if bar_side == "at":
            break
        if side is None:
            side = bar_side
        if bar_side != side:
            break
        count += 1
    return {
        "state": "available",
        "version": PERSISTENCE_V,
        "window": window,
        "consecutive_bars": count,
        "side": side or "at",
    }


# --- BOS / CHoCH --------------------------------------------------------------
def _directional_structure(bars):
    trend = trend_feature(bars)
    if trend["state"] != "available":
        return None
    if trend["classification"] not in ("uptrend", "downtrend"):
        return None
    return trend["classification"]


def break_of_structure_feature(bars):
    """A completed close beyond the most recent confirmed swing extreme in the
    established trend direction. Requires an established directional structure;
    wick-only penetration is not a BOS."""
    structure = _directional_structure(bars)
    if structure is None:
        return _unavailable(BOS_V, "no_established_structure")
    swings = confirmed_swings(bars)
    close = bars[-1].close
    if structure == "uptrend":
        level = _by_kind(swings, "high")[-1].price
        broken = close > level
        direction = "up"
    else:
        level = _by_kind(swings, "low")[-1].price
        broken = close < level
        direction = "down"
    return {
        "state": "available",
        "version": BOS_V,
        "structure": structure,
        "broken": broken,
        "direction": direction,
        "level": format_decimal(level),
        "close": format_decimal(close),
    }


def change_of_character_feature(bars):
    """A completed close beyond the most recent *opposing* confirmed swing — the
    first counter-trend structural break. An ordinary pullback that does not
    close beyond the opposing swing is not a CHoCH."""
    structure = _directional_structure(bars)
    if structure is None:
        return _unavailable(CHOCH_V, "no_established_structure")
    swings = confirmed_swings(bars)
    close = bars[-1].close
    if structure == "uptrend":
        level = _by_kind(swings, "low")[-1].price
        changed = close < level
        direction = "down"
    else:
        level = _by_kind(swings, "high")[-1].price
        changed = close > level
        direction = "up"
    return {
        "state": "available",
        "version": CHOCH_V,
        "structure": structure,
        "changed": changed,
        "direction": direction,
        "level": format_decimal(level),
        "close": format_decimal(close),
    }


# --- assembly -----------------------------------------------------------------
def higher_timeframe_context(bars):
    """Assemble the higher-timeframe feature block for one granularity."""
    if not bars:
        return {"state": "unavailable", "reason_code": "insufficient_history"}
    return {
        "state": "available",
        "bar_count": len(bars),
        "swings": swing_feature(bars),
        "trend": trend_feature(bars),
        "sequence": sequence_feature(bars),
        "atr": atr_feature(bars),
        "volatility_percentile": volatility_percentile_feature(bars),
        "volatility_regime": volatility_regime_feature(bars),
        "equilibrium": equilibrium_feature(bars),
        "persistence": persistence_feature(bars),
        "break_of_structure": break_of_structure_feature(bars),
        "change_of_character": change_of_character_feature(bars),
    }
