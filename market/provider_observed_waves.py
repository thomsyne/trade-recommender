"""Gate 7B: bounded full replacement acquisition for the remaining 131 chunks.

Deterministic wave planning derived exclusively from the committed ordered
132-chunk manifest, plus the canonical record of the accepted Gate 7A
canary success. Nothing in this module contacts a provider or writes to a
database.
"""

import json
from pathlib import Path

from market.historical_discovery import GLOBAL_SEMANTIC_INVENTORY_SHA256, canonical_hash
from market.provider_observed_canary import (
    ACQUISITION_CANARY_EXPECTED_OBSERVATION_COUNT,
    ACQUISITION_CANARY_LOGICAL_KEY,
    ACQUISITION_CANARY_REQUEST_SHA256,
    ACQUISITION_CANARY_SEMANTIC_SHA256,
    REPLACEMENT_DATASET_MANIFEST_SHA256,
    REPLACEMENT_PLAN_SHA256,
    replacement_contract_sha256,
)

DOCS_DIR = Path("docs/strategy/failed-break/v1")
CHUNK_MANIFEST_PATH = DOCS_DIR / "phase-2b1r-gate1b-replacement-chunk-manifest.json"

# The accepted Gate 7A live-canary outcome, pinned from the independently
# reviewed evidence. Content-addressed values only: no database ids,
# operational timestamps or provider request-id values.
CANARY_SUCCESS_MANIFEST_SHA256 = "ea390f39b3837a799f5a7295f98381a3e77496fdcb906837bc29dcd8d4ba4e3c"
CANARY_SUCCESS_CANDLE_KEY_HASH = "ce00c1037570338658b7d886b9b18f8538979e753cb9ee179217a91b3516ff61"
CANARY_SUCCESS_CANDLE_PAYLOAD_HASH = (
    "4d519ad2d3634deb77dab5889ea851d6b71a56080543781f8d02d9ab58d675ff"
)
CANARY_SUCCESS_TERMINAL_EVENT_SHA256 = (
    "bbcd862d261401507b88c14e10f0e5d48b11666a2c160e47e8874c9f84183d2d"
)
CANARY_SUCCESS_OPERATIONAL_EVIDENCE_SHA256 = (
    "dc79841a04f064a94bfede1546c7ddd9d0fe550f09c2d41249b2638399778053"
)
POST_CANARY_SNAPSHOT_SHA256 = "6732693a5642a1e16251ae0b2e9c482b95015e239c5c21315ca6126648462900"

COMPLETE_DATASET_CHUNKS = 132
COMPLETE_DATASET_CANDLES = 364953
REMAINING_CHUNKS = 131
REMAINING_CANDLES = COMPLETE_DATASET_CANDLES - ACQUISITION_CANARY_EXPECTED_OBSERVATION_COUNT

WAVE_SIZES = (17, 24, 24, 24, 24, 18)
WAVE_ONE_ORDINALS = (1, 22, 23, 24, 44, 45, 46, 66, 67, 68, 88, 89, 90, 110, 111, 112, 132)

RUN_TERMINAL_EVENT_TYPE = "market.ingestion_succeeded"
CANARY_EVIDENCE_EVENT_TYPE = "market.replacement_canary_succeeded"
ACQUISITION_EVIDENCE_EVENT_TYPE = "market.replacement_acquisition_succeeded"


def committed_chunk_rows():
    manifest = json.loads(CHUNK_MANIFEST_PATH.read_text())
    rows = manifest["chunks"]
    if len(rows) != COMPLETE_DATASET_CHUNKS or manifest["chunk_count"] != COMPLETE_DATASET_CHUNKS:
        raise ValueError("committed chunk manifest does not contain 132 chunks")
    if sum(row["expected_observation_count"] for row in rows) != COMPLETE_DATASET_CANDLES:
        raise ValueError("committed chunk manifest does not total 364,953 candles")
    return rows


