import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, transaction
from django.db.models import Max
from django.utils import timezone

from market.historical_acquisition import (
    FROZEN_RANGES,
    INSTRUMENTS,
    PHASE1_MANIFEST_SHA256,
    PHASE1_SPEC_SHA256,
    SOURCE_IDENTITY,
    parse_timestamp,
)
from market.models import (
    AuditEvent,
    HistoricalDiscoveryApproval,
    HistoricalDiscoveryAttempt,
    HistoricalDiscoveryChunk,
    HistoricalDiscoveryPlan,
    HistoricalDiscoveryProviderEvidence,
    HistoricalDiscoveryRegistration,
    HistoricalDiscoverySupersession,
    HistoricalTimestampInventory,
    HistoricalTimestampObservation,
    IngestionRun,
    Instrument,
    SourceRegistry,
)
from market.oanda import OandaError
from market.quality import expected_candle_timestamps, registered_candle_completion
from market.services import DatasetQualityError

DISCOVERY_CONTRACT = "oanda-provider-observed-timestamp-discovery"
DISCOVERY_VERSION = "phase-2b1r-discovery-v1"
DISCOVERY_PLAN_IDENTITY = "failed-break-phase-2b1r-discovery-plan-v1"
DISCOVERY_V2_VERSION = "phase-2b1r-discovery-v2"
DISCOVERY_V2_PLAN_IDENTITY = "failed-break-phase-2b1r-discovery-plan-v2"
DISCOVERY_V2_H1_MAX_HOURS = 4000
DISCOVERY_V1_PLAN_SHA256 = "292556a591024876c7051212d1c6886cd026a097e141295e9b60257fc5402b33"
DISCOVERY_V1_MANIFEST_SHA256 = "a3cf7ef1f484d2379bfd1ef94769216b2ed9b41635cad7cadbd71a8de251bb2e"
DISCOVERY_V2_PLAN_SHA256 = "2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a"
DISCOVERY_V2_MANIFEST_SHA256 = "04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427"
GOVERNING_CANARY_LOGICAL_KEY = "c8e22e7d02432f7022094152182d39eec6571cdf98700f9272735e52fdf8b827"
GOVERNING_CANARY_REQUEST_SHA256 = "beb847b0404bb9facf37ec5354b7bbdfa22335a17d7f9abdcb4178bdf0e8494d"
GOVERNING_CANARY_ATTEMPT_NUMBER = 1
GOVERNING_CANARY_IDEMPOTENCY_KEY = f"historical-discovery-attempt:{GOVERNING_CANARY_LOGICAL_KEY}:1"
# Recorded production Gate 3 evidence hashes. These two values are not portable
# identities: they derive from an ingestion-run primary key, wall-clock
# microsecond timestamps, and the withheld provider request id, so they are
# bound through the immutable provider-evidence and audit chain rather than
# hard-coded into enforcement.
GOVERNING_CANARY_TERMINAL_EVENT_SHA256 = (
    "ac09dc4487659e13728178cc0e3d19e825ea2a7d597b5247c87605fdf2817791"
)
GOVERNING_CANARY_OPERATIONAL_EVIDENCE_SHA256 = (
    "0854a7c391c8fd4562a4e24001438de252ff39c7869629b3abfdea4d709028a0"
)
# Gate 3R single-canary activation: the only replacement-plan attempt the
# governance permits is attempt 1 of this exact approved v2 chunk.
CANARY_V2_LOGICAL_KEY = "63db29db49868205e76c52507dab8da30d4a740fac41e709a1edbb1ea100b88d"
CANARY_V2_REQUEST_SHA256 = "3ec01ff455aeef4b6977fb7350dfa8fd98dae744a886c22ad84d597947677ff1"
CANARY_V2_ORDINAL = 2
CANARY_V2_INSTRUMENT = "AUD_USD"
CANARY_V2_GRANULARITY = "H1"
CANARY_V2_REQUESTED_FROM = "2009-12-31T15:00:00Z"
CANARY_V2_REQUESTED_TO = "2010-06-16T07:00:00Z"
CANARY_V2_ATTEMPT_NUMBER = 1
CANARY_V2_IDEMPOTENCY_KEY = f"historical-discovery-attempt:{CANARY_V2_LOGICAL_KEY}:1"
DISCOVERY_PURPOSE = "provider_timestamp_inventory_discovery"
DISCOVERY_APPROVAL_IDENTITY = "failed-break-phase-2b1r-discovery-approval-v1"
SUPERSEDED_DATA_IDENTITY = "oanda-ba-ny17-friday-v1"
REPLACEMENT_DATA_IDENTITY = "oanda-ba-ny17-friday-provider-observed-v1"
DISCOVERY_PROVIDER_MAX_CANDLES = 5000
DISCOVERY_GRANULARITIES = ("D", "H1", "W")
NEW_YORK = ZoneInfo("America/New_York")
PROVIDER_FIELDS = (
    "canonical_request_sha256",
    "endpoint_identity",
    "environment",
    "http_method",
    "http_status",
    "provider_request_id",
)


class DiscoveryFailureCode:
    PROVIDER_AUTH_ERROR = "DISCOVERY_PROVIDER_AUTH_ERROR"
    PROVIDER_HTTP_ERROR = "DISCOVERY_PROVIDER_HTTP_ERROR"
    PROVIDER_RESPONSE_MALFORMED = "DISCOVERY_PROVIDER_RESPONSE_MALFORMED"
    PROVIDER_EVIDENCE_MISSING = "DISCOVERY_PROVIDER_EVIDENCE_MISSING"
    PROVIDER_LIMIT_SUSPECTED = "DISCOVERY_PROVIDER_LIMIT_SUSPECTED"
    PERSISTENCE_FAILED = "DISCOVERY_PERSISTENCE_FAILED"
    STRUCTURE_INVALID = "DISCOVERY_STRUCTURE_INVALID"
    STALE_ATTEMPT = "DISCOVERY_STALE_ATTEMPT"
    UNKNOWN_FAILURE = "DISCOVERY_UNKNOWN_FAILURE"


