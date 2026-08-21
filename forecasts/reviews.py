import hashlib
import json
from collections import Counter

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from forecasts.models import (
    DeterministicReview,
    PaperLifecycleEvent,
    PaperTradeResult,
    PortfolioAdmissionEvent,
    PortfolioCohort,
    PortfolioCohortMember,
    PortfolioGuard,
    PortfolioSelection,
    Recommendation,
    RecommendationResolution,
    ReviewCohort,
    ReviewCohortMember,
)
from market.models import AuditEvent, Candle

METHOD_KEY = "deterministic-postmortem"
METHOD_VERSION = 1
TERMINAL_EXECUTION_STATES = {
    PaperLifecycleEvent.State.CLOSED,
    PaperLifecycleEvent.State.EXPIRED_UNOBSERVED,
    PaperLifecycleEvent.State.CANCELLED,
    PaperLifecycleEvent.State.MISSING_DATA,
}


def _digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _lock_reviews():
    PortfolioGuard.objects.get_or_create(key="deterministic-reviews")
    return PortfolioGuard.objects.select_for_update().get(key="deterministic-reviews")


def _latest_admission(recommendation, as_of):
    return (
        recommendation.portfolio_admission_events.filter(occurred_at__lte=as_of)
        .order_by("-occurred_at", "-id")
        .first()
    )


def _latest_lifecycle(recommendation, as_of):
    return (
        recommendation.paper_lifecycle_events.filter(occurred_at__lte=as_of)
        .order_by("-occurred_at", "-id")
        .first()
    )


def _cohort_is_open_as_of(cohort, as_of):
    latest_selection = cohort.selections.filter(selected_at__lte=as_of).first()
    if latest_selection and latest_selection.mode == PortfolioSelection.Mode.AUTOMATIC:
        return False
    if (
        PortfolioCohort.objects.filter(
            generated_at__lte=as_of,
        )
        .filter(
            Q(generated_at__gt=cohort.generated_at)
            | Q(generated_at=cohort.generated_at, pk__gt=cohort.pk)
        )
        .exists()
    ):
        return False
    terminal = {
        PaperLifecycleEvent.State.ENTERED,
        PaperLifecycleEvent.State.CLOSED,
        PaperLifecycleEvent.State.EXPIRED_UNOBSERVED,
        PaperLifecycleEvent.State.CANCELLED,
        PaperLifecycleEvent.State.MISSING_DATA,
    }
    for member in cohort.members.select_related("recommendation__instrument"):
        recommendation = member.recommendation
        lifecycle = _latest_lifecycle(recommendation, as_of)
        if lifecycle and lifecycle.state in terminal:
            return False
        candles = Candle.objects.filter(
            instrument=recommendation.instrument,
            granularity="H1",
            timestamp__gte=recommendation.generated_at,
            timestamp__lte=as_of,
            complete=True,
            ingestion_run__finished_at__lte=as_of,
        )
        if recommendation.action == Recommendation.Action.BUY:
            if candles.filter(ask_low__lte=recommendation.entry_level).exists():
                return False
        elif candles.filter(bid_high__gte=recommendation.entry_level).exists():
            return False
    return True


def _execution_readiness(recommendation, as_of):
    if recommendation.action == Recommendation.Action.ABSTAIN:
        return "abstention"
    membership = (
        PortfolioCohortMember.objects.filter(recommendation=recommendation)
        .select_related("cohort")
        .first()
    )
    if not membership:
        return "outside_admission_era"
    admission = _latest_admission(recommendation, as_of)
    if not admission:
        return None if _cohort_is_open_as_of(membership.cohort, as_of) else "owner_not_selected"
    if admission.state == PortfolioAdmissionEvent.State.REVOKED:
        return "admission_revoked"
    if PaperTradeResult.objects.filter(
        recommendation=recommendation, resolved_at__lte=as_of
    ).exists():
        return "paper_result"
    lifecycle = _latest_lifecycle(recommendation, as_of)
    if lifecycle and lifecycle.state in TERMINAL_EXECUTION_STATES:
        return "terminal_without_result"
    return None


