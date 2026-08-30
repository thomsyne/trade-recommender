import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from market.discovery_waves import build_wave_manifest
from market.historical_discovery import (
    CANARY_V2_LOGICAL_KEY,
    DISCOVERY_PURPOSE,
    DISCOVERY_V2_MANIFEST_SHA256,
    DISCOVERY_V2_PLAN_SHA256,
    run_discovery_chunk,
)
from market.models import (
    HistoricalDiscoveryAttempt,
    HistoricalDiscoveryChunk,
    HistoricalDiscoveryPlan,
    HistoricalTimestampInventory,
    IngestionRun,
)
from market.oanda import OandaClient, OandaError
from market.services import DatasetQualityError


class Command(BaseCommand):
    help = (
        "Execute one bounded, separately authorized Gate 4 discovery wave"
        " sequentially against the immutable wave manifest"
    )

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--plan-sha256", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--wave", type=int, required=True)
        parser.add_argument("--max-chunks", type=int, required=True)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--resume", action="store_true")

    def checkpoint(self, **fields):
        self.stdout.write(json.dumps(fields, sort_keys=True))

    def handle(self, *args, **options):
        if not options["execute"]:
            raise CommandError("network discovery requires explicit --execute")
        if options["max_chunks"] <= 0:
            raise CommandError("--max-chunks must be a positive integer")
        if options["wave"] <= 0:
            raise CommandError("--wave must be a positive integer")
        if settings.OANDA_ENVIRONMENT != "practice":
            raise CommandError("historical discovery requires the practice environment")
        if not settings.OANDA_DISCOVERY_TOKEN:
            raise CommandError("historical discovery requires OANDA_API_KEY_TEST")
        if options["plan_sha256"] != DISCOVERY_V2_PLAN_SHA256:
            raise CommandError("--plan-sha256 does not match the approved v2 plan")
        if options["manifest_sha256"] != DISCOVERY_V2_MANIFEST_SHA256:
            raise CommandError("--manifest-sha256 does not match the approved v2 manifest")
        try:
            with open(options["manifest"], encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, ValueError) as error:
            raise CommandError("wave manifest is unreadable or not valid JSON") from error
        semantic_sha = manifest.get("canary_semantic_inventory_sha256")
        if not isinstance(semantic_sha, str):
            raise CommandError("wave manifest lacks the canary semantic inventory sha")
        expected = build_wave_manifest(semantic_sha)
        if manifest != expected:
            raise CommandError(
                "wave manifest does not reconstruct: it must equal the deterministic"
                " manifest for the approved v2 plan (exact chunks, order, waves and"
                " ordered-manifest sha)"
            )
        if (
            manifest["v2_plan_sha256"] != options["plan_sha256"]
            or manifest["v2_manifest_sha256"] != options["manifest_sha256"]
        ):
            raise CommandError("wave manifest identities do not match the arguments")
        plan = HistoricalDiscoveryPlan.objects.filter(sha256=DISCOVERY_V2_PLAN_SHA256).first()
        if plan is None:
            raise CommandError("approved v2 discovery plan is not present")
        canary_semantic = (
            HistoricalTimestampInventory.objects.filter(
                chunk__plan=plan, chunk__logical_key=CANARY_V2_LOGICAL_KEY
            )
            .values_list("semantic_inventory_sha256", flat=True)
            .first()
        )
        if canary_semantic != semantic_sha:
            raise CommandError(
                "manifest canary semantic inventory sha does not match the governed canary success"
            )
        if IngestionRun.objects.filter(
            status=IngestionRun.Status.RUNNING,
            parameters__purpose=DISCOVERY_PURPOSE,
        ).exists():
            raise CommandError("a discovery attempt is already running")
        wave_chunks = [
            item for item in manifest["chunks"] if item["wave_number"] == options["wave"]
        ]
        if not wave_chunks:
            raise CommandError("the requested wave contains no chunks")
        executed = 0
        with OandaClient(settings.OANDA_DISCOVERY_TOKEN, "practice") as client:
            for entry in wave_chunks:
                if executed >= options["max_chunks"]:
                    self.checkpoint(
                        event="wave_bounded",
                        wave=options["wave"],
                        executed=executed,
                        next_ordinal=entry["ordinal"],
                    )
                    return
                chunk = HistoricalDiscoveryChunk.objects.filter(
                    plan=plan, logical_key=entry["logical_key"]
                ).first()
                if chunk is None or chunk.ordinal != entry["ordinal"]:
                    raise CommandError(
                        f"manifest chunk ordinal {entry['ordinal']} does not match the plan"
                    )
                attempts = list(
                    HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").filter(
                        chunk=chunk
                    )
                )
                if attempts:
                    statuses = {attempt.ingestion_run.status for attempt in attempts}
                    if statuses == {IngestionRun.Status.SUCCEEDED}:
                        if not options["resume"]:
                            raise CommandError(
                                f"chunk ordinal {entry['ordinal']} already succeeded;"
                                " resuming an approved manifest requires --resume"
                            )
                        self.checkpoint(
                            event="chunk_skipped_already_succeeded",
                            wave=options["wave"],
                            ordinal=entry["ordinal"],
                            logical_key=entry["logical_key"],
                        )
                        continue
                    raise CommandError(
                        f"chunk ordinal {entry['ordinal']} has a non-succeeded attempt;"
                        " failed or running chunks are never retried or skipped"
                    )
                try:
                    attempt = run_discovery_chunk(entry["logical_key"], client)
                except (DatasetQualityError, OandaError) as error:
                    self.checkpoint(
                        event="chunk_failed",
                        wave=options["wave"],
                        ordinal=entry["ordinal"],
                        logical_key=entry["logical_key"],
                        error=str(error)[:200],
                    )
                    raise CommandError(
                        f"chunk ordinal {entry['ordinal']} failed; wave stopped with no"
                        " retry and later chunks untouched"
                    ) from error
                run = attempt.ingestion_run
                if run.status != IngestionRun.Status.SUCCEEDED:
                    raise CommandError(
                        f"chunk ordinal {entry['ordinal']} finished in unexpected state"
                        f" {run.status}; wave stopped for review"
                    )
                executed += 1
                self.checkpoint(
                    event="chunk_succeeded",
                    wave=options["wave"],
                    ordinal=entry["ordinal"],
                    logical_key=entry["logical_key"],
                    attempt_number=attempt.attempt_number,
                    stored_count=run.stored_count,
                )
        self.checkpoint(event="wave_complete", wave=options["wave"], executed=executed)
