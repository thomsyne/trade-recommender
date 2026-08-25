from datetime import UTC, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from forecasts.costs import assess_due_paper_costs, create_cost_assessment
from forecasts.models import (
    PaperLifecycleEvent,
    PaperTradeEntry,
    PaperTradeResult,
    Recommendation,
)
from market.models import AuditEvent, Candle, IngestionRun

PRICE_QUANTUM = Decimal("0.000001")
PIP_SIZE = Decimal("0.0001")
PIP_QUANTUM = Decimal("0.001")
R_QUANTUM = Decimal("0.0001")
NEW_YORK = ZoneInfo("America/New_York")


def resolve_due_paper_trades(instrument=None):
    assess_due_paper_costs()
    recommendations = Recommendation.objects.filter(
        contract_version__in=(2, 3),
        action__in=(Recommendation.Action.BUY, Recommendation.Action.SELL),
        paper_result__isnull=True,
    ).select_related("reference_candle", "paper_entry")
    if instrument:
        recommendations = recommendations.filter(instrument=instrument)
    changed = []
    for recommendation in recommendations:
        record = resolve_paper_trade(recommendation)
        if record:
            changed.append(record)
    return changed


@transaction.atomic
def resolve_paper_trade(recommendation):
    recommendation = Recommendation.objects.select_for_update().get(pk=recommendation.pk)
    existing = PaperTradeResult.objects.filter(recommendation=recommendation).first()
    if existing:
        return existing
    if (
        recommendation.contract_version not in {2, 3}
        or recommendation.action == Recommendation.Action.ABSTAIN
    ):
        return None
    from forecasts.portfolio import active_admitted_recommendation_ids

    if recommendation.pk not in active_admitted_recommendation_ids():
        return None
    lifecycle = recommendation.paper_lifecycle_events.order_by("-occurred_at", "-id").first()
    if not lifecycle or lifecycle.state in {
        PaperLifecycleEvent.State.LEGACY_UNADJUDICATED,
        PaperLifecycleEvent.State.EXPIRED_UNOBSERVED,
        PaperLifecycleEvent.State.CANCELLED,
        PaperLifecycleEvent.State.MISSING_DATA,
    }:
        return None

    horizon = _horizon_candle(recommendation)
    expires_at = _session_close(horizon.timestamp) if horizon else None
    candles = list(
        Candle.objects.filter(
            instrument=recommendation.instrument,
            granularity="H1",
            timestamp__gte=recommendation.generated_at,
            **({"timestamp__lte": expires_at - timedelta(hours=1)} if expires_at else {}),
        ).order_by("timestamp")
    )
    if candles and not _has_coverage(
        recommendation, candles[-1].timestamp + timedelta(hours=1), candles
    ):
        return None

    entry = PaperTradeEntry.objects.filter(recommendation=recommendation).first()
    entry_created = False
    entry_index = None
    if entry:
        entry_index = next(
            (index for index, candle in enumerate(candles) if candle.pk == entry.candle_id), None
        )
    else:
        for index, candle in enumerate(candles):
            fill = _entry_fill(recommendation, candle)
            if fill:
                entry_index = index
                entry_at_open, fill_price = fill
                target_hit, stop_hit = _exit_touches(recommendation, candle)
                entry = PaperTradeEntry.objects.create(
                    recommendation=recommendation,
                    candle=candle,
                    execution_side=(
                        "ask" if recommendation.action == Recommendation.Action.BUY else "bid"
                    ),
                    fill_price=fill_price,
                    observed_open_spread=(candle.ask_open - candle.bid_open).quantize(
                        PRICE_QUANTUM
                    ),
                    details={
                        "entry_condition": recommendation.entry_condition,
                        "entry_level": str(recommendation.entry_level),
                        "entry_at_candle_open": entry_at_open,
                        "target_touch_on_entry_candle_ignored": (
                            target_hit and not stop_hit and not entry_at_open
                        ),
                        "hourly_bid_ask_evidence": True,
                    },
                    entered_at=timezone.now(),
                )
                entry_created = True
                _record_lifecycle(
                    recommendation,
                    PaperLifecycleEvent.State.ENTERED,
                    details={"paper_entry_id": entry.pk, "candle_id": candle.pk},
                )
                _audit_entry(entry)
                if stop_hit:
                    return _create_result(
                        recommendation,
                        entry,
                        PaperTradeResult.Outcome.INVALIDATED,
                        candle,
                        _stop_fill(recommendation, candle),
                        horizon,
                        same_candle_ambiguity=target_hit,
                        entry_candle=True,
                    )
                if target_hit and entry_at_open:
                    return _create_result(
                        recommendation,
                        entry,
                        PaperTradeResult.Outcome.TARGET,
                        candle,
                        recommendation.target_level,
                        horizon,
                        entry_candle=True,
                    )
                break

    if entry:
        for candle in candles[(entry_index + 1 if entry_index is not None else 0) :]:
            target_hit, stop_hit = _exit_touches(recommendation, candle)
            if stop_hit:
                return _create_result(
                    recommendation,
                    entry,
                    PaperTradeResult.Outcome.INVALIDATED,
                    candle,
                    _stop_fill(recommendation, candle),
                    horizon,
                    same_candle_ambiguity=target_hit,
                )
            if target_hit:
                return _create_result(
                    recommendation,
                    entry,
                    PaperTradeResult.Outcome.TARGET,
                    candle,
                    recommendation.target_level,
                    horizon,
                )

    if not horizon or not _has_coverage(recommendation, expires_at, candles):
        if not horizon and timezone.now() > recommendation.generated_at + timedelta(days=14):
            _record_lifecycle(
                recommendation,
                PaperLifecycleEvent.State.MISSING_DATA,
                reason_code="daily_horizon_unavailable",
                details={"sessions_required": recommendation.expires_after_sessions},
            )
        if expires_at and timezone.now() > expires_at + timedelta(hours=24):
            _record_lifecycle(
                recommendation,
                PaperLifecycleEvent.State.EXPIRED_UNOBSERVED,
                reason_code="hourly_coverage_unavailable",
                details={"expected_through": expires_at.isoformat()},
            )
        return entry if entry_created else None
    if not entry:
        result = PaperTradeResult.objects.create(
            recommendation=recommendation,
            outcome=PaperTradeResult.Outcome.NOT_ACTIVATED,
            horizon_candle=horizon,
            details={
                "expiry_at": expires_at.isoformat(),
                "hourly_coverage_verified": True,
                "no_execution_assumed": True,
            },
        )
        _record_lifecycle(
            recommendation,
            PaperLifecycleEvent.State.CLOSED,
            details={"paper_result_id": result.pk, "outcome": result.outcome},
        )
        _audit_result(result)
        return result
    exit_price = (
        horizon.bid_close
        if recommendation.action == Recommendation.Action.BUY
        else horizon.ask_close
    )
    return _create_result(
        recommendation,
        entry,
        PaperTradeResult.Outcome.EXPIRED,
        horizon,
        exit_price,
        horizon,
    )


