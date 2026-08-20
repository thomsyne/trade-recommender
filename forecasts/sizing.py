from collections import deque
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from forecasts.models import PositionSizeAdvice, Recommendation
from market.models import AuditEvent, Candle, Instrument

POLICY_KEY = "fixed-cad-risk"
POLICY_VERSION = 1
MODEL_EQUITY_CAD = Decimal("25000.00")
RISK_FRACTION = Decimal("0.005000")
SETUP_RISK_CAP_CAD = Decimal("125.00")
AGGREGATE_RISK_CAP_CAD = Decimal("500.00")
CURRENCY_DIRECTION_RISK_CAP_CAD = Decimal("250.00")
RATE_QUANTUM = Decimal("0.00000001")
RISK_QUANTUM = Decimal("0.01")


def calculate_size(entry_level, invalidation_level, quote_to_cad_rate):
    stop_distance = abs(Decimal(entry_level) - Decimal(invalidation_level))
    conversion_rate = Decimal(quote_to_cad_rate)
    if stop_distance <= 0:
        raise ValidationError("Position sizing requires a positive stop distance")
    if conversion_rate <= 0:
        raise ValidationError("Position sizing requires a positive CAD conversion rate")
    unit_risk_cad = stop_distance * conversion_rate
    units = int((SETUP_RISK_CAP_CAD / unit_risk_cad).to_integral_value(rounding=ROUND_FLOOR))
    if units < 1:
        raise ValidationError("The declared risk cap cannot fund one unit")
    projected_risk = (Decimal(units) * unit_risk_cad).quantize(RISK_QUANTUM, rounding=ROUND_HALF_UP)
    return stop_distance, units, min(projected_risk, SETUP_RISK_CAP_CAD)


def quote_to_cad(quote_currency, *, as_of):
    if quote_currency == "CAD":
        return Decimal("1.00000000"), [{"currency": "CAD", "rate": "1.00000000"}]

    graph = {}
    for instrument in Instrument.objects.filter(active=True).order_by("display_order", "code"):
        candle = (
            Candle.objects.filter(
                instrument=instrument,
                granularity="H1",
                timestamp__lte=as_of,
                ingestion_run__finished_at__lte=as_of,
            )
            .select_related("ingestion_run")
            .order_by("-timestamp", "-id")
            .first()
        )
        if not candle:
            continue
        midpoint = candle.midpoint_close
        evidence = {
            "instrument": instrument.code,
            "candle_id": candle.pk,
            "candle_timestamp": candle.timestamp.isoformat(),
            "ingestion_finished_at": candle.ingestion_run.finished_at.isoformat(),
        }
        graph.setdefault(instrument.base_currency, []).append(
            (instrument.quote_currency, midpoint, {**evidence, "orientation": "direct"})
        )
        graph.setdefault(instrument.quote_currency, []).append(
            (
                instrument.base_currency,
                Decimal("1") / midpoint,
                {**evidence, "orientation": "inverse"},
            )
        )

    queue = deque([(quote_currency, Decimal("1"), [])])
    visited = {quote_currency}
    while queue:
        currency, accumulated_rate, path = queue.popleft()
        for next_currency, edge_rate, evidence in graph.get(currency, []):
            if next_currency in visited:
                continue
            rate = accumulated_rate * edge_rate
            next_path = path + [
                {
                    **evidence,
                    "from_currency": currency,
                    "to_currency": next_currency,
                    "edge_rate": str(edge_rate.quantize(RATE_QUANTUM)),
                }
            ]
            if next_currency == "CAD":
                return rate.quantize(RATE_QUANTUM), next_path
            visited.add(next_currency)
            queue.append((next_currency, rate, next_path))
    raise ValidationError(f"No point-in-time {quote_currency}/CAD conversion path exists")


@transaction.atomic
def size_recommendation(recommendation, *, sized_at=None):
    recommendation = (
        Recommendation.objects.select_for_update()
        .select_related("instrument")
        .get(pk=recommendation.pk)
    )
    existing = PositionSizeAdvice.objects.filter(
        recommendation=recommendation,
        policy_key=POLICY_KEY,
        policy_version=POLICY_VERSION,
    ).first()
    if existing:
        return existing
    if recommendation.contract_version not in {2, 3} or recommendation.action not in {
        Recommendation.Action.BUY,
        Recommendation.Action.SELL,
    }:
        return None

    sized_at = sized_at or timezone.now()
    conversion_rate, conversion_path = quote_to_cad(
        recommendation.instrument.quote_currency, as_of=sized_at
    )
    stop_distance, units, projected_risk = calculate_size(
        recommendation.entry_level, recommendation.invalidation_level, conversion_rate
    )
    advice = PositionSizeAdvice.objects.create(
        recommendation=recommendation,
        policy_key=POLICY_KEY,
        policy_version=POLICY_VERSION,
        account_currency="CAD",
        model_equity_cad=MODEL_EQUITY_CAD,
        risk_fraction=RISK_FRACTION,
        setup_risk_cap_cad=SETUP_RISK_CAP_CAD,
        aggregate_risk_cap_cad=AGGREGATE_RISK_CAP_CAD,
        currency_direction_risk_cap_cad=CURRENCY_DIRECTION_RISK_CAP_CAD,
        stop_distance_quote=stop_distance,
        quote_to_cad_rate=conversion_rate,
        recommended_units=units,
        projected_risk_cad=projected_risk,
        conversion_path=conversion_path,
        sized_at=sized_at,
    )
    AuditEvent.objects.create(
        event_type="forecast.position_size_advised",
        actor="forecasts.sizing.size_recommendation",
        subject_type="PositionSizeAdvice",
        subject_id=str(advice.pk),
        payload={
            "instrument": recommendation.instrument.code,
            "recommendation_id": recommendation.pk,
            "policy": f"{POLICY_KEY}-v{POLICY_VERSION}",
            "recommended_units": units,
            "projected_risk_cad": str(projected_risk),
        },
    )
    return advice


def size_active_recommendations(*, sized_at=None):
    sized_at = sized_at or timezone.now()
    recommendations = Recommendation.objects.filter(
        contract_version__in=(2, 3),
        action__in=(Recommendation.Action.BUY, Recommendation.Action.SELL),
        paper_result__isnull=True,
    ).select_related("instrument")
    return [size_recommendation(item, sized_at=sized_at) for item in recommendations]
