"""Assemble and persist a market-state snapshot from causal inputs.

The payload is a per-granularity block of observable facts at the cutoff: the
eligible-candle count and latest midpoint close, plus the higher-timeframe
descriptive context (swings, trend, HH/HL sequence, ATR, rolling volatility
percentile and regime, range/equilibrium, persistence, break-of-structure and
change-of-character). Every feature carries an explicit availability state; an
unavailable feature is never reported as a neutral or false value. No threshold
here selects a trade — these are descriptive facts (docs/phase4/design.md §7.1).
"""

from collections import defaultdict

from market.quality import NEW_YORK
from market.state import features, liquidity, structure
from market.state.canonical import format_decimal
from market.state.definitions import register_definition
from market.state.manifest import _iso, build_input_manifest, eligible_observations
from market.state.snapshots import persist_snapshot

DESCRIPTOR_KEY = "market-state-descriptor"
DESCRIPTOR_VERSION = "0.4.0"

#: The canonical body of the descriptor definition. Observable facts only; the
#: feature list and thresholds are pinned so a snapshot binds the exact
#: algorithm versions that produced it.
DESCRIPTOR_DEFINITION = {
    "algorithms": {
        "input_manifest": "causal-eligibility-v1",
        "descriptor": "latest-eligible-candle-v1",
        "higher_timeframe": "htf-context-v1",
        "structure": "structure-context-v1",
    },
    "features": [
        "eligible_candle_count",
        "latest_eligible_candle",
        features.SWING_V,
        features.TREND_V,
        features.SEQUENCE_V,
        features.ATR_V,
        features.VOLATILITY_V,
        features.VOL_REGIME_V,
        features.EQUILIBRIUM_V,
        features.PERSISTENCE_V,
        features.BOS_V,
        features.CHOCH_V,
        structure.ZONE_V,
        structure.EQUAL_LEVELS_V,
        structure.SD_CANDIDATE_V,
        structure.CONSOLIDATION_V,
        structure.PRIOR_EXTREME_V,
        liquidity.SWEEP_V,
        liquidity.ACCEPTANCE_V,
    ],
    "price_basis": "midpoint",
    "rounding": {"quantum": "0.000001", "mode": "ROUND_HALF_EVEN"},
    "calendar_policy": "ny-fx-week-v1",
    "missing_data_policy": "explicit-unavailable-v1",
    "lookbacks": {},
    "thresholds": {
        "swing_left": features.SWING_LEFT,
        "swing_right": features.SWING_RIGHT,
        "atr_period": features.ATR_PERIOD,
        "volatility_population": features.VOL_POPULATION,
        "volatility_min_population": features.VOL_MIN_POPULATION,
        "compression_percentile": str(features.COMPRESSION_PCTL),
        "expansion_percentile": str(features.EXPANSION_PCTL),
        "persistence_window": features.PERSISTENCE_WINDOW,
        "zone_cluster_atr": str(structure.ZONE_CLUSTER_ATR),
        "equal_level_atr": str(structure.EQUAL_LEVEL_ATR),
        "displacement_atr": str(structure.DISPLACEMENT_ATR),
        "consolidation_atr": str(structure.CONSOLIDATION_ATR),
        "consolidation_window": structure.CONSOLIDATION_WINDOW,
        "failed_breakout_bars": structure.FAILED_BREAKOUT_BARS,
        "sweep_depth_atr": str(liquidity.SWEEP_DEPTH_ATR),
        "reclaim_window": liquidity.RECLAIM_WINDOW,
    },
}


def ensure_descriptor_definition():
    """Register (idempotently) and return the descriptor definition."""
    return register_definition(DESCRIPTOR_KEY, DESCRIPTOR_VERSION, DESCRIPTOR_DEFINITION)


def _midpoint(bid, ask):
    return (bid + ask) / 2


def _bars_from_observations(rows):
    return [
        features.Bar(
            timestamp=row.timestamp,
            open=_midpoint(row.bid_open, row.ask_open),
            high=_midpoint(row.bid_high, row.ask_high),
            low=_midpoint(row.bid_low, row.ask_low),
            close=_midpoint(row.bid_close, row.ask_close),
        )
        for row in rows
    ]


def _granularity_descriptor(instrument, granularity, information_cutoff):
    rows = eligible_observations(instrument, granularity, information_cutoff)
    if not rows:
        return {"state": "unavailable", "reason_code": "insufficient_history"}
    latest = rows[-1]
    bars = _bars_from_observations(rows)
    atr = features._current_atr(bars)
    return {
        "state": "available",
        "eligible_candle_count": len(rows),
        "latest_eligible_candle": {
            "timestamp": _iso(latest.timestamp),
            "revision": latest.revision,
            "midpoint_close": format_decimal(bars[-1].close),
        },
        "higher_timeframe": features.higher_timeframe_context(bars),
        "structure": structure.structure_context(bars, atr),
        "liquidity": liquidity.liquidity_context(bars, atr),
    }


def _prior_extreme(instrument, granularity, information_cutoff):
    rows = eligible_observations(instrument, granularity, information_cutoff)
    if not rows:
        return {
            "state": "unavailable",
            "version": structure.PRIOR_EXTREME_V,
            "reason_code": "insufficient_history",
        }
    return structure.prior_period_extreme(_bars_from_observations(rows[-1:]))


def _prior_completed_month(instrument, information_cutoff):
    rows = eligible_observations(instrument, "D", information_cutoff)
    if not rows:
        return {
            "state": "unavailable",
            "version": structure.PRIOR_EXTREME_V,
            "reason_code": "insufficient_history",
        }
    cutoff_local = information_cutoff.astimezone(NEW_YORK)
    cutoff_month = (cutoff_local.year, cutoff_local.month)
    months = defaultdict(list)
    for bar, row in zip(_bars_from_observations(rows), rows):
        local = row.timestamp.astimezone(NEW_YORK)
        months[(local.year, local.month)].append(bar)
    completed = [m for m in months if m < cutoff_month]
    if not completed:
        return {
            "state": "unavailable",
            "version": structure.PRIOR_EXTREME_V,
            "reason_code": "incomplete_period",
        }
    latest = max(completed)
    result = structure.prior_period_extreme(months[latest])
    result["month"] = f"{latest[0]:04d}-{latest[1]:02d}"
    return result


def compute_market_state(instrument, definition, information_cutoff, granularities):
    """Compute and persist the descriptive snapshot for ``instrument`` at cutoff.

    Returns ``(snapshot, created)``. Idempotent: recomputing the same identity
    returns the existing snapshot.
    """
    granularities = sorted(set(granularities))
    manifest, manifest_sha256 = build_input_manifest(instrument, granularities, information_cutoff)
    per_granularity = {
        granularity: _granularity_descriptor(instrument, granularity, information_cutoff)
        for granularity in granularities
    }
    prior_extremes = {
        "prior_day": _prior_extreme(instrument, "D", information_cutoff),
        "prior_week": _prior_extreme(instrument, "W", information_cutoff),
        "prior_completed_month": _prior_completed_month(instrument, information_cutoff),
    }
    output_payload = {
        "schema": "market-state/descriptor-v0",
        "definition": [definition.key, definition.version],
        "instrument": instrument.code,
        "information_cutoff": _iso(information_cutoff),
        "granularities": per_granularity,
        "prior_extremes": prior_extremes,
    }
    all_available = all(g["state"] == "available" for g in per_granularity.values())
    data_quality_status = "complete" if all_available else "partial"
    return persist_snapshot(
        instrument,
        definition,
        information_cutoff,
        manifest,
        manifest_sha256,
        output_payload,
        data_quality_status=data_quality_status,
    )