def _entry_fill(recommendation, candle):
    buy = recommendation.action == Recommendation.Action.BUY
    side_open = candle.ask_open if buy else candle.bid_open
    side_low = candle.ask_low if buy else candle.bid_low
    side_high = candle.ask_high if buy else candle.bid_high
    level = recommendation.entry_level
    if recommendation.entry_condition == Recommendation.EntryCondition.AT_OR_BELOW:
        if side_low > level:
            return None
        at_open = side_open <= level
        if buy:
            fill = level
        else:
            fill = min(level, side_open) if at_open else level
    else:
        if side_high < level:
            return None
        at_open = side_open >= level
        if buy:
            fill = max(level, side_open) if at_open else level
        else:
            fill = level
    return at_open, fill.quantize(PRICE_QUANTUM)


def _exit_touches(recommendation, candle):
    if recommendation.action == Recommendation.Action.BUY:
        return (
            candle.bid_high >= recommendation.target_level,
            candle.bid_low <= recommendation.invalidation_level,
        )
    return (
        candle.ask_low <= recommendation.target_level,
        candle.ask_high >= recommendation.invalidation_level,
    )


def _stop_fill(recommendation, candle):
    if recommendation.action == Recommendation.Action.BUY:
        return min(recommendation.invalidation_level, candle.bid_open).quantize(PRICE_QUANTUM)
    return max(recommendation.invalidation_level, candle.ask_open).quantize(PRICE_QUANTUM)


