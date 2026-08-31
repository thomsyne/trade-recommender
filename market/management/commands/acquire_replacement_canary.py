import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from market.historical_acquisition import HistoricalResponseError, run_historical_chunk
from market.models import IngestionRun
from market.oanda import OandaClient, OandaError
from market.provider_observed_canary import (
    ACQUISITION_CANARY_LOGICAL_KEY,
    canary_dry_run_report,
    resolve_canary_chunk,
)
from market.services import DatasetQualityError


class Command(BaseCommand):
    help = (
        "Execute exactly attempt 1 of the single governed provider-observed"
        " replacement acquisition canary chunk"
    )

    def add_arguments(self, parser):
        parser.add_argument("--logical-key", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        if options["logical_key"] != ACQUISITION_CANARY_LOGICAL_KEY:
            raise CommandError("acquisition canary requires the exact governed logical key")
        try:
            chunk = resolve_canary_chunk()
        except DatasetQualityError as error:
            raise CommandError(str(error)) from error
        if not options["execute"]:
            self.stdout.write(json.dumps(canary_dry_run_report(chunk), sort_keys=True))
            return
        if settings.OANDA_ENVIRONMENT != "practice":
            raise CommandError("acquisition canary requires the practice environment")
        if not settings.OANDA_DISCOVERY_TOKEN:
            raise CommandError("acquisition canary requires OANDA_API_KEY_TEST")
        if IngestionRun.objects.filter(status=IngestionRun.Status.RUNNING).exists():
            raise CommandError("an acquisition is already running")
        if chunk.attempts.exists():
            raise CommandError("acquisition canary attempt already exists; retry is prohibited")
        try:
            with OandaClient(settings.OANDA_DISCOVERY_TOKEN, "practice") as client:
                attempt = run_historical_chunk(chunk.logical_key, client)
        except HistoricalResponseError as error:
            self.stdout.write(
                json.dumps(
                    {
                        "status": "failed",
                        "error_code": error.error_code,
                        "failure_stage": error.failure_stage,
                    },
                    sort_keys=True,
                )
            )
            raise CommandError(f"acquisition canary failed: {error.error_code}") from error
        except OandaError as error:
            self.stdout.write(
                json.dumps(
                    {"status": "failed", "failure_kind": error.failure_kind},
                    sort_keys=True,
                )
            )
            raise CommandError("acquisition canary provider request failed") from error
        except (DatasetQualityError, DatabaseError) as error:
            raise CommandError("acquisition canary was rejected before persistence") from error
        self.stdout.write(
            json.dumps(
                {
                    "attempt_id": attempt.pk,
                    "attempt_number": attempt.attempt_number,
                    "ingestion_run_id": attempt.ingestion_run_id,
                    "status": attempt.ingestion_run.status,
                    "logical_key": chunk.logical_key,
                },
                sort_keys=True,
            )
        )