@dataclass(frozen=True)
class StructuralObservation:
    timestamp: datetime
    complete: bool
    volume: int
    bid_present: bool
    ask_present: bool


@dataclass(frozen=True)
class DiscoveryResponseError(DatasetQualityError):
    message: str
    error_code: str
    stage: str
    diagnostics: dict
    provider_evidence: dict
    fetched_count: int = 0

    def __str__(self):
        return self.message


class DiscoveryPersistenceError(DatasetQualityError):
    def __init__(self, component):
        super().__init__("historical discovery persistence failed")
        self.component = component


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def canonical_timestamp(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_request(*, instrument, granularity, requested_from, requested_to):
    return {
        "instrument": instrument,
        "granularity": granularity,
        "from": canonical_timestamp(requested_from),
        "to": canonical_timestamp(requested_to),
        "price": "BA",
        "price_component": "COMBINED_BID_ASK",
        "smooth": False,
        "dailyAlignment": 17,
        "alignmentTimezone": "America/New_York",
        "weeklyAlignment": "Friday",
        "includeFirst": True,
    }


def logical_discovery_key(
    *,
    request_sha256,
    instrument,
    granularity,
    requested_from,
    requested_to,
    discovery_version=DISCOVERY_VERSION,
):
    return canonical_hash(
        {
            "discovery_contract": DISCOVERY_CONTRACT,
            "discovery_version": discovery_version,
            "source_identity": SOURCE_IDENTITY,
            "instrument": instrument,
            "granularity": granularity,
            "requested_from": canonical_timestamp(requested_from),
            "requested_to": canonical_timestamp(requested_to),
            "canonical_request_sha256": request_sha256,
        }
    )


def build_initial_discovery_plan():
    requests = []
    for instrument in INSTRUMENTS:
        for granularity in DISCOVERY_GRANULARITIES:
            candle_range = FROZEN_RANGES[granularity]
            timestamps = expected_candle_timestamps(
                parse_timestamp(candle_range["from"]),
                parse_timestamp(candle_range["to"]),
                granularity,
            )
            for offset in range(0, len(timestamps), 4999):
                batch = timestamps[offset : offset + 4999]
                requested_from = batch[0]
                requested_to = registered_candle_completion(batch[-1], granularity)
                request = canonical_request(
                    instrument=instrument,
                    granularity=granularity,
                    requested_from=requested_from,
                    requested_to=requested_to,
                )
                request_sha = canonical_hash(request)
                requests.append(
                    {
                        "ordinal": len(requests) + 1,
                        "logical_discovery_key": logical_discovery_key(
                            request_sha256=request_sha,
                            instrument=instrument,
                            granularity=granularity,
                            requested_from=requested_from,
                            requested_to=requested_to,
                        ),
                        "canonical_request": request,
                        "canonical_request_sha256": request_sha,
                    }
                )
    payload = {
        "discovery_contract": DISCOVERY_CONTRACT,
        "discovery_version": DISCOVERY_VERSION,
        "identity": DISCOVERY_PLAN_IDENTITY,
        "purpose": DISCOVERY_PURPOSE,
        "source": {"name": "OANDA v20", "governed_identity": SOURCE_IDENTITY},
        "environment": "practice",
        "phase1_spec_hash": PHASE1_SPEC_SHA256,
        "phase1_manifest_hash": PHASE1_MANIFEST_SHA256,
        "superseded_data_identity": SUPERSEDED_DATA_IDENTITY,
        "replacement_data_identity": REPLACEMENT_DATA_IDENTITY,
        "declared_chunk_count": len(requests),
        "canonical_request_manifest_sha256": canonical_hash(requests),
        "requests": requests,
    }
    return {**payload, "plan_sha256": canonical_hash(payload)}


def build_replacement_discovery_plan():
    requests = []
    for instrument in INSTRUMENTS:
        for granularity in DISCOVERY_GRANULARITIES:
            candle_range = FROZEN_RANGES[granularity]
            range_start = parse_timestamp(candle_range["from"])
            range_end = parse_timestamp(candle_range["to"])
            boundaries = [(range_start, range_end)]
            if granularity == "H1":
                boundaries = []
                requested_from = range_start
                while requested_from < range_end:
                    requested_to = min(
                        requested_from + timedelta(hours=DISCOVERY_V2_H1_MAX_HOURS),
                        range_end,
                    )
                    boundaries.append((requested_from, requested_to))
                    requested_from = requested_to
            for requested_from, requested_to in boundaries:
                request = canonical_request(
                    instrument=instrument,
                    granularity=granularity,
                    requested_from=requested_from,
                    requested_to=requested_to,
                )
                request_sha = canonical_hash(request)
                requests.append(
                    {
                        "ordinal": len(requests) + 1,
                        "logical_discovery_key": logical_discovery_key(
                            request_sha256=request_sha,
                            instrument=instrument,
                            granularity=granularity,
                            requested_from=requested_from,
                            requested_to=requested_to,
                            discovery_version=DISCOVERY_V2_VERSION,
                        ),
                        "canonical_request": request,
                        "canonical_request_sha256": request_sha,
                    }
                )
    payload = {
        "discovery_contract": DISCOVERY_CONTRACT,
        "discovery_version": DISCOVERY_V2_VERSION,
        "identity": DISCOVERY_V2_PLAN_IDENTITY,
        "purpose": DISCOVERY_PURPOSE,
        "source": {"name": "OANDA v20", "governed_identity": SOURCE_IDENTITY},
        "environment": "practice",
        "phase1_spec_hash": PHASE1_SPEC_SHA256,
        "phase1_manifest_hash": PHASE1_MANIFEST_SHA256,
        "superseded_data_identity": SUPERSEDED_DATA_IDENTITY,
        "replacement_data_identity": REPLACEMENT_DATA_IDENTITY,
        "declared_chunk_count": len(requests),
        "canonical_request_manifest_sha256": canonical_hash(requests),
        "requests": requests,
    }
    return {**payload, "plan_sha256": canonical_hash(payload)}


@transaction.atomic
def create_discovery_plan(payload):
    supplied = dict(payload)
    supplied_hash = supplied.pop("plan_sha256", None)
    required = set(build_initial_discovery_plan())
    if set(payload) != required or supplied_hash != canonical_hash(supplied):
        raise ValueError("discovery plan payload or SHA-256 is not canonical")
    requests = supplied.get("requests")
    if not isinstance(requests, list) or supplied["declared_chunk_count"] != len(requests):
        raise ValueError("declared discovery count does not match request manifest")
    if supplied["canonical_request_manifest_sha256"] != canonical_hash(requests):
        raise ValueError("discovery request manifest hash does not match")
    if supplied["discovery_contract"] != DISCOVERY_CONTRACT or not re.fullmatch(
        r"phase-2b1r-discovery-v[1-9][0-9]*", supplied["discovery_version"]
    ):
        raise ValueError("unsupported discovery contract version")
    source = SourceRegistry.objects.get(name="OANDA v20")
    instruments = {item.code: item for item in Instrument.objects.filter(code__in=INSTRUMENTS)}
    if set(instruments) != set(INSTRUMENTS):
        raise ValueError("discovery requires all six governed instruments")
    plan = HistoricalDiscoveryPlan.objects.create(
        identity=supplied["identity"],
        version=supplied["discovery_version"],
        source=source,
        purpose=supplied["purpose"],
        environment=supplied["environment"],
        phase1_spec_hash=supplied["phase1_spec_hash"],
        phase1_manifest_hash=supplied["phase1_manifest_hash"],
        superseded_data_identity=supplied["superseded_data_identity"],
        declared_chunk_count=supplied["declared_chunk_count"],
        canonical_request_manifest=requests,
        canonical_request_manifest_sha256=supplied["canonical_request_manifest_sha256"],
        payload=supplied,
        sha256=supplied_hash,
    )
    chunks = []
    for expected_ordinal, item in enumerate(requests, 1):
        if (
            set(item)
            != {
                "ordinal",
                "logical_discovery_key",
                "canonical_request",
                "canonical_request_sha256",
            }
            or item["ordinal"] != expected_ordinal
        ):
            raise ValueError("discovery request manifest is not canonically ordered")
        request = item["canonical_request"]
        start, end = parse_timestamp(request["from"]), parse_timestamp(request["to"])
        expected_request = canonical_request(
            instrument=request["instrument"],
            granularity=request["granularity"],
            requested_from=start,
            requested_to=end,
        )
        request_sha = canonical_hash(expected_request)
        expected_key = logical_discovery_key(
            request_sha256=request_sha,
            instrument=request["instrument"],
            granularity=request["granularity"],
            requested_from=start,
            requested_to=end,
            discovery_version=supplied["discovery_version"],
        )
        if request != expected_request or item["canonical_request_sha256"] != request_sha:
            raise ValueError("discovery request is not canonical")
        if item["logical_discovery_key"] != expected_key:
            raise ValueError("discovery logical key does not match request")
        chunks.append(
            HistoricalDiscoveryChunk(
                plan=plan,
                ordinal=expected_ordinal,
                instrument=instruments[request["instrument"]],
                granularity=request["granularity"],
                requested_from=start,
                requested_to=end,
                canonical_request=request,
                canonical_request_sha256=request_sha,
                logical_key=expected_key,
            )
        )
    HistoricalDiscoveryChunk.objects.bulk_create(chunks)
    return plan


def semantic_inventory_hashes(chunk, observations):
    rows = [
        {
            "timestamp": canonical_timestamp(item.timestamp),
            "complete": item.complete,
            "volume": item.volume,
            "bid_present": item.bid_present,
            "ask_present": item.ask_present,
        }
        for item in observations
    ]
    timestamp_hash = canonical_hash([item["timestamp"] for item in rows])
    structural_hash = canonical_hash(rows)
    semantic_hash = canonical_hash(
        {
            "logical_discovery_key": chunk.logical_key,
            "canonical_request_sha256": chunk.canonical_request_sha256,
            "observation_count": len(rows),
            "timestamp_set_sha256": timestamp_hash,
            "structural_observation_sha256": structural_hash,
        }
    )
    return timestamp_hash, structural_hash, semantic_hash


def future_data_contract_semantic_hash(*, global_semantic_inventory_sha256):
    """Gate 1B fixture: operational discovery facts can never affect this identity."""
    return canonical_hash(
        {
            "discovery_contract": DISCOVERY_CONTRACT,
            "discovery_version": DISCOVERY_VERSION,
            "source_identity": SOURCE_IDENTITY,
            "phase1_spec_hash": PHASE1_SPEC_SHA256,
            "phase1_manifest_hash": PHASE1_MANIFEST_SHA256,
            "replacement_data_identity": REPLACEMENT_DATA_IDENTITY,
            "superseded_semantic_identity": SUPERSEDED_DATA_IDENTITY,
            "global_semantic_inventory_sha256": global_semantic_inventory_sha256,
        }
    )


def _validate_replacement_canary_activation(chunk):
    plan = chunk.plan
    supersession = HistoricalDiscoverySupersession.objects.filter(replacement_plan=plan).first()
    if supersession is None:
        return
    if (
        plan.version != DISCOVERY_V2_VERSION
        or plan.identity != DISCOVERY_V2_PLAN_IDENTITY
        or plan.sha256 != DISCOVERY_V2_PLAN_SHA256
        or canonical_hash(plan.payload) != DISCOVERY_V2_PLAN_SHA256
        or plan.canonical_request_manifest_sha256 != DISCOVERY_V2_MANIFEST_SHA256
        or canonical_hash(plan.payload["requests"]) != DISCOVERY_V2_MANIFEST_SHA256
        or supersession.replacement_plan_sha256 != plan.sha256
        or supersession.reason_code
        != HistoricalDiscoverySupersession.REASON_PROVIDER_REQUEST_BOUND_UNSAFE
        or supersession.sha256 != canonical_hash(supersession.payload)
        or chunk.logical_key != CANARY_V2_LOGICAL_KEY
        or chunk.canonical_request_sha256 != CANARY_V2_REQUEST_SHA256
        or chunk.ordinal != CANARY_V2_ORDINAL
        or chunk.instrument.code != CANARY_V2_INSTRUMENT
        or chunk.granularity != CANARY_V2_GRANULARITY
        or chunk.requested_from != parse_timestamp(CANARY_V2_REQUESTED_FROM)
        or chunk.requested_to != parse_timestamp(CANARY_V2_REQUESTED_TO)
        or HistoricalDiscoveryAttempt.objects.filter(chunk__plan=plan).exists()
        or HistoricalDiscoveryApproval.objects.filter(plan=plan).exists()
        or HistoricalDiscoveryRegistration.objects.filter(plan=plan).exists()
        or IngestionRun.objects.filter(
            status=IngestionRun.Status.RUNNING,
            parameters__purpose=DISCOVERY_PURPOSE,
        ).exists()
    ):
        raise DatasetQualityError("replacement canary activation rejects this attempt")


@transaction.atomic
def begin_discovery_attempt(logical_key):
    chunk = (
        HistoricalDiscoveryChunk.objects.select_for_update()
        .select_related("plan", "instrument")
        .get(logical_key=logical_key)
    )
    if chunk.plan.sealed_at is not None:
        raise DatasetQualityError("registered discovery plans are sealed")
    if HistoricalDiscoverySupersession.objects.filter(superseded_plan=chunk.plan).exists():
        raise DatasetQualityError("superseded discovery plans reject new attempts")
    _validate_replacement_canary_activation(chunk)
    attempts = chunk.attempts.select_related("ingestion_run")
    if attempts.filter(ingestion_run__status=IngestionRun.Status.SUCCEEDED).exists():
        raise DatasetQualityError("successful discovery chunks cannot be retried")
    if attempts.filter(ingestion_run__status=IngestionRun.Status.RUNNING).exists():
        raise DatasetQualityError("discovery chunk already has a running attempt")
    number = (attempts.aggregate(value=Max("attempt_number"))["value"] or 0) + 1
    key = f"historical-discovery-attempt:{chunk.logical_key}:{number}"
    parameters = {
        "purpose": DISCOVERY_PURPOSE,
        "logical_discovery_key": chunk.logical_key,
        "canonical_request_sha256": chunk.canonical_request_sha256,
        **chunk.canonical_request,
    }
    run = IngestionRun.objects.create(
        source=chunk.plan.source,
        instrument=chunk.instrument,
        granularity=chunk.granularity,
        requested_from=chunk.requested_from,
        requested_to=chunk.requested_to,
        parameters=parameters,
        request_manifest_hash=canonical_hash(
            {"purpose": DISCOVERY_PURPOSE, "attempt_idempotency_key": key}
        ),
    )
    return HistoricalDiscoveryAttempt.objects.create(
        chunk=chunk, ingestion_run=run, attempt_number=number, idempotency_key=key
    )


def _safe_provider_evidence(chunk, raw):
    raw = raw if isinstance(raw, dict) else {}
    expected_endpoint = f"oanda-v20-practice:GET:/v3/instruments/{chunk.instrument.code}/candles"
    request_id = raw.get("provider_request_id")
    request_id = (
        request_id.strip()
        if isinstance(request_id, str)
        and 0 < len(request_id.strip()) <= 200
        and re.fullmatch(r"[A-Za-z0-9._:-]+", request_id.strip())
        else None
    )
    status = raw.get("http_status")
    environment = raw.get("oanda_environment", raw.get("environment"))
    evidence = {
        "endpoint_identity": (
            expected_endpoint if raw.get("endpoint_identity") == expected_endpoint else None
        ),
        "http_method": "GET" if raw.get("http_method") == "GET" else None,
        "environment": "practice" if environment == "practice" else None,
        "http_status": status if type(status) is int and 100 <= status <= 599 else None,
        "provider_request_id": request_id,
        "canonical_request_sha256": (
            chunk.canonical_request_sha256
            if raw.get("canonical_request_sha256") == chunk.canonical_request_sha256
            else None
        ),
    }
    evidence["unavailable_fields"] = sorted(
        field for field in PROVIDER_FIELDS if evidence[field] is None
    )
    return evidence


def _aligned(timestamp, granularity):
    if not timezone.is_aware(timestamp) or timestamp.utcoffset() != timedelta(0):
        return False
    local = timestamp.astimezone(NEW_YORK)
    if local.minute or local.second or local.microsecond:
        return False
    if granularity == "D":
        return local.hour == 17
    if granularity == "W":
        return local.weekday() == 4 and local.hour == 17
    return (
        local.weekday() in {0, 1, 2, 3}
        or (local.weekday() == 4 and local.hour < 17)
        or (local.weekday() == 6 and local.hour >= 17)
    )


def _validate_response(chunk, observations, raw_evidence):
    evidence = _safe_provider_evidence(chunk, raw_evidence)
    required = {
        "canonical_request_sha256",
        "endpoint_identity",
        "environment",
        "http_method",
        "http_status",
        "provider_request_id",
    }
    if evidence["unavailable_fields"] or evidence["http_status"] != 200:
        raise DiscoveryResponseError(
            "discovery response lacks complete successful provider evidence",
            DiscoveryFailureCode.PROVIDER_EVIDENCE_MISSING,
            "provider_evidence",
            {"unavailable_fields": evidence["unavailable_fields"]},
            evidence,
            len(observations) if isinstance(observations, (list, tuple)) else 0,
        )
    if set(evidence) != required | {"unavailable_fields"}:
        raise DiscoveryResponseError(
            "discovery provider evidence is not allowlisted",
            DiscoveryFailureCode.PROVIDER_EVIDENCE_MISSING,
            "provider_evidence",
            {},
            evidence,
        )
    if not isinstance(observations, (list, tuple)):
        raise DiscoveryResponseError(
            "discovery response is malformed",
            DiscoveryFailureCode.PROVIDER_RESPONSE_MALFORMED,
            "response_validation",
            {},
            evidence,
        )
    if len(observations) == DISCOVERY_PROVIDER_MAX_CANDLES:
        raise DiscoveryResponseError(
            "discovery response equals the provider candle limit",
            DiscoveryFailureCode.PROVIDER_LIMIT_SUSPECTED,
            "response_validation",
            {"observation_count": len(observations)},
            evidence,
            len(observations),
        )
    issues = []
    timestamps = []
    for index, item in enumerate(observations):
        if not isinstance(item, StructuralObservation):
            issues.append({"index": index, "code": "malformed_observation"})
            continue
        timestamps.append(item.timestamp)
        if not chunk.requested_from <= item.timestamp < chunk.requested_to:
            issues.append({"index": index, "code": "timestamp_out_of_range"})
        if not _aligned(item.timestamp, chunk.granularity):
            issues.append({"index": index, "code": "timestamp_misaligned"})
        if type(item.complete) is not bool:
            issues.append({"index": index, "code": "completeness_missing"})
        elif not item.complete:
            issues.append({"index": index, "code": "incomplete"})
        if type(item.volume) is not int or isinstance(item.volume, bool) or item.volume < 0:
            issues.append({"index": index, "code": "invalid_volume"})
        if item.bid_present is not True:
            issues.append({"index": index, "code": "bid_missing"})
        if item.ask_present is not True:
            issues.append({"index": index, "code": "ask_missing"})
    if timestamps != sorted(timestamps):
        issues.append({"index": None, "code": "unordered_timestamps"})
    if len(timestamps) != len(set(timestamps)):
        issues.append({"index": None, "code": "duplicate_timestamps"})
    if not observations:
        issues.append({"index": None, "code": "empty_response"})
    if issues:
        counts = {}
        for issue in issues:
            counts[issue["code"]] = counts.get(issue["code"], 0) + 1
        raise DiscoveryResponseError(
            "discovery response contains invalid structural observations",
            DiscoveryFailureCode.STRUCTURE_INVALID,
            "response_validation",
            {
                "issue_counts": dict(sorted(counts.items())),
                "issue_samples": issues[:32],
                "diagnostic_truncated": len(issues) > 32,
            },
            evidence,
            len(observations),
        )
    return tuple(observations), evidence


def _terminal_event_body(attempt, *, code, stage, evidence, diagnostics, occurred_at):
    return {
        "schema_version": 1,
        "error_code": code,
        "stage": stage,
        "logical_discovery_key": attempt.chunk.logical_key,
        "attempt_number": attempt.attempt_number,
        "idempotency_key": attempt.idempotency_key,
        "instrument": attempt.chunk.instrument.code,
        "granularity": attempt.chunk.granularity,
        "requested_from": canonical_timestamp(attempt.chunk.requested_from),
        "requested_to": canonical_timestamp(attempt.chunk.requested_to),
        "canonical_request_sha256": attempt.chunk.canonical_request_sha256,
        "provider_evidence": evidence,
        "diagnostics": diagnostics,
        "occurred_at": occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
    }


def _operational_hash(attempt, run, evidence, event_hash):
    return canonical_hash(
        {
            "logical_discovery_key": attempt.chunk.logical_key,
            "attempt_number": attempt.attempt_number,
            "attempt_idempotency_key": attempt.idempotency_key,
            "run_id": run.pk,
            "run_request_manifest_hash": run.request_manifest_hash,
            **{field: evidence[field] for field in PROVIDER_FIELDS},
            "unavailable_fields": evidence["unavailable_fields"],
            "started_at": run.started_at.astimezone(UTC).isoformat(timespec="microseconds"),
            "finished_at": run.finished_at.astimezone(UTC).isoformat(timespec="microseconds"),
            "terminal_status": run.status,
            "failure_code": run.failure_reason or None,
            "terminal_event_sha256": event_hash,
        }
    )


@transaction.atomic
def _record_failure(attempt_id, failure):
    attempt = (
        HistoricalDiscoveryAttempt.objects.select_for_update()
        .select_related("chunk__instrument")
        .get(pk=attempt_id)
    )
    run = IngestionRun.objects.select_for_update().get(pk=attempt.ingestion_run_id)
    if run.status != IngestionRun.Status.RUNNING:
        raise DatasetQualityError("discovery failure requires a running attempt")
    evidence = _safe_provider_evidence(attempt.chunk, failure.provider_evidence)
    occurred_at = timezone.now()
    event_body = _terminal_event_body(
        attempt,
        code=failure.error_code,
        stage=failure.stage,
        evidence=evidence,
        diagnostics=failure.diagnostics,
        occurred_at=occurred_at,
    )
    event_hash = canonical_hash(event_body)
    run.status = IngestionRun.Status.FAILED
    run.failure_reason = failure.error_code
    run.fetched_count = failure.fetched_count
    run.stored_count = 0
    run.rejected_count = failure.fetched_count
    run.finished_at = occurred_at
    run.save()
    HistoricalDiscoveryProviderEvidence.objects.create(
        attempt=attempt,
        endpoint_identity=evidence["endpoint_identity"],
        http_method=evidence["http_method"],
        environment=evidence["environment"],
        http_status=evidence["http_status"],
        provider_request_id=evidence["provider_request_id"],
        canonical_request_sha256=evidence["canonical_request_sha256"],
        unavailable_fields=evidence["unavailable_fields"],
        terminal_event_sha256=event_hash,
        operational_evidence_sha256=_operational_hash(attempt, run, evidence, event_hash),
    )
    AuditEvent.objects.create(
        event_type="market.historical_discovery_failed",
        actor="market.historical_discovery.run_discovery_chunk",
        subject_type="HistoricalDiscoveryAttempt",
        subject_id=str(attempt.pk),
        payload={**event_body, "event_sha256": event_hash},
    )


@transaction.atomic
def _record_success(attempt_id, observations, evidence):
    attempt = (
        HistoricalDiscoveryAttempt.objects.select_for_update()
        .select_related("chunk__instrument")
        .get(pk=attempt_id)
    )
    run = IngestionRun.objects.select_for_update().get(pk=attempt.ingestion_run_id)
    if run.status != IngestionRun.Status.RUNNING:
        raise DatasetQualityError("discovery success requires a running attempt")
    timestamp_hash, structural_hash, semantic_hash = semantic_inventory_hashes(
        attempt.chunk, observations
    )
    try:
        inventory = HistoricalTimestampInventory.objects.create(
            chunk=attempt.chunk,
            accepted_attempt=attempt,
            observation_count=len(observations),
            timestamp_set_sha256=timestamp_hash,
            structural_observation_sha256=structural_hash,
            semantic_inventory_sha256=semantic_hash,
        )
    except Exception:
        raise DiscoveryPersistenceError("inventory") from None
    try:
        HistoricalTimestampObservation.objects.bulk_create(
            [
                HistoricalTimestampObservation(inventory=inventory, **asdict(item))
                for item in observations
            ]
        )
    except Exception:
        raise DiscoveryPersistenceError("observations") from None
    occurred_at = timezone.now()
    event_body = _terminal_event_body(
        attempt,
        code=None,
        stage="complete",
        evidence=evidence,
        diagnostics={
            "observation_count": len(observations),
            "semantic_inventory_sha256": semantic_hash,
        },
        occurred_at=occurred_at,
    )
    event_hash = canonical_hash(event_body)
    run.status = IngestionRun.Status.SUCCEEDED
    run.fetched_count = len(observations)
    run.stored_count = len(observations)
    run.rejected_count = 0
    run.finished_at = occurred_at
    try:
        run.save()
    except Exception:
        raise DiscoveryPersistenceError("run") from None
    try:
        HistoricalDiscoveryProviderEvidence.objects.create(
            attempt=attempt,
            endpoint_identity=evidence["endpoint_identity"],
            http_method=evidence["http_method"],
            environment=evidence["environment"],
            http_status=evidence["http_status"],
            provider_request_id=evidence["provider_request_id"],
            canonical_request_sha256=evidence["canonical_request_sha256"],
            unavailable_fields=evidence["unavailable_fields"],
            terminal_event_sha256=event_hash,
            operational_evidence_sha256=_operational_hash(attempt, run, evidence, event_hash),
        )
    except Exception:
        raise DiscoveryPersistenceError("provider_evidence") from None
    try:
        AuditEvent.objects.create(
            event_type="market.historical_discovery_succeeded",
            actor="market.historical_discovery.run_discovery_chunk",
            subject_type="HistoricalDiscoveryAttempt",
            subject_id=str(attempt.pk),
            payload={**event_body, "event_sha256": event_hash},
        )
    except Exception:
        raise DiscoveryPersistenceError("audit_event") from None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SET CONSTRAINTS market_discovery_inventory_reconstruct, "
                "market_discovery_provider_validate, market_discovery_run_terminal IMMEDIATE"
            )
            cursor.execute(
                "SET CONSTRAINTS market_discovery_inventory_reconstruct, "
                "market_discovery_provider_validate, market_discovery_run_terminal DEFERRED"
            )
    except Exception:
        raise DiscoveryPersistenceError("database_constraints") from None
    attempt.ingestion_run = run
    return attempt


