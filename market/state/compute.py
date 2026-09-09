"""Assemble and persist a market-state snapshot from causal inputs.

This slice establishes the persistence/causality contract end to end with a
deliberately small, honest descriptive payload: per requested granularity, the
count of eligible candles and the latest eligible candle's midpoint close, or an
explicit ``unavailable`` reason. The higher-timeframe features (trend, swings,
volatility, structure, …) are layered into this same payload by later slices
without changing the contract. Every value is an observable fact at the cutoff;
no threshold, classification, entry, exit or risk rule is applied here.
"""

from market.state.canonical import format_decimal
from market.state.definitions import register_definition
from market.state.manifest import _iso, build_input_manifest, eligible_observations
from market.state.snapshots import persist_snapshot

DESCRIPTOR_KEY = "market-state-descriptor"
DESCRIPTOR_VERSION = "0.1.0"

#: The canonical body of the v0 descriptor definition. Observable facts only.
DESCRIPTOR_DEFINITION = {
    "algorithms": {
        "input_manifest": "causal-eligibility-v1",
        "descriptor": "latest-eligible-candle-v1",
    },
    "features": ["eligible_candle_count", "latest_eligible_candle"],
    "price_basis": "midpoint",
    "rounding": {"quantum": "0.000001", "mode": "ROUND_HALF_EVEN"},
    "calendar_policy": "ny-fx-week-v1",
    "missing_data_policy": "explicit-unavailable-v1",
    "lookbacks": {},
    "thresholds": {},
}


def ensure_descriptor_definition():
    """Register (idempotently) and return the v0 descriptor definition."""
    return register_definition(DESCRIPTOR_KEY, DESCRIPTOR_VERSION, DESCRIPTOR_DEFINITION)


def _midpoint_close(observation):
    return format_decimal((observation.bid_close + observation.ask_close) / 2)


def _granularity_descriptor(instrument, granularity, information_cutoff):
    rows = eligible_observations(instrument, granularity, information_cutoff)
    if not rows:
        return {"state": "unavailable", "reason_code": "insufficient_history"}
    latest = rows[-1]
    return {
        "state": "available",
        "eligible_candle_count": len(rows),
        "latest_eligible_candle": {
            "timestamp": _iso(latest.timestamp),
            "revision": latest.revision,
            "midpoint_close": _midpoint_close(latest),
        },
    }


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
    output_payload = {
        "schema": "market-state/descriptor-v0",
        "definition": [definition.key, definition.version],
        "instrument": instrument.code,
        "information_cutoff": _iso(information_cutoff),
        "granularities": per_granularity,
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
