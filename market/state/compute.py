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
from datetime import timedelta
from decimal import Decimal

from market.quality import NEW_YORK
from market.state import context, features, fvg, liquidity, orb, sessions, structure
from market.state.canonical import format_decimal
from market.state.definitions import register_definition
from market.state.manifest import _iso, build_input_manifest, eligible_observations
from market.state.snapshots import persist_snapshot

DESCRIPTOR_KEY = "market-state-descriptor"
DESCRIPTOR_VERSION = "0.6.0"

FVG_GRANULARITIES = frozenset({"M15", "H1", "H4"})
ORB_SESSION_WINDOW_HOURS = 12

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
        fvg.FVG_V,
        orb.ORB_V,
        sessions.SESSION_V,
        context.SPREAD_V,
        context.EVENT_STATE_V,
        context.MACRO_REGIME_V,
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
        "fvg_displacement_atr": str(fvg.FVG_DISPLACEMENT_ATR),
        "orb_minutes": sessions.ORB_MINUTES,
    },
}


def ensure_descriptor_definition():
    """Register (idempotently) and return the descriptor definition."""
    return register_definition(DESCRIPTOR_KEY, DESCRIPTOR_VERSION, DESCRIPTOR_DEFINITION)


def _midpoint(bid, ask):
    return (bid + ask) / 2


def _pip_size(instrument):
    return Decimal("0.01") if instrument.quote_currency == "JPY" else Decimal("0.0001")


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
    if granularity in FVG_GRANULARITIES:
        fvg_block = fvg.find_fvgs(bars, atr, _pip_size(instrument))
    else:
        fvg_block = {"state": "not_applicable", "reason_code": "unsupported_granularity"}
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
        "fvg": fvg_block,
        "spread": context.spread_context(latest, atr),
    }


def _orb_block(instrument, information_cutoff):
    rows = eligible_observations(instrument, "M15", information_cutoff)
    out = {}
    if not rows:
        for name in sessions.SESSIONS:
            out[name] = orb.orb_unavailable("insufficient_history", session_name=name)
        return out
    bars = _bars_from_observations(rows)
    atr = features._current_atr(bars)
    obs_by_ts = {row.timestamp: row for row in rows}
    bar_by_ts = {row.timestamp: bar for row, bar in zip(rows, bars)}
    for name in sessions.SESSIONS:
        found = sessions.most_recent_completed_orb_open(information_cutoff, name)
        if found is None:
            out[name] = orb.orb_unavailable("session_market_closed", session_name=name)
            continue
        utc_open, local_open, tz = found
        opening = obs_by_ts.get(utc_open)
        if opening is None:
            out[name] = orb.orb_unavailable("opening_interval_missing", session_name=name)
            continue
        window_end = utc_open + timedelta(hours=ORB_SESSION_WINDOW_HOURS)
        session_bars = [
            bar_by_ts[row.timestamp] for row in rows if utc_open < row.timestamp <= window_end
        ]
        spread = opening.ask_close - opening.bid_close
        out[name] = orb.opening_range(
            bar_by_ts[utc_open],
            session_bars,
            atr,
            spread,
            session_name=name,
            local_open=local_open,
            tzinfo=tz,
        )
    return out


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


def build_market_state(instrument, definition, information_cutoff, granularities):
    """Build the canonical payload and input manifest without persisting.

    Returns ``(output_payload, manifest, manifest_sha256, data_quality_status)``.
    This is the pure computation shared by the persisting path and the read-only
    preview/dry-run command.
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
        "opening_range": _orb_block(instrument, information_cutoff),
        "event_state": context.event_state(instrument, information_cutoff),
        "macro_regime": context.macro_regime(instrument, information_cutoff),
    }
    all_available = all(g["state"] == "available" for g in per_granularity.values())
    data_quality_status = "complete" if all_available else "partial"
    return output_payload, manifest, manifest_sha256, data_quality_status


def compute_market_state(instrument, definition, information_cutoff, granularities):
    """Compute and persist the descriptive snapshot for ``instrument`` at cutoff.

    Returns ``(snapshot, created)``. Idempotent: recomputing the same identity
    returns the existing snapshot.
    """
    payload, manifest, manifest_sha256, data_quality_status = build_market_state(
        instrument, definition, information_cutoff, granularities
    )
    return persist_snapshot(
        instrument,
        definition,
        information_cutoff,
        manifest,
        manifest_sha256,
        payload,
        data_quality_status=data_quality_status,
    )
