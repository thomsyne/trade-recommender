"""Single-use, fail-closed persistent execution gate for failed-break v2 S1."""

from __future__ import annotations

import hashlib
import signal
import subprocess
from contextlib import contextmanager

from django.db import transaction

from research.failed_break_services import evidence_hash
from research.failed_break_v2_s0 import V2_S0_AS_OF, validate_v2_s0_prerequisites
from research.failed_break_v2_s0_governance import (
    OUTCOME_ARTIFACT_SHA256,
    select_persistent_v2_s0_evidence,
    verify_v2_s0_acceptance,
)
from research.failed_break_v2_s1 import (
    V2S1Refusal,
    _assert_pristine,
    _configuration,
    persist_projection,
    project_v2_s1,
)
from research.failed_break_v2_s1_governance import (
    ROOT,
    inspect_v2_s1_execution_authorization,
    load_v2_s1_policy,
)
from research.models import (
    AnalysisRun,
    EntryEligibilityEvaluation,
    JobRun,
    Level,
    LevelLifecycleEvent,
    SetupEvent,
    SetupLevelAttribution,
    SetupTransition,
    StrategyParameterManifest,
    StrategyVersion,
)

AUTHORIZED_BASELINE = "badfaee13e63b1764de291de3dd260c037db65ea"
OPERATIONAL_CEILING_SECONDS = 1_800


def _sha256(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def _verify_repository_and_sources(authorization: dict) -> None:
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", AUTHORIZED_BASELINE, "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise V2S1Refusal("authorized repository baseline is not an ancestor of HEAD") from error
    if authorization["repository_baseline"] != AUTHORIZED_BASELINE:
        raise V2S1Refusal("authorized repository baseline changed")
    for path, expected in authorization["source_sha256"].items():
        if _sha256(path) != expected:
            raise V2S1Refusal(f"authorized execution source changed: {path}")


def _observed_pre_state(*, dataset, strategy) -> dict:
    return {
        "analysis_runs_v1": AnalysisRun.objects.filter(strategy_version_id=1).count(),
        "analysis_runs_v2": AnalysisRun.objects.filter(
            dataset_version=dataset, strategy_version=strategy
        ).count(),
        "entry_eligibility_v2": EntryEligibilityEvaluation.objects.filter(
            setup__dataset_version=dataset, setup__strategy_version=strategy
        ).count(),
        "job_runs": JobRun.objects.count(),
        "levels_v2": Level.objects.filter(
            dataset_version=dataset, strategy_version=strategy
        ).count(),
        "lifecycle_events_v2": LevelLifecycleEvent.objects.filter(
            level__dataset_version=dataset, level__strategy_version=strategy
        ).count(),
        "parameter_manifests": StrategyParameterManifest.objects.count(),
        "setup_attributions_v2": SetupLevelAttribution.objects.filter(
            setup__dataset_version=dataset, setup__strategy_version=strategy
        ).count(),
        "setup_transitions_v2": SetupTransition.objects.filter(
            dataset_version=dataset, strategy_version=strategy
        ).count(),
        "setups_v2": SetupEvent.objects.filter(
            dataset_version=dataset, strategy_version=strategy
        ).count(),
        "strategy_versions": StrategyVersion.objects.count(),
    }


def _verify_lineage(*, authorization, acceptance, s0_job, dataset, strategy, contract) -> None:
    binding = authorization["bindings"]
    registration = dataset.registration
    parameter = strategy.strategyparametermanifest
    actual = {
        "dataset": {
            "contract_sha256": contract.sha256,
            "effective_data_identity": contract.identity,
            "global_semantic_inventory_sha256": contract.global_semantic_inventory_sha256,
            "manifest_sha256": dataset.manifest_sha256,
            "name": dataset.name,
            "operational_id": dataset.pk,
            "registration_configuration_sha256": registration.configuration_sha256,
            "registration_report_sha256": registration.report_sha256,
            "version": dataset.version,
        },
        "strategy": {
            "content_sha256": strategy.content_hash,
            "detector_artifact_sha256": parameter.sha256,
            "detector_identity": strategy.detector_version,
            "identity": strategy.version,
            "operational_id": strategy.pk,
            "parameter_manifest_operational_id": parameter.pk,
        },
        "s0": {
            "acceptance_artifact_sha256": OUTCOME_ARTIFACT_SHA256,
            "acceptance_self_sha256": acceptance["acceptance_sha256"],
            "configuration_sha256": s0_job.config_hash,
            "job_identity": s0_job.job_name,
            "operational_job_id": s0_job.pk,
            "report_sha256": s0_job.evidence["report"]["report_sha256"],
        },
    }
    expected = {
        "dataset": binding["dataset"],
        "strategy": binding["strategy"],
        "s0": binding["s0"],
    }
    if actual != expected:
        raise V2S1Refusal("authorized dataset, strategy, registration, or S0 lineage changed")


def _projected_identity(*, projection, dataset, strategy, s0_job, policy) -> dict:
    configuration = _configuration(
        dataset=dataset,
        strategy=strategy,
        s0_job=s0_job,
        governance=policy,
    )
    canonical_evidence_sha256 = evidence_hash(projection.canonical_evidence())
    return {
        "canonical_evidence_sha256": canonical_evidence_sha256,
        "configuration_sha256": evidence_hash(configuration),
        "data_quality": projection.report["data_quality"],
        "inventory_counts": projection.report["inventory_counts"],
        "inventory_sha256": projection.report["inventory_sha256"],
        "projection_sha256": canonical_evidence_sha256,
        "report_sha256": projection.report["report_sha256"],
        "row_counts": projection.report["row_counts"],
        "setup_counts": projection.report["setup_counts"],
    }


def _verify_projection(*, authorization, projection, dataset, strategy, s0_job, policy) -> None:
    expected = {
        key: authorization["full_projection"][key]
        for key in (
            "canonical_evidence_sha256",
            "configuration_sha256",
            "data_quality",
            "inventory_counts",
            "inventory_sha256",
            "projection_sha256",
            "report_sha256",
            "row_counts",
            "setup_counts",
        )
    }
    if (
        _projected_identity(
            projection=projection,
            dataset=dataset,
            strategy=strategy,
            s0_job=s0_job,
            policy=policy,
        )
        != expected
    ):
        raise V2S1Refusal("complete v2 S1 projection differs from authorization")


@contextmanager
def _operational_ceiling():
    def expired(_signum, _frame):
        raise TimeoutError("v2 S1 exceeded its 30-minute operational ceiling")

    if not hasattr(signal, "setitimer"):
        raise V2S1Refusal("platform cannot enforce the v2 S1 operational ceiling")
    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, OPERATIONAL_CEILING_SECONDS)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _validated_inputs(authorization: dict):
    policy = load_v2_s1_policy()
    s0_job, dataset, strategy = select_persistent_v2_s0_evidence()
    acceptance = verify_v2_s0_acceptance(job=s0_job, dataset=dataset, strategy=strategy)
    ranges, contract, _ = validate_v2_s0_prerequisites(
        dataset=dataset,
        strategy=strategy,
        as_of=V2_S0_AS_OF,
    )
    _verify_lineage(
        authorization=authorization,
        acceptance=acceptance,
        s0_job=s0_job,
        dataset=dataset,
        strategy=strategy,
        contract=contract,
    )
    observed = _observed_pre_state(dataset=dataset, strategy=strategy)
    if observed != authorization["expected_pre_state"]:
        raise V2S1Refusal("v2 S1 database is not in the exact authorized pristine state")
    _assert_pristine(dataset, strategy)
    return policy, s0_job, dataset, strategy, ranges, contract


