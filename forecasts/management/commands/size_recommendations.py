from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from forecasts.sizing import size_active_recommendations


class Command(BaseCommand):
    help = "Create missing advisory CAD position sizes for active directional recommendations"

    def handle(self, *args, **options):
        try:
            advice = size_active_recommendations()
        except ValidationError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS(f"sized {len(advice)} active recommendation(s)"))
