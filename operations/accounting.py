"""Provider spend and model-identity accounting that keeps populations distinct.

Reserved estimates, settled provider cost, paid-but-failed attempts, validated
recommendations and rejected responses are reported side by side instead of
being folded into one number. Legacy reservations that predate outcome
recording are reconciled through the recommendation idempotency key; their
outcome column stays blank and is labelled as not recorded.
"""

from dataclasses import dataclass, field
from datetime import UTC
from decimal import Decimal

from django.utils import timezone

from operations.models import ProviderBudget, ProviderBudgetReservation

RECOMMENDATION_KEY_PREFIX = "recommendation:"


@dataclass
class ProviderAccount:
    budget: ProviderBudget
    period: str
    reserved_estimate_usd: Decimal = Decimal("0")
    reserved_count: int = 0
    settled_cost_usd: Decimal = Decimal("0")
    settled_count: int = 0
    uncertain_count: int = 0
    uncertain_usd: Decimal = Decimal("0")
    released_count: int = 0
    validated_count: int = 0
    rejected_count: int = 0
    failed_paid_count: int = 0
    failed_paid_usd: Decimal = Decimal("0")
    outcome_not_recorded_count: int = 0
    reconciled_recommendations: int = 0
    settled_without_recommendation: int = 0
    committed_usd: Decimal = Decimal("0")
    cap_usd: Decimal = Decimal("0")
    rows: list = field(default_factory=list)

    @property
    def cap_used_percent(self):
        if not self.cap_usd:
            return None
        return (self.committed_usd * 100 / self.cap_usd).quantize(Decimal("0.1"))


def _committed(row):
    if row.status == row.Status.SETTLED:
        return row.actual_usd or Decimal("0")
    if row.status == row.Status.UNCERTAIN:
        return row.actual_usd if row.actual_usd is not None else row.estimated_usd
    if row.status == row.Status.RESERVED:
        return row.estimated_usd
    return Decimal("0")


def provider_accounts(now=None):
    """Return per-budget daily and monthly accounts with distinct populations."""
    from forecasts.models import Recommendation

    now = (now or timezone.now()).astimezone(UTC)
    accounts = []
    recommendation_keys = set(
        RECOMMENDATION_KEY_PREFIX + key
        for key in Recommendation.objects.values_list("idempotency_key", flat=True)
    )
    for budget in ProviderBudget.objects.order_by("provider", "purpose"):
        rows = list(budget.reservations.order_by("-budget_at", "-id"))
        for period, cap, selector in (
            (
                "today",
                budget.daily_cap_usd,
                lambda r: r.budget_at.astimezone(UTC).date() == now.date(),
            ),
            (
                "month",
                budget.monthly_cap_usd,
                lambda r: (r.budget_at.year, r.budget_at.month) == (now.year, now.month),
            ),
        ):
            account = ProviderAccount(budget=budget, period=period, cap_usd=cap)
            for row in rows:
                if not selector(row):
                    continue
                account.rows.append(row)
                account.committed_usd += _committed(row)
                if row.status == row.Status.RESERVED:
                    account.reserved_count += 1
                    account.reserved_estimate_usd += row.estimated_usd
                elif row.status == row.Status.SETTLED:
                    account.settled_count += 1
                    account.settled_cost_usd += row.actual_usd or Decimal("0")
                elif row.status == row.Status.UNCERTAIN:
                    account.uncertain_count += 1
                    account.uncertain_usd += _committed(row)
                elif row.status == row.Status.RELEASED:
                    account.released_count += 1
                outcome = row.outcome
                if outcome == row.Outcome.VALIDATED:
                    account.validated_count += 1
                elif outcome == row.Outcome.REJECTED:
                    account.rejected_count += 1
                elif outcome in {row.Outcome.CAP_EXCEEDED, row.Outcome.PROVIDER_FAILED}:
                    pass
                elif outcome in {"", None}:
                    account.outcome_not_recorded_count += 1
                if row.status == row.Status.SETTLED and outcome in {
                    row.Outcome.REJECTED,
                    row.Outcome.CAP_EXCEEDED,
                }:
                    account.failed_paid_count += 1
                    account.failed_paid_usd += row.actual_usd or Decimal("0")
                if row.idempotency_key.startswith(RECOMMENDATION_KEY_PREFIX):
                    if row.idempotency_key in recommendation_keys:
                        account.reconciled_recommendations += 1
                    elif row.status == row.Status.SETTLED:
                        account.settled_without_recommendation += 1
            accounts.append(account)
    return accounts


OUTCOME_LABELS = {
    "": "Not recorded (legacy)",
    ProviderBudgetReservation.Outcome.PENDING: "Pending",
    ProviderBudgetReservation.Outcome.VALIDATED: "Validated",
    ProviderBudgetReservation.Outcome.REJECTED: "Rejected (paid)",
    ProviderBudgetReservation.Outcome.CAP_EXCEEDED: "Cap exceeded (paid)",
    ProviderBudgetReservation.Outcome.PROVIDER_FAILED: "Provider failed",
}
