"""Canonical preregistration and fail-closed acceptance boundary for v2 S0."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREREG_ARTIFACT_PATH = ROOT / "docs/strategy/failed-break/v2/s0-preregistration-v2.json"
OUTCOME_ARTIFACT_PATH = ROOT / "docs/strategy/failed-break/v2/s0-outcome-acceptance-v2.json"
PREREG_ARTIFACT_SHA256 = "99b45b18b1345cd0d6f12863354e8aea7a39b62ab9b95651ed12db7836752d6f"
PREREG_SELF_SHA256 = "336502cbdb8dbf9098891478b29ac90af39e7b7c1be3e02592edd2e2b36b984d"
OUTCOME_ARTIFACT_SHA256 = None
PREREG_SCHEMA = "failed-break-v2-s0-preregistration-v1"
PREREG_IDENTITY = "failed-break-v2-s0-preregistration-v1"
OUTCOME_SCHEMA = "failed-break-v2-s0-outcome-acceptance-v1"
OUTCOME_IDENTITY = "failed-break-v2-s0-outcome-acceptance-v1"


class V2S0GovernanceRefusal(ValueError):
    """A v2 S0 governance identity or acceptance condition failed closed."""


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def canonical_hash(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _load_canonical(path: Path, expected_file_sha256: str, self_hash_field: str) -> dict:
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_file_sha256:
            raise V2S0GovernanceRefusal(f"{path.name} file digest mismatch")
        value = json.loads(raw)
        if canonical_bytes(value) + b"\n" != raw:
            raise V2S0GovernanceRefusal(f"{path.name} bytes are not canonical")
        body = dict(value)
        claimed = body.pop(self_hash_field, None)
        if claimed != canonical_hash(body):
            raise V2S0GovernanceRefusal(f"{path.name} self-hash mismatch")
        return value
    except (OSError, TypeError, json.JSONDecodeError) as error:
        raise V2S0GovernanceRefusal(f"invalid committed {path.name}") from error


def load_v2_s0_preregistration() -> dict:
    artifact = _load_canonical(
        PREREG_ARTIFACT_PATH,
        PREREG_ARTIFACT_SHA256,
        "preregistration_sha256",
    )
    if (
        artifact.get("schema") != PREREG_SCHEMA
        or artifact.get("identity") != PREREG_IDENTITY
        or artifact.get("preregistration_sha256") != PREREG_SELF_SHA256
        or artifact.get("repository_baseline") != "db7a774c8e381b013a26aaa82d8ab3730b823bab"
        or artifact.get("status")
        != "PREREGISTERED_PENDING_PERSISTENT_EXECUTION_AND_OUTCOME_ACCEPTANCE"
        or artifact.get("outcome_acceptance")
        != {
            "artifact_path": ("docs/strategy/failed-break/v2/s0-outcome-acceptance-v2.json"),
            "identity": OUTCOME_IDENTITY,
            "required": True,
            "schema": OUTCOME_SCHEMA,
            "status": "ABSENT_NOT_ACCEPTED",
        }
        or artifact.get("authorization")
        != {
            "persistent_s0_execution": False,
            "persistent_database_write": False,
            "v2_s1_implementation": False,
            "v2_s1_execution": False,
            "outcomes_or_returns": False,
            "provider_access": False,
            "production_access": False,
        }
    ):
        raise V2S0GovernanceRefusal("v2 S0 preregistration boundary changed")
    for relative_path, expected in artifact.get("source_sha256", {}).items():
        if hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() != expected:
            raise V2S0GovernanceRefusal(f"v2 S0 source pin changed: {relative_path}")
    return artifact


def load_v2_s0_outcome_acceptance() -> dict:
    if OUTCOME_ARTIFACT_SHA256 is None:
        raise V2S0GovernanceRefusal("v2 S0 has no committed post-execution outcome acceptance")
    artifact = _load_canonical(
        OUTCOME_ARTIFACT_PATH,
        OUTCOME_ARTIFACT_SHA256,
        "acceptance_sha256",
    )
    if (
        artifact.get("schema") != OUTCOME_SCHEMA
        or artifact.get("identity") != OUTCOME_IDENTITY
        or artifact.get("status") != "ACCEPTED_RETURN_BLIND_V2_S0_EVIDENCE"
        or artifact.get("v2_s1_execution_authorized") is not False
    ):
        raise V2S0GovernanceRefusal("v2 S0 outcome acceptance identity changed")
    return artifact


def validate_stored_v2_s0_evidence(*, job, dataset, strategy, derived_numerical: dict):
    from research.failed_break_v2_s0 import (
        V2_S0_AS_OF,
        V2_S0_JOB_NAME,
        build_v2_s0_evidence,
    )

    expected_configuration, expected_output = build_v2_s0_evidence(
        dataset=dataset,
        strategy=strategy,
        numerical_evidence=derived_numerical,
    )
    if (
        job.job_name != V2_S0_JOB_NAME
        or job.strategy_version_id != strategy.pk
        or job.dataset_version_id != dataset.pk
        or job.status != "succeeded"
        or job.as_of != V2_S0_AS_OF
        or set(job.evidence) != {"configuration", "report"}
        or job.config_hash != expected_output.configuration_sha256
        or job.evidence["configuration"] != expected_configuration
        or job.evidence["report"] != expected_output.as_dict()
    ):
        raise V2S0GovernanceRefusal("stored v2 S0 evidence is partial or changed")
    return expected_output


def build_v2_s0_outcome_candidate(*, job, dataset, strategy, derived_numerical: dict) -> dict:
    output = validate_stored_v2_s0_evidence(
        job=job,
        dataset=dataset,
        strategy=strategy,
        derived_numerical=derived_numerical,
    )
    preregistration = load_v2_s0_preregistration()
    return {
        "schema": OUTCOME_SCHEMA,
        "identity": OUTCOME_IDENTITY,
        "status": "PENDING_INDEPENDENT_REVIEW_NOT_ACCEPTED",
        "preregistration_artifact_sha256": PREREG_ARTIFACT_SHA256,
        "preregistration_sha256": preregistration["preregistration_sha256"],
        "job_run_id": job.pk,
        "dataset_id": dataset.pk,
        "strategy_version_id": strategy.pk,
        "strategy_identity": strategy.version,
        "strategy_content_sha256": strategy.content_hash,
        "configuration_sha256": job.config_hash,
        "report_sha256": output.report_sha256,
        "numerical_evidence_sha256": canonical_hash(derived_numerical),
        "v2_s1_execution_authorized": False,
    }


def verify_v2_s0_acceptance(*, job, dataset, strategy) -> dict:
    from research.failed_break_v2_s0 import (
        V2_S0_AS_OF,
        V2_S0_JOB_NAME,
        V2_S0_MAXIMUM_OBSERVATIONS,
        derive_v2_s0_numerical_evidence,
        validate_v2_s0_prerequisites,
    )
    from research.models import JobRun

    if job.job_name != V2_S0_JOB_NAME:
        raise V2S0GovernanceRefusal("v1 S0 evidence cannot authorize v2")
    ranges, contract, preregistration = validate_v2_s0_prerequisites(
        dataset=dataset,
        strategy=strategy,
        as_of=V2_S0_AS_OF,
    )
    matching = JobRun.objects.filter(
        job_name=V2_S0_JOB_NAME,
        strategy_version=strategy,
        dataset_version=dataset,
    )
    if matching.count() != 1 or matching.get().pk != job.pk:
        raise V2S0GovernanceRefusal("v2 S0 evidence is missing or duplicated")
    derived = derive_v2_s0_numerical_evidence(
        dataset=dataset,
        ranges_by_instrument=ranges,
        contract=contract,
        as_of=V2_S0_AS_OF,
        maximum_observations=V2_S0_MAXIMUM_OBSERVATIONS,
    )
    if derived != preregistration["expected_numerical_evidence"]:
        raise V2S0GovernanceRefusal("v2 S0 numerical evidence does not reconstruct")
    output = validate_stored_v2_s0_evidence(
        job=job,
        dataset=dataset,
        strategy=strategy,
        derived_numerical=derived,
    )
    outcome = load_v2_s0_outcome_acceptance()
    expected = build_v2_s0_outcome_candidate(
        job=job,
        dataset=dataset,
        strategy=strategy,
        derived_numerical=derived,
    )
    expected["status"] = "ACCEPTED_RETURN_BLIND_V2_S0_EVIDENCE"
    expected["acceptance_sha256"] = canonical_hash(expected)
    if outcome != expected or outcome["report_sha256"] != output.report_sha256:
        raise V2S0GovernanceRefusal("v2 S0 outcome acceptance does not reconstruct")
    return outcome


def v2_s0_code_readiness() -> dict:
    preregistration = load_v2_s0_preregistration()
    return {
        "status": "READY_FOR_SEPARATELY_AUTHORIZED_PERSISTENT_V2_S0_EXECUTION",
        "preregistration_artifact_sha256": PREREG_ARTIFACT_SHA256,
        "preregistration_sha256": preregistration["preregistration_sha256"],
        "persistent_s0_execution_authorized": False,
        "outcome_acceptance_present": OUTCOME_ARTIFACT_SHA256 is not None,
        "v2_s1_implementation_authorized": False,
        "v2_s1_execution_authorized": False,
    }
