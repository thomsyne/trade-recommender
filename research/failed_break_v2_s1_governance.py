"""Fixed-path, fail-closed governance for the optimized v2 S1 runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = ROOT / "docs/strategy/failed-break/v2/s1-runner-preregistration-v2.json"
ARTIFACT_SHA256 = "051a5b26820b0f4da947353f3bcca13592b3fabe2b127383892a949610fccc75"
POLICY_SHA256 = "7e7c1999301942f5724dc17148ad89a1676ad820d1f0ea1dfed8679e73913b3b"
EXECUTION_ARTIFACT_PATH = ROOT / "docs/strategy/failed-break/v2/s1-execution-authorization-v2.json"
EXECUTION_ARTIFACT_SHA256 = None
SCHEMA = "failed-break-v2-s1-runner-preregistration-v1"
IDENTITY = "failed-break-optimized-s1-runner-v2"


class V2S1GovernanceRefusal(ValueError):
    """The committed v2 S1 implementation boundary failed verification."""


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def canonical_hash(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_v2_s1_policy() -> dict:
    try:
        raw = ARTIFACT_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ARTIFACT_SHA256:
            raise V2S1GovernanceRefusal("v2 S1 artifact digest mismatch")
        policy = json.loads(raw)
        if canonical_bytes(policy) + b"\n" != raw:
            raise V2S1GovernanceRefusal("v2 S1 artifact bytes are not canonical")
        body = dict(policy)
        claimed = body.pop("v2_s1_policy_sha256", None)
        if claimed != POLICY_SHA256 or canonical_hash(body) != POLICY_SHA256:
            raise V2S1GovernanceRefusal("v2 S1 artifact self-hash mismatch")
        if (
            policy.get("schema") != SCHEMA
            or policy.get("identity") != IDENTITY
            or policy.get("repository_baseline") != "ea0c5d5d403c36661d18b049a6d2f0e532d7f189"
            or policy.get("authorization")
            != {
                "implementation": True,
                "persistent_v2_s1_execution": False,
                "promotion_or_live_trading": False,
                "returns_or_backtesting": False,
            }
            or policy.get("expected", {}).get("complete_h1_members") != 344_817
            or policy.get("expected", {}).get("new_job_identity")
            != "failed-break-signal-count-s1-v2"
        ):
            raise V2S1GovernanceRefusal("v2 S1 governed boundary changed")
        bindings = policy["bindings"]
        if (
            bindings["detector_artifact_sha256"]
            != "3b9188749c10581d7518e25838a2cb65704d1329e7ebe3061cd7fe4b82115861"
            or bindings["s0"]["acceptance_artifact_sha256"]
            != "7c438598d6ad8f9b94aa1d264eaa57040f1d91bc1e4f758b1231dda5a9801548"
            or bindings["s0"]["configuration_sha256"]
            != "d4a61a87ed54f3a479f05a81f83cb52a97c46a2b4bf6be5f5cc735462a56d1ba"
            or bindings["s0"]["report_sha256"]
            != "cebaab3f8ff2157d0f40159f5d4e931d76a17edfc5237be54f39781cfefa424c"
            or bindings["strategy"]["identity"] != "failed-break-phase-1-admission-correction-v2"
            or bindings["strategy"]["detector_identity"]
            != "failed-break-detector-v2-admission-correction"
            or bindings["dataset"]["id"] != 3
        ):
            raise V2S1GovernanceRefusal("v2 S1 accepted lineage changed")
        if (
            policy["admission"]["d_and_w"]
            != "EVERY_SEALED_MEMBER_EXACTLY_ONCE_INDEPENDENT_OF_H1_COINCIDENCE"
            or policy["admission"]["h1_decision_state"] != "PRE_COMPLETION"
            or policy["persistence"]["atomicity"]
            != "ONE_TRANSACTION_NO_RETRY_RESUME_OR_PARTIAL_SUCCESS"
            or policy["persistence"]["duplicate_policy"] != "REFUSE_BEFORE_FIRST_WRITE"
        ):
            raise V2S1GovernanceRefusal("v2 S1 detector or persistence semantics changed")
        for relative_path, expected in policy["source_sha256"].items():
            if hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() != expected:
                raise V2S1GovernanceRefusal(f"v2 S1 source pin changed: {relative_path}")
        return {**policy, "artifact_sha256": ARTIFACT_SHA256}
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise V2S1GovernanceRefusal("invalid committed v2 S1 artifact") from error


def load_v2_s1_execution_authorization() -> dict | None:
    """Load only a future fixed-path authorization; absence is the closed state."""

    if EXECUTION_ARTIFACT_SHA256 is None:
        if EXECUTION_ARTIFACT_PATH.exists():
            raise V2S1GovernanceRefusal("unreviewed v2 S1 execution artifact is present")
        return None
    raw = EXECUTION_ARTIFACT_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXECUTION_ARTIFACT_SHA256:
        raise V2S1GovernanceRefusal("v2 S1 execution artifact digest mismatch")
    authorization = json.loads(raw)
    expected = {
        "persistent_v2_s1_execution": True,
        "promotion_or_live_trading": False,
        "returns_or_backtesting": False,
        "runner_artifact_sha256": ARTIFACT_SHA256,
        "schema": "failed-break-v2-s1-execution-authorization-v1",
    }
    if canonical_bytes(authorization) + b"\n" != raw or authorization != expected:
        raise V2S1GovernanceRefusal("v2 S1 execution authorization changed")
    return authorization
