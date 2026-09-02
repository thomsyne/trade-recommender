"""Gate 1B: provider-observed replacement acquisition (code only).

Deterministic generators binding the sealed Gate 5 discovery inventory to a
replacement acquisition plan, dataset manifest and logical acquisition keys.
Nothing in this module contacts a provider; materialization against the
governed research database is a later, separately authorized gate.
"""

from django.db import transaction

from market.historical_acquisition import (
    ALIGNMENT,
    PARTITION,
    PHASE1_MANIFEST_SHA256,
    PHASE1_SPEC_SHA256,
    SOURCE_IDENTITY,
)
from market.historical_discovery import (
    DISCOVERY_V2_MANIFEST_SHA256,
    DISCOVERY_V2_PLAN_SHA256,
    GATE5_ACCEPTED_INVENTORY_COUNT,
    GATE5_STRUCTURAL_OBSERVATION_COUNT,
    GLOBAL_SEMANTIC_INVENTORY_SHA256,
    REPLACEMENT_DATA_IDENTITY,
    SUPERSEDED_DATA_IDENTITY,
    canonical_hash,
    canonical_timestamp,
    future_data_contract_semantic_hash,
)
from market.models import (
    HistoricalDataContract,
    HistoricalDiscoveryRegistration,
    HistoricalIngestionChunk,
    HistoricalTimestampInventory,
    Instrument,
)
from market.services import DatasetQualityError

REPLACEMENT_ACQUISITION_CONTRACT = "failed-break-provider-observed-historical-acquisition"
REPLACEMENT_ACQUISITION_VERSION = "phase-2b1r-v1"
REPLACEMENT_DATASET_NAME = "failed-break-provider-observed-historical"
REPLACEMENT_DATASET_VERSION = "phase-2b1r-v1"
REPLACEMENT_DATASET_DESCRIPTION = (
    "Provider-observed failed-break historical dataset acquired against the"
    " sealed Gate 5 timestamp inventory"
)
REPLACEMENT_GRANULARITY_CHUNKS = {"D": 6, "H1": 120, "W": 6}
REPLACEMENT_REGISTRATION_IDENTITY = "failed-break-provider-observed-dataset-registration-v1"


def build_data_contract_payload(global_semantic_inventory_sha256):
    """The frozen Gate 1B semantic body; its canonical hash is the contract
    identity fixture pinned since migration 0014 review
    (future_data_contract_semantic_hash)."""
    from market.historical_discovery import (
        DISCOVERY_CONTRACT,
        DISCOVERY_VERSION,
    )
    from market.historical_discovery import (
        SOURCE_IDENTITY as DISCOVERY_SOURCE_IDENTITY,
    )

    return {
        "discovery_contract": DISCOVERY_CONTRACT,
        "discovery_version": DISCOVERY_VERSION,
        "source_identity": DISCOVERY_SOURCE_IDENTITY,
        "phase1_spec_hash": PHASE1_SPEC_SHA256,
        "phase1_manifest_hash": PHASE1_MANIFEST_SHA256,
        "replacement_data_identity": REPLACEMENT_DATA_IDENTITY,
        "superseded_semantic_identity": SUPERSEDED_DATA_IDENTITY,
        "global_semantic_inventory_sha256": global_semantic_inventory_sha256,
    }


def _sealed_pinned_registration():
    registration = (
        HistoricalDiscoveryRegistration.objects.select_related("plan", "approval")
        .filter(plan__sha256=DISCOVERY_V2_PLAN_SHA256)
        .first()
    )
    if (
        registration is None
        or registration.plan.sealed_at is None
        or registration.plan.sealed_at != registration.registered_at
        or registration.ordered_chunk_manifest_sha256 != DISCOVERY_V2_MANIFEST_SHA256
        or registration.global_semantic_inventory_sha256
        != registration.approval.global_semantic_inventory_sha256
    ):
        raise DatasetQualityError(
            "data contract requires the sealed approved discovery registration"
        )
    return registration