def build_canary_success_record():
    """The frozen record of the accepted Gate 7A outcome; the committed
    artifact file must contain exactly its canonical JSON."""
    body = {
        "schema_identity": "phase-2b1r-gate7a-canary-success-v1",
        "schema_version": 1,
        "logical_key": ACQUISITION_CANARY_LOGICAL_KEY,
        "canonical_request_sha256": ACQUISITION_CANARY_REQUEST_SHA256,
        "semantic_inventory_sha256": ACQUISITION_CANARY_SEMANTIC_SHA256,
        "expected_candle_count": ACQUISITION_CANARY_EXPECTED_OBSERVATION_COUNT,
        "stored_candle_count": ACQUISITION_CANARY_EXPECTED_OBSERVATION_COUNT,
        "attempt_number": 1,
        "ingestion_manifest_sha256": CANARY_SUCCESS_MANIFEST_SHA256,
        "candle_key_hash": CANARY_SUCCESS_CANDLE_KEY_HASH,
        "candle_payload_hash": CANARY_SUCCESS_CANDLE_PAYLOAD_HASH,
        "terminal_event_sha256": CANARY_SUCCESS_TERMINAL_EVENT_SHA256,
        "operational_evidence_sha256": CANARY_SUCCESS_OPERATIONAL_EVIDENCE_SHA256,
        "data_contract_sha256": replacement_contract_sha256(),
        "replacement_plan_sha256": REPLACEMENT_PLAN_SHA256,
        "replacement_dataset_manifest_sha256": REPLACEMENT_DATASET_MANIFEST_SHA256,
        "global_semantic_inventory_sha256": GLOBAL_SEMANTIC_INVENTORY_SHA256,
        "post_canary_snapshot_sha256": POST_CANARY_SNAPSHOT_SHA256,
        "audit_event_semantics": {
            "run_scoped_terminal_event": RUN_TERMINAL_EVENT_TYPE,
            "attempt_scoped_evidence_event": CANARY_EVIDENCE_EVENT_TYPE,
            "statement": (
                "The run-scoped event records the terminal ingestion"
                " transition; the attempt-scoped event carries the governed"
                " provider-observed evidence chain. They address different"
                " subjects and are individually unique."
            ),
        },
        "dataset_registration_created": False,
        "s0_s1_executed": False,
    }
    return {**body, "record_sha256": canonical_hash(body)}