def _classify_failure(error, chunk):
    if isinstance(error, DiscoveryResponseError):
        return error
    if isinstance(error, OandaError):
        if error.failure_kind == "limit":
            return DiscoveryResponseError(
                "historical discovery provider limit suspected",
                DiscoveryFailureCode.PROVIDER_LIMIT_SUSPECTED,
                "response_validation",
                {"observation_count": 0},
                _safe_provider_evidence(chunk, error.provider_evidence),
            )
        code = {
            "auth": DiscoveryFailureCode.PROVIDER_AUTH_ERROR,
            "http": DiscoveryFailureCode.PROVIDER_HTTP_ERROR,
            "malformed": DiscoveryFailureCode.PROVIDER_RESPONSE_MALFORMED,
        }.get(error.failure_kind, DiscoveryFailureCode.UNKNOWN_FAILURE)
        return DiscoveryResponseError(
            "historical discovery provider request failed",
            code,
            "provider_request",
            {},
            _safe_provider_evidence(chunk, error.provider_evidence),
        )
    return DiscoveryResponseError(
        "historical discovery failed",
        DiscoveryFailureCode.UNKNOWN_FAILURE,
        "provider_request",
        {},
        _safe_provider_evidence(chunk, {}),
    )


def run_discovery_chunk(logical_key, client):
    attempt = begin_discovery_attempt(logical_key)
    try:
        observations, provider_evidence = client.fetch_historical_inventory(
            attempt.chunk.instrument.code,
            attempt.chunk.granularity,
            attempt.chunk.requested_from,
            attempt.chunk.requested_to,
        )
        observations, provider_evidence = _validate_response(
            attempt.chunk, observations, provider_evidence
        )
    except Exception as error:
        _record_failure(attempt.pk, _classify_failure(error, attempt.chunk))
        raise
    try:
        return _record_success(attempt.pk, observations, provider_evidence)
    except (DiscoveryPersistenceError, DatabaseError) as error:
        component = (
            error.component
            if isinstance(error, DiscoveryPersistenceError)
            else "database_constraints"
        )
        failure = DiscoveryResponseError(
            "historical discovery persistence failed",
            DiscoveryFailureCode.PERSISTENCE_FAILED,
            "persistence",
            {"component": component},
            provider_evidence,
            len(observations),
        )
        try:
            _record_failure(attempt.pk, failure)
        except Exception:
            pass
        raise


