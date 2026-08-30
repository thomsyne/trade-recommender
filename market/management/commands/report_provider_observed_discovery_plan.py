import json

from django.core.management.base import BaseCommand

from market.historical_discovery import (
    build_initial_discovery_plan,
    build_replacement_discovery_plan,
)


class Command(BaseCommand):
    help = "Render the offline Phase 2B.1R discovery plan without database or provider access"

    def add_arguments(self, parser):
        parser.add_argument("--plan-version", choices=("v1", "v2"), default="v1")

    def handle(self, *args, **options):
        builder = (
            build_replacement_discovery_plan
            if options["plan_version"] == "v2"
            else build_initial_discovery_plan
        )
        self.stdout.write(json.dumps(builder(), sort_keys=True, separators=(",", ":")))
