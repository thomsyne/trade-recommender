"""Read-only attribution; no ranking, promotion or hypothesis self-acceptance."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from market.models import StrategyEvaluation
from market.strategy.contracts import arithmetic
from market.strategy.definitions import STRATEGIES, definition_digest, population_definition


def population(cutoff):
    policy = population_definition()
    start, end = (datetime.fromisoformat(x) for x in policy["holdout"])
    development = datetime.fromisoformat(policy["development"][0])
    if start <= cutoff < end:
        return "untouched_holdout"
    if development <= cutoff < start:
        return "development"
    return "exploratory_outside_registered_population"


@arithmetic
def summarize_outcomes(rows, *, strategy, era):
    """Rows must already cite immutable simulation results; never pooled variants.

    Net/gross R are supplied separately from an independently verified simulator.
    This diagnostic reports dependence counts, NOT a significance calculation.
    """
    if strategy not in STRATEGIES or era != population_definition()["era"]:
        raise ValueError("unsupported_attribution")
    if len(rows) > 10000:
        raise ValueError("report_bound")
    seen = set()
    groups = []
    gross, net = D(0), D(0)
    for row in rows:
        if (
            row["strategy_sha256"] != definition_digest(strategy)
            or row["era"] != era
            or row["population"] != "untouched_holdout"
        ):
            raise ValueError("mixed_strategy_era_or_population")
        if row["identity"] in seen:
            raise ValueError("duplicate_outcome")
        seen.add(row["identity"])
        start, end = row["entered_at"], row["exited_at"]
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or start >= end
            or population(start) != "untouched_holdout"
            or population(end - timedelta(microseconds=1)) != "untouched_holdout"
        ):
            raise ValueError("holdout_boundary")
        if row["net_r"] is None or row["gross_r"] is None:
            raise ValueError("net_evidence_unavailable")
        gross += row["gross_r"]
        net += row["net_r"]
        day = start.astimezone(UTC).date()
        weeks = set()
        last = (end - timedelta(microseconds=1)).astimezone(UTC).date()
        while day <= last:
            weeks.add(day.isocalendar()[:2])
            day += timedelta(days=1)
        overlapping = [g for g in groups if g & weeks]
        for group in overlapping:
            groups.remove(group)
            weeks |= group
        groups.append(weeks)
    return {
        "strategy": strategy,
        "era": era,
        "rows": len(rows),
        "independent_units": len(groups),
        "gross_r": str(gross),
        "net_r": str(net),
        "acceptance": "not_evaluated_owner_review_required",
        "pooling": "forbidden",
    }


def availability_report(*, after_id=0, limit=100):
    if type(limit) is not int or not 1 <= limit <= 100 or after_id < 0:
        raise ValueError("report_bounds")
    rows = list(
        StrategyEvaluation.objects.select_related("definition", "snapshot")
        .filter(pk__gt=after_id)
        .order_by("pk")[: limit + 1]
    )
    results = []
    for row in rows[:limit]:
        results.append(
            {
                "id": row.pk,
                "strategy": row.definition.strategy,
                "snapshot": row.snapshot_id,
                "population": population(row.snapshot.information_cutoff),
                "outputs": [
                    {"schema": p["schema"], "reason": p.get("reason")}
                    for p in row.output["outputs"]
                ],
            }
        )
    return {
        "rows": results,
        "has_more": len(rows) > limit,
        "next_after_id": rows[min(len(rows), limit) - 1].pk if rows else after_id,
        "economic_validation": "unavailable",
        "activation": "forbidden",
    }
