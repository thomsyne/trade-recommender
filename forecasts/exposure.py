from collections import defaultdict
from decimal import Decimal

from django.db.models import Prefetch
from django.utils import timezone

from forecasts.models import PositionSizeAdvice, Recommendation
from forecasts.sizing import (
    AGGREGATE_RISK_CAP_CAD,
    CURRENCY_DIRECTION_RISK_CAP_CAD,
    MODEL_EQUITY_CAD,
    POLICY_KEY,
    POLICY_VERSION,
    RISK_FRACTION,
    SETUP_RISK_CAP_CAD,
)

CURRENCY_SETUP_BUDGET = 2


def active_directional_recommendations(*, as_of=None):
    from forecasts.lifecycle import current_risk_projection
    from forecasts.portfolio import active_admitted_recommendation_ids

    as_of = as_of or timezone.now()
    rows = (
        Recommendation.objects.filter(
            pk__in=active_admitted_recommendation_ids(as_of=as_of),
            contract_version__in=(2, 3, 4),
            action__in=(Recommendation.Action.BUY, Recommendation.Action.SELL),
        )
        .select_related("instrument", "paper_entry", "paper_result")
        .prefetch_related(
            Prefetch(
                "position_sizes",
                queryset=PositionSizeAdvice.objects.filter(
                    policy_key=POLICY_KEY, policy_version=POLICY_VERSION
                ),
                to_attr="current_position_sizes",
            )
        )
    )

    return [r for r in rows if current_risk_projection(r, as_of=as_of)]


def decompose_pair(base_currency, quote_currency, action):
    if action == Recommendation.Action.BUY:
        return ((base_currency, 1), (quote_currency, -1))
    if action == Recommendation.Action.SELL:
        return ((base_currency, -1), (quote_currency, 1))
    return ()


def build_exposure_report(recommendations, budget=CURRENCY_SETUP_BUDGET, *, as_of=None):
    from forecasts.lifecycle import current_risk_projection

    as_of = as_of or timezone.now()
    currency_legs = defaultdict(
        lambda: {
            "long": [],
            "short": [],
            "long_risk_cad": Decimal("0"),
            "short_risk_cad": Decimal("0"),
        }
    )
    setups = []
    total_risk_cad = Decimal("0")
    sizing_missing_count = 0
    for recommendation in recommendations:
        lifecycle = current_risk_projection(recommendation, as_of=as_of)
        if lifecycle is None:
            continue
        current_sizes = getattr(recommendation, "current_position_sizes", None)
        size = current_sizes[0] if current_sizes else getattr(recommendation, "position_size", None)
        if size:
            total_risk_cad += size.projected_risk_cad
        else:
            sizing_missing_count += 1
        legs = decompose_pair(
            recommendation.instrument.base_currency,
            recommendation.instrument.quote_currency,
            recommendation.action,
        )
        setup = {
            "recommendation": recommendation,
            "state": lifecycle["state"],
            "state_label": lifecycle["label"],
            "size": size,
            "legs": [
                {"currency": currency, "direction": "long" if direction > 0 else "short"}
                for currency, direction in legs
            ],
        }
        setups.append(setup)
        for currency, direction in legs:
            side = "long" if direction > 0 else "short"
            currency_legs[currency][side].append(setup)
            if size:
                currency_legs[currency][f"{side}_risk_cad"] += size.projected_risk_cad

    currencies = []
    for currency in sorted(currency_legs):
        long_setups = currency_legs[currency]["long"]
        short_setups = currency_legs[currency]["short"]
        long_risk_cad = currency_legs[currency]["long_risk_cad"]
        short_risk_cad = currency_legs[currency]["short_risk_cad"]
        largest_side = max(len(long_setups), len(short_setups))
        largest_side_risk_cad = max(long_risk_cad, short_risk_cad)
        over_budget = (
            largest_side > budget or largest_side_risk_cad > CURRENCY_DIRECTION_RISK_CAP_CAD
        )
        has_conflict = bool(long_setups and short_setups)
        has_duplicate = largest_side > 1
        if over_budget:
            state = "over_budget"
            state_label = "Over advisory cap"
        elif has_conflict:
            state = "conflict"
            state_label = "Opposing exposure"
        elif has_duplicate:
            state = "duplicate"
            state_label = "Repeated exposure"
        else:
            state = "clear"
            state_label = "Single exposure"
        currencies.append(
            {
                "currency": currency,
                "long_count": len(long_setups),
                "short_count": len(short_setups),
                "gross_count": len(long_setups) + len(short_setups),
                "net_count": len(long_setups) - len(short_setups),
                "long_risk_cad": long_risk_cad,
                "short_risk_cad": short_risk_cad,
                "net_risk_cad": long_risk_cad - short_risk_cad,
                "net_risk_abs_cad": abs(long_risk_cad - short_risk_cad),
                "largest_side_risk_cad": largest_side_risk_cad,
                "largest_side": largest_side,
                "budget": budget,
                "risk_budget_cad": CURRENCY_DIRECTION_RISK_CAP_CAD,
                "over_budget": over_budget,
                "has_conflict": has_conflict,
                "has_duplicate": has_duplicate,
                "state": state,
                "state_label": state_label,
            }
        )

    over_budget = sum(row["over_budget"] for row in currencies)
    conflicts = sum(row["has_conflict"] for row in currencies)
    duplicates = sum(row["has_duplicate"] for row in currencies)
    aggregate_over_budget = total_risk_cad > AGGREGATE_RISK_CAP_CAD
    if over_budget or aggregate_over_budget:
        status, status_label = "over_budget", "Review required"
    elif conflicts:
        status, status_label = "conflict", "Conflicts detected"
    elif duplicates:
        status, status_label = "duplicate", "Overlap detected"
    elif sizing_missing_count:
        status, status_label = "missing", "Sizing unavailable"
    else:
        status, status_label = "clear", "Within guardrails"
    return {
        "setups": setups,
        "currencies": currencies,
        "budget": budget,
        "over_budget_count": over_budget,
        "conflict_count": conflicts,
        "duplicate_count": duplicates,
        "total_risk_cad": total_risk_cad,
        "aggregate_risk_cap_cad": AGGREGATE_RISK_CAP_CAD,
        "aggregate_over_budget": aggregate_over_budget,
        "currency_risk_cap_cad": CURRENCY_DIRECTION_RISK_CAP_CAD,
        "setup_risk_cap_cad": SETUP_RISK_CAP_CAD,
        "model_equity_cad": MODEL_EQUITY_CAD,
        "risk_fraction_percent": RISK_FRACTION * 100,
        "sizing_missing_count": sizing_missing_count,
        "policy_label": f"{POLICY_KEY}-v{POLICY_VERSION}",
        "status": status,
        "status_label": status_label,
    }
