"""Bounded read-only diagnostics: identifiers and static codes only."""

from collections import Counter

from django.core.exceptions import ValidationError
from django.utils import timezone

from forecasts.lifecycle import project_lifecycle
from forecasts.models import (
    ExperimentAssessment,
    ExperimentSample,
    PortfolioCohort,
    PortfolioSelectionMember,
    Recommendation,
    TargetOccurrence,
    TargetResolution,
)
from forecasts.targets import (
    target_endpoint,
    validate_recommendation,
    validate_resolution,
    validate_target,
)
from market.quality import registered_candle_completion


def report(*, as_of=None):
    as_of = as_of or timezone.now()
    counts, legacy = Counter(), Counter()
    details = []

    def issue(code, identifier):
        counts[code] += 1
        if len(details) < 50:
            details.append({"code": code, "id": identifier})

    for rec in Recommendation.objects.order_by("pk").iterator():
        try:
            projection = project_lifecycle(rec, as_of=as_of)
        except (KeyError, ValueError, TypeError, AttributeError):
            issue("canonical_projection_invalid", rec.pk)
            continue
        if rec.contract_version != 4:
            legacy[projection["state"]] += 1
            if not rec.target_occurrence_id or not rec.control_forecast_id:
                legacy["unpaired_legacy"] += 1
            continue
        if not rec.target_occurrence_id:
            issue("recommendation_missing_target", rec.pk)
        if not rec.control_forecast_id:
            issue("recommendation_missing_control", rec.pk)
        else:
            if rec.control_forecast.issued_at > rec.generated_at:
                issue("retrospective_control", rec.pk)
            try:
                validate_recommendation(rec)
            except (ValidationError, AttributeError):
                issue("recommendation_control_identity_mismatch", rec.pk)
        if not rec.lifecycle_events.exists():
            issue("canonical_lifecycle_missing", rec.pk)
        member = getattr(rec, "portfolio_membership", None)
        disposition = getattr(rec, "portfolio_disposition", None)
        if rec.action != "abstain" and not disposition:
            issue("directional_disposition_missing", rec.pk)
        if member and not disposition:
            issue("membership_disposition_missing", rec.pk)
        if rec.action == "abstain" and (
            member
            or rec.portfolio_admission_events.exists()
            or projection["entry_id"]
            or projection["result_id"]
        ):
            issue("abstention_execution_records", rec.pk)
        if projection["entry_id"] and projection["admission_status"] != "admitted":
            issue("entry_without_active_admission", rec.pk)
        if (
            projection["state"] == "admitted_awaiting_entry"
            and projection["admission_status"] != "admitted"
        ):
            issue("non_admitted_awaiting_entry", rec.pk)
        if projection["result_id"] and not projection["terminal"]:
            issue("terminal_result_nonterminal_lifecycle", rec.pk)
        result = getattr(rec, "paper_result", None)
        if result and (
            (result.outcome != "not_activated" and not result.entry_id)
            or projection["admission_status"] != "admitted"
        ):
            issue("result_entry_admission_mismatch", rec.pk)
        admission = rec.portfolio_admission_events.order_by("-occurred_at", "-id").first()
        if admission and (
            not member
            or admission.cohort_id != member.cohort_id
            or (
                admission.state == "admitted"
                and not admission.selection.selected_members.filter(recommendation=rec).exists()
            )
            or not member.cohort.selections.exists()
            or admission.selection_id != member.cohort.selections.first().pk
        ):
            issue("admission_selection_mismatch", rec.pk)
        resolution = getattr(rec, "resolution", None)
        if resolution and rec.target_occurrence_id:
            shared = getattr(rec.target_occurrence, "resolution", None)
            if (
                not shared
                or resolution.target_resolution_id != shared.pk
                or resolution.outcome != shared.outcome
            ):
                issue("recommendation_shared_resolution_disagreement", rec.pk)
    for target in TargetOccurrence.objects.order_by("pk").iterator():
        try:
            validate_target(target)
        except ValidationError:
            issue("target_identity_invalid", target.pk)
        controls = list(target.controls.all())
        if len({(c.method, c.method_version) for c in controls}) != len(controls):
            issue("duplicate_target_control", target.pk)
        if len(controls) > 1:
            issue("multiple_incompatible_target_controls", target.pk)
        if TargetResolution.objects.filter(target_id=target.pk).count() > 1:
            issue("multiple_target_resolutions", target.pk)
        for control in controls:
            if (
                control.instrument_id != target.instrument_id
                or control.target_contract_id != target.target_contract_id
                or control.evidence_snapshot.anchor_candle_id != target.reference_candle_id
                or control.reference_midpoint != target.reference_midpoint
                or control.neutral_band != target.neutral_band
                or control.setup_expires_after_sessions != target.horizon_sessions
                or control.information_cutoff != target.information_cutoff
                or control.method not in {"mechanical-ewma", "fixture-mechanical-ewma"}
                or control.method_version != 1
            ):
                issue("control_target_identity_mismatch", control.pk)
        mature = (
            registered_candle_completion(
                target_endpoint(target.reference_candle.timestamp, target.horizon_sessions), "D"
            )
            <= as_of
        )
        shared = getattr(target, "resolution", None)
        if mature and (not shared or shared.resolved_at > as_of):
            issue("mature_target_missing_resolution", target.pk)
        if shared:
            try:
                validate_resolution(shared)
            except ValidationError:
                issue("shared_resolution_invalid", target.pk)
            if not mature and shared.outcome == "missing":
                issue("immature_target_marked_missing", target.pk)
            for control in controls:
                resolution = getattr(control, "resolution", None)
                if resolution and (
                    resolution.target_resolution_id != shared.pk
                    or resolution.outcome != shared.outcome
                ):
                    issue("forecast_shared_resolution_disagreement", control.pk)
    for member in (
        PortfolioSelectionMember.objects.select_related("selection", "recommendation")
        .order_by("pk")
        .iterator()
    ):
        if member.recommendation.contract_version != 4:
            continue
        if not member.selection.cohort.members.filter(
            recommendation=member.recommendation
        ).exists():
            issue("selection_member_outside_cohort", member.pk)
        if not member.selection.admission_events.filter(
            recommendation=member.recommendation, state="admitted"
        ).exists():
            issue("selection_without_admission", member.pk)
    for cohort in (
        PortfolioCohort.objects.filter(decision_deadline__isnull=False).order_by("pk").iterator()
    ):
        if not getattr(cohort, "closure", None):
            if cohort.decision_deadline <= as_of:
                issue("open_cohort_past_deadline", cohort.pk)
            identities = dict(
                cohort.members.values_list(
                    "recommendation__instrument_id", "recommendation__target_occurrence_id"
                )
            )
            later = PortfolioCohort.objects.filter(
                generated_at__gt=cohort.generated_at,
                generated_at__lte=as_of,
                decision_deadline__isnull=False,
            )
            if any(
                instrument in identities and identities[instrument] != target_id
                for instrument, target_id in later.values_list(
                    "members__recommendation__instrument_id",
                    "members__recommendation__target_occurrence_id",
                )
            ):
                issue("superseded_cohort_without_closure", cohort.pk)
    for sample in (
        ExperimentSample.objects.select_related("era__method", "recommendation")
        .order_by("pk")
        .iterator()
    ):
        if sample.era.method.contract_version != 4:
            continue
        rec = sample.recommendation
        if (
            rec.contract_version != 4
            or rec.provider != sample.era.method.provider
            or rec.model != sample.era.method.requested_model
        ):
            issue("mixed_contract_era", sample.pk)
        if rec.generated_at < sample.era.starts_at:
            issue("sample_before_cutover", sample.pk)
        if (
            rec.target_occurrence_id
            and sample.issuance_cluster_key != rec.target_occurrence.identity_sha256
        ):
            issue("repeated_target_independence_mismatch", sample.pk)
    for assessment in (
        ExperimentAssessment.objects.filter(attempt__era__method__contract_version=4)
        .order_by("pk")
        .iterator()
    ):
        from forecasts.populations import assessment_values

        samples = list(
            assessment.attempt.era.samples.filter(
                assigned_at__lte=assessment.attempt.assessed_at,
                recommendation__generated_at__lte=assessment.attempt.assessed_at,
            )
        )
        expected = assessment_values(
            assessment.attempt.era, samples, assessment.attempt.assessed_at
        )
        if assessment.resolution_coverage != expected["resolution_coverage"].quantize(
            __import__("decimal").Decimal("0.000001")
        ):
            issue("mature_coverage_denominator_mismatch", assessment.pk)
        if not isinstance(assessment.metrics, dict):
            issue("malformed_assessment_metrics", assessment.pk)
            continue
        if assessment.metrics.get("populations") != expected["metrics"]["populations"]:
            issue("assessment_population_or_cutoff_mismatch", assessment.pk)
        if (
            assessment.metrics.get("mechanical_comparison")
            != expected["metrics"]["mechanical_comparison"]
        ):
            issue("unpaired_sample_or_cutoff_comparison_mismatch", assessment.pk)
        if any(
            getattr(assessment, key) != expected[key]
            for key in (
                "mean_brier_score",
                "mechanical_baseline_brier",
                "effective_cluster_count",
                "raw_sample_count",
                "resolved_sample_count",
            )
        ):
            issue("assessment_score_or_cutoff_mismatch", assessment.pk)
        if (
            assessment.status in {"descriptive_ready", "promotion_eligible"}
            and assessment.status != expected["status"]
        ):
            issue("paired_readiness_without_complete_controls", assessment.pk)
    from forecasts.schedules import schedule_errors

    for item in schedule_errors():
        issue(item["code"], item["id"])
    return {
        "schema_version": 1,
        "as_of": as_of.isoformat(),
        "violations": dict(sorted(counts.items())),
        "total": sum(counts.values()),
        "details": details,
        "omitted": max(0, sum(counts.values()) - len(details)),
        "legacy": dict(sorted(legacy.items())),
        "read_only": True,
    }
