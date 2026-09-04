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
OUTCOME_ARTIFACT_SHA256 = "7c438598d6ad8f9b94aa1d264eaa57040f1d91bc1e4f758b1231dda5a9801548"
OUTCOME_SELF_SHA256 = "4b6f6ac1f24c2a0fb0fb7f5a7246ae265e1c2b0504b06d7e30d1f7ef8cb64e31"
PREREG_SCHEMA = "failed-break-v2-s0-preregistration-v1"
PREREG_IDENTITY = "failed-break-v2-s0-preregistration-v1"
OUTCOME_SCHEMA = "failed-break-v2-s0-outcome-acceptance-v1"
OUTCOME_IDENTITY = "failed-break-v2-s0-outcome-acceptance-v1"
OUTCOME_REPOSITORY_BASELINE = "1506eea0dc785907b2c22e3d93b16e7c9489076f"
ACCEPTED_CONFIGURATION_SHA256 = "d4a61a87ed54f3a479f05a81f83cb52a97c46a2b4bf6be5f5cc735462a56d1ba"
ACCEPTED_REPORT_SHA256 = "cebaab3f8ff2157d0f40159f5d4e931d76a17edfc5237be54f39781cfefa424c"
ACCEPTED_OPERATIONAL_ANCHORS = {
    "dataset_version_id": 3,
    "job_run_id": 4,
    "strategy_parameter_manifest_id": 2,
    "strategy_version_id": 2,
}
ACCEPTED_AUTHORIZATION = {
    "promotion_or_live_trading_authorized": False,
    "returns_or_backtesting_authorized": False,
    "v2_s0_outcome": "ACCEPTED",
    "v2_s1_implementation_authorized": False,
    "v2_s1_persistent_execution_authorized": False,
}


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
    artifact = _load_canonical(
        OUTCOME_ARTIFACT_PATH,
        OUTCOME_ARTIFACT_SHA256,
        "acceptance_sha256",
    )
    preregistration = load_v2_s0_preregistration()
    dataset = preregistration["dataset"]
    strategy = preregistration["strategy"]
    expected = {
        "authorization": ACCEPTED_AUTHORIZATION,
        "dataset": {
            "contract_sha256": dataset["contract_sha256"],
            "effective_data_identity": dataset["effective_data_identity"],
            "global_semantic_inventory_sha256": dataset["global_semantic_inventory_sha256"],
            "manifest_sha256": dataset["manifest_sha256"],
            "name": dataset["name"],
            "registration_configuration_sha256": dataset["registration_configuration_sha256"],
            "registration_identity": preregistration["registration_identity"],
            "registration_report_sha256": dataset["registration_report_sha256"],
            "version": dataset["version"],
        },
        "identity": OUTCOME_IDENTITY,
        "operational_anchors": ACCEPTED_OPERATIONAL_ANCHORS,
        "preregistration": {
            "artifact_sha256": PREREG_ARTIFACT_SHA256,
            "identity": PREREG_IDENTITY,
            "self_sha256": PREREG_SELF_SHA256,
        },
        "repository_baseline": OUTCOME_REPOSITORY_BASELINE,
        "s0": {
            "as_of": preregistration["methodology"]["as_of"],
            "configuration_identity": "failed-break-v2-s0-configuration-v1",
            "configuration_sha256": ACCEPTED_CONFIGURATION_SHA256,
            "job_identity": "failed-break-signal-count-s0-v2",
            "methodology_identity": preregistration["methodology"]["identity"],
            "numerical_evidence_sha256": canonical_hash(
                preregistration["expected_numerical_evidence"]
            ),
            "report_identity": "failed-break-v2-s0-report-v1",
            "report_sha256": ACCEPTED_REPORT_SHA256,
        },
        "schema": OUTCOME_SCHEMA,
        "status": "ACCEPTED_RETURN_BLIND_V2_S0_EVIDENCE",
        "strategy": {
            "content_sha256": strategy["content_sha256"],
            "data_identity": strategy["data_identity"],
            "detector_artifact_sha256": strategy["detector_artifact_sha256"],
            "detector_identity": strategy["detector_identity"],
            "identity": strategy["identity"],
            "parameter_manifest_sha256": strategy["detector_artifact_sha256"],
        },
    }
    actual = dict(artifact)
    actual.pop("acceptance_sha256", None)
    if (
        actual != expected
        or artifact.get("acceptance_sha256") != OUTCOME_SELF_SHA256
        or artifact.get("authorization") != ACCEPTED_AUTHORIZATION
        or artifact.get("operational_anchors") != ACCEPTED_OPERATIONAL_ANCHORS
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
    contract = dataset.registration.data_contract
    registration = dataset.registration
    return {
        "authorization": ACCEPTED_AUTHORIZATION,
        "dataset": {
            "contract_sha256": contract.sha256,
            "effective_data_identity": contract.identity,
            "global_semantic_inventory_sha256": contract.global_semantic_inventory_sha256,
            "manifest_sha256": dataset.manifest_sha256,
            "name": dataset.name,
            "registration_configuration_sha256": registration.configuration_sha256,
            "registration_identity": preregistration["registration_identity"],
            "registration_report_sha256": registration.report_sha256,
            "version": dataset.version,
        },
        "schema": OUTCOME_SCHEMA,
        "identity": OUTCOME_IDENTITY,
        "status": "PENDING_INDEPENDENT_REVIEW_NOT_ACCEPTED",
        "operational_anchors": {
            "dataset_version_id": dataset.pk,
            "job_run_id": job.pk,
            "strategy_parameter_manifest_id": strategy.strategyparametermanifest.pk,
            "strategy_version_id": strategy.pk,
        },
        "preregistration": {
            "artifact_sha256": PREREG_ARTIFACT_SHA256,
            "identity": PREREG_IDENTITY,
            "self_sha256": preregistration["preregistration_sha256"],
        },
        "repository_baseline": OUTCOME_REPOSITORY_BASELINE,
        "s0": {
            "as_of": job.as_of.isoformat(),
            "configuration_identity": job.evidence["configuration"]["identity"],
            "configuration_sha256": job.config_hash,
            "job_identity": job.job_name,
            "methodology_identity": job.evidence["configuration"]["methodology_identity"],
            "numerical_evidence_sha256": canonical_hash(derived_numerical),
            "report_identity": job.evidence["report"]["identity"],
            "report_sha256": output.report_sha256,
        },
        "strategy": {
            "content_sha256": strategy.content_hash,
            "data_identity": strategy.data_identity,
            "detector_artifact_sha256": strategy.strategyparametermanifest.sha256,
            "detector_identity": strategy.detector_version,
            "identity": strategy.version,
            "parameter_manifest_sha256": strategy.strategyparametermanifest.sha256,
        },
    }


def select_persistent_v2_s0_evidence():
    """Select the accepted rows by governed semantic identities, never by database key."""
    from market.models import DatasetVersion
    from research.models import JobRun, StrategyParameterManifest, StrategyVersion

    outcome = load_v2_s0_outcome_acceptance()
    strategy_identity = outcome["strategy"]
    strategies = StrategyVersion.objects.filter(
        version=strategy_identity["identity"],
        detector_version=strategy_identity["detector_identity"],
        data_identity=strategy_identity["data_identity"],
        content_hash=strategy_identity["content_sha256"],
    )
    if strategies.count() != 1:
        raise V2S0GovernanceRefusal("v2 S0 strategy evidence is missing or duplicated")
    strategy = strategies.get()
    manifests = StrategyParameterManifest.objects.filter(
        strategy_version=strategy,
        sha256=strategy_identity["parameter_manifest_sha256"],
    )
    if manifests.count() != 1:
        raise V2S0GovernanceRefusal("v2 S0 parameter evidence is missing or duplicated")

    dataset_identity = outcome["dataset"]
    datasets = DatasetVersion.objects.filter(
        name=dataset_identity["name"],
        version=dataset_identity["version"],
        manifest_sha256=dataset_identity["manifest_sha256"],
    )
    if datasets.count() != 1:
        raise V2S0GovernanceRefusal("v2 S0 dataset evidence is missing or duplicated")
    dataset = datasets.get()

    s0_identity = outcome["s0"]
    jobs = JobRun.objects.filter(
        job_name=s0_identity["job_identity"],
        strategy_version=strategy,
        dataset_version=dataset,
        config_hash=s0_identity["configuration_sha256"],
        status="succeeded",
    )
    if jobs.count() != 1:
        raise V2S0GovernanceRefusal("v2 S0 evidence is missing or duplicated")
    return jobs.get(), dataset, strategy


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
    # Database keys are recorded for operational audit only.  The accepted rows
    # are selected and governed by the semantic identities above.
    expected["operational_anchors"] = outcome["operational_anchors"]
    expected["acceptance_sha256"] = canonical_hash(expected)
    if outcome != expected or outcome["s0"]["report_sha256"] != output.report_sha256:
        raise V2S0GovernanceRefusal("v2 S0 outcome acceptance does not reconstruct")
    return outcome


def verify_persistent_v2_s0_acceptance() -> dict:
    job, dataset, strategy = select_persistent_v2_s0_evidence()
    return verify_v2_s0_acceptance(job=job, dataset=dataset, strategy=strategy)


def v2_s0_code_readiness() -> dict:
    preregistration = load_v2_s0_preregistration()
    acceptance = load_v2_s0_outcome_acceptance()
    return {
        "status": "V2_S0_ACCEPTED_V2_S1_REMAINS_SEPARATELY_UNAUTHORIZED",
        "preregistration_artifact_sha256": PREREG_ARTIFACT_SHA256,
        "preregistration_sha256": preregistration["preregistration_sha256"],
        "outcome_artifact_sha256": OUTCOME_ARTIFACT_SHA256,
        "outcome_acceptance_sha256": acceptance["acceptance_sha256"],
        "persistent_s0_execution_authorized": False,
        "outcome_acceptance_present": True,
        "v2_s0_outcome": "ACCEPTED",
        "v2_s1_implementation_authorized": False,
        "v2_s1_execution_authorized": False,
        "returns_or_backtesting_authorized": False,
        "promotion_or_live_trading_authorized": False,
    }
