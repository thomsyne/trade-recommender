import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from market.historical_discovery import run_discovery_chunk
from market.oanda import OandaClient


class Command(BaseCommand):
    help = "Execute exactly one approved provider-observed discovery chunk"

    def add_arguments(self, parser):
        parser.add_argument("--logical-discovery-key", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        if not options["execute"]:
            raise CommandError("network discovery requires explicit --execute")
        if settings.OANDA_ENVIRONMENT != "practice":
            raise CommandError("historical discovery requires the practice environment")
        if not settings.OANDA_DISCOVERY_TOKEN:
            raise CommandError("historical discovery requires OANDA_API_KEY_TEST")
        try:
            with OandaClient(settings.OANDA_DISCOVERY_TOKEN, "practice") as client:
                attempt = run_discovery_chunk(options["logical_discovery_key"], client)
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                {
                    "attempt_id": attempt.pk,
                    "attempt_number": attempt.attempt_number,
                    "ingestion_run_id": attempt.ingestion_run_id,
                    "status": attempt.ingestion_run.status,
                },
                sort_keys=True,
            )
        )