def authorization_readiness_v2_s1() -> dict:
    authorization = inspect_v2_s1_execution_authorization()
    _verify_repository_and_sources(authorization)
    policy, s0_job, dataset, strategy, ranges, contract = _validated_inputs(authorization)
    return {
        "authorization_artifact_sha256": authorization["artifact_sha256"],
        "authorization_sha256": authorization["authorization_sha256"],
        "contract_sha256": contract.sha256,
        "dataset_id": dataset.pk,
        "instrument_count": len(ranges),
        "persistent_execution_authorized": True,
        "runner_artifact_sha256": policy["artifact_sha256"],
        "s0_job_id": s0_job.pk,
        "status": "AUTHORIZED_NOT_EXECUTED",
        "strategy_version_id": strategy.pk,
    }


def execute_authorized_v2_s1(progress=None):
    authorization = inspect_v2_s1_execution_authorization()
    _verify_repository_and_sources(authorization)
    with _operational_ceiling(), transaction.atomic():
        policy, s0_job, dataset, strategy, ranges, contract = _validated_inputs(authorization)
        projection = project_v2_s1(
            dataset=dataset,
            strategy=strategy,
            ranges_by_instrument=ranges,
            contract=contract,
            s0_job=s0_job,
            progress=progress,
        )
        _verify_projection(
            authorization=authorization,
            projection=projection,
            dataset=dataset,
            strategy=strategy,
            s0_job=s0_job,
            policy=policy,
        )
        job = persist_projection(
            projection=projection,
            dataset=dataset,
            strategy=strategy,
            s0_job=s0_job,
            governance=policy,
        )
    return {
        "authorization_artifact_sha256": authorization["artifact_sha256"],
        "authorization_sha256": authorization["authorization_sha256"],
        "job_run_id": job.pk,
        **projection.report,
    }
