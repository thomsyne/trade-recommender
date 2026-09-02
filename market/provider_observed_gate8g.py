"""Gate 8G successor acquisition readiness and governed manifest.

Everything up to :func:`successor_gate8g_readiness` is deterministic artifact
handling.  Readiness itself is read-only: it neither constructs a provider
client nor writes a database row.  The predecessor Gate 7B implementation is
deliberately not imported or modified.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from market.historical_discovery import canonical_hash, canonical_timestamp
from market.provider_observed_acquisition import replacement_chunk_logical_key
from market.provider_observed_gate8e import (
    SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY,
    SUCCESSOR_ACQUISITION_PLAN_SHA256,
    SUCCESSOR_CONTRACT_SHA256,
    SUCCESSOR_DATA_IDENTITY,
    SUCCESSOR_DATASET_MANIFEST_SHA256,
    SUCCESSOR_DATASET_VERSION,
)
from market.provider_observed_outcome import load_committed_gate8d3_outcome

ARTIFACT_SCHEMA = "phase-2b1r-gate8f-successor-canary-outcome-v1"
ARTIFACT_NAME = "phase-2b1r-gate8f-successor-canary-outcome.json"
ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "strategy"
    / "failed-break"
    / "v1"
    / ARTIFACT_NAME
)

# Filled only with the SHA-256 of the canonical committed bytes.  Callers may
# neither supply nor override this pin.
GATE8F_OUTCOME_ARTIFACT_SHA256 = "2bc4db198c720f5d9b35b737d2cd2703688b86f4da68f88eba61f3b6932d1548"

SUCCESSOR_DISCOVERY_PLAN_SHA256 = "e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88"
SUCCESSOR_DISCOVERY_REQUEST_MANIFEST_SHA256 = (
    "6d31a7aee0866c1e4b2479a78816594769005eaa759714c93dea39d55fddbea0"
)
SUCCESSOR_GLOBAL_SEMANTIC_INVENTORY_SHA256 = (
    "f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427"
)

CANARY_CANONICAL_REQUEST_SHA256 = "9be615659265307cceecee27a19274013c897484613627115d7687558e618f38"
CANARY_TIMESTAMP_SET_SHA256 = "9b5dfc0d283aef1031e486f8683d56b6754ef0424942aaef8648735e15eb45b0"
CANARY_STRUCTURAL_INVENTORY_SHA256 = (
    "56f8931d6dae301608e0d01a6378928e30703ba17acf8a6dc7ba3c5188f74be5"
)
CANARY_SEMANTIC_INVENTORY_SHA256 = (
    "3c7eecdc1842d16d2629a13284ef47d2da4b25a00320e99c80acaff2c98ee923"
)
CANARY_INGESTION_MANIFEST_SHA256 = (
    "1d3560139fc76de23f6aba31e943b6289e915f937c1d23128aa95b2077692be7"
)
CANARY_CANDLE_KEY_SHA256 = "4603365940d1c75951f640eca8e36b72cfe5c9456f9d1291b2cb2a065f5ca72d"
CANARY_CANDLE_PAYLOAD_SHA256 = "2f9ff07b605778de0d9d8926d0ba6e3c60a53d49efd78b8e3ef049223349413c"
CANARY_TERMINAL_EVENT_SHA256 = "c19ecdb2a260b6339287399e6ea8b85335b39d389ad26f76e602586eeb14d3a2"
CANARY_OPERATIONAL_EVIDENCE_SHA256 = (
    "2a329006323c4fc51856aff9fcf97528efcca42b6aa2e75e711865776aeed7fb"
)
CANARY_EXPECTED_CANDLES = 2891
SUCCESSOR_CHUNK_COUNT = 132
GATE8G_CHUNK_COUNT = 131
GATE8G_EXPECTED_CANDLES = 362164
GATE8G_ORDERED_MANIFEST_SHA256 = "2cd63cf9ee79d3af107cd08952dc367aa4af6d2b07aa7c487b968b5f29eeef87"

RUN_SUCCESS_EVENT_TYPE = "market.ingestion_succeeded"
ACQUISITION_SUCCESS_EVENT_TYPE = "market.replacement_acquisition_succeeded"
ACQUISITION_FAILURE_EVENT_TYPE = "market.historical_ingestion_failed"


def _successor_chunk_manifest():
    """Reconstruct all successor keys from the accepted discovery artifact."""
    records = load_committed_gate8d3_outcome()["chunk_records"]
    chunks = []
    for record in records:
        chunk = {
            "ordinal": record["ordinal"],
            "instrument": record["instrument"],
            "granularity": record["granularity"],
            "requested_from": record["requested_from"],
            "requested_to": record["requested_to"],
            "canonical_request_sha256": record["canonical_request_sha256"],
            "semantic_inventory_sha256": record["semantic_inventory_sha256"],
            "expected_observation_count": record["observation_count"],
        }
        chunk["logical_key"] = replacement_chunk_logical_key(
            replacement_plan_sha256=SUCCESSOR_ACQUISITION_PLAN_SHA256,
            replacement_dataset_manifest_sha256=SUCCESSOR_DATASET_MANIFEST_SHA256,
            semantic_inventory_sha256=chunk["semantic_inventory_sha256"],
            canonical_request_sha256=chunk["canonical_request_sha256"],
        )
        chunks.append(chunk)
    if len(chunks) != SUCCESSOR_CHUNK_COUNT or [row["ordinal"] for row in chunks] != list(
        range(1, SUCCESSOR_CHUNK_COUNT + 1)
    ):
        raise ValueError("accepted successor outcome does not define ordered 132-chunk coverage")
    if chunks[0]["logical_key"] != SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY:
        raise ValueError("accepted successor ordinal 1 is not the Gate 8F canary")
    return chunks


def build_gate8f_outcome():
    """Build the canonical runtime authorization record from accepted artifacts."""
    chunks = _successor_chunk_manifest()
    canary = chunks[0]
    remaining = chunks[1:]
    if (
        canary["canonical_request_sha256"] != CANARY_CANONICAL_REQUEST_SHA256
        or canary["semantic_inventory_sha256"] != CANARY_SEMANTIC_INVENTORY_SHA256
        or canary["expected_observation_count"] != CANARY_EXPECTED_CANDLES
        or len(remaining) != GATE8G_CHUNK_COUNT
        or sum(item["expected_observation_count"] for item in remaining) != GATE8G_EXPECTED_CANDLES
        or canonical_hash(remaining) != GATE8G_ORDERED_MANIFEST_SHA256
    ):
        raise ValueError("Gate 8F outcome does not reconstruct the governed Gate 8G manifest")
    body = {
        "schema": ARTIFACT_SCHEMA,
        "successor": {
            "data_identity": SUCCESSOR_DATA_IDENTITY,
            "data_contract_sha256": SUCCESSOR_CONTRACT_SHA256,
            "acquisition_plan_sha256": SUCCESSOR_ACQUISITION_PLAN_SHA256,
            "dataset_manifest_sha256": SUCCESSOR_DATASET_MANIFEST_SHA256,
            "dataset_version": SUCCESSOR_DATASET_VERSION,
            "discovery_plan_sha256": SUCCESSOR_DISCOVERY_PLAN_SHA256,
            "discovery_request_manifest_sha256": SUCCESSOR_DISCOVERY_REQUEST_MANIFEST_SHA256,
            "global_semantic_inventory_sha256": SUCCESSOR_GLOBAL_SEMANTIC_INVENTORY_SHA256,
        },
        "accepted_canary": {
            **canary,
            "attempt_number": 1,
            "run_status": "succeeded",
            "fetched_candle_count": CANARY_EXPECTED_CANDLES,
            "stored_candle_count": CANARY_EXPECTED_CANDLES,
            "rejected_candle_count": 0,
            "timestamp_set_sha256": CANARY_TIMESTAMP_SET_SHA256,
            "structural_inventory_sha256": CANARY_STRUCTURAL_INVENTORY_SHA256,
            "ingestion_manifest_sha256": CANARY_INGESTION_MANIFEST_SHA256,
            "candle_key_sha256": CANARY_CANDLE_KEY_SHA256,
            "candle_payload_sha256": CANARY_CANDLE_PAYLOAD_SHA256,
            "terminal_event_sha256": CANARY_TERMINAL_EVENT_SHA256,
            "operational_evidence_sha256": CANARY_OPERATIONAL_EVIDENCE_SHA256,
            "permanently_closed": True,
        },
        "gate8g": {
            "chunk_count": GATE8G_CHUNK_COUNT,
            "expected_candle_count": GATE8G_EXPECTED_CANDLES,
            "ordered_manifest_sha256": GATE8G_ORDERED_MANIFEST_SHA256,
            "chunks": remaining,
        },
        "execution_semantics": {
            "attempt_number": 1,
            "maximum_attempts_per_chunk": 1,
            "retry": False,
            "sequential": True,
            "stop_on_first_failure": True,
            "explicit_execute_required": True,
        },
    }
    return {**body, "outcome_sha256": canonical_hash(body)}


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def load_committed_gate8f_outcome():
    """Load only canonical bytes matching the code pin and deterministic build."""
    try:
        committed = ARTIFACT_PATH.read_bytes()
    except OSError as error:
        raise ValueError(f"committed artifact {ARTIFACT_NAME} cannot be read") from error
    if hashlib.sha256(committed).hexdigest() != GATE8F_OUTCOME_ARTIFACT_SHA256:
        raise ValueError(f"committed artifact {ARTIFACT_NAME} does not match its governed pin")
    try:
        document = json.loads(committed)
    except ValueError as error:
        raise ValueError(f"committed artifact {ARTIFACT_NAME} is not valid JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"committed artifact {ARTIFACT_NAME} is not a JSON object")
    claimed = document.get("outcome_sha256")
    body = {key: value for key, value in document.items() if key != "outcome_sha256"}
    if not isinstance(claimed, str) or claimed != canonical_hash(body):
        raise ValueError(f"committed artifact {ARTIFACT_NAME} self-hash does not verify")
    if committed != _canonical_bytes(document):
        raise ValueError(f"committed artifact {ARTIFACT_NAME} is not canonical JSON")
    if committed != _canonical_bytes(build_gate8f_outcome()):
        raise ValueError(f"committed artifact {ARTIFACT_NAME} does not reconstruct")
    return document


@dataclass(frozen=True)
class Gate8GReadiness:
    canary_permanently_closed: bool
    ready_keys: tuple[str, ...]
    complete: bool
    blocked_reason: str | None
    manifest_sha256: str


def evaluate_gate8g_readiness(*, artifact, attempt_states, canary_valid, registered=False):
    """Pure state transition used by the database adapter and focused tests.

    ``attempt_states`` maps governed logical keys to zero or more read-only
    snapshots with ``attempt_number``, ``idempotency_key``, ``status`` and
    ``accepted_manifest`` fields.
    """
    ordered = [artifact["accepted_canary"], *artifact["gate8g"]["chunks"]]
    expected_keys = [entry["logical_key"] for entry in ordered]
    if set(attempt_states) - set(expected_keys):
        return Gate8GReadiness(
            True, (), False, "unexpected successor chunk state", GATE8G_ORDERED_MANIFEST_SHA256
        )
    if not canary_valid:
        return Gate8GReadiness(
            True,
            (),
            False,
            "Gate 8F canary evidence is absent or altered",
            GATE8G_ORDERED_MANIFEST_SHA256,
        )

    pending = []
    succeeded = 0
    for entry in ordered:
        states = attempt_states.get(entry["logical_key"], ())
        if not states:
            if entry["logical_key"] == SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY:
                return Gate8GReadiness(
                    True, (), False, "Gate 8F canary is absent", GATE8G_ORDERED_MANIFEST_SHA256
                )
            pending.append(entry["logical_key"])
            continue
        if len(states) != 1:
            return Gate8GReadiness(
                True,
                (),
                False,
                "successor attempt count is not one",
                GATE8G_ORDERED_MANIFEST_SHA256,
            )
        state = states[0]
        expected_idempotency = f"failed-break-ingestion-attempt:{entry['logical_key']}:1"
        if state["attempt_number"] != 1 or state["idempotency_key"] != expected_idempotency:
            return Gate8GReadiness(
                True,
                (),
                False,
                "successor attempt is not canonical attempt 1",
                GATE8G_ORDERED_MANIFEST_SHA256,
            )
        if state["status"] == "running":
            return Gate8GReadiness(
                True, (), False, "a successor attempt is running", GATE8G_ORDERED_MANIFEST_SHA256
            )
        if state["status"] != "succeeded":
            return Gate8GReadiness(
                True, (), False, "a successor attempt failed", GATE8G_ORDERED_MANIFEST_SHA256
            )
        if not state["accepted_manifest"]:
            return Gate8GReadiness(
                True,
                (),
                False,
                "a successor success lacks accepted evidence",
                GATE8G_ORDERED_MANIFEST_SHA256,
            )
        succeeded += 1
    complete = succeeded == SUCCESSOR_CHUNK_COUNT and not pending
    return Gate8GReadiness(
        True,
        () if registered or complete else tuple(pending),
        complete,
        "successor dataset is registered" if registered else None,
        GATE8G_ORDERED_MANIFEST_SHA256,
    )


def _candle_hashes_and_membership(chunk, run):
    from market.models import Candle

    sealed = list(
        chunk.discovery_inventory.observations.order_by("timestamp").values_list(
            "timestamp", "volume", "complete"
        )
    )
    candles = list(
        Candle.objects.filter(ingestion_run=run, dataset_version=chunk.dataset_version)
        .select_related("instrument")
        .order_by("timestamp")
    )
    if [(row.timestamp, row.volume, row.complete) for row in candles] != sealed:
        return None
    key_hash = hashlib.sha256()
    payload_hash = hashlib.sha256()
    for row in candles:
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
        key_hash.update(json.dumps(key, separators=(",", ":")).encode())
        payload_hash.update(json.dumps(payload, separators=(",", ":")).encode())
    return key_hash.hexdigest(), payload_hash.hexdigest(), len(candles)


def _accepted_attempt_success(chunk, attempt, expected, *, canary):
    from market.historical_acquisition import stable_hash
    from market.models import AuditEvent, IngestionManifest

    run = attempt.ingestion_run
    if (
        attempt.attempt_number != 1
        or attempt.idempotency_key != f"failed-break-ingestion-attempt:{chunk.logical_key}:1"
        or run.status != "succeeded"
        or run.fetched_count != expected["expected_observation_count"]
        or run.stored_count != expected["expected_observation_count"]
        or run.rejected_count != 0
        or run.finished_at is None
    ):
        return False
    manifests = list(IngestionManifest.objects.filter(ingestion_run=run))
    if len(manifests) != 1 or manifests[0].sha256 != stable_hash(manifests[0].payload):
        return False
    if canary and manifests[0].sha256 != CANARY_INGESTION_MANIFEST_SHA256:
        return False
    hashes = _candle_hashes_and_membership(chunk, run)
    if hashes is None or hashes[2] != expected["expected_observation_count"]:
        return False
    if canary and hashes[:2] != (CANARY_CANDLE_KEY_SHA256, CANARY_CANDLE_PAYLOAD_SHA256):
        return False
    evidence = list(
        AuditEvent.objects.filter(
            event_type=ACQUISITION_SUCCESS_EVENT_TYPE,
            subject_type="HistoricalIngestionAttempt",
            subject_id=str(attempt.pk),
        )
    )
    if len(evidence) != 1:
        return False
    payload = evidence[0].payload
    terminal = {
        key: value
        for key, value in payload.items()
        if key
        not in (
            "schema_version",
            "provider_evidence",
            "terminal_event_sha256",
            "operational_evidence_sha256",
        )
    }
    if (
        payload.get("logical_key") != chunk.logical_key
        or payload.get("ingestion_manifest_sha256") != manifests[0].sha256
        or payload.get("candle_key_hash") != hashes[0]
        or payload.get("candle_payload_hash") != hashes[1]
        or payload.get("terminal_event_sha256") != stable_hash(terminal)
        or payload.get("operational_evidence_sha256")
        != stable_hash(
            [
                payload.get("terminal_event_sha256"),
                payload.get("provider_evidence"),
                attempt.idempotency_key,
            ]
        )
    ):
        return False
    if canary and (
        payload.get("terminal_event_sha256") != CANARY_TERMINAL_EVENT_SHA256
        or payload.get("operational_evidence_sha256") != CANARY_OPERATIONAL_EVIDENCE_SHA256
    ):
        return False
    return (
        AuditEvent.objects.filter(
            event_type=RUN_SUCCESS_EVENT_TYPE,
            subject_type="IngestionRun",
            subject_id=str(run.pk),
        ).count()
        == 1
        and not AuditEvent.objects.filter(
            event_type=ACQUISITION_FAILURE_EVENT_TYPE,
            subject_type="HistoricalIngestionAttempt",
            subject_id=str(attempt.pk),
        ).exists()
    )


def _resolve_successor_chunks(artifact):
    from market.models import HistoricalDatasetPlan
    from market.services import DatasetQualityError

    plans = list(
        HistoricalDatasetPlan.objects.filter(
            sha256=SUCCESSOR_ACQUISITION_PLAN_SHA256
        ).select_related("data_contract")
    )
    if len(plans) != 1:
        raise DatasetQualityError("Gate 8G requires the exact successor acquisition plan")
    plan = plans[0]
    chunks = list(
        plan.chunks.select_related("instrument", "dataset_version", "discovery_inventory").order_by(
            "created_at", "id"
        )
    )
    expected = [artifact["accepted_canary"], *artifact["gate8g"]["chunks"]]
    if (
        plan.identity != SUCCESSOR_DATA_IDENTITY
        or plan.data_contract is None
        or plan.data_contract.sha256 != SUCCESSOR_CONTRACT_SHA256
        or len(chunks) != SUCCESSOR_CHUNK_COUNT
    ):
        raise DatasetQualityError("Gate 8G successor plan lineage does not reconstruct")
    by_key = {chunk.logical_key: chunk for chunk in chunks}
    if len(by_key) != SUCCESSOR_CHUNK_COUNT or set(by_key) != {
        item["logical_key"] for item in expected
    }:
        raise DatasetQualityError("Gate 8G successor chunk membership does not reconstruct")
    ordered = []
    for item in expected:
        chunk = by_key[item["logical_key"]]
        if (
            chunk.instrument.code != item["instrument"]
            or chunk.granularity != item["granularity"]
            or canonical_timestamp(chunk.requested_from) != item["requested_from"]
            or canonical_timestamp(chunk.requested_to) != item["requested_to"]
            or chunk.canonical_request_sha256 != item["canonical_request_sha256"]
            or chunk.semantic_inventory_sha256 != item["semantic_inventory_sha256"]
            or chunk.expected_observation_count != item["expected_observation_count"]
            or chunk.data_contract_sha256 != SUCCESSOR_CONTRACT_SHA256
            or chunk.dataset_version.manifest_sha256 != SUCCESSOR_DATASET_MANIFEST_SHA256
            or chunk.dataset_version.version != SUCCESSOR_DATASET_VERSION
            or (
                chunk.logical_key == SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY
                and (
                    chunk.discovery_inventory.timestamp_set_sha256 != CANARY_TIMESTAMP_SET_SHA256
                    or chunk.discovery_inventory.structural_observation_sha256
                    != CANARY_STRUCTURAL_INVENTORY_SHA256
                    or chunk.discovery_inventory.semantic_inventory_sha256
                    != CANARY_SEMANTIC_INVENTORY_SHA256
                    or chunk.discovery_inventory.observation_count != CANARY_EXPECTED_CANDLES
                )
            )
        ):
            raise DatasetQualityError("Gate 8G successor chunk identity does not reconstruct")
        ordered.append((chunk, item))
    return ordered


def successor_gate8g_readiness():
    """Return successor-only Gate 8G readiness without provider or writes."""
    from market.models import DatasetRegistration
    from market.services import DatasetQualityError

    artifact = load_committed_gate8f_outcome()
    try:
        ordered = _resolve_successor_chunks(artifact)
    except DatasetQualityError as error:
        return Gate8GReadiness(True, (), False, str(error), GATE8G_ORDERED_MANIFEST_SHA256)
    attempt_states = {}
    canary_valid = False
    for chunk, expected in ordered:
        attempts = list(chunk.attempts.select_related("ingestion_run"))
        states = []
        for attempt in attempts:
            accepted = False
            if attempt.ingestion_run.status == "succeeded":
                accepted = _accepted_attempt_success(
                    chunk,
                    attempt,
                    expected,
                    canary=chunk.logical_key == SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY,
                )
            states.append(
                {
                    "attempt_number": attempt.attempt_number,
                    "idempotency_key": attempt.idempotency_key,
                    "status": attempt.ingestion_run.status,
                    "accepted_manifest": accepted,
                }
            )
        attempt_states[chunk.logical_key] = states
        if chunk.logical_key == SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY:
            canary_valid = len(states) == 1 and states[0]["accepted_manifest"]
    dataset = ordered[0][0].dataset_version
    registered = DatasetRegistration.objects.filter(dataset_version=dataset).exists()
    return evaluate_gate8g_readiness(
        artifact=artifact,
        attempt_states=attempt_states,
        canary_valid=canary_valid,
        registered=registered,
    )


def ready_gate8g_entries(readiness=None):
    """Map current ready keys back to the pinned deterministic entry order."""
    readiness = successor_gate8g_readiness() if readiness is None else readiness
    if not readiness.ready_keys:
        return []
    artifact = load_committed_gate8f_outcome()
    ready = set(readiness.ready_keys)
    return [entry for entry in artifact["gate8g"]["chunks"] if entry["logical_key"] in ready]