@transaction.atomic
def create_historical_data_contract(strategy_version):
    """Create the single governed data contract for the sealed registration."""
    registration = _sealed_pinned_registration()
    if (
        strategy_version.content_hash != PHASE1_MANIFEST_SHA256
        or strategy_version.data_identity != SUPERSEDED_DATA_IDENTITY
    ):
        raise DatasetQualityError("data contract requires the unchanged approved strategy version")
    payload = build_data_contract_payload(registration.global_semantic_inventory_sha256)
    return HistoricalDataContract.objects.create(
        identity=REPLACEMENT_DATA_IDENTITY,
        strategy_version=strategy_version,
        discovery_registration=registration,
        superseded_data_identity=SUPERSEDED_DATA_IDENTITY,
        phase1_spec_hash=PHASE1_SPEC_SHA256,
        phase1_manifest_hash=PHASE1_MANIFEST_SHA256,
        global_semantic_inventory_sha256=registration.global_semantic_inventory_sha256,
        approval_sha256=registration.approval.sha256,
        registration_report_sha256=registration.report_sha256,
        payload=payload,
        sha256=future_data_contract_semantic_hash(
            global_semantic_inventory_sha256=registration.global_semantic_inventory_sha256
        ),
    )


def replacement_chunk_logical_key(
    *,
    replacement_plan_sha256,
    replacement_dataset_manifest_sha256,
    semantic_inventory_sha256,
    canonical_request_sha256,
):
    """Portable logical acquisition key: canonical inputs only, never ids."""
    return canonical_hash(
        {
            "replacement_plan_sha256": replacement_plan_sha256,
            "replacement_dataset_manifest_sha256": replacement_dataset_manifest_sha256,
            "semantic_inventory_sha256": semantic_inventory_sha256,
            "canonical_request_sha256": canonical_request_sha256,
        }
    )


def _replacement_chunk_rows(discovery_plan):
    rows = []
    for chunk in (
        discovery_plan.chunks.select_related("instrument", "inventory").order_by("ordinal").all()
    ):
        try:
            inventory = chunk.inventory
        except type(chunk).inventory.RelatedObjectDoesNotExist as error:
            raise DatasetQualityError(
                "replacement plan requires an accepted inventory for every chunk"
            ) from error
        rows.append(
            {
                "ordinal": chunk.ordinal,
                "instrument": chunk.instrument.code,
                "granularity": chunk.granularity,
                "requested_from": canonical_timestamp(chunk.requested_from),
                "requested_to": canonical_timestamp(chunk.requested_to),
                "canonical_request": chunk.canonical_request,
                "canonical_request_sha256": chunk.canonical_request_sha256,
                "semantic_inventory_sha256": inventory.semantic_inventory_sha256,
                "expected_observation_count": inventory.observation_count,
            }
        )
    return rows


def acquisition_identities(
    *,
    acquisition_contract,
    acquisition_version,
    data_identity,
    discovery_plan_sha256,
    dataset_name,
    dataset_version,
    dataset_description,
):
    """The portable identity bundle a provider-observed acquisition generation binds.

    Every value is a governed identity or an already accepted evidence digest; no
    operational row id, timestamp or provider result may enter this bundle.
    """
    return {
        "acquisition_contract": acquisition_contract,
        "acquisition_version": acquisition_version,
        "data_identity": data_identity,
        "discovery_plan_sha256": discovery_plan_sha256,
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "dataset_description": dataset_description,
    }


REPLACEMENT_IDENTITIES = acquisition_identities(
    acquisition_contract=REPLACEMENT_ACQUISITION_CONTRACT,
    acquisition_version=REPLACEMENT_ACQUISITION_VERSION,
    data_identity=REPLACEMENT_DATA_IDENTITY,
    discovery_plan_sha256=DISCOVERY_V2_PLAN_SHA256,
    dataset_name=REPLACEMENT_DATASET_NAME,
    dataset_version=REPLACEMENT_DATASET_VERSION,
    dataset_description=REPLACEMENT_DATASET_DESCRIPTION,
)


