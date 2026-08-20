import hashlib
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from forecasts.exposure import decompose_pair
from forecasts.models import (
    PaperLifecycleEvent,
    PortfolioAdmissionEvent,
    PortfolioCohort,
    PortfolioCohortMember,
    PortfolioGuard,
    PortfolioPolicyActivation,
    PortfolioSelection,
    PortfolioSelectionMember,
    Recommendation,
)
from forecasts.sizing import (
    AGGREGATE_RISK_CAP_CAD,
    CURRENCY_DIRECTION_RISK_CAP_CAD,
    POLICY_KEY,
    POLICY_VERSION,
)
from market.models import AuditEvent, Candle
from operations.notifications import create_owner_notification


def _latest_admission_states():
    states = {}
    for event in PortfolioAdmissionEvent.objects.order_by("recommendation_id", "occurred_at", "id"):
        states[event.recommendation_id] = event.state
    return states


def active_admitted_recommendation_ids():
    return [
        recommendation_id
        for recommendation_id, state in _latest_admission_states().items()
        if state == PortfolioAdmissionEvent.State.ADMITTED
    ]


def _legs(recommendation):
    return [
        {"currency": currency, "direction": direction}
        for currency, direction in decompose_pair(
            recommendation.instrument.base_currency,
            recommendation.instrument.quote_currency,
            recommendation.action,
        )
    ]


def _fits(recommendations):
    total, directional = _capacity_usage(recommendations)
    return total <= AGGREGATE_RISK_CAP_CAD and all(
        risk <= CURRENCY_DIRECTION_RISK_CAP_CAD for risk in directional.values()
    )


def _capacity_usage(recommendations):
    total = Decimal("0")
    directional = defaultdict(lambda: Decimal("0"))
    for recommendation in recommendations:
        size = recommendation.position_size
        if not size:
            raise ValidationError("Portfolio capacity requires complete position sizing")
        total += size.projected_risk_cad
        for leg in _legs(recommendation):
            directional[(leg["currency"], leg["direction"])] += size.projected_risk_cad
    return total, directional


def _selection_fits_snapshot(cohort, selected_members):
    snapshot = cohort.capacity_snapshot
    total = Decimal(snapshot["base_total_risk_cad"])
    directional = defaultdict(
        lambda: Decimal("0"),
        {
            (key.rsplit(":", 1)[0], int(key.rsplit(":", 1)[1])): Decimal(risk)
            for key, risk in snapshot["base_currency_direction_risk_cad"].items()
        },
    )
    for member in selected_members:
        total += member.projected_risk_cad
        for leg in member.currency_legs:
            directional[(leg["currency"], leg["direction"])] += member.projected_risk_cad
    return total <= Decimal(snapshot["aggregate_risk_cap_cad"]) and all(
        risk <= Decimal(snapshot["currency_direction_risk_cap_cad"])
        for risk in directional.values()
    )


def _active_admitted(excluding=()):
    return list(
        Recommendation.objects.filter(
            pk__in=active_admitted_recommendation_ids(), paper_result__isnull=True
        )
        .exclude(pk__in=excluding)
        .select_related("instrument")
        .prefetch_related("position_sizes")
    )


def _lock_portfolio():
    PortfolioGuard.objects.get_or_create(key="paper-portfolio")
    return PortfolioGuard.objects.select_for_update().get(key="paper-portfolio")


def _policy_activation():
    activation, _ = PortfolioPolicyActivation.objects.get_or_create(
        policy_key=POLICY_KEY,
        policy_version=POLICY_VERSION,
        defaults={"effective_at": timezone.now()},
    )
    return activation


