from django.core.management.base import BaseCommand

from forecasts.paper import resolve_due_paper_trades
from forecasts.recommendations import resolve_due_recommendations
from forecasts.reviews import build_due_review_cohort
from forecasts.services import resolve_due_forecasts


class Command(BaseCommand):
    help = "Resolve due immutable forecasts against later completed daily candles"

    def handle(self, *args, **options):
        forecast_resolutions = resolve_due_forecasts()
        recommendation_resolutions = resolve_due_recommendations()
        paper_changes = resolve_due_paper_trades()
        review_cohort = build_due_review_cohort()
        self.stdout.write(
            self.style.SUCCESS(
                f"resolved {len(forecast_resolutions)} forecast(s) and "
                f"{len(recommendation_resolutions)} recommendation(s); "
                f"recorded {len(paper_changes)} paper-trade change(s); "
                f"{'froze review cohort ' + str(review_cohort.pk) if review_cohort else 'no reviews due'}"
            )
        )
