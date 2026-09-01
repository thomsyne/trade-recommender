import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from market.models import (
    AuditEvent,
    Candle,
    DatasetRegistration,
    DatasetVersion,
    HistoricalDatasetPlan,
    HistoricalIngestionAttempt,
    HistoricalIngestionChunk,
    IngestionRun,
    Instrument,
    SourceRegistry,
    validate_historical_ingestion_manifest,
)
from market.oanda import OandaError
from market.quality import (
    expected_candle_timestamps,
    final_registered_completion_before,
    registered_candle_completion,
    validate_candles,
)
from market.services import DatasetQualityError, store_ingestion

DEVELOPMENT_END = datetime(2019, 1, 1, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
INSTRUMENTS = ("AUD_USD", "EUR_GBP", "EUR_USD", "GBP_USD", "USD_CAD", "USD_JPY")
STRATEGY_INSTRUMENTS = ("EUR_USD", "GBP_USD", "EUR_GBP", "USD_CAD", "USD_JPY", "AUD_USD")
GRANULARITIES = ("D", "H1", "W")
ALIGNMENT = {
    "timezone": "America/New_York",
    "daily_hour": 17,
    "weekly_day": "Friday",
    "smooth": False,
}
PHASE1_SPEC_SHA256 = "47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd"
PHASE1_MANIFEST_SHA256 = "f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882"
PARTITION = {"name": "development", "start_year": 2010, "end_year": 2018}
ACQUISITION_CONTRACT = "failed-break-historical-acquisition"
ACQUISITION_VERSION = "phase-2b1-v1"
SOURCE_IDENTITY = "oanda-v20-market-candles-v1"
FROZEN_RANGES = {
    "D": {
        "from": "2009-02-26T22:00:00+00:00",
        "to": "2018-12-31T22:00:00+00:00",
        "expected_count_per_instrument": 2567,
    },
    "H1": {
        "from": "2009-12-31T15:00:00+00:00",
        "to": "2019-01-01T04:00:00+00:00",
        "expected_count_per_instrument": 56341,
    },
    "W": {
        "from": "2009-12-18T22:00:00+00:00",
        "to": "2018-12-28T22:00:00+00:00",
        "expected_count_per_instrument": 471,
    },
}


class HistoricalFailureCode:
    PROVIDER_AUTH_ERROR = "PROVIDER_AUTH_ERROR"
    PROVIDER_HTTP_ERROR = "PROVIDER_HTTP_ERROR"
    PROVIDER_RESPONSE_MALFORMED = "PROVIDER_RESPONSE_MALFORMED"
    PROVIDER_EVIDENCE_MISSING = "PROVIDER_EVIDENCE_MISSING"
    TIMESTAMP_SET_MISMATCH = "TIMESTAMP_SET_MISMATCH"
    STRUCTURAL_INVENTORY_DRIFT = "STRUCTURAL_INVENTORY_DRIFT"
    INVALID_PRICE_STRUCTURE = "INVALID_PRICE_STRUCTURE"
    CANDLE_VALIDATION_FAILED = "CANDLE_VALIDATION_FAILED"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


@dataclass(frozen=True)
class HistoricalResponseError(DatasetQualityError):
    message: str
    error_code: str
    failure_stage: str
    diagnostics: dict
    provider_evidence: dict

    def __str__(self):
        return self.message


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
        "acquisition_contract",
        "acquisition_version",
        "source",
        "strategy",
        "data_identity",
        "phase1_spec_hash",
        "phase1_manifest_hash",
        "dataset",
        "instruments",
        "granularities",
        "ranges",
        "chunk_size",
    }
    if set(payload) != required:
        raise ValueError(f"historical plan fields must be exactly {sorted(required)}")
    if (
        payload["acquisition_contract"] != ACQUISITION_CONTRACT
        or payload["acquisition_version"] != ACQUISITION_VERSION
    ):
        raise ValueError("historical plan requires the approved acquisition contract")
    if tuple(sorted(payload["instruments"])) != INSTRUMENTS:
        raise ValueError("historical plan must contain exactly the frozen six instruments")
    if tuple(sorted(payload["granularities"])) != GRANULARITIES:
        raise ValueError("historical plan must contain exactly W/D/H1")
    if set(payload["ranges"]) != set(GRANULARITIES):
        raise ValueError("historical plan requires one range for each of W/D/H1")
    chunk_size = int(payload["chunk_size"])
    if not 1 <= chunk_size <= 4999:
        raise ValueError("historical chunk_size must be between 1 and 4999")

    source_selector = payload["source"]
    if source_selector != {"name": "OANDA v20", "governed_identity": SOURCE_IDENTITY}:
        raise ValueError("historical plan requires the governed OANDA source identity")
    source = SourceRegistry.objects.get(name=source_selector["name"])
    if (
        not source.enabled
        or source.tier != SourceRegistry.Tier.ESTABLISHED
        or source.acquisition_method != "v20 REST API"
        or source.llm_processing_allowed
    ):
        raise ValueError("historical plans require the enabled OANDA v20 source")
    strategy = source_plan_strategy(payload["strategy"])
    if (
        strategy.data_identity != payload["data_identity"]
        or strategy.data_identity != "oanda-ba-ny17-friday-v1"
        or strategy.content_hash != payload["strategy"]["content_hash"]
        or strategy.content_hash != PHASE1_MANIFEST_SHA256
        or strategy.pair_metadata != {"instruments": list(STRATEGY_INSTRUMENTS)}
    ):
        raise ValueError("historical plan identity must match the strategy data identity")
    parameter_manifest = strategy.strategyparametermanifest
    if (
        parameter_manifest.sha256 != payload["strategy"]["content_hash"]
        or parameter_manifest.phase1_manifest_hash != payload["phase1_manifest_hash"]
        or parameter_manifest.phase1_spec_hash != payload["phase1_spec_hash"]
        or payload["phase1_manifest_hash"] != PHASE1_MANIFEST_SHA256
        or payload["phase1_spec_hash"] != PHASE1_SPEC_SHA256
    ):
        raise ValueError("historical plan requires the exact approved Phase 1 artifacts")
    dataset_fields = payload["dataset"]
    if set(dataset_fields) != {"name", "version", "description"}:
        raise ValueError("dataset fields must be exactly name, version and description")
    normalized_ranges = {}
    for granularity in GRANULARITIES:
        raw = payload["ranges"][granularity]
        if set(raw) != {"from", "to"}:
            raise ValueError("historical ranges require exactly from and to")
        start, end = parse_timestamp(raw["from"]), parse_timestamp(raw["to"])
        if end != final_registered_completion_before(DEVELOPMENT_END, granularity):
            raise ValueError(
                f"historical {granularity} range must end at its final development completion"
            )
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
        if normalized_ranges[granularity] != FROZEN_RANGES[granularity]:
            raise ValueError(
                f"historical {granularity} range must equal the frozen acquisition range"
            )

    normalized = {
        "acquisition_contract": ACQUISITION_CONTRACT,
        "acquisition_version": ACQUISITION_VERSION,
        "source": source_selector,
        "strategy": payload["strategy"],
        "data_identity": payload["data_identity"],
        "dataset": dataset_fields,
        "instruments": list(INSTRUMENTS),
        "granularities": list(GRANULARITIES),
        "ranges": normalized_ranges,
        "alignment": ALIGNMENT,
        "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
        "complete_only": True,
        "chunk_size": chunk_size,
        "phase1_spec_hash": PHASE1_SPEC_SHA256,
        "phase1_manifest_hash": PHASE1_MANIFEST_SHA256,
    }
    digest = stable_hash(normalized)
    plan, created = HistoricalDatasetPlan.objects.get_or_create(
        sha256=digest,
        defaults={
            "identity": normalized["data_identity"],
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

    required_ranges = [
        {
            "instrument": code,
            "granularity": granularity,
            "start": normalized_ranges[granularity]["from"],
            "end": normalized_ranges[granularity]["to"],
        }
        for code in INSTRUMENTS
        for granularity in GRANULARITIES
    ]
    dataset_manifest = {
        "strategy_manifest_sha256": PHASE1_MANIFEST_SHA256,
        "partition": PARTITION,
        "required_ranges": required_ranges,
        "historical_plan_sha256": plan.sha256,
        "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
        "complete_only": True,
        "instruments": list(INSTRUMENTS),
        "granularities": list(GRANULARITIES),
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


def source_plan_strategy(selector):
    from research.models import StrategyVersion

    if set(selector) != {"definition_key", "version", "content_hash"}:
        raise ValueError("strategy selector requires definition_key, version and content_hash")
    return StrategyVersion.objects.select_related("strategyparametermanifest").get(
        definition__key=selector["definition_key"],
        version=selector["version"],
        content_hash=selector["content_hash"],
    )


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
                    "includeFirst": True,
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
    provider_observed = getattr(chunk, "discovery_inventory_id", None) is not None
    manifest = None
    failure_stage = "provider_request"
    try:
        if provider_observed:
            candles, manifest = client.fetch_historical_chunk(
                chunk.instrument.code,
                chunk.granularity,
                chunk.requested_from,
                chunk.requested_to,
                canonical_request_sha256=chunk.canonical_request_sha256,
            )
        else:
            candles, manifest = client.fetch_historical_chunk(
                chunk.instrument.code,
                chunk.granularity,
                chunk.requested_from,
                chunk.requested_to,
            )
        failure_stage = "response_validation"
        _validate_chunk_response(chunk, candles, manifest)
        manifest = {
            **manifest,
            "historical_logical_key": chunk.logical_key,
            "historical_attempt": attempt.attempt_number,
            "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
            "complete_only": True,
        }
        failure_stage = "persistence"
        with transaction.atomic():
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
                provider_observed=provider_observed,
            )
            if stored.status != IngestionRun.Status.SUCCEEDED:
                raise DatasetQualityError(f"historical ingestion ended as {stored.status}")
            if provider_observed:
                _record_replacement_canary_success(attempt, manifest)
    except Exception as error:
        failure = _classify_historical_failure(error, chunk, manifest, failure_stage)
        _record_historical_failure(attempt.pk, failure)
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
        "includeFirst": True,
    }
    if not isinstance(manifest, dict):
        raise HistoricalResponseError(
            "provider response manifest is malformed",
            HistoricalFailureCode.PROVIDER_RESPONSE_MALFORMED,
            "response_validation",
            {},
            _unavailable_provider_evidence(),
        )
    provider_evidence = _sanitized_provider_evidence(chunk, manifest)
    if provider_evidence["unavailable_fields"]:
        raise HistoricalResponseError(
            "provider response lacks canonical request evidence",
            HistoricalFailureCode.PROVIDER_EVIDENCE_MISSING,
            "response_validation",
            {"unavailable_provider_fields": provider_evidence["unavailable_fields"]},
            provider_evidence,
        )
    invalid_manifest_fields = sorted(
        key for key, value in required_manifest.items() if manifest.get(key) != value
    )
    if invalid_manifest_fields:
        raise HistoricalResponseError(
            "provider manifest conflicts with the logical chunk",
            HistoricalFailureCode.PROVIDER_EVIDENCE_MISSING,
            "response_validation",
            {"invalid_manifest_fields": invalid_manifest_fields},
            provider_evidence,
        )
    try:
        range_matches = (
            parse_timestamp(manifest.get("from", "")) == chunk.requested_from
            and parse_timestamp(manifest.get("to", "")) == chunk.requested_to
        )
    except (TypeError, ValueError):
        range_matches = False
    if not range_matches:
        raise HistoricalResponseError(
            "provider manifest range conflicts with the logical chunk",
            HistoricalFailureCode.PROVIDER_EVIDENCE_MISSING,
            "response_validation",
            {"invalid_manifest_fields": ["from", "to"]},
            provider_evidence,
        )
    provider_observed = getattr(chunk, "discovery_inventory_id", None) is not None
    if provider_observed:
        from market.provider_observed_acquisition import sealed_inventory_timestamps

        # Exact membership comes only from the sealed provider-observed
        # inventory; a differing response is provider drift and fails as
        # immutable evidence without ever mutating the sealed inventory.
        expected = tuple(
            timestamp.astimezone(UTC) for timestamp in sealed_inventory_timestamps(chunk)
        )
    else:
        expected = expected_candle_timestamps(
            chunk.requested_from, chunk.requested_to, chunk.granularity
        )
    try:
        actual = tuple(item.timestamp.astimezone(UTC) for item in candles)
    except (AttributeError, TypeError, ValueError) as error:
        raise HistoricalResponseError(
            "provider response contains a malformed candle",
            HistoricalFailureCode.PROVIDER_RESPONSE_MALFORMED,
            "response_validation",
            {},
            provider_evidence,
        ) from error
    if actual != expected:
        raise HistoricalResponseError(
            (
                "provider response drifted from the sealed timestamp inventory"
                if provider_observed
                else "provider response does not exactly cover the logical chunk"
            ),
            HistoricalFailureCode.TIMESTAMP_SET_MISMATCH,
            "response_validation",
            _timestamp_mismatch_evidence(expected, actual),
            provider_evidence,
        )
    if provider_observed:
        # Structural equality with the sealed observations: volume,
        # completeness and component presence must match per timestamp;
        # any difference is drift and never mutates the sealed inventory.
        drift = _structural_inventory_drift(chunk, candles)
        if drift:
            raise HistoricalResponseError(
                "provider response structurally drifted from the sealed inventory",
                HistoricalFailureCode.STRUCTURAL_INVENTORY_DRIFT,
                "response_validation",
                drift,
                provider_evidence,
            )
        invalid_prices = _invalid_price_structure(candles)
        if invalid_prices:
            raise HistoricalResponseError(
                "provider response contains invalid price structures",
                HistoricalFailureCode.INVALID_PRICE_STRUCTURE,
                "response_validation",
                invalid_prices,
                provider_evidence,
            )
    issues = validate_candles(
        candles,
        chunk.granularity,
        require_registered_alignment=not provider_observed,
        enforce_succession=not provider_observed,
    )
    if issues:
        raise HistoricalResponseError(
            "provider response contains invalid candles",
            HistoricalFailureCode.CANDLE_VALIDATION_FAILED,
            "response_validation",
            _candle_validation_evidence(candles, issues),
            provider_evidence,
        )


def _canonical_request_sha256(chunk):
    registered = getattr(chunk, "canonical_request_sha256", None)
    if registered:
        return registered
    return stable_hash(
        {
            "instrument": chunk.instrument.code,
            "granularity": chunk.granularity,
            "from": chunk.requested_from.isoformat(),
            "to": chunk.requested_to.isoformat(),
            "price": "BA",
            "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
            "smooth": False,
            "dailyAlignment": 17,
            "alignmentTimezone": "America/New_York",
            "weeklyAlignment": "Friday",
            "includeFirst": True,
            "complete_only": True,
        }
    )


def _unavailable_provider_evidence():
    return {
        "unavailable_fields": [
            "canonical_request_sha256",
            "endpoint_identity",
            "http_method",
            "http_status",
            "oanda_environment",
            "provider_request_id",
        ]
    }


def _sanitized_provider_evidence(chunk, manifest):
    fields = (
        "endpoint_identity",
        "http_method",
        "oanda_environment",
        "http_status",
        "provider_request_id",
        "canonical_request_sha256",
    )
    requests = manifest.get("requests")
    request = requests[0] if isinstance(requests, list) and len(requests) == 1 else {}
    evidence = {}
    environment = request.get("oanda_environment")
    expected = {
        "endpoint_identity": (
            f"oanda-v20-{environment}:GET:/v3/instruments/{chunk.instrument.code}/candles"
            if environment in {"practice", "live"}
            else None
        ),
        "http_method": "GET",
        "oanda_environment": environment if environment in {"practice", "live"} else None,
        "http_status": 200,
        "provider_request_id": request.get("provider_request_id")
        if isinstance(request.get("provider_request_id"), str)
        and 0 < len(request.get("provider_request_id").strip()) <= 200
        and re.fullmatch(r"[A-Za-z0-9._:-]+", request.get("provider_request_id").strip())
        else None,
        "canonical_request_sha256": _canonical_request_sha256(chunk),
    }
    for field in fields:
        value = request.get(field)
        if expected[field] is not None and value == expected[field]:
            evidence[field] = value.strip() if field == "provider_request_id" else value
    evidence["unavailable_fields"] = sorted(set(fields) - set(evidence))
    return evidence


def _sanitized_oanda_error_evidence(chunk, raw):
    fields = (
        "endpoint_identity",
        "http_method",
        "oanda_environment",
        "http_status",
        "provider_request_id",
        "canonical_request_sha256",
    )
    environment = raw.get("oanda_environment")
    expected_endpoint = (
        f"oanda-v20-{environment}:GET:/v3/instruments/{chunk.instrument.code}/candles"
        if environment in {"practice", "live"}
        else None
    )
    evidence = {}
    if raw.get("endpoint_identity") == expected_endpoint and expected_endpoint is not None:
        evidence["endpoint_identity"] = expected_endpoint
    if raw.get("http_method") == "GET":
        evidence["http_method"] = "GET"
    if environment in {"practice", "live"}:
        evidence["oanda_environment"] = environment
    if isinstance(raw.get("http_status"), int):
        evidence["http_status"] = raw["http_status"]
    request_id = raw.get("provider_request_id")
    if (
        isinstance(request_id, str)
        and 0 < len(request_id.strip()) <= 200
        and re.fullmatch(r"[A-Za-z0-9._:-]+", request_id.strip())
    ):
        evidence["provider_request_id"] = request_id.strip()
    if raw.get("canonical_request_sha256") == _canonical_request_sha256(chunk):
        evidence["canonical_request_sha256"] = raw["canonical_request_sha256"]
    evidence["unavailable_fields"] = sorted(set(fields) - set(evidence))
    return evidence


def _bounded_first_last(values, size=64):
    if len(values) <= size * 2:
        return values
    return values[:size] + values[-size:]


def _timestamp_mismatch_evidence(expected, actual):
    expected_values = sorted({item.astimezone(UTC).isoformat() for item in expected})
    actual_values = [item.astimezone(UTC).isoformat() for item in actual]
    actual_set = sorted(set(actual_values))
    missing = sorted(set(expected_values) - set(actual_set))
    extra = sorted(set(actual_set) - set(expected_values))
    duplicates = sorted(value for value, count in Counter(actual_values).items() if count > 1)
    difference_truncated = len(missing) + len(extra) > 512
    return {
        "expected_count": len(expected),
        "actual_count": len(actual),
        "expected_timestamp_set_sha256": stable_hash(expected_values),
        "actual_timestamp_set_sha256": stable_hash(actual_set),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "missing_timestamps": (_bounded_first_last(missing) if difference_truncated else missing),
        "extra_timestamps": _bounded_first_last(extra) if difference_truncated else extra,
        "difference_truncated": difference_truncated,
        "duplicate_count": len(actual_values) - len(actual_set),
        "duplicate_timestamps": _bounded_first_last(duplicates),
        "duplicate_timestamps_truncated": len(duplicates) > 128,
        "ordering_mismatch": actual_values != sorted(actual_values),
    }


PRICE_FIELDS = (
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
)
# The governed candle columns are numeric(12,6): six decimal places and an
# integer part strictly below one million. Every provider-observed price
# must be an exact, finite, strictly positive Decimal representable at that
# precision without any rounding, and structurally consistent.
PRICE_QUANTUM = Decimal("0.000001")
PRICE_UPPER_BOUND = Decimal("1000000")


def _invalid_price_categories(candle):
    categories = set()
    values = {}
    for field in PRICE_FIELDS:
        value = getattr(candle, field, None)
        if not isinstance(value, Decimal):
            categories.add("missing_or_non_decimal")
            continue
        if not value.is_finite():
            categories.add("non_finite")
            continue
        if value <= 0:
            categories.add("non_positive")
            continue
        try:
            exact = value.quantize(PRICE_QUANTUM) == value
        except InvalidOperation:
            exact = False
        if not exact:
            categories.add("excessive_precision")
            continue
        if value >= PRICE_UPPER_BOUND:
            categories.add("out_of_range")
            continue
        values[field] = value
    if len(values) == len(PRICE_FIELDS):
        for side in ("bid", "ask"):
            open_, high, low, close = (
                values[f"{side}_{part}"] for part in ("open", "high", "low", "close")
            )
            if low > min(open_, close) or high < max(open_, close) or low > high:
                categories.add("inconsistent_ohlc")
        for part in ("open", "high", "low", "close"):
            if values[f"bid_{part}"] > values[f"ask_{part}"]:
                categories.add("crossed_bid_ask")
    return sorted(categories)


def _invalid_price_structure(candles):
    """Bounded strict price validation for provider-observed responses;
    returns falsy when every bid/ask OHLC value is a finite, strictly
    positive, exactly-representable and structurally consistent Decimal.
    Diagnostics never carry price values."""
    affected = []
    categories = set()
    for index, candle in enumerate(candles):
        found = _invalid_price_categories(candle)
        if found:
            affected.append(index)
            categories.update(found)
    if not affected:
        return None
    return {
        "categories": sorted(categories),
        "affected_count": len(affected),
        "affected_indexes": _bounded_first_last(affected),
        "diagnostic_truncated": len(affected) > 128,
    }


def _structural_inventory_drift(chunk, candles):
    """Bounded structural comparison of a response against the sealed
    observations; returns falsy when every candle matches exactly."""
    observations = {
        row["timestamp"].astimezone(UTC): row
        for row in chunk.discovery_inventory.observations.values(
            "timestamp", "complete", "volume", "bid_present", "ask_present"
        )
    }
    drifted = []
    for candle in candles:
        observation = observations.get(candle.timestamp.astimezone(UTC))
        if observation is None:
            fields = ["timestamp"]
        else:
            fields = [
                field
                for field, value in (
                    ("complete", candle.complete),
                    ("volume", candle.volume),
                    ("bid_present", True),
                    ("ask_present", True),
                )
                if observation[field] != value
            ]
        if fields:
            drifted.append(
                {
                    "timestamp": candle.timestamp.astimezone(UTC).isoformat(),
                    "fields": fields,
                }
            )
    if not drifted:
        return None
    timestamps = [item["timestamp"] for item in drifted]
    return {
        "drifted_count": len(drifted),
        "drifted_fields": sorted({field for item in drifted for field in item["fields"]}),
        "drifted_timestamp_samples": _bounded_first_last(timestamps),
        "diagnostic_truncated": len(drifted) > 128,
    }


def _replacement_candle_hashes(chunk):
    """The registration candle key/payload hash formulas scoped to one chunk."""
    candle_keys = hashlib.sha256()
    candle_payloads = hashlib.sha256()
    rows = (
        Candle.objects.filter(
            dataset_version=chunk.dataset_version,
            instrument=chunk.instrument,
            granularity=chunk.granularity,
            timestamp__gte=chunk.requested_from,
            timestamp__lt=chunk.requested_to,
        )
        .select_related("instrument")
        .order_by("timestamp")
    )
    count = 0
    for row in rows.iterator():
        count += 1
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
    return candle_keys.hexdigest(), candle_payloads.hexdigest(), count


def _record_replacement_canary_success(attempt, manifest):
    """Persist the governed success evidence chain for a provider-observed
    replacement acquisition, atomically with its candles. The completed
    Gate 7A canary keeps its historical event type; every other
    replacement chunk records the Gate 7B acquisition evidence type."""
    from market.provider_observed_canary import ACQUISITION_CANARY_LOGICAL_KEY

    chunk = attempt.chunk
    event_type = (
        "market.replacement_canary_succeeded"
        if chunk.logical_key == ACQUISITION_CANARY_LOGICAL_KEY
        else "market.replacement_acquisition_succeeded"
    )
    ingestion_manifest = attempt.ingestion_run.ingestion_manifest
    candle_key_hash, candle_payload_hash, stored_count = _replacement_candle_hashes(chunk)
    provider_evidence = _sanitized_provider_evidence(chunk, manifest)
    terminal_event = {
        "event": event_type,
        "logical_key": chunk.logical_key,
        "canonical_request_sha256": chunk.canonical_request_sha256,
        "semantic_inventory_sha256": chunk.semantic_inventory_sha256,
        "data_contract_sha256": chunk.data_contract_sha256,
        "plan_sha256": chunk.plan.sha256,
        "dataset_manifest_sha256": chunk.dataset_version.manifest_sha256,
        "ingestion_manifest_sha256": ingestion_manifest.sha256,
        "attempt_number": attempt.attempt_number,
        "idempotency_key": attempt.idempotency_key,
        "expected_candle_count": chunk.expected_observation_count,
        "stored_candle_count": stored_count,
        "candle_key_hash": candle_key_hash,
        "candle_payload_hash": candle_payload_hash,
    }
    terminal_event_sha256 = stable_hash(terminal_event)
    operational_evidence_sha256 = stable_hash(
        [terminal_event_sha256, provider_evidence, attempt.idempotency_key]
    )
    AuditEvent.objects.create(
        event_type=event_type,
        actor="market.historical_acquisition.run_historical_chunk",
        subject_type="HistoricalIngestionAttempt",
        subject_id=str(attempt.pk),
        payload={
            "schema_version": 1,
            **terminal_event,
            "provider_evidence": provider_evidence,
            "terminal_event_sha256": terminal_event_sha256,
            "operational_evidence_sha256": operational_evidence_sha256,
        },
    )


def _candle_validation_evidence(candles, issues):
    categories = {
        "alignment_mismatch": "timestamp",
        "crossed_bid_ask": "spread",
        "duplicate_timestamp": "timestamp",
        "impossible_ohlc": "ohlc",
        "incomplete_candle": "complete",
        "negative_volume": "volume",
        "non_monotonic_timestamp": "timestamp",
        "timestamp_not_utc": "timestamp",
        "unexpected_gap": "timestamp",
    }
    counts = Counter(issue.code for issue in issues)
    timestamps = sorted(
        {
            candles[issue.index].timestamp.astimezone(UTC).isoformat()
            for issue in issues
            if 0 <= issue.index < len(candles)
            and getattr(candles[issue.index], "timestamp", None) is not None
        }
    )
    return {
        "issue_codes": sorted(counts),
        "issue_counts": dict(sorted(counts.items())),
        "categories": sorted({categories.get(code, "structural") for code in counts}),
        "affected_timestamp_samples": _bounded_first_last(timestamps),
        "diagnostic_truncated": len(timestamps) > 128 or len(issues) > 512,
    }


def _classify_historical_failure(error, chunk, manifest, failure_stage):
    if isinstance(error, HistoricalResponseError):
        return error
    if isinstance(error, OandaError):
        codes = {
            "auth": HistoricalFailureCode.PROVIDER_AUTH_ERROR,
            "http": HistoricalFailureCode.PROVIDER_HTTP_ERROR,
            "malformed": HistoricalFailureCode.PROVIDER_RESPONSE_MALFORMED,
        }
        return HistoricalResponseError(
            "historical provider request failed",
            codes.get(error.failure_kind, HistoricalFailureCode.UNKNOWN_FAILURE),
            "provider_response" if error.failure_kind == "malformed" else "provider_request",
            {},
            _sanitized_oanda_error_evidence(chunk, error.provider_evidence),
        )
    if failure_stage == "persistence":
        code = HistoricalFailureCode.PERSISTENCE_FAILED
    else:
        code = HistoricalFailureCode.UNKNOWN_FAILURE
    provider_evidence = (
        _sanitized_provider_evidence(chunk, manifest)
        if isinstance(manifest, dict)
        else _unavailable_provider_evidence()
    )
    return HistoricalResponseError(
        "historical acquisition failed",
        code,
        failure_stage,
        {},
        provider_evidence,
    )


@transaction.atomic
def _record_historical_failure(attempt_id, failure):
    attempt = (
        HistoricalIngestionAttempt.objects.select_for_update()
        .select_related("chunk__plan", "chunk__dataset_version", "chunk__instrument")
        .get(pk=attempt_id)
    )
    run = IngestionRun.objects.select_for_update().get(pk=attempt.ingestion_run_id)
    if run.status != IngestionRun.Status.RUNNING:
        raise DatasetQualityError("historical failure evidence requires a running attempt")
    chunk = attempt.chunk
    occurred_at = timezone.now()
    payload = {
        "schema_version": 1,
        "error_code": failure.error_code,
        "logical_chunk_key": chunk.logical_key,
        "attempt_id": attempt.pk,
        "attempt_number": attempt.attempt_number,
        "idempotency_key": attempt.idempotency_key,
        "ingestion_run_id": run.pk,
        "plan_sha256": chunk.plan.sha256,
        "dataset_manifest_sha256": chunk.dataset_version.manifest_sha256,
        "instrument": chunk.instrument.code,
        "granularity": chunk.granularity,
        "requested_from": chunk.requested_from.astimezone(UTC).isoformat(),
        "requested_to": chunk.requested_to.astimezone(UTC).isoformat(),
        "canonical_request_sha256": chunk.canonical_request_sha256,
        "expected_candle_count": len(
            expected_candle_timestamps(chunk.requested_from, chunk.requested_to, chunk.granularity)
        ),
        "failure_stage": failure.failure_stage,
        "occurred_at": occurred_at.isoformat(),
        "provider_evidence": failure.provider_evidence,
        "diagnostics": failure.diagnostics,
    }
    run.status = IngestionRun.Status.FAILED
    run.failure_reason = failure.error_code
    run.finished_at = occurred_at
    run.save(update_fields=("status", "failure_reason", "finished_at"))
    AuditEvent.objects.create(
        event_type="market.historical_ingestion_failed",
        actor="market.historical_acquisition.run_historical_chunk",
        subject_type="HistoricalIngestionAttempt",
        subject_id=str(attempt.pk),
        payload=payload,
    )
    if chunk.data_contract_sha256 is not None:
        # Governed replacement failures are terminal with two-scope evidence;
        # the deferred completeness trigger requires both events at commit.
        AuditEvent.objects.create(
            event_type="market.ingestion_rejected",
            actor="market.historical_acquisition.run_historical_chunk",
            subject_type="IngestionRun",
            subject_id=str(run.pk),
            payload={
                "schema_version": 1,
                "error_code": failure.error_code,
                "failure_stage": failure.failure_stage,
                "logical_chunk_key": chunk.logical_key,
                "attempt_id": attempt.pk,
            },
        )


@transaction.atomic
def resolve_stale_historical_attempt(attempt_id, stale_threshold, reason):
    """Fail one explicitly selected stale RUNNING attempt; retry remains a separate action."""
    if not isinstance(stale_threshold, timedelta) or stale_threshold <= timedelta(0):
        raise ValueError("stale threshold must be a positive timedelta")
    if not reason or not reason.strip():
        raise ValueError("stale resolution requires a reason")
    attempt = (
        HistoricalIngestionAttempt.objects.select_for_update()
        .select_related("chunk__dataset_version", "ingestion_run")
        .get(pk=attempt_id)
    )
    chunk = HistoricalIngestionChunk.objects.select_for_update().get(pk=attempt.chunk_id)
    run = IngestionRun.objects.select_for_update().get(pk=attempt.ingestion_run_id)
    if DatasetRegistration.objects.filter(dataset_version=chunk.dataset_version).exists():
        raise DatasetQualityError("registered datasets are sealed against recovery")
    if run.status != IngestionRun.Status.RUNNING:
        raise DatasetQualityError("stale recovery requires a RUNNING attempt")
    cutoff = timezone.now() - stale_threshold
    if run.started_at > cutoff:
        raise DatasetQualityError("historical attempt is not stale")
    run.status = IngestionRun.Status.FAILED
    run.failure_reason = f"governed stale resolution: {reason.strip()}"
    run.finished_at = timezone.now()
    run.save()
    from market.models import AuditEvent

    AuditEvent.objects.create(
        event_type="market.historical_attempt_stale_failed",
        actor="market.historical_acquisition.resolve_stale_historical_attempt",
        subject_type="HistoricalIngestionAttempt",
        subject_id=str(attempt.pk),
        payload={
            "attempt_id": attempt.pk,
            "ingestion_run_id": run.pk,
            "logical_key": chunk.logical_key,
            "stale_threshold_seconds": int(stale_threshold.total_seconds()),
            "reason": reason.strip(),
        },
    )
    if chunk.data_contract_sha256 is not None:
        # A governed replacement run may only become terminal together with its
        # two-scope evidence; stale resolution records the same required pair.
        AuditEvent.objects.create(
            event_type="market.historical_ingestion_failed",
            actor="market.historical_acquisition.resolve_stale_historical_attempt",
            subject_type="HistoricalIngestionAttempt",
            subject_id=str(attempt.pk),
            payload={
                "schema_version": 1,
                "error_code": "STALE_ATTEMPT_RESOLVED",
                "logical_chunk_key": chunk.logical_key,
                "attempt_id": attempt.pk,
                "attempt_number": attempt.attempt_number,
                "ingestion_run_id": run.pk,
                "failure_stage": "stale_resolution",
                "reason": reason.strip(),
            },
        )
        AuditEvent.objects.create(
            event_type="market.ingestion_rejected",
            actor="market.historical_acquisition.resolve_stale_historical_attempt",
            subject_type="IngestionRun",
            subject_id=str(run.pk),
            payload={
                "schema_version": 1,
                "error_code": "STALE_ATTEMPT_RESOLVED",
                "failure_stage": "stale_resolution",
                "logical_chunk_key": chunk.logical_key,
                "attempt_id": attempt.pk,
            },
        )
    attempt.ingestion_run = run
    return attempt


def replacement_registration_contract(plan, dataset, chunks):
    """Resolve the provider-observed contract this registration must carry, or
    None for a legacy dataset. Resolution is strictly relational through the
    plan, contract, dataset manifest and every acquisition chunk; a partial or
    disagreeing v2 marker fails closed instead of degrading to the legacy path."""
    contract = plan.data_contract
    markers = (
        contract is not None,
        plan.data_contract_sha256 is not None,
        dataset.data_contract_sha256 is not None,
        isinstance(dataset.manifest, dict)
        and dataset.manifest.get("historical_data_contract_sha256") is not None,
        isinstance(dataset.manifest, dict)
        and dataset.manifest.get("global_semantic_inventory_sha256") is not None,
        any(chunk.data_contract_sha256 is not None for chunk in chunks),
        any(chunk.discovery_inventory_id is not None for chunk in chunks),
    )
    if not any(markers):
        return None
    if not all(markers):
        raise DatasetQualityError("provider-observed registration lineage does not verify")
    manifest = dataset.manifest
    if (
        contract.sha256 != stable_hash(contract.payload)
        or contract.discovery_registration_id is None
        or plan.data_contract_sha256 != contract.sha256
        or dataset.data_contract_sha256 != contract.sha256
        or manifest.get("historical_data_contract_sha256") != contract.sha256
        or manifest.get("global_semantic_inventory_sha256")
        != contract.global_semantic_inventory_sha256
        or manifest.get("historical_plan_sha256") != plan.sha256
        or dataset.manifest_sha256 != stable_hash(manifest)
        or any(
            chunk.data_contract_sha256 != contract.sha256
            or chunk.plan_id != plan.pk
            or chunk.dataset_version_id != dataset.pk
            or chunk.discovery_inventory_id is None
            or chunk.expected_observation_count is None
            or chunk.semantic_inventory_sha256
            != chunk.discovery_inventory.semantic_inventory_sha256
            or chunk.expected_observation_count != chunk.discovery_inventory.observation_count
            for chunk in chunks
        )
    ):
        raise DatasetQualityError("provider-observed registration lineage does not verify")
    return contract


def replacement_series_coverage(plan, dataset, chunks):
    """Coverage for a provider-observed dataset is the exact sealed discovery
    membership of its acquisition chunks. The theoretical registered calendar
    is never consulted: the provider's observed series legitimately differs
    from it, and the sealed inventory is the governed reference."""
    by_series = {}
    for chunk in chunks:
        by_series.setdefault((chunk.instrument.code, chunk.granularity), []).append(chunk)
    series_manifest, row_counts, first_last = [], {}, {}
    expected_total = 0
    for code in plan.instruments:
        for granularity in plan.granularities:
            series_chunks = sorted(
                by_series.get((code, granularity), ()), key=lambda item: item.requested_from
            )
            if not series_chunks:
                raise DatasetQualityError(
                    f"replacement dataset has no acquisition chunk for {code} {granularity}"
                )
            # the same sealed rows sealed_inventory_timestamps() exposes, with
            # the observed volume and completeness each candle must reproduce
            sealed, previous = [], None
            for chunk in series_chunks:
                observations = tuple(
                    chunk.discovery_inventory.observations.order_by("timestamp").values_list(
                        "timestamp", "volume", "complete"
                    )
                )
                if len(observations) != chunk.expected_observation_count:
                    raise DatasetQualityError(
                        f"sealed inventory count disagrees for {code} {granularity}"
                    )
                for stamp, _volume, _complete in observations:
                    if not chunk.requested_from <= stamp < chunk.requested_to:
                        raise DatasetQualityError(
                            f"sealed observation falls outside its chunk for {code} {granularity}"
                        )
                    if previous is not None and stamp <= previous:
                        raise DatasetQualityError(
                            f"sealed membership is not strictly increasing for {code} {granularity}"
                        )
                    previous = stamp
                sealed.extend(observations)
            rows = tuple(
                dataset.candles.filter(instrument__code=code, granularity=granularity)
                .order_by("timestamp")
                .values_list("timestamp", "volume", "complete")
            )
            if rows != tuple(sealed):
                raise DatasetQualityError(
                    f"dataset does not equal the sealed inventory for {code} {granularity}"
                )
            key = f"{code}:{granularity}"
            series_expected = sum(chunk.expected_observation_count for chunk in series_chunks)
            expected_total += series_expected
            row_counts[key] = len(rows)
            first_last[key] = {
                "first": rows[0][0].isoformat(),
                "last": rows[-1][0].isoformat(),
            }
            series_manifest.append(
                {
                    "series": key,
                    "range": plan.ranges[granularity],
                    "row_count": series_expected,
                }
            )
    stored_total = dataset.candles.count()
    if (
        expected_total != stored_total
        or expected_total != sum(chunk.expected_observation_count for chunk in chunks)
        or stored_total != sum(row_counts.values())
    ):
        raise DatasetQualityError(
            "replacement dataset candle total does not equal the sealed inventory"
        )
    return series_manifest, row_counts, first_last


def _legacy_series_coverage(plan, dataset):
    """The legacy theoretical-calendar coverage rule, unchanged."""
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
    return series_manifest, row_counts, first_last


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
        .select_related("instrument", "discovery_inventory")
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
        try:
            manifest = succeeded[0].ingestion_run.ingestion_manifest
            validate_historical_ingestion_manifest(
                ingestion_run=succeeded[0].ingestion_run,
                dataset_version=dataset,
                payload=manifest.payload,
            )
            if manifest.sha256 != stable_hash(manifest.payload):
                raise ValueError
        except (AttributeError, ValidationError, ValueError) as error:
            raise DatasetQualityError(
                "successful historical attempt has an invalid ingestion manifest"
            ) from error
        successful_attempts.extend(succeeded)
    if dataset.conflicts.exists() or dataset.incidents.exists():
        raise DatasetQualityError("dataset has a conflict or data-quality incident")

    contract = replacement_registration_contract(plan, dataset, chunks)
    if contract is not None:
        series_manifest, row_counts, first_last = replacement_series_coverage(plan, dataset, chunks)
    else:
        series_manifest, row_counts, first_last = _legacy_series_coverage(plan, dataset)

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
    if contract is not None:
        from market.provider_observed_acquisition import REPLACEMENT_REGISTRATION_IDENTITY

        configuration = {
            "identity": REPLACEMENT_REGISTRATION_IDENTITY,
            "plan_sha256": plan.sha256,
            "dataset_manifest_sha256": dataset.manifest_sha256,
            "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
            "logical_chunk_set_hash": logical_chunk_set_hash,
            "data_contract_sha256": contract.sha256,
            "global_semantic_inventory_sha256": contract.global_semantic_inventory_sha256,
        }
    else:
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
        data_contract=contract,
        global_semantic_inventory_sha256=(
            contract.global_semantic_inventory_sha256 if contract is not None else None
        ),
    )


def load_plan(path):
    return json.loads(Path(path).read_text())


def offline_acquisition_report(plan, dataset):
    """Render deterministic acquisition intent without contacting the provider."""
    chunks = []
    queryset = plan.chunks.select_related("instrument").order_by(
        "instrument__code", "granularity", "requested_from"
    )
    for index, chunk in enumerate(queryset, 1):
        chunks.append(
            {
                "order": index,
                "expected_candle_count": len(
                    expected_candle_timestamps(
                        chunk.requested_from, chunk.requested_to, chunk.granularity
                    )
                ),
                "canonical_request": chunk.canonical_request,
                "canonical_request_sha256": chunk.canonical_request_sha256,
                "logical_key": chunk.logical_key,
            }
        )
    return {
        "report_identity": "failed-break-phase-2b1-offline-acquisition-report-v1",
        "offline_only": True,
        "provider_requests_performed": 0,
        "plan_sha256": plan.sha256,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "logical_chunk_count": len(chunks),
        "ordered_manifest_sha256": stable_hash(chunks),
        "chunks": chunks,
    }
