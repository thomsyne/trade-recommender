from collections import defaultdict

from forecasts.models import Recommendation

CURRENCY_SETUP_BUDGET = 2


def active_directional_recommendations():
    return Recommendation.objects.filter(
        contract_version__gte=2,
        action__in=(Recommendation.Action.BUY, Recommendation.Action.SELL),
        paper_result__isnull=True,
    ).select_related("instrument", "paper_entry", "paper_result")


def decompose_pair(base_currency, quote_currency, action):
    if action == Recommendation.Action.BUY:
        return ((base_currency, 1), (quote_currency, -1))
    if action == Recommendation.Action.SELL:
        return ((base_currency, -1), (quote_currency, 1))
    return ()


def build_exposure_report(recommendations, budget=CURRENCY_SETUP_BUDGET):
    currency_legs = defaultdict(lambda: {"long": [], "short": []})
    setups = []
    for recommendation in recommendations:
        if recommendation.contract_version < 2 or recommendation.action not in {
            Recommendation.Action.BUY,
            Recommendation.Action.SELL,
        }:
            continue
        if getattr(recommendation, "paper_result", None):
            continue

        entry = getattr(recommendation, "paper_entry", None)
        legs = decompose_pair(
            recommendation.instrument.base_currency,
            recommendation.instrument.quote_currency,
            recommendation.action,
        )
        setup = {
            "recommendation": recommendation,
            "state": "entered" if entry else "waiting",
            "state_label": "Entered paper position" if entry else "Waiting for entry",
            "legs": [
                {"currency": currency, "direction": "long" if direction > 0 else "short"}
                for currency, direction in legs
            ],
        }
        setups.append(setup)
        for currency, direction in legs:
            currency_legs[currency]["long" if direction > 0 else "short"].append(setup)

    currencies = []
    for currency in sorted(currency_legs):
        long_setups = currency_legs[currency]["long"]
        short_setups = currency_legs[currency]["short"]
        largest_side = max(len(long_setups), len(short_setups))
        over_budget = largest_side > budget
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
                "largest_side": largest_side,
                "budget": budget,
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
    if over_budget:
        status, status_label = "over_budget", "Review required"
    elif conflicts:
        status, status_label = "conflict", "Conflicts detected"
    elif duplicates:
        status, status_label = "duplicate", "Overlap detected"
    else:
        status, status_label = "clear", "Within guardrails"
    return {
        "setups": setups,
        "currencies": currencies,
        "budget": budget,
        "over_budget_count": over_budget,
        "conflict_count": conflicts,
        "duplicate_count": duplicates,
        "status": status,
        "status_label": status_label,
    }
