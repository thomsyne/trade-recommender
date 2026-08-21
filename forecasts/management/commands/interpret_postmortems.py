from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from forecasts.interpretations import interpret_due_reviews


class Command(BaseCommand):
    help = "Run bounded Sonnet interpretation for eligible deterministic postmortems"

    def handle(self, *args, **options):
        if not settings.POSTMORTEM_INTERPRETATION_ENABLED:
            raise CommandError("POSTMORTEM_INTERPRETATION_ENABLED is false")
        if not settings.ANTHROPIC_API_KEY:
            raise CommandError("ANTHROPIC_API_KEY is not configured")
        interpretations = interpret_due_reviews()
        self.stdout.write(f"created {len(interpretations)} bounded interpretation(s)")