def _create_result(
    recommendation,
    entry,
    outcome,
    exit_candle,
    exit_price,
    horizon,
    *,
    same_candle_ambiguity=False,
    entry_candle=False,
):
    exit_price = exit_price.quantize(PRICE_QUANTUM)
    signed_change = (
        exit_price - entry.fill_price
        if recommendation.action == Recommendation.Action.BUY
        else entry.fill_price - exit_price
    )
    risk = abs(entry.fill_price - recommendation.invalidation_level)
    result = PaperTradeResult.objects.create(
        recommendation=recommendation,
        entry=entry,
        outcome=outcome,
        horizon_candle=horizon,
        exit_candle=exit_candle,
        exit_price=exit_price,
        gross_pips=(signed_change / PIP_SIZE).quantize(PIP_QUANTUM),
        r_multiple=(signed_change / risk).quantize(R_QUANTUM),
        details={
            "same_candle_target_and_stop": same_candle_ambiguity,
            "adverse_invalidation_precedence": same_candle_ambiguity,
            "exit_on_entry_candle": entry_candle,
            "spread_aware_execution_sides": True,
            "financing_included": False,
            "commission_included": False,
        },
    )
    _record_lifecycle(
        recommendation,
        PaperLifecycleEvent.State.CLOSED,
        details={"paper_result_id": result.pk, "outcome": result.outcome},
    )
    _audit_result(result)
    create_cost_assessment(result)
    return result


def _horizon_candle(recommendation):
    candles = list(
        Candle.objects.filter(
            instrument=recommendation.instrument,
            granularity="D",
            timestamp__gt=recommendation.reference_candle.timestamp,
            complete=True,
            ingestion_run__status=IngestionRun.Status.SUCCEEDED,
        ).order_by("timestamp")[: recommendation.expires_after_sessions]
    )
    return candles[-1] if len(candles) == recommendation.expires_after_sessions else None


def _session_close(interval_start):
    local_start = interval_start.astimezone(NEW_YORK)
    return (local_start + timedelta(days=1)).astimezone(UTC)


def _has_coverage(recommendation, through, candles):
    manifest_covers_range = IngestionRun.objects.filter(
        instrument=recommendation.instrument,
        granularity="H1",
        status=IngestionRun.Status.SUCCEEDED,
        requested_from__lte=recommendation.generated_at,
        requested_to__gte=through,
    ).exists()
    if not manifest_covers_range or not candles:
        return False
    if candles[0].timestamp != _next_market_hour(recommendation.generated_at):
        return False
    if _next_market_hour(candles[-1].timestamp) < through:
        return False
    return all(
        current.timestamp - previous.timestamp == timedelta(hours=1)
        or _is_weekend_gap(previous.timestamp, current.timestamp)
        for previous, current in zip(candles, candles[1:], strict=False)
    )


def _next_market_hour(value):
    local = value.astimezone(NEW_YORK)
    local = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if local.weekday() == 4 and local.hour >= 17:
        local = (local + timedelta(days=2)).replace(hour=17, minute=0, second=0, microsecond=0)
    elif local.weekday() == 5:
        local = (local + timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
    elif local.weekday() == 6 and local.hour < 17:
        local = local.replace(hour=17, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC)


def _is_weekend_gap(start, end):
    local_end = (start + timedelta(hours=1)).astimezone(NEW_YORK)
    local_next = end.astimezone(NEW_YORK)
    return (
        local_end.weekday() == 4
        and local_end.hour == 17
        and local_next.weekday() == 6
        and local_next.hour == 17
    )


def _audit_entry(entry):
    AuditEvent.objects.create(
        event_type="forecast.paper_trade_entered",
        actor="forecasts.paper.resolve_paper_trade",
        subject_type="PaperTradeEntry",
        subject_id=str(entry.pk),
        payload={
            "recommendation_id": entry.recommendation_id,
            "candle_id": entry.candle_id,
            "fill_price": str(entry.fill_price),
            "execution_side": entry.execution_side,
        },
    )


def _record_lifecycle(recommendation, state, *, reason_code="", details=None):
    event, _ = PaperLifecycleEvent.objects.get_or_create(
        recommendation=recommendation,
        state=state,
        defaults={
            "reason_code": reason_code,
            "details": details or {},
            "occurred_at": max(timezone.now(), recommendation.generated_at),
        },
    )
    return event


def _audit_result(result):
    AuditEvent.objects.create(
        event_type="forecast.paper_trade_resolved",
        actor="forecasts.paper.resolve_paper_trade",
        subject_type="PaperTradeResult",
        subject_id=str(result.pk),
        payload={
            "recommendation_id": result.recommendation_id,
            "outcome": result.outcome,
            "gross_pips": str(result.gross_pips) if result.gross_pips is not None else None,
            "r_multiple": str(result.r_multiple) if result.r_multiple is not None else None,
        },
    )
