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
EXECUTION_ARTIFACT_SHA256 = "9c9d0ed067447db74e33728aa77c5a925b80cc4793b5fadf69170c1dbd64a659"
EXECUTION_POLICY_SHA256 = "f548c819c6381e4531d8a3720e78e3ae2b96a6c5e7b512044ce7719c200922d5"
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


def inspect_v2_s1_execution_authorization() -> dict:
    """Verify the fixed authorization for audit or the guarded command path."""

    try:
        raw = EXECUTION_ARTIFACT_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXECUTION_ARTIFACT_SHA256:
            raise V2S1GovernanceRefusal("v2 S1 execution artifact digest mismatch")
        authorization = json.loads(raw)
        if canonical_bytes(authorization) + b"\n" != raw:
            raise V2S1GovernanceRefusal("v2 S1 execution artifact bytes are not canonical")
        body = dict(authorization)
        claimed = body.pop("authorization_sha256", None)
        if claimed != EXECUTION_POLICY_SHA256 or canonical_hash(body) != claimed:
            raise V2S1GovernanceRefusal("v2 S1 execution artifact self-hash mismatch")
        permitted = authorization["authorization"]
        if (
            authorization["schema"] != "failed-break-v2-s1-execution-authorization-v1"
            or authorization["identity"] != "failed-break-v2-s1-single-execution-v1"
            or authorization["repository_baseline"] != "badfaee13e63b1764de291de3dd260c037db65ea"
            or permitted
            != {
                "alternate_dataset_strategy_or_s0": False,
                "deployment": False,
                "exactly_one_complete_invocation": True,
                "persistent_v2_s1_execution": True,
                "production_access": False,
                "promotion_or_live_trading": False,
                "provider_or_credential_access": False,
                "resume_retry_or_truncation": False,
                "returns_or_backtesting": False,
                "s0_rerun": False,
                "v1_s1_modification": False,
            }
            or authorization["command"]
            != {
                "argv": ["python", "manage.py", "signal_count_s1_v2", "--execute"],
                "execution_parameters_allowed": False,
                "operational_ceiling_seconds": 1800,
                "persistence": "ONE_ATOMIC_TRANSACTION",
            }
        ):
            raise V2S1GovernanceRefusal("v2 S1 execution authority changed")
        bindings = authorization["bindings"]
        if (
            bindings["runner_sha256"]
            != "5a52a94f48fcd0a28ce601782a3367ca8f0829731208d9842c177bb91864da17"
            or bindings["runner_artifact_sha256"] != ARTIFACT_SHA256
            or bindings["accepted_s0_artifact_sha256"]
            != "7c438598d6ad8f9b94aa1d264eaa57040f1d91bc1e4f758b1231dda5a9801548"
            or bindings["strategy"]["identity"] != "failed-break-phase-1-admission-correction-v2"
            or bindings["strategy"]["detector_identity"]
            != "failed-break-detector-v2-admission-correction"
            or bindings["dataset"]["operational_id"] != 3
            or bindings["s0"]["operational_job_id"] != 4
            or bindings["s0"]["configuration_sha256"]
            != "d4a61a87ed54f3a479f05a81f83cb52a97c46a2b4bf6be5f5cc735462a56d1ba"
            or bindings["s0"]["report_sha256"]
            != "cebaab3f8ff2157d0f40159f5d4e931d76a17edfc5237be54f39781cfefa424c"
        ):
            raise V2S1GovernanceRefusal("v2 S1 execution lineage changed")
        projection = authorization["full_projection"]
        if (
            projection["configuration_sha256"]
            != "cff541256f9d2138260e2b7ebe04d44ff3e2ddaa0ddeafd5f0058c69af13f08b"
            or projection["report_sha256"]
            != "02ce750ee803881a06877a0474cea94f6f04e63439f979041fb294569ae2af2a"
            or projection["projection_sha256"]
            != "5aab5a0e20eae00c6984a7740d9df5d14f0c575b3b0a997b66e055818d66e714"
            or projection["canonical_evidence_sha256"] != projection["projection_sha256"]
            or projection["row_counts"]
            != {
                "analysis_runs": 344_817,
                "attributions": 1_213,
                "entry_eligibility": 752,
                "job_runs": 1,
                "levels": 17_935,
                "lifecycle_events": 17_901,
                "setups": 868,
                "transitions": 1_620,
            }
            or projection["setup_counts"]
            != {
                "confirmed": 314,
                "eligibility_decisions": {
                    "BLOCKED_SESSION": 221,
                    "BLOCKED_SPREAD": 194,
                    "ENTRY_PENDING": 188,
                    "INSUFFICIENT_REWARD": 43,
                    "NO_TARGET": 106,
                },
                "included_confirmed": 313,
                "partition_boundary_censored": 0,
                "partition_boundary_purged": 1,
                "sweeps": 868,
            }
            or projection["data_quality"] != {"analysis_data_incomplete": 0, "cancelled": 0}
            or projection["determinism"]["identical"] is not True
            or authorization["expected_pre_state"]
            != {
                "analysis_runs_v1": 344_667,
                "analysis_runs_v2": 0,
                "entry_eligibility_v2": 0,
                "job_runs": 4,
                "levels_v2": 0,
                "lifecycle_events_v2": 0,
                "parameter_manifests": 2,
                "setup_attributions_v2": 0,
                "setup_transitions_v2": 0,
                "setups_v2": 0,
                "strategy_versions": 2,
            }
        ):
            raise V2S1GovernanceRefusal("v2 S1 authorized projection changed")
        for relative_path, expected in authorization["source_sha256"].items():
            if hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() != expected:
                raise V2S1GovernanceRefusal(f"v2 S1 execution source pin changed: {relative_path}")
        return {**authorization, "artifact_sha256": EXECUTION_ARTIFACT_SHA256}
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise V2S1GovernanceRefusal("missing or invalid v2 S1 execution artifact") from error


def load_v2_s1_execution_authorization() -> dict:
    """Keep the original direct runner entry point permanently fail-closed."""

    inspect_v2_s1_execution_authorization()
    raise V2S1GovernanceRefusal(
        "direct v2 S1 execution is disabled; use the governed management command"
    )
