"""Bounded, explicitly authorized Gate 8G successor acquisition entrypoint."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from market.historical_acquisition import HistoricalResponseError, run_historical_chunk
from market.oanda import OandaClient, OandaError
from market.provider_observed_gate8g import (
    load_committed_gate8f_outcome,
    ready_gate8g_entries,
    successor_gate8g_readiness,
)
from market.services import DatasetQualityError


class Command(BaseCommand):
    help = (
        "Execute a bounded prefix of the governed successor Gate 8G manifest, "
        "sequentially without retry and stopping on first failure"
    )

    def add_arguments(self, parser):
        parser.add_argument("--max-chunks", type=int, required=True)
        parser.add_argument("--execute", action="store_true")

    def checkpoint(self, payload):
        self.stdout.write(json.dumps(payload, sort_keys=True))

    def handle(self, *args, **options):
        try:
            artifact = load_committed_gate8f_outcome()
            readiness = successor_gate8g_readiness()
        except (ValueError, OSError) as error:
            raise CommandError(str(error)) from error
        if options["max_chunks"] < 1:
            raise CommandError("max-chunks must be positive")
        if readiness.complete:
            self.checkpoint(
                {
                    "checkpoint": "complete",
                    "canary_permanently_closed": True,
                    "provider_requests_performed": 0,
                    "ordered_manifest_sha256": readiness.manifest_sha256,
                }
            )
            return
        if readiness.blocked_reason is not None:
            raise CommandError(readiness.blocked_reason)
        entries = ready_gate8g_entries(readiness)
        if options["max_chunks"] > len(entries):
            raise CommandError("max-chunks exceeds the remaining governed manifest")
        executions = entries[: options["max_chunks"]]
        if not executions:
            raise CommandError("no governed successor chunk is ready")
        if not options["execute"]:
            self.checkpoint(
                {
                    "checkpoint": "dry-run",
                    "read_only": True,
                    "provider_requests_performed": 0,
                    "canary_permanently_closed": True,
                    "artifact_sha256": artifact["outcome_sha256"],
                    "ordered_manifest_sha256": readiness.manifest_sha256,
                    "remaining_ready_chunks": len(entries),
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
            raise CommandError("successor acquisition requires the practice environment")
        if not settings.OANDA_DISCOVERY_TOKEN:
            raise CommandError("successor acquisition requires OANDA_API_KEY_TEST")

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
                        f"Gate 8G stopped at ordinal {entry['ordinal']}: {error.error_code}"
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
                        f"Gate 8G stopped at ordinal {entry['ordinal']}: provider request failed"
                    ) from error
                except (DatasetQualityError, DatabaseError) as error:
                    raise CommandError(
                        f"Gate 8G stopped at ordinal {entry['ordinal']}: rejected before persistence"
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
                "checkpoint": "batch-complete",
                "executed_chunks": executed,
                "remaining_ready_chunks": len(entries) - executed,
                "canary_permanently_closed": True,
            }
        )