def _evidence_lineage(recommendation):
    payload = recommendation.evidence_snapshot.payload
    return {
        "recommendation_id": recommendation.pk,
        "evidence_snapshot_id": recommendation.evidence_snapshot_id,
        "evidence_snapshot_sha256": recommendation.evidence_snapshot.sha256,
        "cited_evidence_ids": sorted(recommendation.output.get("evidence_ids", [])),
        "market_anchor_candle_id": payload.get("market", {}).get("anchor_candle_id"),
        "technical_snapshot_ids": sorted(
            item["id"] for item in payload.get("technicals", []) if item.get("id")
        ),
        "macro_observation_ids": sorted(
            item["observation_id"]
            for item in payload.get("macro_and_intermarket", [])
            if item.get("observation_id")
        ),
        "macro_retrieval_ids": sorted(
            {
                item["retrieval_id"]
                for item in payload.get("macro_and_intermarket", [])
                if item.get("retrieval_id")
            }
        ),
        "economic_event_ids": sorted(
            item["id"] for item in payload.get("upcoming_events", []) if item.get("id")
        ),
        "event_retrieval_ids": sorted(
            {
                item["retrieval_id"]
                for item in payload.get("upcoming_events", [])
                if item.get("retrieval_id")
            }
        ),
        "news_document_ids": sorted(
            item["document_id"]
            for item in payload.get("recent_news", [])
            if item.get("document_id")
        ),
    }


def _thesis_projection(recommendation, resolution):
    if recommendation.action == Recommendation.Action.ABSTAIN:
        classification = "abstention_observed"
        supported = None
    else:
        supported = resolution.directional_hit
        classification = "direction_supported" if supported else "direction_not_supported"
    facts = {
        "schema": "thesis-review-v1",
        "classification": classification,
        "action": recommendation.action,
        "confidence_percent": recommendation.confidence_percent,
        "probabilities": {
            "up": str(recommendation.probability_up),
            "neutral": str(recommendation.probability_neutral),
            "down": str(recommendation.probability_down),
        },
        "outcome": resolution.outcome,
        "direction_supported": supported,
        "brier_score": str(resolution.brier_score),
        "reference_midpoint": str(recommendation.reference_midpoint),
        "endpoint_midpoint": str(resolution.endpoint_midpoint),
        "midpoint_change": str(resolution.midpoint_change),
        "neutral_band": str(recommendation.neutral_band),
        "sessions_observed": resolution.details["sessions_observed"],
    }
    lineage = _evidence_lineage(recommendation) | {
        "resolution_id": resolution.pk,
        "reference_candle_id": recommendation.reference_candle_id,
        "horizon_candle_id": resolution.horizon_candle_id,
        "outcome_candle_ids": resolution.details.get("candle_ids", []),
        "outcome_ingestion_run_ids": resolution.details.get("ingestion_run_ids", []),
    }
    return {
        "kind": DeterministicReview.Kind.THESIS,
        "coverage": DeterministicReview.Coverage.COMPLETE,
        "facts": facts,
        "source_lineage": lineage,
    }