def build_acquisition_wave_manifest():
    """Six deterministic waves over the 131 remaining chunks, derived only
    from the committed ordered chunk manifest; the completed canary at
    discovery ordinal 2 is excluded.

    Wave 1 reuses the risk-diverse discovery structure: all twelve D and W
    chunks plus the first H1 chunk of each non-canary instrument. Later
    waves take the remaining canonical ordinals in ascending order."""
    rows = committed_chunk_rows()
    by_ordinal = {row["ordinal"]: row for row in rows}
    canary = by_ordinal[2]
    if canary["logical_key"] != ACQUISITION_CANARY_LOGICAL_KEY:
        raise ValueError("committed manifest ordinal 2 is not the accepted canary")
    remaining = [row for row in rows if row["ordinal"] != 2]
    if len(remaining) != REMAINING_CHUNKS:
        raise ValueError("remaining chunk count is not 131")

    wave_one = [by_ordinal[ordinal] for ordinal in WAVE_ONE_ORDINALS]
    for row in wave_one:
        first_h1 = (
            row["granularity"] == "H1" and by_ordinal[row["ordinal"] - 1]["granularity"] != "H1"
        )
        if not (row["granularity"] in ("D", "W") or (first_h1 and row["instrument"] != "AUD_USD")):
            raise ValueError(f"wave 1 ordinal {row['ordinal']} violates the risk-diverse structure")
    if sum(1 for row in wave_one if row["granularity"] in ("D", "W")) != 12:
        raise ValueError("wave 1 must contain all twelve D/W chunks")

    consumed = set(WAVE_ONE_ORDINALS)
    later = [row for row in remaining if row["ordinal"] not in consumed]
    later.sort(key=lambda row: row["ordinal"])
    waves = [wave_one]
    cursor = 0
    for size in WAVE_SIZES[1:]:
        waves.append(later[cursor : cursor + size])
        cursor += size
    if cursor != len(later):
        raise ValueError("wave partitioning did not consume every remaining chunk")

    seen = set()
    wave_entries = []
    for index, wave in enumerate(waves, 1):
        if len(wave) != WAVE_SIZES[index - 1]:
            raise ValueError(f"wave {index} size mismatch")
        for row in wave:
            if row["ordinal"] in seen or row["ordinal"] == 2:
                raise ValueError("duplicate or canary chunk in waves")
            seen.add(row["ordinal"])
        wave_entries.append(
            {
                "wave": index,
                "chunk_count": len(wave),
                "expected_candle_total": sum(row["expected_observation_count"] for row in wave),
                "chunks": [
                    {
                        "ordinal": row["ordinal"],
                        "instrument": row["instrument"],
                        "granularity": row["granularity"],
                        "requested_from": row["requested_from"],
                        "requested_to": row["requested_to"],
                        "logical_key": row["logical_key"],
                        "canonical_request_sha256": row["canonical_request_sha256"],
                        "semantic_inventory_sha256": row["semantic_inventory_sha256"],
                        "expected_observation_count": row["expected_observation_count"],
                    }
                    for row in wave
                ],
            }
        )
    if len(seen) != REMAINING_CHUNKS:
        raise ValueError("waves do not cover exactly the 131 remaining chunks")
    ordered_manifest_sha256 = canonical_hash(wave_entries)
    body = {
        "schema_identity": "phase-2b1r-gate7b-acquisition-wave-manifest-v1",
        "schema_version": 1,
        "data_contract_sha256": replacement_contract_sha256(),
        "replacement_plan_sha256": REPLACEMENT_PLAN_SHA256,
        "replacement_dataset_manifest_sha256": REPLACEMENT_DATASET_MANIFEST_SHA256,
        "global_semantic_inventory_sha256": GLOBAL_SEMANTIC_INVENTORY_SHA256,
        "complete_dataset_chunks": COMPLETE_DATASET_CHUNKS,
        "complete_dataset_candles": COMPLETE_DATASET_CANDLES,
        "excluded_canary": {
            "ordinal": 2,
            "logical_key": ACQUISITION_CANARY_LOGICAL_KEY,
            "reason": "completed by the accepted Gate 7A canary",
            "success_prerequisite": True,
        },
        "remaining_chunks": REMAINING_CHUNKS,
        "remaining_candles": REMAINING_CANDLES,
        "wave_sizes": list(WAVE_SIZES),
        "ordered_wave_manifest_sha256": ordered_manifest_sha256,
        "waves": wave_entries,
    }
    return {**body, "manifest_sha256": canonical_hash(body)}


def wave_manifest_artifact_path():
    return DOCS_DIR / "phase-2b1r-gate7b-acquisition-wave-manifest.json"


def canary_success_artifact_path():
    return DOCS_DIR / "phase-2b1r-gate7a-canary-success.json"


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def load_committed_wave_manifest():
    """Load the committed wave manifest, requiring byte-equality with the
    deterministic regeneration from the committed chunk manifest."""
    committed = wave_manifest_artifact_path().read_bytes()
    regenerated = build_acquisition_wave_manifest()
    if committed != _canonical_bytes(regenerated):
        raise ValueError("committed acquisition-wave manifest does not reconstruct")
    return regenerated


def load_committed_canary_success():
    committed = canary_success_artifact_path().read_bytes()
    regenerated = build_canary_success_record()
    if committed != _canonical_bytes(regenerated):
        raise ValueError("committed canary-success record does not reconstruct")
    return regenerated


