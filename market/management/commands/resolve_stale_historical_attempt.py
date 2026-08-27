import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from market.historical_acquisition import resolve_stale_historical_attempt


class Command(BaseCommand):
    help = "Explicitly fail one verified-stale RUNNING historical attempt without retrying it"

    def add_arguments(self, parser):
        parser.add_argument("--attempt-id", type=int, required=True)
        parser.add_argument("--stale-seconds", type=int, required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        try:
            attempt = resolve_stale_historical_attempt(
                options["attempt_id"],
                timedelta(seconds=options["stale_seconds"]),
                options["reason"],
            )
        except (ValueError, TypeError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                {
                    "attempt_id": attempt.pk,
                    "attempt_number": attempt.attempt_number,
                    "ingestion_run_id": attempt.ingestion_run_id,
                    "status": attempt.ingestion_run.status,
                    "retried": False,
                },
                sort_keys=True,
            )
        )
