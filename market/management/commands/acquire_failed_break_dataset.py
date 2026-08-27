import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from market.historical_acquisition import run_historical_chunk
from market.oanda import OandaClient


class Command(BaseCommand):
    help = "Execute exactly one registered bounded failed-break acquisition chunk"

    def add_arguments(self, parser):
        parser.add_argument("--logical-chunk-key", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        if not options["execute"]:
            raise CommandError("network acquisition requires explicit --execute")
        try:
            with OandaClient(settings.OANDA_TOKEN, settings.OANDA_ENVIRONMENT) as client:
                attempt = run_historical_chunk(options["logical_chunk_key"], client)
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