def _build_replacement_payloads(
    *, contract_sha256, global_semantic_inventory_sha256, strategy, chunk_rows, identities=None
):
    """Pure deterministic construction from portable inputs only.

    `identities` defaults to the predecessor v2 bundle, so the v2 plan, dataset
    manifest and logical keys this function produced before parameterization are
    unchanged byte-for-byte. Gate 8E passes the successor bundle instead; nothing
    else about the construction differs between generations.
    """
    identities = REPLACEMENT_IDENTITIES if identities is None else identities
    granularity_bounds = {}
    for row in chunk_rows:
        bounds = granularity_bounds.setdefault(
            row["granularity"],
            {"from": row["requested_from"], "to": row["requested_to"]},
        )
        bounds["from"] = min(bounds["from"], row["requested_from"])
        bounds["to"] = max(bounds["to"], row["requested_to"])
    instruments = sorted({row["instrument"] for row in chunk_rows})
    granularities = sorted(granularity_bounds)
    plan_payload = {
        "acquisition_contract": identities["acquisition_contract"],
        "acquisition_version": identities["acquisition_version"],
        "source": {"name": "OANDA v20", "governed_identity": SOURCE_IDENTITY},
        "strategy": {
            "definition_key": strategy["definition_key"],
            "version": strategy["version"],
            "content_hash": strategy["content_hash"],
        },
        "data_identity": identities["data_identity"],
        "data_contract_sha256": contract_sha256,
        "discovery_plan_sha256": identities["discovery_plan_sha256"],
        "phase1_spec_hash": PHASE1_SPEC_SHA256,
        "phase1_manifest_hash": PHASE1_MANIFEST_SHA256,
        "dataset": {
            "name": identities["dataset_name"],
            "version": identities["dataset_version"],
            "description": identities["dataset_description"],
        },
        "instruments": instruments,
        "granularities": granularities,
        "ranges": {key: dict(value) for key, value in sorted(granularity_bounds.items())},
        "alignment": ALIGNMENT,
        "price_component": "COMBINED_BID_ASK",
        "complete_only": True,
        "chunk_size": 4999,
        "expected_total_observations": sum(row["expected_observation_count"] for row in chunk_rows),
        "requests": chunk_rows,
    }
    plan_sha256 = canonical_hash(plan_payload)
    required_ranges = [
        {
            "instrument": instrument,
            "granularity": granularity,
            "start": granularity_bounds[granularity]["from"],
            "end": granularity_bounds[granularity]["to"],
        }
        for instrument in instruments
        for granularity in granularities
    ]
    dataset_manifest = {
        "strategy_manifest_sha256": strategy["content_hash"],
        "partition": PARTITION,
        "required_ranges": required_ranges,
        "historical_plan_sha256": plan_sha256,
        "price_component": "COMBINED_BID_ASK",
        "complete_only": True,
        "instruments": instruments,
        "granularities": granularities,
        "alignment": ALIGNMENT,
        "data_identity": identities["data_identity"],
        "historical_data_contract_sha256": contract_sha256,
        "global_semantic_inventory_sha256": global_semantic_inventory_sha256,
    }
    dataset_manifest_sha = canonical_hash(dataset_manifest)
    chunks = [
        {
            **row,
            "logical_key": replacement_chunk_logical_key(
                replacement_plan_sha256=plan_sha256,
                replacement_dataset_manifest_sha256=dataset_manifest_sha,
                semantic_inventory_sha256=row["semantic_inventory_sha256"],
                canonical_request_sha256=row["canonical_request_sha256"],
            ),
        }
        for row in chunk_rows
    ]
    return {
        "plan": plan_payload,
        "plan_sha256": plan_sha256,
        "dataset_manifest": dataset_manifest,
        "dataset_manifest_sha256": dataset_manifest_sha,
        "chunks": chunks,
    }


def build_replacement_acquisition_payloads(contract):
    """Governed generation from the sealed 132 inventories: exactly the
    discovery request ranges (D 6, H1 120, W 6), every chunk bound to its
    sealed inventory, totalling exactly the 364,953 sealed observations."""
    registration = _sealed_pinned_registration()
    if (
        contract.discovery_registration_id != registration.pk
        or contract.identity != REPLACEMENT_DATA_IDENTITY
        or contract.sha256
        != future_data_contract_semantic_hash(
            global_semantic_inventory_sha256=registration.global_semantic_inventory_sha256
        )
        or contract.global_semantic_inventory_sha256
        != registration.global_semantic_inventory_sha256
    ):
        raise DatasetQualityError("replacement plan requires the governed sealed data contract")
    chunk_rows = _replacement_chunk_rows(registration.plan)
    grouped = {}
    for row in chunk_rows:
        grouped[row["granularity"]] = grouped.get(row["granularity"], 0) + 1
    total = sum(row["expected_observation_count"] for row in chunk_rows)
    if (
        len(chunk_rows) != GATE5_ACCEPTED_INVENTORY_COUNT
        or grouped != REPLACEMENT_GRANULARITY_CHUNKS
        or total != GATE5_STRUCTURAL_OBSERVATION_COUNT
        or registration.global_semantic_inventory_sha256 != GLOBAL_SEMANTIC_INVENTORY_SHA256
    ):
        raise DatasetQualityError("replacement plan requires the exact sealed inventory coverage")
    strategy = contract.strategy_version
    return _build_replacement_payloads(
        contract_sha256=contract.sha256,
        global_semantic_inventory_sha256=contract.global_semantic_inventory_sha256,
        strategy={
            "definition_key": strategy.definition.key,
            "version": strategy.version,
            "content_hash": strategy.content_hash,
        },
        chunk_rows=chunk_rows,
    )


