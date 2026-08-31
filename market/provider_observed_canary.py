"""Gate 7A: the single provider-observed replacement acquisition canary.

Frozen portable pins for exactly one replacement acquisition chunk — the
proven discovery canary (AUD_USD H1, discovery ordinal 2) — resolved from
the committed Gate 1B artifacts, never guessed or recomputed at runtime.
Nothing in this module contacts a provider or writes to a database.
"""

from market.historical_discovery import (
    DISCOVERY_V2_MANIFEST_SHA256,
    DISCOVERY_V2_PLAN_SHA256,
    GLOBAL_SEMANTIC_INVENTORY_SHA256,
    canonical_hash,
    future_data_contract_semantic_hash,
)

ACQUISITION_CANARY_INSTRUMENT = "AUD_USD"
ACQUISITION_CANARY_GRANULARITY = "H1"
ACQUISITION_CANARY_REQUESTED_FROM = "2009-12-31T15:00:00Z"
ACQUISITION_CANARY_REQUESTED_TO = "2010-06-16T07:00:00Z"
ACQUISITION_CANARY_EXPECTED_OBSERVATION_COUNT = 2932
ACQUISITION_CANARY_DISCOVERY_ORDINAL = 2
ACQUISITION_CANARY_LOGICAL_KEY = "e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c"
ACQUISITION_CANARY_REQUEST_SHA256 = (
    "3ec01ff455aeef4b6977fb7350dfa8fd98dae744a886c22ad84d597947677ff1"
)
ACQUISITION_CANARY_SEMANTIC_SHA256 = (
    "fdf82569dc323bc58cadb5b48d5309fc0ec987c5caf66e16a1225d478b09e9de"
)
REPLACEMENT_PLAN_SHA256 = "f0be516c732d775ce57fd98a39a7dd7df917d4eaa2c9c0ffd2fc7028d9a23528"
REPLACEMENT_DATASET_MANIFEST_SHA256 = (
    "9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54"
)
SEALED_APPROVAL_SHA256 = "41d3d0cc97c82882fd56fd1459b71df862f76d2e4c698eb759df1a82a0f25586"
SEALED_REGISTRATION_REPORT_SHA256 = (
    "cd0acdcb52aa0a321aed3ecbb4a7f9edc38fa8d31444c5bbc2927fefd9154844"
)
ACQUISITION_CANARY_IDEMPOTENCY_KEY = (
    f"failed-break-ingestion-attempt:{ACQUISITION_CANARY_LOGICAL_KEY}:1"
)


def replacement_contract_sha256():
    return future_data_contract_semantic_hash(
        global_semantic_inventory_sha256=GLOBAL_SEMANTIC_INVENTORY_SHA256
    )


def acquisition_canary_request():
    return {
        "instrument": ACQUISITION_CANARY_INSTRUMENT,
        "granularity": ACQUISITION_CANARY_GRANULARITY,
        "from": ACQUISITION_CANARY_REQUESTED_FROM,
        "to": ACQUISITION_CANARY_REQUESTED_TO,
        "price": "BA",
        "price_component": "COMBINED_BID_ASK",
        "smooth": False,
        "dailyAlignment": 17,
        "alignmentTimezone": "America/New_York",
        "weeklyAlignment": "Friday",
        "includeFirst": True,
    }


def build_canary_authorization():
    """The frozen Gate 7A authorization body; the committed artifact file
    must contain exactly its canonical JSON."""
    body = {
        "schema_identity": "phase-2b1r-gate7a-acquisition-canary-authorization-v1",
        "schema_version": 1,
        "instrument": ACQUISITION_CANARY_INSTRUMENT,
        "granularity": ACQUISITION_CANARY_GRANULARITY,
        "requested_from": ACQUISITION_CANARY_REQUESTED_FROM,
        "requested_to": ACQUISITION_CANARY_REQUESTED_TO,
        "expected_observation_count": ACQUISITION_CANARY_EXPECTED_OBSERVATION_COUNT,
        "discovery_ordinal": ACQUISITION_CANARY_DISCOVERY_ORDINAL,
        "logical_key": ACQUISITION_CANARY_LOGICAL_KEY,
        "canonical_request_sha256": ACQUISITION_CANARY_REQUEST_SHA256,
        "semantic_inventory_sha256": ACQUISITION_CANARY_SEMANTIC_SHA256,
        "canonical_request": acquisition_canary_request(),
        "data_contract_sha256": replacement_contract_sha256(),
        "replacement_plan_sha256": REPLACEMENT_PLAN_SHA256,
        "replacement_dataset_manifest_sha256": REPLACEMENT_DATASET_MANIFEST_SHA256,
        "global_semantic_inventory_sha256": GLOBAL_SEMANTIC_INVENTORY_SHA256,
        "discovery_plan_sha256": DISCOVERY_V2_PLAN_SHA256,
        "ordered_chunk_manifest_sha256": DISCOVERY_V2_MANIFEST_SHA256,
        "approval_sha256": SEALED_APPROVAL_SHA256,
        "registration_report_sha256": SEALED_REGISTRATION_REPORT_SHA256,
        "single_attempt_only": True,
        "max_provider_requests": 1,
        "environment": "practice",
    }
    return {**body, "authorization_sha256": canonical_hash(body)}