@transaction.atomic
def assess_recommendation_batch(recommendations, *, generated_at=None):
    generated_at = generated_at or timezone.now()
    effective_at = _policy_activation().effective_at
    already_assessed = set(
        PortfolioCohortMember.objects.filter(
            recommendation_id__in=[item.pk for item in recommendations]
        ).values_list("recommendation_id", flat=True)
    )
    candidates = [
        recommendation
        for recommendation in recommendations
        if recommendation.generated_at >= effective_at
        and recommendation.pk not in already_assessed
        and recommendation.action in {Recommendation.Action.BUY, Recommendation.Action.SELL}
    ]
    if not candidates:
        return None
    guard = _lock_portfolio()
    del guard
    key_material = ",".join(str(item.pk) for item in sorted(candidates, key=lambda item: item.pk))
    key = f"portfolio-cohort:{POLICY_KEY}:v{POLICY_VERSION}:{key_material}"
    existing = PortfolioCohort.objects.filter(idempotency_key=key).first()
    if existing:
        return existing

    base = _active_admitted(excluding=[item.pk for item in candidates])
    base_total, base_directional = _capacity_usage(base)
    cohort = PortfolioCohort.objects.create(
        idempotency_key=key,
        policy_key=POLICY_KEY,
        policy_version=POLICY_VERSION,
        generated_at=generated_at,
        capacity_snapshot={
            "base_recommendation_ids": [item.pk for item in base],
            "base_total_risk_cad": str(base_total),
            "base_currency_direction_risk_cad": {
                f"{currency}:{direction}": str(risk)
                for (currency, direction), risk in base_directional.items()
            },
            "aggregate_risk_cap_cad": str(AGGREGATE_RISK_CAP_CAD),
            "currency_direction_risk_cap_cad": str(CURRENCY_DIRECTION_RISK_CAP_CAD),
            "confidence_used_for_ranking": False,
        },
    )
    for recommendation in candidates:
        size = recommendation.position_size
        if not size:
            raise ValidationError("A portfolio candidate requires versioned position sizing")
        PortfolioCohortMember.objects.create(
            cohort=cohort,
            recommendation=recommendation,
            position_size=size,
            projected_risk_cad=size.projected_risk_cad,
            currency_legs=_legs(recommendation),
        )

    if _fits(base + candidates):
        _record_selection(
            cohort,
            [item.pk for item in candidates],
            mode=PortfolioSelection.Mode.AUTOMATIC,
            actor=None,
        )
    else:
        create_owner_notification(
            idempotency_key=f"portfolio-selection:{cohort.pk}",
            kind="portfolio_selection_required",
            severity="action",
            title="Choose which FX setups enter the paper portfolio",
            body=(
                f"{len(candidates)} new directional setups cannot all fit the current "
                "CAD and currency-direction risk caps. Confidence is shown for context only."
            ),
            action_path=f"/inbox/#cohort-{cohort.pk}",
            subject_type="PortfolioCohort",
            subject_id=str(cohort.pk),
        )
    return cohort


def cohort_has_triggered(cohort):
    for member in cohort.members.select_related("recommendation__instrument"):
        recommendation = member.recommendation
        candles = Candle.objects.filter(
            instrument=recommendation.instrument,
            granularity="H1",
            timestamp__gte=recommendation.generated_at,
            complete=True,
        )
        if recommendation.action == Recommendation.Action.BUY:
            if candles.filter(ask_low__lte=recommendation.entry_level).exists():
                return True
        elif candles.filter(bid_high__gte=recommendation.entry_level).exists():
            return True
    return False


def cohort_is_open(cohort):
    latest_selection = cohort.selections.first()
    if latest_selection and latest_selection.mode == PortfolioSelection.Mode.AUTOMATIC:
        return False
    if PortfolioCohort.objects.filter(
        Q(generated_at__gt=cohort.generated_at)
        | Q(generated_at=cohort.generated_at, pk__gt=cohort.pk)
    ).exists():
        return False
    terminal = {
        PaperLifecycleEvent.State.ENTERED,
        PaperLifecycleEvent.State.CLOSED,
        PaperLifecycleEvent.State.EXPIRED_UNOBSERVED,
        PaperLifecycleEvent.State.CANCELLED,
        PaperLifecycleEvent.State.MISSING_DATA,
    }
    for member in cohort.members.select_related("recommendation"):
        latest = member.recommendation.paper_lifecycle_events.order_by(
            "-occurred_at", "-id"
        ).first()
        if latest and latest.state in terminal:
            return False
    return not cohort_has_triggered(cohort)