def materialize_replacement_chunks(plan, dataset, payloads):
    """Create the replacement acquisition chunk rows from generated payloads.

    Row creation only; the governed offline materialization against the
    research database is a later, separately authorized gate."""
    if (
        plan.sha256 != payloads["plan_sha256"]
        or dataset.manifest_sha256 != payloads["dataset_manifest_sha256"]
        or plan.data_contract_id is None
    ):
        raise DatasetQualityError("replacement chunks require their generated lineage")
    instruments = {
        item.code: item
        for item in Instrument.objects.filter(
            code__in={row["instrument"] for row in payloads["chunks"]}
        )
    }
    inventory_by_semantic = {
        inventory.semantic_inventory_sha256: inventory
        for inventory in HistoricalTimestampInventory.objects.filter(
            chunk__plan=plan.data_contract.discovery_registration.plan
        )
    }
    created = []
    for row in payloads["chunks"]:
        inventory = inventory_by_semantic.get(row["semantic_inventory_sha256"])
        if inventory is None:
            raise DatasetQualityError("replacement chunk lacks its sealed inventory")
        created.append(
            HistoricalIngestionChunk(
                plan=plan,
                dataset_version=dataset,
                instrument=instruments[row["instrument"]],
                granularity=row["granularity"],
                requested_from=inventory.chunk.requested_from,
                requested_to=inventory.chunk.requested_to,
                canonical_request=row["canonical_request"],
                canonical_request_sha256=row["canonical_request_sha256"],
                logical_key=row["logical_key"],
                discovery_inventory=inventory,
                semantic_inventory_sha256=row["semantic_inventory_sha256"],
                expected_observation_count=row["expected_observation_count"],
                data_contract_sha256=plan.data_contract_sha256,
            )
        )
    HistoricalIngestionChunk.objects.bulk_create(created)
    return created


def sealed_inventory_timestamps(chunk):
    """The exact sealed timestamp membership an acquisition response must equal."""
    if chunk.discovery_inventory_id is None:
        raise DatasetQualityError("chunk carries no sealed inventory binding")
    return tuple(
        chunk.discovery_inventory.observations.order_by("timestamp").values_list(
            "timestamp", flat=True
        )
    )


def replacement_supersession_lineage_report(contract):
    """Deterministic supersession/lineage report for the governed record."""
    registration = contract.discovery_registration
    body = {
        "identity": "failed-break-provider-observed-supersession-report-v1",
        "replacement_data_identity": contract.identity,
        "superseded_data_identity": contract.superseded_data_identity,
        "data_contract_sha256": contract.sha256,
        "phase1_spec_hash": contract.phase1_spec_hash,
        "phase1_manifest_hash": contract.phase1_manifest_hash,
        "discovery_plan_sha256": registration.plan.sha256,
        "ordered_chunk_manifest_sha256": registration.ordered_chunk_manifest_sha256,
        "global_semantic_inventory_sha256": contract.global_semantic_inventory_sha256,
        "accepted_operational_evidence_set_sha256": (
            registration.accepted_operational_evidence_set_sha256
        ),
        "approval_sha256": contract.approval_sha256,
        "registration_report_sha256": contract.registration_report_sha256,
        "cross_series_report_sha256": registration.cross_series_report_sha256,
    }
    return {**body, "report_sha256": canonical_hash(body)}