def resolve_canary_chunk():
    """Read-only resolution of the exact canary chunk with its complete
    governed lineage; every pin must reconstruct or resolution fails."""
    from market.models import HistoricalIngestionChunk
    from market.services import DatasetQualityError

    chunk = (
        HistoricalIngestionChunk.objects.select_related(
            "plan__data_contract__discovery_registration__plan",
            "plan__data_contract__discovery_registration__approval",
            "dataset_version",
            "instrument",
            "discovery_inventory__chunk",
        )
        .filter(logical_key=ACQUISITION_CANARY_LOGICAL_KEY)
        .first()
    )
    if chunk is None:
        raise DatasetQualityError("acquisition canary chunk is not materialized")
    plan = chunk.plan
    contract = plan.data_contract
    dataset = chunk.dataset_version
    inventory = chunk.discovery_inventory
    registration = contract.discovery_registration if contract else None
    expected_contract = replacement_contract_sha256()
    if (
        contract is None
        or inventory is None
        or registration is None
        or contract.sha256 != expected_contract
        or plan.sha256 != REPLACEMENT_PLAN_SHA256
        or plan.data_contract_sha256 != contract.sha256
        or dataset.manifest_sha256 != REPLACEMENT_DATASET_MANIFEST_SHA256
        or dataset.data_contract_sha256 != contract.sha256
        or contract.global_semantic_inventory_sha256 != GLOBAL_SEMANTIC_INVENTORY_SHA256
        or contract.approval_sha256 != SEALED_APPROVAL_SHA256
        or contract.registration_report_sha256 != SEALED_REGISTRATION_REPORT_SHA256
        or registration.plan.sha256 != DISCOVERY_V2_PLAN_SHA256
        or registration.plan.sealed_at is None
        or registration.plan.sealed_at != registration.registered_at
        or registration.ordered_chunk_manifest_sha256 != DISCOVERY_V2_MANIFEST_SHA256
        or chunk.canonical_request_sha256 != ACQUISITION_CANARY_REQUEST_SHA256
        or chunk.semantic_inventory_sha256 != ACQUISITION_CANARY_SEMANTIC_SHA256
        or inventory.semantic_inventory_sha256 != ACQUISITION_CANARY_SEMANTIC_SHA256
        or chunk.expected_observation_count != ACQUISITION_CANARY_EXPECTED_OBSERVATION_COUNT
        or inventory.observation_count != ACQUISITION_CANARY_EXPECTED_OBSERVATION_COUNT
        or inventory.chunk.ordinal != ACQUISITION_CANARY_DISCOVERY_ORDINAL
        or chunk.instrument.code != ACQUISITION_CANARY_INSTRUMENT
        or chunk.granularity != ACQUISITION_CANARY_GRANULARITY
        or chunk.canonical_request != acquisition_canary_request()
    ):
        raise DatasetQualityError("acquisition canary lineage does not reconstruct")
    return chunk


def canary_dry_run_report(chunk):
    """Deterministic read-only report of the resolved canary lineage."""
    contract = chunk.plan.data_contract
    return {
        "report_identity": "phase-2b1r-gate7a-acquisition-canary-dry-run-v1",
        "read_only": True,
        "provider_requests_performed": 0,
        "data_contract_sha256": contract.sha256,
        "replacement_plan_sha256": chunk.plan.sha256,
        "replacement_dataset_manifest_sha256": chunk.dataset_version.manifest_sha256,
        "global_semantic_inventory_sha256": contract.global_semantic_inventory_sha256,
        "instrument": chunk.instrument.code,
        "granularity": chunk.granularity,
        "requested_from": ACQUISITION_CANARY_REQUESTED_FROM,
        "requested_to": ACQUISITION_CANARY_REQUESTED_TO,
        "logical_key": chunk.logical_key,
        "canonical_request_sha256": chunk.canonical_request_sha256,
        "semantic_inventory_sha256": chunk.semantic_inventory_sha256,
        "expected_candle_count": chunk.expected_observation_count,
        "existing_attempts": chunk.attempts.count(),
        "single_attempt_only": True,
    }
