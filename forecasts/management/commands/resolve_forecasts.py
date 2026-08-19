from django.core.management.base import BaseCommand

from forecasts.services import resolve_due_forecasts


class Command(BaseCommand):
    help = "Resolve due immutable forecasts against later completed daily candles"

    def handle(self, *args, **options):
        resolutions = resolve_due_forecasts()
        self.stdout.write(
            self.style.SUCCESS(
                f"resolved {len(resolutions)} forecast(s): {[item.pk for item in resolutions]}"
            )
        )
