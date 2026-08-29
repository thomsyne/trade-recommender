import json

from django.core.management.base import BaseCommand

from market.historical_discovery import build_initial_discovery_plan


class Command(BaseCommand):
    help = "Render the offline Phase 2B.1R discovery plan without database or provider access"

    def handle(self, *args, **options):
        self.stdout.write(
            json.dumps(build_initial_discovery_plan(), sort_keys=True, separators=(",", ":"))
        )