def _execution_projection(recommendation, readiness, as_of):
    membership = PortfolioCohortMember.objects.filter(recommendation=recommendation).first()
    admission = _latest_admission(recommendation, as_of)
    lifecycle = _latest_lifecycle(recommendation, as_of)
    result = (
        PaperTradeResult.objects.filter(recommendation=recommendation, resolved_at__lte=as_of)
        .select_related("entry__candle", "exit_candle", "horizon_candle")
        .first()
    )
    lineage = {
        "recommendation_id": recommendation.pk,
        "portfolio_cohort_id": membership.cohort_id if membership else None,
        "portfolio_admission_event_ids": list(
            recommendation.portfolio_admission_events.filter(occurred_at__lte=as_of)
            .order_by("occurred_at", "id")
            .values_list("id", flat=True)
        ),
        "paper_lifecycle_event_ids": list(
            recommendation.paper_lifecycle_events.filter(occurred_at__lte=as_of)
            .order_by("occurred_at", "id")
            .values_list("id", flat=True)
        ),
    }
    facts = {
        "schema": "execution-review-v1",
        "admission_state": admission.state if admission else "not_admitted",
        "readiness_reason": readiness,
        "paper_outcome": result.outcome if result else None,
        "entry_activated": bool(result and result.entry_id),
        "target_observed": result.outcome == PaperTradeResult.Outcome.TARGET if result else None,
        "gross_pips": str(result.gross_pips) if result and result.gross_pips is not None else None,
        "gross_r_multiple": (
            str(result.r_multiple) if result and result.r_multiple is not None else None
        ),
        "terminal_lifecycle_state": lifecycle.state if lifecycle else None,
        "terminal_reason_code": lifecycle.reason_code if lifecycle else "",
    }
    if readiness in {
        "abstention",
        "outside_admission_era",
        "owner_not_selected",
        "admission_revoked",
    }:
        coverage = DeterministicReview.Coverage.NOT_APPLICABLE
    elif result:
        coverage = DeterministicReview.Coverage.COMPLETE
        cost = result.cost_assessments.filter(assessed_at__lte=as_of).first()
        facts.update(
            {
                "entry_price": str(result.entry.fill_price) if result.entry_id else None,
                "exit_price": str(result.exit_price) if result.exit_price is not None else None,
                "entry_at": (
                    result.entry.candle.timestamp.isoformat() if result.entry_id else None
                ),
                "exit_at": (
                    result.exit_candle.timestamp.isoformat() if result.exit_candle_id else None
                ),
                "same_candle_ambiguity": result.details.get("same_candle_target_and_stop", False),
                "adverse_precedence_applied": result.details.get(
                    "adverse_invalidation_precedence", False
                ),
                "cost_policy": cost.policy_version if cost else None,
                "net_pips": (
                    {
                        "optimistic": str(cost.optimistic_net_pips),
                        "base": str(cost.base_net_pips),
                        "conservative": str(cost.conservative_net_pips),
                    }
                    if cost
                    else None
                ),
                "net_r": (
                    {
                        "optimistic": str(cost.optimistic_net_r),
                        "base": str(cost.base_net_r),
                        "conservative": str(cost.conservative_net_r),
                    }
                    if cost
                    else None
                ),
            }
        )
        through = result.exit_candle.timestamp if result.exit_candle_id else as_of
        hourly = Candle.objects.filter(
            instrument=recommendation.instrument,
            granularity="H1",
            timestamp__gte=recommendation.generated_at,
            timestamp__lte=through,
            ingestion_run__finished_at__lte=as_of,
        ).order_by("timestamp")
        lineage.update(
            {
                "paper_result_id": result.pk,
                "paper_entry_id": result.entry_id,
                "entry_candle_id": result.entry.candle_id if result.entry_id else None,
                "exit_candle_id": result.exit_candle_id,
                "horizon_candle_id": result.horizon_candle_id,
                "cost_assessment_id": cost.pk if cost else None,
                "hourly_candle_ids": list(hourly.values_list("id", flat=True)),
                "hourly_ingestion_run_ids": sorted(
                    set(hourly.values_list("ingestion_run_id", flat=True))
                ),
            }
        )
    else:
        coverage = DeterministicReview.Coverage.MISSING
    return {
        "kind": DeterministicReview.Kind.EXECUTION,
        "coverage": coverage,
        "facts": facts,
        "source_lineage": lineage,
    }


def _reconciliation_projection(thesis, execution):
    thesis_facts = thesis["facts"]
    execution_facts = execution["facts"]
    if execution["coverage"] == DeterministicReview.Coverage.MISSING:
        classification = "execution_coverage_missing"
        coverage = DeterministicReview.Coverage.MISSING
    elif execution["coverage"] == DeterministicReview.Coverage.NOT_APPLICABLE:
        classification = "thesis_only_research_record"
        coverage = DeterministicReview.Coverage.COMPLETE
    elif thesis_facts["direction_supported"] and execution_facts["target_observed"]:
        classification = "direction_supported_and_target_observed"
        coverage = DeterministicReview.Coverage.COMPLETE
    elif thesis_facts["direction_supported"]:
        classification = "direction_supported_without_target_outcome"
        coverage = DeterministicReview.Coverage.COMPLETE
    elif execution_facts["target_observed"]:
        classification = "direction_not_supported_with_target_observed"
        coverage = DeterministicReview.Coverage.COMPLETE
    else:
        classification = "direction_not_supported_without_target_outcome"
        coverage = DeterministicReview.Coverage.COMPLETE
    return {
        "kind": DeterministicReview.Kind.RECONCILIATION,
        "coverage": coverage,
        "facts": {
            "schema": "reconciliation-review-v1",
            "classification": classification,
            "direction_supported": thesis_facts["direction_supported"],
            "paper_outcome": execution_facts["paper_outcome"],
            "target_observed": execution_facts["target_observed"],
            "execution_coverage": execution["coverage"],
            "association_note": (
                "Thesis and execution outcomes are recorded as associated observations only."
            ),
        },
        "source_lineage": {
            "thesis_projection_sha256": _digest(thesis),
            "execution_projection_sha256": _digest(execution),
            "recommendation_id": thesis["source_lineage"]["recommendation_id"],
        },
    }


def _projections(recommendation, as_of):
    resolution = RecommendationResolution.objects.filter(
        recommendation=recommendation, resolved_at__lte=as_of
    ).first()
    if not resolution:
        return None
    readiness = _execution_readiness(recommendation, as_of)
    if not readiness:
        return None
    thesis = _thesis_projection(recommendation, resolution)
    execution = _execution_projection(recommendation, readiness, as_of)
    reconciliation = _reconciliation_projection(thesis, execution)
    return (thesis, execution, reconciliation)