def verify_live_canary_success(record=None):
    """Read-only reconstruction of the accepted canary success from live
    rows against the committed pinned record; raises unless every governed
    fact and hash reconstructs. Tests may pass a fixture-derived record of
    the same schema; production callers use the committed artifact."""
    import hashlib

    from market.historical_acquisition import stable_hash
    from market.models import AuditEvent, Candle, DatasetRegistration, IngestionManifest
    from market.provider_observed_canary import resolve_canary_chunk
    from market.services import DatasetQualityError

    if record is None:
        record = load_committed_canary_success()
    chunk = resolve_canary_chunk()
    attempts = list(chunk.attempts.select_related("ingestion_run"))
    if len(attempts) != 1 or attempts[0].attempt_number != 1:
        raise DatasetQualityError("canary prerequisite requires exactly attempt 1")
    attempt = attempts[0]
    run = attempt.ingestion_run
    if (
        run.status != "succeeded"
        or run.fetched_count != record["expected_candle_count"]
        or run.stored_count != record["stored_candle_count"]
        or run.rejected_count != 0
        or run.finished_at is None
    ):
        raise DatasetQualityError("canary prerequisite requires the terminal succeeded run")
    manifest = IngestionManifest.objects.filter(ingestion_run=run).first()
    if (
        manifest is None
        or manifest.sha256 != record["ingestion_manifest_sha256"]
        or manifest.sha256 != stable_hash(manifest.payload)
    ):
        raise DatasetQualityError("canary prerequisite requires the exact ingestion manifest")
    stored = Candle.objects.filter(dataset_version=chunk.dataset_version)
    sealed = list(
        chunk.discovery_inventory.observations.order_by("timestamp").values_list(
            "timestamp", "volume", "complete"
        )
    )
    rows = list(
        stored.filter(ingestion_run=run)
        .order_by("timestamp")
        .values_list("timestamp", "volume", "complete")
    )
    if len(rows) != record["expected_candle_count"] or rows != sealed:
        raise DatasetQualityError("canary prerequisite requires exact sealed-inventory candles")
    candle_keys = hashlib.sha256()
    candle_payloads = hashlib.sha256()
    for row in (
        stored.filter(ingestion_run=run)
        .select_related("instrument")
        .order_by("timestamp")
        .iterator()
    ):
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
    if (
        candle_keys.hexdigest() != record["candle_key_hash"]
        or candle_payloads.hexdigest() != record["candle_payload_hash"]
    ):
        raise DatasetQualityError("canary prerequisite candle hashes do not reconstruct")
    evidence = AuditEvent.objects.filter(
        event_type=CANARY_EVIDENCE_EVENT_TYPE,
        subject_type="HistoricalIngestionAttempt",
        subject_id=str(attempt.pk),
    )
    if evidence.count() != 1:
        raise DatasetQualityError("canary prerequisite requires the attempt evidence event")
    payload = evidence.get().payload
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
        payload["terminal_event_sha256"] != record["terminal_event_sha256"]
        or stable_hash(terminal) != payload["terminal_event_sha256"]
        or payload["operational_evidence_sha256"] != record["operational_evidence_sha256"]
        or stable_hash(
            [
                payload["terminal_event_sha256"],
                payload["provider_evidence"],
                attempt.idempotency_key,
            ]
        )
        != payload["operational_evidence_sha256"]
    ):
        raise DatasetQualityError("canary prerequisite event hashes do not reconstruct")
    if (
        AuditEvent.objects.filter(
            event_type=RUN_TERMINAL_EVENT_TYPE,
            subject_type="IngestionRun",
            subject_id=str(run.pk),
        ).count()
        != 1
    ):
        raise DatasetQualityError("canary prerequisite requires the run terminal event")
    if AuditEvent.objects.filter(
        event_type="market.historical_ingestion_failed",
        subject_id=str(attempt.pk),
        subject_type="HistoricalIngestionAttempt",
    ).exists():
        raise DatasetQualityError("canary prerequisite forbids a canary failure event")
    if DatasetRegistration.objects.exists():
        raise DatasetQualityError("canary prerequisite forbids a dataset registration")
    return chunk
