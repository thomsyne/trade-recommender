"""Fixed-path governance for the v2 exploratory-return runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research import exploratory_returns_v2_governance as calculator_governance
from research import s2_policy_v2

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs/strategy/failed-break/v2"
ARTIFACT_PATH = DOCS / "exploratory-return-runner-preregistration-v2.json"
REPORT_PATH = DOCS / "exploratory-return-runner-architecture.md"
AUTHORIZATION_PATH = DOCS / "exploratory-return-execution-authorization-v2.json"

REPOSITORY_BASELINE = "efd125f1a5c6fe9778cfdc966c36b1a33f918c07"
SCHEMA = "failed-break-v2-exploratory-return-runner-preregistration-v1"
IDENTITY = "failed-break-v2-exploratory-return-runner-v1"
ARTIFACT_SHA256 = "2604c39f8ab9aa5076da4dfe97e71d749de7b2fddb979a296b9ec256270ef6d7"
SELF_SHA256 = "8c2e4bf7956fcc8e697b04095803a8e65604282cfe92264ca3d4f87c24645043"
REPORT_SHA256 = "cb4fa82a1a4d8e7a2f358e56589d12492b866a33a54a4fb9636b0a90bf25cb37"
RUNNER_SHA256 = "e436cbd5eb1d5e39a83382d28eaf3696dbbbaecf6a4d372832f472e75f043eb5"
ADAPTER_SHA256 = "6ec419cd8d6d250aeef54fa98a867aeaa89f91b5092ff3614b6d8888e6f142d0"
COMMAND_SHA256 = "4d41b1021837c59f71fde4ce6edd20c30c9064334f35548801233e9b05913d52"
CALCULATOR_ARTIFACT_SHA256 = calculator_governance.ARTIFACT_SHA256
CALCULATOR_SELF_SHA256 = calculator_governance.SELF_SHA256
S2_ARTIFACT_SHA256 = s2_policy_v2.ARTIFACT_SHA256
S2_POLICY_SHA256 = s2_policy_v2.POLICY_SHA256
S1_ACCEPTANCE_SHA256 = s2_policy_v2.S1_ARTIFACT_SHA256
GEOMETRY_ARTIFACT_SHA256 = s2_policy_v2.GEOMETRY_ARTIFACT_SHA256
GEOMETRY_EVENT_SET_SHA256 = s2_policy_v2.EVENT_SET_SHA256
BOUNDARY_PURGED_EVENT_KEY = calculator_governance.BOUNDARY_PURGED_EVENT_KEY


class RunnerGovernanceRefusal(ValueError):
    """A fixed artifact, source identity, or authority failed closed."""


def require(condition, message):
    if not condition:
        raise RunnerGovernanceRefusal(message)


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def governed_event_keys() -> tuple[str, ...]:
    keys = calculator_governance.governed_event_keys()
    require(len(keys) == 82 and BOUNDARY_PURGED_EVENT_KEY not in keys, "event set changed")
    return keys


def load_preregistration() -> dict:
    try:
        raw = ARTIFACT_PATH.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == ARTIFACT_SHA256, "artifact digest mismatch")
        artifact = json.loads(raw)
        require(canonical_bytes(artifact) + b"\n" == raw, "artifact bytes are not canonical")
        body = dict(artifact)
        require(
            body.pop("implementation_sha256", None) == SELF_SHA256 == digest(body),
            "artifact self-hash mismatch",
        )
        require(
            artifact["schema"] == SCHEMA
            and artifact["identity"] == IDENTITY
            and artifact["repository_baseline"] == REPOSITORY_BASELINE,
            "runner identity changed",
        )
        require(
            artifact["authority"]
            == {
                "code_only_implementation": True,
                "persistent_execution": False,
                "post_entry_real_outcome_access": False,
                "real_outcome_access": False,
                "return_calculation": False,
                "synthetic_verification": True,
                "promotion_or_live_trading": False,
                "provider_production_or_deployment": False,
            },
            "implementation authority changed",
        )
        require(
            artifact["execution_authorization"]
            == {
                "artifact_present": False,
                "future_command": "python manage.py calculate_exploratory_returns_v2 --execute",
                "retry": "PROHIBITED",
                "resume": "PROHIBITED",
                "status": "SEPARATELY_UNAUTHORIZED",
            },
            "execution boundary changed",
        )
        bindings = artifact["bindings"]
        require(
            bindings["calculator"]
            == {
                "artifact_sha256": CALCULATOR_ARTIFACT_SHA256,
                "self_sha256": CALCULATOR_SELF_SHA256,
            }
            and bindings["effective_s2_policy"]
            == {
                "artifact_sha256": S2_ARTIFACT_SHA256,
                "policy_sha256": S2_POLICY_SHA256,
            }
            and bindings["s1_acceptance_sha256"] == S1_ACCEPTANCE_SHA256
            and bindings["geometry_artifact_sha256"] == GEOMETRY_ARTIFACT_SHA256
            and bindings["geometry_event_set_sha256"] == GEOMETRY_EVENT_SET_SHA256,
            "upstream governed identity changed",
        )
        source_files = bindings["source_files"]
        expected_sources = {
            "research/exploratory_return_adapter_v2.py": ADAPTER_SHA256,
            "research/exploratory_return_runner_v2.py": RUNNER_SHA256,
            "research/management/commands/calculate_exploratory_returns_v2.py": COMMAND_SHA256,
        }
        require(source_files == expected_sources, "governed source map changed")
        for relative, expected in expected_sources.items():
            require(_source_hash(ROOT / relative) == expected, f"source drift: {relative}")
        require(_source_hash(REPORT_PATH) == REPORT_SHA256, "architecture report drift")
        calculator_governance.load_preregistration()
        policy = s2_policy_v2.load_policy()
        require(
            policy["status"] == "EFFECTIVE_EXPLORATORY_ONLY"
            and policy["boundary"]["promotion_permanently_prohibited"] is True,
            "effective exploratory-only policy changed",
        )
        require(
            artifact["expected"]["physical_event_count"] == len(governed_event_keys()) == 82
            and artifact["expected"]["one_complete_result"] is True,
            "expected result boundary changed",
        )
        return artifact
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise RunnerGovernanceRefusal("incomplete runner preregistration") from error


def inspect_execution_authorization() -> dict:
    """Inspect only the fixed expected path; absence is the committed state."""
    if not AUTHORIZATION_PATH.exists():
        return {
            "path": str(AUTHORIZATION_PATH.relative_to(ROOT)),
            "present": False,
            "status": "SEPARATELY_UNAUTHORIZED",
        }
    return {
        "path": str(AUTHORIZATION_PATH.relative_to(ROOT)),
        "present": True,
        "status": "UNVERIFIED_AUTHORIZATION_PRESENT",
    }


def require_execution_authorization() -> dict:
    """Fail before any outcome adapter or Django model can be imported."""
    status = inspect_execution_authorization()
    require(status["present"] is True, "persistent exploratory return execution unauthorized")
    # A later additive gate must pin and verify the exact authorization bytes.
    raise RunnerGovernanceRefusal("execution authorization verifier is not yet governed")


def require_promotion(*_args, **_kwargs):
    load_preregistration()
    raise RunnerGovernanceRefusal("promotion and live trading are permanently prohibited")
