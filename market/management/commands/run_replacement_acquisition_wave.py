import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from market.historical_acquisition import HistoricalResponseError, run_historical_chunk
from market.models import HistoricalIngestionAttempt, IngestionRun
from market.oanda import OandaClient, OandaError
from market.provider_observed_waves import (
    load_committed_wave_manifest,
    verify_live_canary_success,
)
from market.services import DatasetQualityError


class Command(BaseCommand):
    help = (
        "Execute one bounded wave of the governed provider-observed"
        " replacement acquisition, one request per chunk, stopping on the"
        " first failure"
    )

    def add_arguments(self, parser):
        parser.add_argument("--wave", type=int, required=True)
        parser.add_argument("--max-chunks", type=int, required=True)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--resume", action="store_true")

    def checkpoint(self, payload):
        self.stdout.write(json.dumps(payload, sort_keys=True))

    def handle(self, *args, **options):
        try:
            manifest = load_committed_wave_manifest()
        except (ValueError, OSError) as error:
            raise CommandError(str(error)) from error
        waves = {entry["wave"]: entry for entry in manifest["waves"]}
        wave = waves.get(options["wave"])
        if wave is None:
            raise CommandError("wave number is not part of the governed manifest")
        if not 0 < options["max_chunks"] <= wave["chunk_count"]:
            raise CommandError("max-chunks must be positive and at most the declared wave size")
        try:
            verify_live_canary_success()
        except DatasetQualityError as error:
            raise CommandError(str(error)) from error

        statuses = []
        for entry in wave["chunks"]:
            attempts = list(
                HistoricalIngestionAttempt.objects.filter(
                    chunk__logical_key=entry["logical_key"]
                ).select_related("ingestion_run")
            )
            if not attempts:
                status = "pending"
            elif len(attempts) > 1:
                raise CommandError("chunk carries more than one attempt")
            else:
                status = attempts[0].ingestion_run.status
            statuses.append({**entry, "status": status})

        planned = []
        for entry in statuses:
            if entry["status"] == "pending":
                planned.append(entry)
                continue
            if entry["status"] == "succeeded":
                if not options["resume"]:
                    raise CommandError("wave contains a completed chunk; rerun with --resume")
                self.checkpoint(
                    {
                        "checkpoint": "skip",
                        "ordinal": entry["ordinal"],
                        "logical_key": entry["logical_key"],
                        "status": "succeeded",
                    }
                )
                continue
            raise CommandError(
                "wave contains a failed or running chunk; a reason-specific"
                " retry authorization is required"
            )
        executions = planned[: options["max_chunks"]]

        if not options["execute"]:
            self.checkpoint(
                {
                    "checkpoint": "dry-run",
                    "read_only": True,
                    "provider_requests_performed": 0,
                    "wave": wave["wave"],
                    "wave_chunk_count": wave["chunk_count"],
                    "wave_expected_candle_total": wave["expected_candle_total"],
                    "manifest_sha256": manifest["manifest_sha256"],
                    "ordered_wave_manifest_sha256": manifest["ordered_wave_manifest_sha256"],
                    "planned_executions": [
                        {
                            "ordinal": entry["ordinal"],
                            "logical_key": entry["logical_key"],
                            "expected_observation_count": entry["expected_observation_count"],
                        }
                        for entry in executions
                    ],
                }
            )
            return
        if settings.OANDA_ENVIRONMENT != "practice":
            raise CommandError("replacement acquisition requires the practice environment")
        if not settings.OANDA_DISCOVERY_TOKEN:
            raise CommandError("replacement acquisition requires OANDA_API_KEY_TEST")
        if IngestionRun.objects.filter(status=IngestionRun.Status.RUNNING).exists():
            raise CommandError("an acquisition is already running")

        executed = 0
        with OandaClient(settings.OANDA_DISCOVERY_TOKEN, "practice") as client:
            for entry in executions:
                try:
                    attempt = run_historical_chunk(entry["logical_key"], client)
                except HistoricalResponseError as error:
                    self.checkpoint(
                        {
                            "checkpoint": "failed",
                            "ordinal": entry["ordinal"],
                            "logical_key": entry["logical_key"],
                            "error_code": error.error_code,
                            "failure_stage": error.failure_stage,
                        }
                    )
                    raise CommandError(
                        f"wave stopped at ordinal {entry['ordinal']}: {error.error_code}"
                    ) from error
                except OandaError as error:
                    self.checkpoint(
                        {
                            "checkpoint": "failed",
                            "ordinal": entry["ordinal"],
                            "logical_key": entry["logical_key"],
                            "failure_kind": error.failure_kind,
                        }
                    )
                    raise CommandError(
                        f"wave stopped at ordinal {entry['ordinal']}: provider request failed"
                    ) from error
                except (DatasetQualityError, DatabaseError) as error:
                    raise CommandError(
                        f"wave stopped at ordinal {entry['ordinal']}: rejected before persistence"
                    ) from error
                executed += 1
                self.checkpoint(
                    {
                        "checkpoint": "succeeded",
                        "ordinal": entry["ordinal"],
                        "logical_key": entry["logical_key"],
                        "attempt_number": attempt.attempt_number,
                        "stored_count": attempt.ingestion_run.stored_count,
                    }
                )
        self.checkpoint(
            {
                "checkpoint": "wave-complete",
                "wave": wave["wave"],
                "executed_chunks": executed,
                "skipped_chunks": len(statuses) - len(planned),
                "remaining_in_wave": len(planned) - executed,
            }
        )
