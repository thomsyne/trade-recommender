import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from market.models import (
    Candle,
    DatasetRegistration,
    DatasetVersion,
    HistoricalDatasetPlan,
    HistoricalIngestionAttempt,
    HistoricalIngestionChunk,
    IngestionRun,
    Instrument,
    SourceRegistry,
)
from market.quality import expected_candle_timestamps, registered_candle_completion
from market.services import DatasetQualityError, store_ingestion

DEVELOPMENT_END = datetime(2019, 1, 1, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
INSTRUMENTS = ("AUD_USD", "EUR_GBP", "EUR_USD", "GBP_USD", "USD_CAD", "USD_JPY")
GRANULARITIES = ("D", "H1", "W")
ALIGNMENT = {
    "timezone": "America/New_York",
    "daily_hour": 17,
    "weekly_day": "Friday",
    "smooth": False,
}


def stable_hash(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def parse_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not timezone.is_aware(parsed):
        raise ValueError("historical range timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


@transaction.atomic
def create_historical_dataset_plan(payload):
    required = {
        "identity",
        "source_id",
        "strategy_version_id",
        "dataset",
        "instruments",
        "granularities",
        "ranges",
        "chunk_size",
    }
    if set(payload) != required:
        raise ValueError(f"historical plan fields must be exactly {sorted(required)}")
    if tuple(sorted(payload["instruments"])) != INSTRUMENTS:
        raise ValueError("historical plan must contain exactly the frozen six instruments")
    if tuple(sorted(payload["granularities"])) != GRANULARITIES:
        raise ValueError("historical plan must contain exactly W/D/H1")
    if set(payload["ranges"]) != set(GRANULARITIES):
        raise ValueError("historical plan requires one range for each of W/D/H1")
    chunk_size = int(payload["chunk_size"])
    if not 1 <= chunk_size <= 4999:
        raise ValueError("historical chunk_size must be between 1 and 4999")

    source = SourceRegistry.objects.get(pk=payload["source_id"])
    if source.name != "OANDA v20" or not source.enabled:
        raise ValueError("historical plans require the enabled OANDA v20 source")
    strategy = source_plan_strategy(payload["strategy_version_id"])
    if strategy.data_identity != payload["identity"]:
        raise ValueError("historical plan identity must match the strategy data identity")
    parameter_manifest = strategy.strategyparametermanifest
    normalized_ranges = {}
    for granularity in GRANULARITIES:
        raw = payload["ranges"][granularity]
        if set(raw) != {"from", "to"}:
            raise ValueError("historical ranges require exactly from and to")
        start, end = parse_timestamp(raw["from"]), parse_timestamp(raw["to"])
        timestamps = expected_candle_timestamps(start, end, granularity)
        if registered_candle_completion(timestamps[-1], granularity) >= DEVELOPMENT_END:
            raise ValueError(
                "historical range includes a candle completing at/after development end"
            )
        normalized_ranges[granularity] = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "expected_count_per_instrument": len(timestamps),
        }

    normalized = {
        "identity": payload["identity"],
        "source_id": source.pk,
        "strategy_version_id": strategy.pk,
        "dataset": payload["dataset"],
        "instruments": list(INSTRUMENTS),
        "granularities": list(GRANULARITIES),
        "ranges": normalized_ranges,
        "alignment": ALIGNMENT,
        "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
        "complete_only": True,
        "chunk_size": chunk_size,
        "phase1_spec_hash": parameter_manifest.phase1_spec_hash,
        "phase1_manifest_hash": parameter_manifest.phase1_manifest_hash,
    }
    digest = stable_hash(normalized)
    plan, created = HistoricalDatasetPlan.objects.get_or_create(
        sha256=digest,
        defaults={
            "identity": normalized["identity"],
            "source": source,
            "strategy_version": strategy,
            "instruments": normalized["instruments"],
            "granularities": normalized["granularities"],
            "ranges": normalized_ranges,
            "alignment": ALIGNMENT,
            "chunk_size": chunk_size,
            "phase1_spec_hash": normalized["phase1_spec_hash"],
            "phase1_manifest_hash": normalized["phase1_manifest_hash"],
            "payload": normalized,
        },
    )
    if not created:
        dataset = DatasetVersion.objects.get(manifest__historical_plan_sha256=plan.sha256)
        return plan, dataset

    dataset_fields = payload["dataset"]
    if set(dataset_fields) != {"name", "version", "description"}:
        raise ValueError("dataset fields must be exactly name, version and description")
    dataset_manifest = {
        "identity": payload["identity"],
        "historical_plan_sha256": plan.sha256,
        "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
        "complete_only": True,
        "instruments": list(INSTRUMENTS),
        "granularities": list(GRANULARITIES),
        "ranges": normalized_ranges,
        "alignment": ALIGNMENT,
    }
    dataset = DatasetVersion.objects.create(
        name=dataset_fields["name"],
        version=dataset_fields["version"],
        description=dataset_fields["description"],
        source=source,
        manifest=dataset_manifest,
    )
    materialize_historical_chunks(plan, dataset)
    return plan, dataset


def source_plan_strategy(strategy_id):
    from research.models import StrategyVersion

    return StrategyVersion.objects.select_related("strategyparametermanifest").get(pk=strategy_id)


def materialize_historical_chunks(plan, dataset):
    chunks = []
    instruments = {item.code: item for item in Instrument.objects.filter(code__in=INSTRUMENTS)}
    if set(instruments) != set(INSTRUMENTS):
        raise ValueError("all frozen instruments must exist before planning")
    for code in INSTRUMENTS:
        for granularity in GRANULARITIES:
            candle_range = plan.ranges[granularity]
            timestamps = expected_candle_timestamps(
                parse_timestamp(candle_range["from"]),
                parse_timestamp(candle_range["to"]),
                granularity,
            )
            for offset in range(0, len(timestamps), plan.chunk_size):
                batch = timestamps[offset : offset + plan.chunk_size]
                requested_from = batch[0]
                requested_to = registered_candle_completion(batch[-1], granularity)
                canonical_request = {
                    "instrument": code,
                    "granularity": granularity,
                    "from": requested_from.isoformat(),
                    "to": requested_to.isoformat(),
                    "price": "BA",
                    "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
                    "smooth": False,
                    "dailyAlignment": 17,
                    "alignmentTimezone": "America/New_York",
                    "weeklyAlignment": "Friday",
                    "complete_only": True,
                }
                request_hash = stable_hash(canonical_request)
                logical_key = stable_hash(
                    {
                        "plan_sha256": plan.sha256,
                        "dataset_manifest_sha256": dataset.manifest_sha256,
                        "canonical_request_sha256": request_hash,
                    }
                )
                chunks.append(
                    HistoricalIngestionChunk(
                        plan=plan,
                        dataset_version=dataset,
                        instrument=instruments[code],
                        granularity=granularity,
                        requested_from=requested_from,
                        requested_to=requested_to,
                        canonical_request=canonical_request,
                        canonical_request_sha256=request_hash,
                        logical_key=logical_key,
                    )
                )
    HistoricalIngestionChunk.objects.bulk_create(chunks)


@transaction.atomic
def begin_historical_attempt(logical_key):
    chunk = (
        HistoricalIngestionChunk.objects.select_for_update()
        .select_related("plan", "dataset_version", "instrument")
        .get(logical_key=logical_key)
    )
    if DatasetRegistration.objects.filter(dataset_version=chunk.dataset_version).exists():
        raise DatasetQualityError("registered datasets are sealed against further acquisition")
    attempts = chunk.attempts.select_related("ingestion_run")
    successful = attempts.filter(ingestion_run__status=IngestionRun.Status.SUCCEEDED).first()
    if successful:
        return successful, False
    if attempts.filter(ingestion_run__status=IngestionRun.Status.RUNNING).exists():
        raise DatasetQualityError("historical chunk already has a running attempt")
    attempt_number = (attempts.aggregate(value=Max("attempt_number"))["value"] or 0) + 1
    idempotency_key = f"failed-break-ingestion-attempt:{chunk.logical_key}:{attempt_number}"
    run = IngestionRun.objects.create(
        source=chunk.plan.source,
        dataset_version=chunk.dataset_version,
        instrument=chunk.instrument,
        granularity=chunk.granularity,
        requested_from=chunk.requested_from,
        requested_to=chunk.requested_to,
        parameters=chunk.canonical_request,
        request_manifest_hash=stable_hash({"attempt": idempotency_key}),
    )
    attempt = HistoricalIngestionAttempt.objects.create(
        chunk=chunk,
        ingestion_run=run,
        attempt_number=attempt_number,
        idempotency_key=idempotency_key,
    )
    return attempt, True


def run_historical_chunk(logical_key, client):
    attempt, created = begin_historical_attempt(logical_key)
    if not created:
        return attempt
    chunk, run = attempt.chunk, attempt.ingestion_run
    try:
        candles, manifest = client.fetch_candles(
            chunk.instrument.code,
            chunk.granularity,
            chunk.requested_from,
            chunk.requested_to,
        )
        _validate_chunk_response(chunk, candles, manifest)
        manifest = {
            **manifest,
            "historical_logical_key": chunk.logical_key,
            "historical_attempt": attempt.attempt_number,
            "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
            "complete_only": True,
        }
        stored = store_ingestion(
            chunk.plan.source,
            chunk.instrument,
            chunk.granularity,
            chunk.requested_from,
            chunk.requested_to,
            candles,
            manifest,
            dataset_version=chunk.dataset_version,
            ingestion_run=run,
        )
        if stored.status != IngestionRun.Status.SUCCEEDED:
            raise DatasetQualityError(f"historical ingestion ended as {stored.status}")
    except Exception:
        run.refresh_from_db()
        if run.status == IngestionRun.Status.RUNNING:
            run.status = IngestionRun.Status.FAILED
            run.failure_reason = "historical provider request or persistence failed"
            run.finished_at = timezone.now()
            run.save()
        raise
    return attempt


def _validate_chunk_response(chunk, candles, manifest):
    required_manifest = {
        "instrument": chunk.instrument.code,
        "granularity": chunk.granularity,
        "price": "BA",
        "smooth": False,
        "alignmentTimezone": "America/New_York",
        "dailyAlignment": 17,
        "weeklyAlignment": "Friday",
    }
    if any(manifest.get(key) != value for key, value in required_manifest.items()):
        raise DatasetQualityError("provider manifest conflicts with the logical chunk")
    if (
        parse_timestamp(manifest.get("from", "")) != chunk.requested_from
        or parse_timestamp(manifest.get("to", "")) != chunk.requested_to
    ):
        raise DatasetQualityError("provider manifest range conflicts with the logical chunk")
    expected = expected_candle_timestamps(
        chunk.requested_from, chunk.requested_to, chunk.granularity
    )
    if tuple(item.timestamp for item in candles) != expected:
        raise DatasetQualityError("provider response does not exactly cover the logical chunk")


@transaction.atomic
def register_historical_dataset(dataset_id, plan_sha256):
    dataset = DatasetVersion.objects.select_for_update().get(pk=dataset_id)
    existing = DatasetRegistration.objects.filter(dataset_version=dataset).first()
    if existing:
        if existing.plan.sha256 != plan_sha256:
            raise DatasetQualityError("dataset is registered under a different plan")
        return existing
    plan = HistoricalDatasetPlan.objects.get(sha256=plan_sha256)
    chunks = list(
        plan.chunks.filter(dataset_version=dataset)
        .select_related("instrument")
        .prefetch_related("attempts__ingestion_run__ingestion_manifest")
        .order_by("instrument__code", "granularity", "requested_from")
    )
    if not chunks or dataset.manifest.get("historical_plan_sha256") != plan.sha256:
        raise DatasetQualityError("dataset does not belong to the historical plan")
    if dataset.ingestion_runs.filter(historical_attempt__isnull=True).exists():
        raise DatasetQualityError("dataset contains an ingestion outside the historical plan")

    successful_attempts = []
    for chunk in chunks:
        attempts = list(chunk.attempts.all())
        if any(item.ingestion_run.status == IngestionRun.Status.RUNNING for item in attempts):
            raise DatasetQualityError("historical chunk has an unfinished attempt")
        succeeded = [
            item for item in attempts if item.ingestion_run.status == IngestionRun.Status.SUCCEEDED
        ]
        if len(succeeded) != 1:
            raise DatasetQualityError(
                "every historical chunk requires exactly one successful attempt"
            )
        successful_attempts.extend(succeeded)
    if dataset.conflicts.exists() or dataset.incidents.exists():
        raise DatasetQualityError("dataset has a conflict or data-quality incident")

    series_manifest, row_counts, first_last = [], {}, {}
    for code in INSTRUMENTS:
        for granularity in GRANULARITIES:
            range_payload = plan.ranges[granularity]
            expected = expected_candle_timestamps(
                parse_timestamp(range_payload["from"]),
                parse_timestamp(range_payload["to"]),
                granularity,
            )
            rows = tuple(
                dataset.candles.filter(instrument__code=code, granularity=granularity)
                .order_by("timestamp")
                .values_list("timestamp", flat=True)
            )
            if rows != expected:
                raise DatasetQualityError(f"dataset does not exactly cover {code} {granularity}")
            key = f"{code}:{granularity}"
            row_counts[key] = len(rows)
            first_last[key] = {"first": rows[0].isoformat(), "last": rows[-1].isoformat()}
            series_manifest.append({"series": key, "range": range_payload, "row_count": len(rows)})

    candle_keys = hashlib.sha256()
    candle_payloads = hashlib.sha256()
    for row in (
        Candle.objects.filter(dataset_version=dataset)
        .select_related("instrument")
        .order_by("instrument__code", "granularity", "timestamp")
    ).iterator():
        key = [row.instrument.code, row.granularity, row.timestamp.isoformat()]
        payload = key + [
            row.complete,
            row.volume,
            *[
                format(getattr(row, field), ".6f")
                for field in (
                    "bid_open",
                    "bid_high",
                    "bid_low",
                    "bid_close",
                    "ask_open",
                    "ask_high",
                    "ask_low",
                    "ask_close",
                )
            ],
        ]
        candle_keys.update(json.dumps(key, separators=(",", ":")).encode())
        candle_payloads.update(json.dumps(payload, separators=(",", ":")).encode())

    logical_chunk_set_hash = stable_hash([item.logical_key for item in chunks])
    successful_attempt_set_hash = stable_hash(
        [item.idempotency_key for item in successful_attempts]
    )
    ingestion_manifest_set_hash = stable_hash(
        sorted(item.ingestion_run.ingestion_manifest.sha256 for item in successful_attempts)
    )
    configuration = {
        "identity": "failed-break-historical-dataset-registration-v1",
        "plan_sha256": plan.sha256,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
        "logical_chunk_set_hash": logical_chunk_set_hash,
    }
    report = {
        "configuration_sha256": stable_hash(configuration),
        "series_manifest": series_manifest,
        "row_counts": row_counts,
        "first_last_timestamps": first_last,
        "missingness": {key: 0 for key in row_counts},
        "conflict_count": 0,
        "incident_count": 0,
        "logical_chunk_set_hash": logical_chunk_set_hash,
        "successful_attempt_set_hash": successful_attempt_set_hash,
        "ingestion_manifest_set_hash": ingestion_manifest_set_hash,
        "candle_key_hash": candle_keys.hexdigest(),
        "candle_payload_hash": candle_payloads.hexdigest(),
    }
    return DatasetRegistration.objects.create(
        dataset_version=dataset,
        plan=plan,
        series_manifest=series_manifest,
        row_counts=row_counts,
        first_last_timestamps=first_last,
        missingness=report["missingness"],
        conflict_count=0,
        incident_count=0,
        logical_chunk_set_hash=logical_chunk_set_hash,
        successful_attempt_set_hash=successful_attempt_set_hash,
        ingestion_manifest_set_hash=ingestion_manifest_set_hash,
        candle_key_hash=report["candle_key_hash"],
        candle_payload_hash=report["candle_payload_hash"],
        configuration_sha256=report["configuration_sha256"],
        report_sha256=stable_hash(report),
    )


def load_plan(path):
    return json.loads(Path(path).read_text())
