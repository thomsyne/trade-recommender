"""Gate 7C: the bounded authorization artifact for provider-observed dataset
registration, and the read-only readiness check the command applies before it
is allowed to register anything.

The artifact binds only portable governed identities. Database primary keys,
usernames, provider request identifiers, credentials and timestamps are never
part of a semantic identity here.
"""

import hashlib
import json
from pathlib import Path

from market.historical_acquisition import (
    replacement_registration_contract,
    replacement_series_coverage,
    stable_hash,
)
from market.provider_observed_acquisition import REPLACEMENT_REGISTRATION_IDENTITY
from market.provider_observed_waves import (
    canary_success_artifact_path,
    wave_manifest_artifact_path,
)
from market.services import DatasetQualityError

ARTIFACT_SCHEMA = "phase-2b1r-gate7c-dataset-registration-authorization-v1"
ARTIFACT_NAME = "phase-2b1r-gate7c-dataset-registration-authorization.json"

DATA_CONTRACT_SHA256 = "60b603f26662bfc8faa4373177690bc0ae23820b914815f47c11d8367c07f7bf"
REPLACEMENT_PLAN_SHA256 = "f0be516c732d775ce57fd98a39a7dd7df917d4eaa2c9c0ffd2fc7028d9a23528"
REPLACEMENT_DATASET_MANIFEST_SHA256 = (
    "9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54"
)
GLOBAL_SEMANTIC_INVENTORY_SHA256 = (
    "78f8559bc9b14e84f8c1b1002d30ddd77d1918e9c026812b5ce6e2b0ca8af02c"
)
FINAL_ACQUISITION_SNAPSHOT_SHA256 = (
    "a61cb7690502f49bb79bfcb7aada223372f21f1a185fc1a0eed2feb25b1e0a01"
)
CANARY_SUCCESS_ARTIFACT_SHA256 = "471329e9b4252f2047ef9ec45e7d6b18071d487688fff7c3fe61b5976e5dd363"
WAVE_MANIFEST_ARTIFACT_SHA256 = "875704fb2e6a2d1dd9bad7143d06d4bd7cc19af2dac076fc669fc4aeec4b191c"

CHUNK_COUNT = 132
SUCCESSFUL_ATTEMPT_COUNT = 132
INGESTION_MANIFEST_COUNT = 132
CANDLE_COUNT = 364953
GRANULARITY_TOTALS = {"D": 17412, "H1": 344715, "W": 2826}

LOGICAL_CHUNK_SET_HASH = "de9c977eeac2097eba2e410187f84bf2052f3454b136d50e1b66727aadbedd0a"
SUCCESSFUL_ATTEMPT_SET_HASH = "ccb71254f70aebaee585de8b86a1c869657622ec0340adf8f4b5603e8607068e"
INGESTION_MANIFEST_SET_HASH = "dc3da68f95969b32e2f6a84b6f1c60ad4ea7832f110fa7b107c0b25fd2349b4f"
CANDLE_KEY_HASH = "5f7850a317808688066ead6f46f7085e05e840d0a0c73b1ab4fc56f792ede5ea"
CANDLE_PAYLOAD_HASH = "218bb6fb8c456a02bb10193179bed9b93e4be5a71da10ff9aee028e4e41c0d10"

AGGREGATE_FIELDS = (
    "logical_chunk_set_hash",
    "successful_attempt_set_hash",
    "ingestion_manifest_set_hash",
    "candle_key_hash",
    "candle_payload_hash",
)


def registration_authorization_path():
    return (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "strategy"
        / "failed-break"
        / "v1"
        / ARTIFACT_NAME
    )