@transaction.atomic
def resolve_stale_discovery_attempt(attempt_id, stale_threshold, reason):
    if not isinstance(stale_threshold, timedelta) or stale_threshold <= timedelta(0):
        raise ValueError("stale threshold must be a positive timedelta")
    if not isinstance(reason, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", reason):
        raise ValueError("stale reason must be a bounded stable code")
    attempt = (
        HistoricalDiscoveryAttempt.objects.select_for_update()
        .select_related("chunk__plan", "chunk__instrument")
        .get(pk=attempt_id)
    )
    HistoricalDiscoveryChunk.objects.select_for_update().get(pk=attempt.chunk_id)
    run = IngestionRun.objects.select_for_update().get(pk=attempt.ingestion_run_id)
    if attempt.chunk.plan.sealed_at is not None or run.status != IngestionRun.Status.RUNNING:
        raise DatasetQualityError("stale resolution requires an unsealed running attempt")
    if run.started_at > timezone.now() - stale_threshold:
        raise DatasetQualityError("discovery attempt is not stale")
    failure = DiscoveryResponseError(
        "discovery attempt was explicitly resolved as stale",
        DiscoveryFailureCode.STALE_ATTEMPT,
        "stale_resolution",
        {
            "reason": reason,
            "stale_threshold_seconds": int(stale_threshold.total_seconds()),
        },
        _safe_provider_evidence(
            attempt.chunk,
            {
                "endpoint_identity": (
                    "oanda-v20-practice:GET:/v3/instruments/"
                    f"{attempt.chunk.instrument.code}/candles"
                ),
                "http_method": "GET",
                "oanda_environment": "practice",
                "canonical_request_sha256": attempt.chunk.canonical_request_sha256,
            },
        ),
    )
    _record_failure(attempt.pk, failure)
    return HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").get(pk=attempt.pk)


def _registration_hashes(plan):
    chunks = list(plan.chunks.select_related("inventory").order_by("ordinal"))
    if len(chunks) != plan.declared_chunk_count:
        raise DatasetQualityError("discovery plan does not contain its declared request count")
    expected_manifest = [
        {
            "ordinal": item.ordinal,
            "logical_discovery_key": item.logical_key,
            "canonical_request": item.canonical_request,
            "canonical_request_sha256": item.canonical_request_sha256,
        }
        for item in chunks
    ]
    if expected_manifest != plan.canonical_request_manifest:
        raise DatasetQualityError("discovery chunks do not equal the declared request manifest")
    if any(
        item.attempts.filter(ingestion_run__status=IngestionRun.Status.RUNNING).exists()
        for item in chunks
    ):
        raise DatasetQualityError("running discovery attempts prevent sealing")
    try:
        semantic_rows = [
            {
                "logical_discovery_key": item.logical_key,
                "semantic_inventory_sha256": item.inventory.semantic_inventory_sha256,
            }
            for item in chunks
        ]
    except HistoricalTimestampInventory.DoesNotExist as error:
        raise DatasetQualityError("every discovery chunk requires an accepted inventory") from error
    attempts = (
        HistoricalDiscoveryAttempt.objects.filter(chunk__plan=plan)
        .select_related("chunk", "provider_evidence")
        .order_by("chunk__ordinal", "attempt_number")
    )
    if not attempts.exists() or any(
        item.ingestion_run.status == IngestionRun.Status.RUNNING for item in attempts
    ):
        raise DatasetQualityError("discovery operational ledger is incomplete")
    try:
        operational_rows = [item.provider_evidence.operational_evidence_sha256 for item in attempts]
    except HistoricalDiscoveryProviderEvidence.DoesNotExist as error:
        raise DatasetQualityError("terminal discovery attempt lacks provider evidence") from error
    return (
        canonical_hash(expected_manifest),
        canonical_hash(semantic_rows),
        canonical_hash(operational_rows),
    )


@transaction.atomic
def approve_and_register_discovery(plan_sha256, approver_id, cross_series_report_sha256):
    plan = HistoricalDiscoveryPlan.objects.select_for_update().get(sha256=plan_sha256)
    list(plan.chunks.select_for_update().values_list("pk", flat=True))
    list(
        HistoricalDiscoveryAttempt.objects.select_for_update()
        .filter(chunk__plan=plan)
        .values_list("pk", flat=True)
    )
    list(
        HistoricalTimestampInventory.objects.select_for_update()
        .filter(chunk__plan=plan)
        .values_list("pk", flat=True)
    )
    if plan.sealed_at is not None:
        raise DatasetQualityError("discovery plan is already sealed")
    if HistoricalDiscoverySupersession.objects.filter(superseded_plan=plan).exists():
        raise DatasetQualityError("superseded discovery plans cannot be approved")
    if HistoricalDiscoverySupersession.objects.filter(replacement_plan=plan).exists():
        raise DatasetQualityError(
            "supersession replacement plans reject approval until governed activation"
        )
    approver = get_user_model().objects.select_for_update().get(pk=approver_id)
    if not approver.is_active or not approver.has_perm("market.approve_historical_discovery"):
        raise PermissionDenied("active governed discovery approval permission is required")
    if not re.fullmatch(r"[0-9a-f]{64}", cross_series_report_sha256):
        raise ValueError("cross-series report SHA-256 is invalid")
    chunk_hash, semantic_hash, operational_hash = _registration_hashes(plan)
    now = timezone.now()
    approval_payload = {
        "identity": DISCOVERY_APPROVAL_IDENTITY,
        "plan_sha256": plan.sha256,
        "global_semantic_inventory_sha256": semantic_hash,
        "accepted_operational_evidence_set_sha256": operational_hash,
        "cross_series_report_sha256": cross_series_report_sha256,
        "approved_by": approver.get_username(),
        "approved_at": now.astimezone(UTC).isoformat(timespec="microseconds"),
    }
    approval = HistoricalDiscoveryApproval.objects.create(
        plan=plan,
        approved_by=approver,
        global_semantic_inventory_sha256=semantic_hash,
        accepted_operational_evidence_set_sha256=operational_hash,
        payload=approval_payload,
        sha256=canonical_hash(approval_payload),
        approved_at=now,
    )
    registration_payload = {
        "plan_sha256": plan.sha256,
        "approval_sha256": approval.sha256,
        "ordered_chunk_manifest_sha256": chunk_hash,
        "global_semantic_inventory_sha256": semantic_hash,
        "accepted_operational_evidence_set_sha256": operational_hash,
        "cross_series_report_sha256": cross_series_report_sha256,
        "registered_at": now.astimezone(UTC).isoformat(timespec="microseconds"),
    }
    registration = HistoricalDiscoveryRegistration.objects.create(
        plan=plan,
        approval=approval,
        ordered_chunk_manifest_sha256=chunk_hash,
        global_semantic_inventory_sha256=semantic_hash,
        accepted_operational_evidence_set_sha256=operational_hash,
        cross_series_report_sha256=cross_series_report_sha256,
        payload=registration_payload,
        report_sha256=canonical_hash(registration_payload),
        registered_at=now,
    )
    HistoricalDiscoveryPlan.objects.filter(pk=plan.pk, sealed_at__isnull=True).update(sealed_at=now)
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    plan.sealed_at = now
    return registration


@transaction.atomic
def supersede_discovery_plan(
    superseded_plan_sha256,
    replacement_plan_sha256,
    governing_attempt_id,
    reason_code=HistoricalDiscoverySupersession.REASON_PROVIDER_REQUEST_BOUND_UNSAFE,
):
    plans = {
        item.sha256: item
        for item in HistoricalDiscoveryPlan.objects.select_for_update().filter(
            sha256__in=(superseded_plan_sha256, replacement_plan_sha256)
        )
    }
    if len(plans) != 2:
        raise DatasetQualityError("supersession requires two distinct discovery plans")
    superseded_plan = plans[superseded_plan_sha256]
    replacement_plan = plans[replacement_plan_sha256]
    attempt = (
        HistoricalDiscoveryAttempt.objects.select_for_update()
        .select_related("chunk", "ingestion_run")
        .get(pk=governing_attempt_id)
    )
    run = attempt.ingestion_run
    evidence = HistoricalDiscoveryProviderEvidence.objects.select_for_update().get(attempt=attempt)
    event = AuditEvent.objects.select_for_update().get(
        subject_type="HistoricalDiscoveryAttempt",
        subject_id=str(attempt.pk),
        event_type="market.historical_discovery_failed",
    )
    try:
        superseded_version = int(superseded_plan.version.rsplit("v", 1)[1])
        replacement_version = int(replacement_plan.version.rsplit("v", 1)[1])
    except (IndexError, ValueError) as error:
        raise DatasetQualityError("discovery supersession versions are invalid") from error
    if (
        reason_code != HistoricalDiscoverySupersession.REASON_PROVIDER_REQUEST_BOUND_UNSAFE
        or superseded_plan.pk == replacement_plan.pk
        or superseded_plan.sealed_at is not None
        or replacement_plan.sealed_at is not None
        or superseded_plan.version != DISCOVERY_VERSION
        or superseded_plan.identity != DISCOVERY_PLAN_IDENTITY
        or superseded_plan.sha256 != DISCOVERY_V1_PLAN_SHA256
        or canonical_hash(superseded_plan.payload) != DISCOVERY_V1_PLAN_SHA256
        or superseded_plan.canonical_request_manifest_sha256 != DISCOVERY_V1_MANIFEST_SHA256
        or canonical_hash(superseded_plan.payload["requests"]) != DISCOVERY_V1_MANIFEST_SHA256
        or replacement_plan.version != DISCOVERY_V2_VERSION
        or replacement_plan.identity != DISCOVERY_V2_PLAN_IDENTITY
        or replacement_plan.sha256 != DISCOVERY_V2_PLAN_SHA256
        or canonical_hash(replacement_plan.payload) != DISCOVERY_V2_PLAN_SHA256
        or replacement_plan.canonical_request_manifest_sha256 != DISCOVERY_V2_MANIFEST_SHA256
        or canonical_hash(replacement_plan.payload["requests"]) != DISCOVERY_V2_MANIFEST_SHA256
        or attempt.chunk.plan_id != superseded_plan.pk
        or attempt.chunk.logical_key != GOVERNING_CANARY_LOGICAL_KEY
        or attempt.chunk.canonical_request_sha256 != GOVERNING_CANARY_REQUEST_SHA256
        or attempt.attempt_number != GOVERNING_CANARY_ATTEMPT_NUMBER
        or attempt.idempotency_key != GOVERNING_CANARY_IDEMPOTENCY_KEY
        or run.status != IngestionRun.Status.FAILED
        or run.failure_reason != DiscoveryFailureCode.PROVIDER_HTTP_ERROR
        or replacement_version <= superseded_version
        or superseded_plan.payload["discovery_contract"]
        != replacement_plan.payload["discovery_contract"]
        or HistoricalDiscoveryAttempt.objects.filter(chunk__plan=replacement_plan).exists()
    ):
        raise DatasetQualityError("discovery supersession lineage is invalid")
    payload = {
        "identity": "historical-discovery-supersession-v1",
        "reason_code": reason_code,
        "superseded_plan_sha256": superseded_plan.sha256,
        "superseded_request_manifest_sha256": (superseded_plan.canonical_request_manifest_sha256),
        "replacement_plan_sha256": replacement_plan.sha256,
        "replacement_request_manifest_sha256": (replacement_plan.canonical_request_manifest_sha256),
        "governing_attempt_idempotency_key": attempt.idempotency_key,
        "governing_run_request_manifest_hash": run.request_manifest_hash,
        "governing_failure_code": run.failure_reason,
        "governing_terminal_event_sha256": evidence.terminal_event_sha256,
        "governing_operational_evidence_sha256": evidence.operational_evidence_sha256,
        "governing_audit_event_sha256": event.payload["event_sha256"],
    }
    return HistoricalDiscoverySupersession.objects.create(
        superseded_plan=superseded_plan,
        replacement_plan=replacement_plan,
        governing_attempt=attempt,
        reason_code=reason_code,
        superseded_plan_sha256=superseded_plan.sha256,
        replacement_plan_sha256=replacement_plan.sha256,
        governing_terminal_event_sha256=evidence.terminal_event_sha256,
        governing_operational_evidence_sha256=evidence.operational_evidence_sha256,
        payload=payload,
        sha256=canonical_hash(payload),
    )
