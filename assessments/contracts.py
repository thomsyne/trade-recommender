"""Closed Phase 6A contracts. No consumers, transport, or execution semantics."""

import hashlib
from pathlib import Path

from market.state.canonical import identity_digest
from market.strategy.definitions import STRATEGIES, definition_digest

METHOD_KEY = "deterministic-multi-timeframe-assessment"
METHOD_VERSION = "1.0.0"
PHASE4_DIGEST = "9213b548d3e6c6656805d2cf230c242926f08a42112373d7518d685384b9f7d3"
IMPLEMENTATION_FILES = ("engine.py", "models.py", "services.py")
IMPLEMENTATION_SHA256 = "b6b52fc1c15fe9511ac1d66b00c2d6b3b1a8f3053d66d5cc08940f7bf01206b8"


def verify_implementation():
    root = Path(__file__).resolve().parent
    actual = identity_digest(
        {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in IMPLEMENTATION_FILES
        }
    )
    if actual != IMPLEMENTATION_SHA256:
        raise ValueError("phase6a_implementation_version_drift")


REASONS = (
    "input_integrity_failure",
    "no_economically_admitted_strategy",
    "strategy_not_admitted_for_instrument",
    "strategy_role_cannot_originate_intent",
    "required_timeframe_unavailable",
    "m15_confirmation_unavailable",
    "required_evidence_not_ready",
    "event_state_unknown",
    "event_window_blocked",
    "technical_setup_absent",
    "trigger_pending",
    "trigger_rejected",
    "trigger_invalidated",
    "trigger_expired",
    "spread_unknown",
    "spread_exceeds_strategy_limit",
    "cost_evidence_missing",
    "cost_evidence_stale",
    "net_reward_nonpositive",
    "capacity_assessment_missing",
    "aggregate_capacity_exceeded",
    "currency_direction_capacity_exceeded",
    "conflicting_eligible_setups",
    "unsupported_intent_shape",
    "unchanged_duplicate_intent",
)

CONTINUOUS = {"ewmac-d-v1", "breakout-d-v1"}
READINESS = {"carry-readiness-v1"}
OVERLAYS = {"macro-risk-v1", "fixed-risk-v1", "ewma-risk-v1", "garch-t-risk-v1"}
ROLES = {
    strategy: (
        "continuous_forecast"
        if strategy in CONTINUOUS
        else "readiness"
        if strategy in READINESS
        else "overlay"
        if strategy in OVERLAYS
        else "setup"
    )
    for strategy in STRATEGIES
}


def method_payload():
    return {
        "schema": "phase6a/method-v1",
        "key": METHOD_KEY,
        "version": METHOD_VERSION,
        "phase4_definition_sha256": PHASE4_DIGEST,
        "implementation_sha256": IMPLEMENTATION_SHA256,
        "phase5_definitions": {strategy: definition_digest(strategy) for strategy in STRATEGIES},
        "roles": ROLES,
        "required_timeframes": ["monthly-context-v1", "W", "D", "H4", "H1", "M15"],
        "required_evidence": {strategy: [] for strategy in STRATEGIES},
        "sentiment": "unavailable_no_frozen_contract",
        "m1": "unsupported_not_required",
        "entry_adapter": {},
        "reason_precedence": list(REASONS),
        "cost_components": ["spread", "commission", "slippage_latency", "financing"],
        "spread_limit_stop_r": "0.100000",
        "activation": "forbidden",
    }


METHOD_DIGEST = identity_digest(method_payload())
