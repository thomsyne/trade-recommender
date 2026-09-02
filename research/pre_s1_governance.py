"""Canonical identities for the consolidated pre-S1 readiness policy."""

from __future__ import annotations

import hashlib
import json

from research.s0_acceptance import ARTIFACT_SHA256 as S0_ACCEPTANCE_ARTIFACT_SHA256

PRE_S1_READINESS_IDENTITY = "failed-break-pre-s1-readiness-v1"
DAILY_SWING_SUPERSESSION_IDENTITY = "daily-swing-same-type-available-at-v1"
SEALED_H1_SUCCESSOR_IDENTITY = "sealed-provider-h1-successor-v1"
SEALED_D_HORIZON_IDENTITY = "sealed-provider-d-ten-session-horizon-v1"
DATA_QUALITY_OUTCOME_IDENTITY = "per-h1-data-incomplete-fail-closed-v1"
CAD_CONVERSION_POLICY_IDENTITY = "failed-break-cad-sealed-h1-midpoint-v1"
CAD_CONVERSION_ROUTES = {
    "CAD": (),
    "USD": (("USD_CAD", "multiply"),),
    "GBP": (("GBP_USD", "multiply"), ("USD_CAD", "multiply")),
    "JPY": (("USD_JPY", "divide"), ("USD_CAD", "multiply")),
}


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


CAD_CONVERSION_ROUTE_SHA256 = _hash(CAD_CONVERSION_ROUTES)
PRE_S1_GOVERNANCE = {
    "identity": PRE_S1_READINESS_IDENTITY,
    "s0_acceptance_artifact_sha256": S0_ACCEPTANCE_ARTIFACT_SHA256,
    "daily_swing_supersession_identity": DAILY_SWING_SUPERSESSION_IDENTITY,
    "sealed_h1_successor_identity": SEALED_H1_SUCCESSOR_IDENTITY,
    "entry_boundary_validator": "research-0015-pre-s1-inventory-entry-boundary",
    "sealed_d_horizon_identity": SEALED_D_HORIZON_IDENTITY,
    "data_quality_transition_identity": DATA_QUALITY_OUTCOME_IDENTITY,
    "cad_conversion_policy_identity": CAD_CONVERSION_POLICY_IDENTITY,
    "cad_conversion_route_sha256": CAD_CONVERSION_ROUTE_SHA256,
    "cad_conversion_staleness": "latest-sealed-completion-strictly-before-entry-no-wall-clock-cutoff",
}
PRE_S1_GOVERNANCE_SHA256 = _hash(PRE_S1_GOVERNANCE)