def _committed_artifact_sha256(path, expected):
    """A committed predecessor artifact is bound by its own file hash; a file
    that no longer hashes to its pin fails closed."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError(f"committed artifact {path.name} does not match its governed pin")
    return digest


def build_registration_authorization():
    """The deterministic authorization body, derived only from governed pins."""
    body = {
        "schema": ARTIFACT_SCHEMA,
        "registration_identity": REPLACEMENT_REGISTRATION_IDENTITY,
        "data_contract_sha256": DATA_CONTRACT_SHA256,
        "replacement_plan_sha256": REPLACEMENT_PLAN_SHA256,
        "replacement_dataset_manifest_sha256": REPLACEMENT_DATASET_MANIFEST_SHA256,
        "global_semantic_inventory_sha256": GLOBAL_SEMANTIC_INVENTORY_SHA256,
        "final_acquisition_snapshot_sha256": FINAL_ACQUISITION_SNAPSHOT_SHA256,
        "gate7a_canary_success_artifact_sha256": _committed_artifact_sha256(
            canary_success_artifact_path(), CANARY_SUCCESS_ARTIFACT_SHA256
        ),
        "gate7b_wave_manifest_artifact_sha256": _committed_artifact_sha256(
            wave_manifest_artifact_path(), WAVE_MANIFEST_ARTIFACT_SHA256
        ),
        "chunk_count": CHUNK_COUNT,
        "successful_attempt_count": SUCCESSFUL_ATTEMPT_COUNT,
        "ingestion_manifest_count": INGESTION_MANIFEST_COUNT,
        "candle_count": CANDLE_COUNT,
        "granularity_candle_totals": dict(sorted(GRANULARITY_TOTALS.items())),
        "logical_chunk_set_hash": LOGICAL_CHUNK_SET_HASH,
        "successful_attempt_set_hash": SUCCESSFUL_ATTEMPT_SET_HASH,
        "ingestion_manifest_set_hash": INGESTION_MANIFEST_SET_HASH,
        "candle_key_hash": CANDLE_KEY_HASH,
        "candle_payload_hash": CANDLE_PAYLOAD_HASH,
        "authorization_scope": (
            "registers the completed provider-observed replacement dataset only;"
            " registration does not authorize S0, S1, returns or Phase 2B.2"
        ),
    }
    if sum(body["granularity_candle_totals"].values()) != CANDLE_COUNT:
        raise ValueError("granularity totals do not sum to the governed candle count")
    return {**body, "authorization_sha256": stable_hash(body)}


def load_committed_registration_authorization():
    """The committed artifact, accepted only when it is byte-for-byte the
    deterministic regeneration of the governed pins."""
    expected = build_registration_authorization()
    encoded = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    committed = registration_authorization_path().read_bytes()
    if committed != encoded:
        raise ValueError("committed registration authorization does not reconstruct")
    return expected


def verify_registration_readiness(dataset, plan, *, authorization=None):
    """Read-only readiness: every pinned identity, count and aggregate hash in
    the committed authorization must agree with the live governed rows. Nothing
    is written and no provider client is ever constructed."""
    from market.models import Candle, DatasetRegistration, IngestionRun

    authorization = authorization or load_committed_registration_authorization()
    if DatasetRegistration.objects.filter(dataset_version=dataset).exists():
        raise DatasetQualityError("replacement dataset is already registered")

    chunks = list(
        plan.chunks.filter(dataset_version=dataset)
        .select_related("instrument", "discovery_inventory")
        .prefetch_related("attempts__ingestion_run__ingestion_manifest")
        .order_by("instrument__code", "granularity", "requested_from")
    )
    contract = replacement_registration_contract(plan, dataset, chunks)
    if contract is None:
        raise DatasetQualityError("dataset is not a provider-observed replacement dataset")

    successful = []
    for chunk in chunks:
        succeeded = [
            attempt
            for attempt in chunk.attempts.all()
            if attempt.ingestion_run.status == IngestionRun.Status.SUCCEEDED
        ]
        if len(succeeded) != 1:
            raise DatasetQualityError("every replacement chunk requires one successful attempt")
        successful.append(succeeded[0])
    if IngestionRun.objects.filter(dataset_version=dataset, status="running").exists():
        raise DatasetQualityError("an ingestion run is still running")

    series_manifest, row_counts, _first_last = replacement_series_coverage(plan, dataset, chunks)
    aggregates = registration_aggregates(dataset, chunks, successful)
    totals = {}
    for granularity in plan.granularities:
        totals[granularity] = sum(
            count for key, count in row_counts.items() if key.endswith(f":{granularity}")
        )

    observed = {
        "data_contract_sha256": contract.sha256,
        "replacement_plan_sha256": plan.sha256,
        "replacement_dataset_manifest_sha256": dataset.manifest_sha256,
        "global_semantic_inventory_sha256": contract.global_semantic_inventory_sha256,
        "chunk_count": len(chunks),
        "successful_attempt_count": len(successful),
        "ingestion_manifest_count": len(
            {attempt.ingestion_run.ingestion_manifest.pk for attempt in successful}
        ),
        "candle_count": Candle.objects.filter(dataset_version=dataset).count(),
        "granularity_candle_totals": dict(sorted(totals.items())),
        **aggregates,
    }
    mismatched = sorted(field for field, value in observed.items() if authorization[field] != value)
    if mismatched:
        raise DatasetQualityError(
            "live governed state disagrees with the registration authorization: "
            + ", ".join(mismatched)
        )
    return {
        "contract": contract,
        "chunks": chunks,
        "successful": successful,
        "series_manifest": series_manifest,
        "observed": observed,
    }


def registration_aggregates(dataset, chunks, successful):
    """The five governed aggregate hashes, computed with exactly the formulas
    register_historical_dataset persists, so readiness and registration cannot
    diverge."""
    import hashlib

    from market.models import Candle

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
    return {
        "logical_chunk_set_hash": stable_hash([chunk.logical_key for chunk in chunks]),
        "successful_attempt_set_hash": stable_hash(
            [attempt.idempotency_key for attempt in successful]
        ),
        "ingestion_manifest_set_hash": stable_hash(
            sorted(attempt.ingestion_run.ingestion_manifest.sha256 for attempt in successful)
        ),
        "candle_key_hash": candle_keys.hexdigest(),
        "candle_payload_hash": candle_payloads.hexdigest(),
    }
