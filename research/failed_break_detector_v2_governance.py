"""Fixed-path, fail-closed loader for the detector-v2 admission correction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = ROOT / "docs/strategy/failed-break/v2/detector-admission-correction-v2.json"
ARTIFACT_SHA256 = "3b9188749c10581d7518e25838a2cb65704d1329e7ebe3061cd7fe4b82115861"
POLICY_SHA256 = "0946c470e82a458a0a626960cf20063ae42f183d59429a9d23dbf6f32ce59f4d"
SCHEMA = "failed-break-detector-admission-correction-v2"
STRATEGY_IDENTITY = "failed-break-phase-1-admission-correction-v2"
DETECTOR_IDENTITY = "failed-break-detector-v2-admission-correction"
DATA_IDENTITY = "oanda-ba-ny17-friday-provider-observed-v2"
DATASET_NAME = "failed-break-provider-observed-historical"
STRATEGY_CONTENT_SHA256 = ARTIFACT_SHA256
DETECTOR_SOURCE_SHA256 = "d6728111464474dce8fe4875e0548a91c32d28f599e5f57bb31d410326070135"


class DetectorV2GovernanceRefusal(ValueError):
    """The fixed v2 policy or requested authority cannot be verified."""


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _require(condition, message) -> None:
    if not condition:
        raise DetectorV2GovernanceRefusal(message)


def load_v2_policy() -> dict:
    """Load only the committed policy; no path or environment override exists."""

    try:
        raw = ARTIFACT_PATH.read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == ARTIFACT_SHA256, "artifact digest mismatch")
        policy = json.loads(raw)
        _require(canonical_bytes(policy) + b"\n" == raw, "artifact bytes are not canonical")
        body = dict(policy)
        claimed = body.pop("v2_policy_sha256")
        _require(claimed == POLICY_SHA256 == digest(body), "policy self-hash mismatch")
        _require(policy["schema"] == SCHEMA, "policy schema changed")
        _require(
            policy["repository_baseline"] == "0a52192d6675a92fe312635896c2f0d1c6dfde96",
            "baseline changed",
        )
        _require(
            policy["dataset"]
            == {
                "data_contract_sha256": (
                    "d630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c"
                ),
                "effective_data_identity": DATA_IDENTITY,
                "global_semantic_inventory_sha256": (
                    "f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427"
                ),
                "manifest_sha256": (
                    "11da094fc7ca6a30e946be33523757d7ab559a9ad1951c9142e8969539930014"
                ),
                "name": DATASET_NAME,
                "version": "phase-2b1r-v2",
            },
            "v2 dataset identity changed",
        )
        _require(
            policy["strategy"]
            == {
                "cost_identity": "cost-observed-spread-only-v1",
                "data_identity": DATA_IDENTITY,
                "detector_identity": DETECTOR_IDENTITY,
                "event_identity": "event-policy-none-v1",
                "execution_identity": "execution-h1-stop-first-v1",
                "identity": STRATEGY_IDENTITY,
                "portfolio_identity": "portfolio-common-fraction-025-100-050-v1",
                "v1_s2_policy_applicable": False,
            },
            "v2 strategy identity changed",
        )
        _require(
            policy["admission"]["event_order"] == ["COMPLETED_AT", "H1", "W", "D"]
            and policy["admission"]["same_completion_phases"]
            == [
                "H1_ENTRY_OPEN_USING_PRE_COMPLETION_STATE",
                "ADMIT_H1",
                "ADMIT_W",
                "ADMIT_D",
                "UPDATE_DW_LIFECYCLE_BIAS_AND_STRUCTURE",
                "RESOLVE_PENDING_H1_CONFIRMATION",
                "EVALUATE_H1_SWEEP_AND_CREATE_ANALYSIS",
            ]
            and policy["admission"]["d_and_w_admission"]
            == "EVERY_SEALED_MEMBER_EXACTLY_ONCE_INDEPENDENT_OF_H1_COINCIDENCE"
            and policy["admission"]["weekend_and_unusual_members"]
            == "RETAIN_WITHOUT_WEEKDAY_OR_HOUR_FILTER",
            "admission semantics changed",
        )
        _require(
            policy["supporting_swing"]
            == {
                "breach_interval": "PIVOT_AVAILABLE_AT_EXCLUSIVE_CONFIRMATION_AT_INCLUSIVE",
                "fallback": "PROVISIONAL_SWING_WHEN_NO_VALID_DAILY_PIVOT",
                "identity": "supporting-swing-pivot-lifetime-v2",
                "price_boundary": "STRICT_BREACH_ONLY_EQUALITY_IS_NOT_A_BREACH",
                "selection": "LATEST_AVAILABLE_UNBREACHED_SAME_DIRECTION_SUPPORTING_PIVOT",
            },
            "supporting-swing semantics changed",
        )
        _require(
            policy["horizon"]["detector_and_b7_membership"] == "EXACT_IDENTITY_REQUIRED"
            and policy["horizon"]["identity"] == "sealed-provider-d-ten-session-horizon-v1",
            "sealed-D horizon semantics changed",
        )
        _require(
            policy["s0_reuse"]["current_v2_readiness"] == "BLOCKED_NO_V2_S0_ACCEPTANCE"
            and policy["detector"]["persistent_runner_exposed"] is False
            and all(value is False for value in policy["authorization"].values()),
            "unauthorised v2 activation",
        )
        for relative_path, expected in policy["source_sha256"].items():
            _require(
                hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() == expected,
                f"source pin changed: {relative_path}",
            )
        return policy
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise DetectorV2GovernanceRefusal("invalid committed detector-v2 policy") from error


def v2_readiness() -> dict:
    policy = load_v2_policy()
    return {
        "policy_sha256": policy["v2_policy_sha256"],
        "strategy_identity": policy["strategy"]["identity"],
        "detector_identity": policy["detector"]["identity"],
        "detector_source_sha256": DETECTOR_SOURCE_SHA256,
        "strategy_content_sha256": STRATEGY_CONTENT_SHA256,
        "status": policy["s0_reuse"]["current_v2_readiness"],
        "persistent_runner_exposed": policy["detector"]["persistent_runner_exposed"],
        "return_execution_authorized": policy["authorization"]["return_execution"],
    }