@transaction.atomic
def select_portfolio_cohort(cohort, selected_ids, *, actor):
    if not actor or not actor.is_superuser:
        raise ValidationError("Only the configured owner can select a portfolio cohort")
    _lock_portfolio()
    cohort = PortfolioCohort.objects.select_for_update().get(pk=cohort.pk)
    members = list(cohort.members.select_related("recommendation__instrument", "position_size"))
    member_ids = {member.recommendation_id for member in members}
    selected_ids = {int(value) for value in selected_ids}
    if selected_ids - member_ids:
        raise ValidationError("Selection contains a recommendation outside this cohort")
    latest = cohort.selections.first()
    if (
        latest
        and set(latest.selected_members.values_list("recommendation_id", flat=True)) == selected_ids
    ):
        return latest
    digest = hashlib.sha256(
        ",".join(str(value) for value in sorted(selected_ids)).encode()
    ).hexdigest()[:16]
    key = f"portfolio-owner:{cohort.pk}:{latest.pk if latest else 0}:{digest}"
    existing = PortfolioSelection.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    if not cohort_is_open(cohort):
        raise ValidationError(
            "This selection cohort is closed because prices moved or a newer batch exists"
        )
    selected = [member for member in members if member.recommendation_id in selected_ids]
    if not _selection_fits_snapshot(cohort, selected):
        raise ValidationError("The selected setups exceed the frozen portfolio risk policy")
    return _record_selection(
        cohort,
        selected_ids,
        mode=PortfolioSelection.Mode.OWNER,
        actor=actor,
        supersedes=latest,
        idempotency_key=key,
    )


def _record_selection(
    cohort,
    selected_ids,
    *,
    mode,
    actor,
    supersedes=None,
    idempotency_key=None,
):
    selected_ids = set(selected_ids)
    selection = PortfolioSelection.objects.create(
        cohort=cohort,
        supersedes=supersedes,
        actor=actor,
        mode=mode,
        idempotency_key=idempotency_key or f"portfolio-auto:{cohort.pk}",
    )
    previous_ids = (
        set(supersedes.selected_members.values_list("recommendation_id", flat=True))
        if supersedes
        else set()
    )
    for recommendation_id in sorted(selected_ids):
        PortfolioSelectionMember.objects.create(
            selection=selection, recommendation_id=recommendation_id
        )
        if recommendation_id not in previous_ids:
            PortfolioAdmissionEvent.objects.create(
                recommendation_id=recommendation_id,
                cohort=cohort,
                selection=selection,
                state=PortfolioAdmissionEvent.State.ADMITTED,
                reason_code="all_fit"
                if mode == PortfolioSelection.Mode.AUTOMATIC
                else "owner_selected",
            )
    for recommendation_id in sorted(previous_ids - selected_ids):
        PortfolioAdmissionEvent.objects.create(
            recommendation_id=recommendation_id,
            cohort=cohort,
            selection=selection,
            state=PortfolioAdmissionEvent.State.REVOKED,
            reason_code="owner_superseded_while_pending",
        )
    AuditEvent.objects.create(
        event_type="forecast.portfolio_selection_recorded",
        actor=(f"user:{actor.pk}" if actor else "forecasts.portfolio.automatic"),
        subject_type="PortfolioSelection",
        subject_id=str(selection.pk),
        payload={
            "cohort_id": cohort.pk,
            "mode": mode,
            "selected_recommendation_ids": sorted(selected_ids),
            "confidence_used_for_ranking": False,
        },
    )
    return selection