def _coverage(projections):
    counts = Counter(
        f"{projection['kind']}:{projection['coverage']}"
        for recommendation_projections in projections.values()
        for projection in recommendation_projections
    )
    return {
        "membership_count": len(projections),
        "by_review_and_coverage": dict(sorted(counts.items())),
        "late_data_rewrites_membership": False,
    }


def _create_or_reuse_review(member, projection, assessed_at):
    input_sha256 = _digest(projection)
    existing = DeterministicReview.objects.filter(
        member=member, kind=projection["kind"], input_sha256=input_sha256
    ).first()
    if existing:
        return existing, False
    latest = member.reviews.filter(kind=projection["kind"]).first()
    review = DeterministicReview.objects.create(
        member=member,
        kind=projection["kind"],
        supersedes=latest,
        method_key=METHOD_KEY,
        method_version=METHOD_VERSION,
        input_sha256=input_sha256,
        coverage=projection["coverage"],
        facts=projection["facts"],
        source_lineage=projection["source_lineage"],
        assessed_at=assessed_at,
    )
    return review, True


@transaction.atomic
def build_due_review_cohort(*, instrument=None, cutoff_at=None):
    cutoff_at = cutoff_at or timezone.now()
    _lock_reviews()
    candidates = Recommendation.objects.select_for_update(of=("self",)).filter(
        contract_version__in=(2, 3),
        generated_at__lte=cutoff_at,
        resolution__resolved_at__lte=cutoff_at,
        review_membership__isnull=True,
    )
    if instrument:
        candidates = candidates.filter(instrument=instrument)
    projections = {}
    recommendations = []
    for recommendation in candidates.select_related(
        "instrument", "evidence_snapshot", "reference_candle", "resolution"
    ):
        values = _projections(recommendation, cutoff_at)
        if values:
            recommendations.append(recommendation)
            projections[recommendation.pk] = values
    if not recommendations:
        return None
    membership_sha256 = _digest(sorted(item.pk for item in recommendations))
    existing = ReviewCohort.objects.filter(membership_sha256=membership_sha256).first()
    if existing:
        return existing
    cohort = ReviewCohort.objects.create(
        idempotency_key=f"review-cohort:{METHOD_KEY}:v{METHOD_VERSION}:{membership_sha256}",
        method_key=METHOD_KEY,
        method_version=METHOD_VERSION,
        cutoff_at=cutoff_at,
        membership_sha256=membership_sha256,
        initial_coverage=_coverage(projections),
    )
    for recommendation in recommendations:
        member = ReviewCohortMember.objects.create(
            cohort=cohort,
            recommendation=recommendation,
            inclusion_reason="resolved_thesis_and_terminal_execution",
        )
        for projection in projections[recommendation.pk]:
            _create_or_reuse_review(member, projection, cutoff_at)
    AuditEvent.objects.create(
        event_type="forecast.review_cohort_frozen",
        actor="forecasts.reviews.build_due_review_cohort",
        subject_type="ReviewCohort",
        subject_id=str(cohort.pk),
        payload={
            "membership_sha256": membership_sha256,
            "recommendation_ids": sorted(item.pk for item in recommendations),
            "coverage": cohort.initial_coverage,
        },
    )
    return cohort


@transaction.atomic
def reassess_review_cohort(cohort, *, correction_as_of):
    if correction_as_of <= cohort.cutoff_at:
        raise ValidationError("A correction assessment must occur after the frozen cutoff")
    _lock_reviews()
    cohort = ReviewCohort.objects.select_for_update().get(pk=cohort.pk)
    created = []
    for member in cohort.members.select_related(
        "recommendation__instrument",
        "recommendation__evidence_snapshot",
        "recommendation__reference_candle",
        "recommendation__resolution",
    ):
        values = _projections(member.recommendation, correction_as_of)
        if not values:
            continue
        for projection in values:
            review, was_created = _create_or_reuse_review(member, projection, correction_as_of)
            if was_created:
                created.append(review)
    if created:
        AuditEvent.objects.create(
            event_type="forecast.review_correction_assessed",
            actor="forecasts.reviews.reassess_review_cohort",
            subject_type="ReviewCohort",
            subject_id=str(cohort.pk),
            payload={
                "correction_as_of": correction_as_of.isoformat(),
                "superseding_review_ids": [review.pk for review in created],
            },
        )
    return created
