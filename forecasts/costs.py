from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction

from forecasts.models import PaperTradeCostAssessment, PaperTradeResult
from market.models import AuditEvent

POLICY_VERSION = "paper-cost-sensitivity-v1"
PIP_SIZE = Decimal("0.0001")
PIP_QUANTUM = Decimal("0.001")
R_QUANTUM = Decimal("0.0001")
NEW_YORK = ZoneInfo("America/New_York")
OANDA_FINANCING_SOURCE = "https://www.oanda.com/us-en/trading/financing-fees"
SCENARIOS = {
    "optimistic": {"annual_financing_rate": Decimal("0"), "commission_pips": Decimal("0")},
    "base": {"annual_financing_rate": Decimal("0.03"), "commission_pips": Decimal("0.5")},
    "conservative": {
        "annual_financing_rate": Decimal("0.06"),
        "commission_pips": Decimal("1.0"),
    },
}


def financing_days_between(start, end):
    if start >= end:
        return 0
    cursor = start.astimezone(NEW_YORK).date()
    final_date = end.astimezone(NEW_YORK).date()
    days = 0
    while cursor <= final_date:
        rollover = datetime.combine(cursor, time(17), NEW_YORK).astimezone(UTC)
        if start < rollover < end and cursor.weekday() < 5:
            days += 3 if cursor.weekday() == 2 else 1
        cursor += timedelta(days=1)
    return days


def financing_day_range(result):
    entry_candle = result.entry.candle
    entry_start = entry_candle.timestamp
    entry_at_open = result.entry.details.get("entry_at_candle_open", False)
    entry_end = entry_start if entry_at_open else entry_start + timedelta(hours=1)

    if result.outcome == PaperTradeResult.Outcome.EXPIRED:
        exit_start = exit_end = _session_close(result.horizon_candle.timestamp)
    else:
        exit_start = result.exit_candle.timestamp
        exit_end = exit_start + timedelta(hours=1)
    return (
        financing_days_between(entry_end, exit_start),
        financing_days_between(entry_start, exit_end),
    )


def assess_due_paper_costs():
    results = (
        PaperTradeResult.objects.filter(
            entry__isnull=False,
        )
        .exclude(
            cost_assessments__policy_version=POLICY_VERSION,
        )
        .select_related("entry__candle", "horizon_candle", "exit_candle", "recommendation")
    )
    return [create_cost_assessment(result) for result in results]


@transaction.atomic
def create_cost_assessment(result):
    result = (
        PaperTradeResult.objects.select_for_update(of=("self",))
        .select_related("entry__candle", "horizon_candle", "exit_candle", "recommendation")
        .get(pk=result.pk)
    )
    existing = PaperTradeCostAssessment.objects.filter(
        result=result, policy_version=POLICY_VERSION
    ).first()
    if existing:
        return existing
    if result.outcome == PaperTradeResult.Outcome.NOT_ACTIVATED or not result.entry_id:
        return None

    minimum_days, maximum_days = financing_day_range(result)
    risk_pips = abs(result.entry.fill_price - result.recommendation.invalidation_level) / PIP_SIZE
    values = {}
    details = {
        "historical_financing_rates_available": False,
        "account_commission_terms_available": False,
        "spread_already_in_gross_pips": True,
        "position_size_required_for_cash_cost": True,
        "financing_source": OANDA_FINANCING_SOURCE,
        "formula": "entry_price * adverse_annual_rate * financing_days / 365 / pip_size",
        "rollover_policy": "17:00 America/New_York; Wednesday counts three; holidays unavailable",
        "entry_exit_hour_ambiguity_bounded": minimum_days != maximum_days,
        "scenarios": {},
    }
    for name, assumptions in SCENARIOS.items():
        days = maximum_days if name == "conservative" else minimum_days
        financing_pips = (
            result.entry.fill_price
            * assumptions["annual_financing_rate"]
            * days
            / Decimal("365")
            / PIP_SIZE
        )
        total_cost_pips = financing_pips + assumptions["commission_pips"]
        net_pips = (result.gross_pips - total_cost_pips).quantize(PIP_QUANTUM)
        values[f"{name}_net_pips"] = net_pips
        values[f"{name}_net_r"] = (net_pips / risk_pips).quantize(R_QUANTUM)
        details["scenarios"][name] = {
            "annual_adverse_financing_rate": str(assumptions["annual_financing_rate"]),
            "commission_pips_round_turn": str(assumptions["commission_pips"]),
            "financing_days": days,
            "financing_pips": str(financing_pips.quantize(PIP_QUANTUM)),
            "total_cost_pips": str(total_cost_pips.quantize(PIP_QUANTUM)),
        }

    assessment = PaperTradeCostAssessment.objects.create(
        result=result,
        policy_version=POLICY_VERSION,
        minimum_financing_days=minimum_days,
        maximum_financing_days=maximum_days,
        details=details,
        **values,
    )
    AuditEvent.objects.create(
        event_type="forecast.paper_cost_assessed",
        actor="forecasts.costs.create_cost_assessment",
        subject_type="PaperTradeCostAssessment",
        subject_id=str(assessment.pk),
        payload={
            "paper_result_id": result.pk,
            "policy_version": POLICY_VERSION,
            "base_net_pips": str(assessment.base_net_pips),
            "conservative_net_pips": str(assessment.conservative_net_pips),
        },
    )
    return assessment


def _session_close(interval_start):
    local_start = interval_start.astimezone(NEW_YORK)
    return (local_start + timedelta(days=1)).astimezone(UTC)
