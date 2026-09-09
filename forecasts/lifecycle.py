"""The single lifecycle projection and serialized append-only v4 state chain."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from forecasts.models import (
    CohortClosure,
    PortfolioDisposition,
    Recommendation,
    RecommendationLifecycleEvent,
)
from forecasts.targets import identity_digest

TRANSITIONS = {
    "abstained": frozenset(),
    "awaiting_portfolio_assessment": frozenset(
        {"portfolio_ineligible", "awaiting_owner_decision", "cancelled"}
    ),
    "portfolio_ineligible": frozenset(),
    "awaiting_owner_decision": frozenset(
        {"admitted_awaiting_entry", "closed_unselected", "cancelled"}
    ),
    "admitted_awaiting_entry": frozenset(
        {
            "entered",
            "admission_revoked",
            "expired_not_activated",
            "expired_unobserved",
            "missing_data",
            "cancelled",
        }
    ),
    "entered": frozenset({"target_hit", "invalidated", "expired_after_entry", "missing_data"}),
    **{
        key: frozenset()
        for key in (
            "closed_unselected",
            "admission_revoked",
            "cancelled",
            "target_hit",
            "invalidated",
            "expired_after_entry",
            "expired_not_activated",
            "expired_unobserved",
            "missing_data",
        )
    },
}
LABELS = {state: state.replace("_", " ").capitalize() for state in TRANSITIONS}
LABELS["legacy_unadjudicated"] = "Legacy unadjudicated"


@transaction.atomic
def transition(rec, state, *, reason_code, source=None, occurred_at=None):
    rec = Recommendation.objects.select_for_update().get(pk=rec.pk)
    if rec.contract_version != 4:
        raise ValidationError("legacy_transition_forbidden")
    source = source or rec
    if state in {"expired_unobserved", "missing_data", "cancelled"}:
        from forecasts.models import PaperLifecycleEvent

        if not isinstance(source, PaperLifecycleEvent) or source.recommendation_id != rec.pk:
            raise ValidationError("coverage_source_required")
        validate_coverage_fact(source)
    occurred_at = occurred_at or timezone.now()
    latest = rec.lifecycle_events.first()
    key = identity_digest([rec.pk, state, type(source).__name__, source.pk])
    existing = rec.lifecycle_events.filter(idempotency_key=key).first()
    if existing:
        return existing
    if latest and latest.state == state:
        return latest
    if state == "expired_not_activated":
        from forecasts.models import PaperTradeResult

        if not isinstance(source, PaperTradeResult) or source.recommendation_id != rec.pk:
            raise ValidationError("result_source_required")
        validate_expiry_result(source)
    initial = "abstained" if rec.action == "abstain" else "awaiting_portfolio_assessment"
    if (
        state not in TRANSITIONS
        or (latest and state not in TRANSITIONS[latest.state])
        or (not latest and state != initial)
        or occurred_at < rec.generated_at
        or (latest and occurred_at < latest.occurred_at)
    ):
        raise ValidationError("illegal_lifecycle_transition")
    return RecommendationLifecycleEvent.objects.create(
        recommendation=rec,
        predecessor=latest,
        state=state,
        reason_code=reason_code,
        source_type=type(source).__name__,
        source_id=source.pk,
        details={"schema_version": 1},
        occurred_at=occurred_at,
        idempotency_key=key,
    )


def initialize(rec):
    if rec.contract_version != 4:
        return
    if rec.action != "abstain":
        PortfolioDisposition.objects.get_or_create(
            recommendation=rec,
            defaults={
                "kind": "requires_assessment",
                "reason_code": "assessment_required",
                "created_at": rec.generated_at,
            },
        )
    transition(
        rec,
        "abstained" if rec.action == "abstain" else "awaiting_portfolio_assessment",
        reason_code="issued",
        occurred_at=rec.generated_at,
    )


def project_lifecycle(rec, *, as_of=None):
    as_of = as_of or timezone.now()
    # A caller may retain an instance from before reconciliation. Read current
    # immutable facts rather than cached missing reverse relations.
    rec = Recommendation.objects.select_related(
        "paper_entry", "paper_result", "portfolio_membership__cohort__closure"
    ).get(pk=rec.pk)
    entry = getattr(rec, "paper_entry", None)
    result = getattr(rec, "paper_result", None)
    if entry and entry.entered_at > as_of:
        entry = None
    if result and result.resolved_at > as_of:
        result = None
    admission = (
        rec.portfolio_admission_events.filter(occurred_at__lte=as_of)
        .order_by("-occurred_at", "-id")
        .first()
    )
    member = getattr(rec, "portfolio_membership", None)
    cohort = member.cohort if member else None
    if cohort and cohort.generated_at > as_of:
        cohort = None
    closure = getattr(cohort, "closure", None) if cohort else None
    if closure and closure.closed_at > as_of:
        closure = None
    selection = cohort.selections.filter(selected_at__lte=as_of).first() if cohort else None
    event = (
        rec.lifecycle_events.filter(occurred_at__lte=as_of).first()
        if rec.contract_version == 4
        else None
    )
    if event:
        state, reason, at = event.state, event.reason_code, event.occurred_at
    else:
        state, reason, at = "legacy_unadjudicated", "legacy_ambiguous", rec.generated_at
        if rec.action == "abstain":
            state, reason = "abstained", "recorded_abstention"
        elif result:
            state = {
                "target": "target_hit",
                "invalidated": "invalidated",
                "expired": "expired_after_entry",
                "not_activated": "expired_not_activated",
            }[result.outcome]
            reason, at = "recorded_result", result.resolved_at
        else:
            historical = (
                rec.paper_lifecycle_events.filter(occurred_at__lte=as_of)
                .order_by("-occurred_at", "-id")
                .first()
            )
            if historical and historical.state in {
                "expired_unobserved",
                "missing_data",
                "cancelled",
            }:
                state, reason, at = historical.state, historical.reason_code, historical.occurred_at
            elif entry:
                state, reason, at = "entered", "recorded_entry", entry.entered_at
            elif admission:
                state = (
                    "admitted_awaiting_entry"
                    if admission.state == "admitted"
                    else "admission_revoked"
                )
                reason, at = "recorded_admission", admission.occurred_at
    return {
        "state": state,
        "label": LABELS[state],
        "reason_code": reason,
        "effective_at": at,
        "terminal": state in TRANSITIONS and not TRANSITIONS[state],
        "admission_status": admission.state if admission else "not_admitted",
        "selection_mode": selection.mode if selection else None,
        "cohort_id": cohort.pk if cohort else None,
        "cohort_status": "closed" if closure or selection else "open" if cohort else None,
        "entry_id": entry.pk if entry else None,
        "result_id": result.pk if result else None,
        "data_coverage": "missing"
        if state in {"missing_data", "expired_unobserved"}
        else "verified"
        if result
        else "not_assessed",
        "legacy": rec.contract_version != 4,
    }


def current_risk_projection(rec, *, as_of=None):
    """Return the factual active projection, or None, at one effective cutoff.

    Admission history alone does not prove continuing risk. Terminal coverage
    facts need no paper result, and stale model instances must not hide them.
    Legacy rows qualify only through recorded admission and active entry state.
    """
    if rec.contract_version not in {2, 3, 4} or rec.action not in {"buy", "sell"}:
        return None
    projection = project_lifecycle(rec, as_of=as_of)
    if projection["admission_status"] != "admitted" or projection["state"] not in {
        "admitted_awaiting_entry",
        "entered",
    }:
        return None
    return projection


@transaction.atomic
def close_cohort(cohort, reason_code, *, superseding=None, as_of=None):
    as_of = as_of or timezone.now()
    cohort = type(cohort).objects.select_for_update().get(pk=cohort.pk)
    closure, _ = CohortClosure.objects.get_or_create(
        cohort=cohort,
        defaults={
            "reason_code": reason_code,
            "superseding_cohort": superseding,
            "closed_at": as_of,
        },
    )
    for member in cohort.members.select_related("recommendation"):
        rec = member.recommendation
        if (
            rec.contract_version == 4
            and project_lifecycle(rec, as_of=as_of)["state"] == "awaiting_owner_decision"
        ):
            transition(
                rec, "closed_unselected", reason_code=reason_code, source=closure, occurred_at=as_of
            )
    return closure


@transaction.atomic
def reconcile_lifecycle(instrument=None, *, as_of=None):
    as_of = as_of or timezone.now()
    from forecasts.models import PortfolioCohort
    from forecasts.portfolio import _lock_portfolio, assess_recommendation_batch

    _lock_portfolio()
    recommendations = Recommendation.objects.filter(contract_version=4, generated_at__lte=as_of)
    if instrument:
        recommendations = recommendations.filter(instrument=instrument)
    for rec in recommendations:
        initialize(rec)
        state = project_lifecycle(rec, as_of=as_of)["state"]
        if state == "awaiting_portfolio_assessment":
            if as_of >= rec.generated_at + timedelta(hours=24):
                from forecasts.models import PaperLifecycleEvent

                fact, _ = PaperLifecycleEvent.objects.get_or_create(
                    recommendation=rec,
                    state="cancelled",
                    defaults={
                        "reason_code": "assessment_window_expired",
                        "details": {"schema_version": 1},
                        "occurred_at": as_of,
                    },
                )
                transition(
                    rec,
                    "cancelled",
                    reason_code="assessment_window_expired",
                    source=fact,
                    occurred_at=as_of,
                )
            else:
                assess_recommendation_batch([rec], generated_at=as_of)
        result = getattr(rec, "paper_result", None)
        entry = getattr(rec, "paper_entry", None)
        if entry and entry.entered_at > as_of:
            entry = None
        if result and result.resolved_at > as_of:
            result = None
        state = project_lifecycle(rec, as_of=as_of)["state"]
        if entry and state == "admitted_awaiting_entry":
            transition(rec, "entered", reason_code="paper_entry", source=entry, occurred_at=as_of)
        if result:
            desired = {
                "target": "target_hit",
                "invalidated": "invalidated",
                "expired": "expired_after_entry",
                "not_activated": "expired_not_activated",
            }[result.outcome]
            transition(rec, desired, reason_code="paper_result", source=result, occurred_at=as_of)
    from forecasts.portfolio import cohort_has_triggered

    for cohort in PortfolioCohort.objects.filter(
        decision_deadline__isnull=False, generated_at__lte=as_of, closure__isnull=True
    ):
        if cohort.decision_deadline <= as_of:
            close_cohort(cohort, "decision_deadline", as_of=as_of)
        elif cohort_has_triggered(cohort, as_of=as_of):
            close_cohort(cohort, "entry_trigger_before_selection", as_of=as_of)


def validate_coverage_fact(fact):
    from forecasts.models import Candle, PaperTradeEntry
    from forecasts.paper import _has_coverage
    from forecasts.targets import target_endpoint
    from market.quality import registered_candle_completion

    rec = fact.recommendation
    if rec.contract_version != 4:
        return
    if (
        not isinstance(fact.details, dict)
        or type(fact.details.get("schema_version")) is not int
        or fact.details.get("schema_version") != 1
    ):
        raise ValidationError("invalid_coverage_details")
    entered = PaperTradeEntry.objects.filter(
        recommendation=rec, entered_at__lte=fact.occurred_at
    ).exists()
    if fact.state == "cancelled":
        if entered or not fact.reason_code:
            raise ValidationError("invalid_cancellation_evidence")
        return
    if fact.state not in {"expired_unobserved", "missing_data"}:
        return
    target = rec.target_occurrence
    maturity = registered_candle_completion(
        target_endpoint(target.reference_candle.timestamp, target.horizon_sessions), "D"
    )
    if fact.occurred_at < maturity:
        raise ValidationError("coverage_before_target_maturity")
    shared = getattr(target, "resolution", None)
    if fact.reason_code == "daily_horizon_unavailable":
        if (
            fact.state != "missing_data"
            or not shared
            or shared.outcome != "missing"
            or shared.resolved_at > fact.occurred_at
            or fact.details.get("target_resolution_id") != shared.pk
        ):
            raise ValidationError("missing_daily_source_required")
        return
    if fact.reason_code != "hourly_coverage_unavailable":
        raise ValidationError("invalid_coverage_reason")
    expected = "missing_data" if entered else "expired_unobserved"
    candles = list(
        Candle.objects.filter(
            instrument=rec.instrument,
            granularity="H1",
            complete=True,
            timestamp__gte=rec.generated_at,
            timestamp__lte=maturity - timedelta(hours=1),
            ingestion_run__status="succeeded",
            ingestion_run__finished_at__lte=fact.occurred_at,
        ).order_by("timestamp")
    )
    if fact.state != expected or _has_coverage(rec, maturity, candles, as_of=fact.occurred_at):
        raise ValidationError("coverage_classification_mismatch")


def validate_expiry_result(result):
    from forecasts.models import Candle
    from forecasts.paper import _entry_fill, _has_coverage
    from forecasts.targets import target_endpoint
    from market.quality import registered_candle_completion

    rec = result.recommendation
    target = rec.target_occurrence
    maturity = registered_candle_completion(
        target_endpoint(target.reference_candle.timestamp, target.horizon_sessions), "D"
    )
    if result.resolved_at < maturity:
        raise ValidationError("expiry_before_target_maturity")
    candles = list(
        Candle.objects.filter(
            instrument=rec.instrument,
            granularity="H1",
            complete=True,
            timestamp__gte=rec.generated_at,
            timestamp__lte=maturity - timedelta(hours=1),
            ingestion_run__status="succeeded",
            ingestion_run__finished_at__lte=result.resolved_at,
        ).order_by("timestamp")
    )
    if not _has_coverage(rec, maturity, candles, as_of=result.resolved_at):
        raise ValidationError("expiry_coverage_required")
    if result.outcome == "not_activated" and any(_entry_fill(rec, candle) for candle in candles):
        raise ValidationError("nonactivation_contradicts_entry_evidence")
