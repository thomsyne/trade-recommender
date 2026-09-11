"""Closed Phase 6A contracts. No consumers, transport, or execution semantics."""

import hashlib
from pathlib import Path

from market.state.canonical import identity_digest
from market.strategy.definitions import STRATEGIES, definition_digest

METHOD_KEY = "deterministic-multi-timeframe-assessment"
METHOD_VERSION = "1.2.0"
PHASE4_DIGEST = "9213b548d3e6c6656805d2cf230c242926f08a42112373d7518d685384b9f7d3"
IMPLEMENTATION_FILES = ("engine.py", "legacy.py", "models.py", "services.py")
IMPLEMENTATION_SHA256 = "1b1d552759276d3887c50a82f9704d5ace4273cf6e6641b627e8d3b694cd68cb"

METHOD_V1_DIGEST = "67b492068602ce4c9df380de98939c57d6abaef0cc1279468d9642ac377676f1"
METHOD_V11_DIGEST = "9ce72ba4fa5032d010266c06ce2928650bd31338398dee223b477c11c363d3fc"
IMPLEMENTATION_V1_SHA256 = "b6b52fc1c15fe9511ac1d66b00c2d6b3b1a8f3053d66d5cc08940f7bf01206b8"
IMPLEMENTATION_V11_SHA256 = "9cdac19ac78ac047fd6b269375892f25a299088ddcddf4a89f9c90fc69183f27"

EMPTY_ELIGIBILITY_ERA = "phase6a-canonical-empty-v1"
EMPTY_DECISION_SHA256 = identity_digest([])
EMPTY_MANIFEST_SHA256 = identity_digest({})
EMPTY_PROVENANCE_SHA256 = identity_digest("canonical-empty-no-phase55-outcome")


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


def _method_payload(version, implementation_sha256):
    payload = {
        "schema": "phase6a/method-v1" if version == "1.0.0" else "phase6a/method-v2",
        "key": METHOD_KEY,
        "version": version,
        "phase4_definition_sha256": PHASE4_DIGEST,
        "implementation_sha256": implementation_sha256,
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
    if version != "1.0.0":
        payload.update(
            economic_admission="unavailable_no_authoritative_phase55_contract",
            cost_authority="unavailable_no_immutable_source_contract",
            capacity_authority="unavailable_no_immutable_policy_source_contract",
        )
    return payload


def method_payload():
    return _method_payload(METHOD_VERSION, IMPLEMENTATION_SHA256)


def historical_method_payload(digest):
    if digest == METHOD_V1_DIGEST:
        return _method_payload("1.0.0", IMPLEMENTATION_V1_SHA256)
    if digest == METHOD_V11_DIGEST:
        return _method_payload("1.1.0", IMPLEMENTATION_V11_SHA256)
    raise ValueError("unsupported_phase6a_method")


METHOD_DIGEST = identity_digest(method_payload())
