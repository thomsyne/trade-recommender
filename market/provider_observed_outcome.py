"""Gate 8D3: the deterministic final-outcome artifact for successor discovery.

What this module is
-------------------
It reconstructs the completed successor discovery result from raw stored rows,
renders it as canonical JSON, and verifies the committed artifact against that
reconstruction. Nothing here writes a row, builds a provider client, or reads a
credential.

What this module is *not*
-------------------------
It is not database authority. Gate 8D3 records and pins the observed result so
that a reviewer can accept it; the database continues to refuse sealing,
approval and registration exactly as before, and migration 0023 is untouched.
Only Gate 8D3', a separately reviewed migration, may embed independently
accepted values as operative literals. Reconstruction here proves internal
consistency; it does not supply acceptance, and no value becomes authority
merely because it appears in this artifact.

Hash conventions are reused, never re-invented: ``canonical_hash`` for canonical
JSON digests, ``semantic_inventory_hashes`` for inventory identity, and the
``_registration_hashes`` formulas for the three plan-level aggregates.
"""

import hashlib
import json
from pathlib import Path

from market.historical_discovery import (
    DISCOVERY_COMPLETION_SUMMARY_SHA256,
    DISCOVERY_V2_MANIFEST_SHA256,
    DISCOVERY_V2_PLAN_SHA256,
    DISCOVERY_V2_VERSION,
    GLOBAL_SEMANTIC_INVENTORY_SHA256,
    canonical_hash,
    canonical_timestamp,
    parse_timestamp,
)
from market.provider_observed_successor import (
    AUTHORIZATION_FILE_SHA256,
    CANARY_INSTRUMENT,
    EXPECTED_CHUNK_COUNT,
    INSTRUMENTS,
    PREDECESSOR_H1_REQUESTED_FROM,
    PREDECESSOR_REGISTRATION_CONFIGURATION_SHA256,
    PREDECESSOR_REGISTRATION_REPORT_SHA256,
    REQUIRED_H1_WARMUP_OBSERVATIONS,
    SUCCESSOR_DISCOVERY_PLAN_IDENTITY,
    SUCCESSOR_DISCOVERY_VERSION,
    SUCCESSOR_H1_REQUESTED_FROM,
    TERMINAL_FAILURE_STATUSES,
    build_successor_discovery_plan,
    load_committed_gate8b_authorization,
)

ARTIFACT_SCHEMA = "phase-2b1r-gate8d3-successor-discovery-outcome-v1"
ARTIFACT_NAME = "phase-2b1r-gate8d3-successor-discovery-outcome.json"

# The committed artifact's own file digest, pinned in code. A caller can neither
# supply nor relax it: a digest read from the document under inspection would
# prove nothing about that document.
OUTCOME_ARTIFACT_SHA256 = "b13fe357e5c2dec3450a6fc15cf755d6a940e6b83af8592cfdedaa9cc74156c5"

MIGRATION_0023_SHA256 = "e13cf659beaa754fb2e491c95fc3842e65e1714800c4daadbfeabd219c1ca7d5"
MIGRATION_0023_NAME = "0023_gate8b_prime_successor_discovery_activation.py"

# The completed provider outcome, as counted from raw rows.
EXPECTED_OBSERVATION_TOTAL = 365055
EXPECTED_RESTRICTED_OBSERVATION_TOTAL = 364953
EXPECTED_EXTENSION_OBSERVATIONS = 102
EXPECTED_EARLIER_PER_INSTRUMENT = 17
EXPECTED_PREDECESSOR_WARMUP = 8
EXPECTED_COMBINED_WARMUP = 25
EXPECTED_GRANULARITY_OBSERVATIONS = {"D": 17412, "H1": 344817, "W": 2826}

# The unchanged development start, and the last H1 timestamp whose candle
# completes at or before it. Both are read from the governed contract rather
# than recomputed from any calendar.
DEVELOPMENT_START = "2010-01-01T05:00:00Z"
LAST_WARMUP_TIMESTAMP_LITERAL = "2010-01-01T04:00:00Z"

AUTHORITY_STATEMENT = (
    "Gate 8D3 records and pins the observed successor discovery outcome for independent"
    " acceptance. It is not database authority: the installed governance continues to"
    " refuse sealing, approval and registration, migration 0023 is unchanged, and no"
    " PostgreSQL predicate compares this artifact's digest. Gate 8D3' is the separately"
    " reviewed migration that may embed independently accepted values as operative"
    " literals. Reconstruction proves internal consistency only; independent review"
    " supplies acceptance, and no row-supplied value becomes authority merely because it"
    " appears here."
)

STRATEGY_ATTESTATION = (
    "No S0 execution, S1 execution, return calculation, strategy output or scheduled job"
    " informed any value in this artifact. Every field is reconstructed from provider-"
    "observed discovery rows and governed repository constants alone."
)

SEMANTIC_HASH_STATEMENT = (
    "A semantic inventory hash is plan-bound by construction: it embeds the logical"
    " discovery key, which embeds the discovery version. Byte-identical observation"
    " content under two plan identities therefore produces two different semantic"
    " hashes, and the successor's must not be required to equal the predecessor's."
    " Content equality across plans is established by the raw fields together with the"
    " timestamp-set and structural hashes, which carry no plan identity."
)

# ---------------------------------------------------------------------------
# Sectioned operational snapshot convention
# ---------------------------------------------------------------------------

SNAPSHOT_CONVENTION = "phase-2b1r-sectioned-operational-snapshot-v1"

SNAPSHOT_LIMIT_STATEMENT = (
    "The established whole-object snapshot aggregated all 23 sections into one JSONB"
    " value. At the present evidence size the observations and candles sections alone"
    " require about 297.2 MB against PostgreSQL's 268,435,455-byte limit for a single"
    " JSONB object, so that formula can no longer be evaluated. Sectioning hashes each"
    " section independently, so no single JSONB value ever combines all sections. This"
    " avoids the current limit because every individual section is below it at this"
    " evidence size. It is not a claim of indefinite scalability: a single section that"
    " grows past the limit would require its own further decomposition."
)

SNAPSHOT_EMPTY_SECTION_RULE = (
    "A section with no rows aggregates to SQL NULL, market_sha256(NULL) is SQL NULL, and"
    " the section's value in the combined mapping is JSON null. Empty sections are never"
    " coalesced to an empty array, because that would change the digest of every"
    " historical snapshot."
)

SNAPSHOT_COMPARABILITY_STATEMENT = (
    "Sectioned digests are a new versioned operational-evidence convention. They are not"
    " numerically comparable to the earlier whole-object digests: the two formulas hash"
    " different structures over the same rows. Continuity is established by computing"
    " both conventions over one identical state, not by comparing their values."
)

# The exact 23 sections, in the exact order, with each section's exact row
# selection, alias and ORDER BY preserved from the established snapshot.
SNAPSHOT_SECTIONS = (
    ("discovery_plans", "market_historicaldiscoveryplan", "p", "p.id"),
    ("discovery_chunks", "market_historicaldiscoverychunk", "c", "c.id"),
    ("discovery_attempts", "market_historicaldiscoveryattempt", "a", "a.id"),
    ("runs", "market_ingestionrun", "r", "r.id"),
    ("inventories", "market_historicaltimestampinventory", "i", "i.id"),
    ("observations", "market_historicaltimestampobservation", "o", "o.id"),
    ("provider_evidence", "market_historicaldiscoveryproviderevidence", "e", "e.id"),
    ("audits", "market_auditevent", "ev", "ev.id"),
    ("approval", "market_historicaldiscoveryapproval", "ap", "ap.id"),
    ("registration", "market_historicaldiscoveryregistration", "rg", "rg.id"),
    ("supersession", "market_historicaldiscoverysupersession", "s", "s.id"),
    ("contracts", "market_historicaldatacontract", "hd", "hd.id"),
    ("acquisition_plans", "market_historicaldatasetplan", "hp", "hp.id"),
    ("acquisition_chunks", "market_historicalingestionchunk", "hc", "hc.id"),
    ("acquisition_attempts", "market_historicalingestionattempt", "ha", "ha.id"),
    ("manifests", "market_ingestionmanifest", "m", "m.id"),
    ("candles", "market_candle", "cd", "cd.id"),
    ("datasets", "market_datasetversion", "dv", "dv.id"),
    ("dataset_registrations", "market_datasetregistration", "dr", "dr.id"),
    ("strategy_definitions", "research_strategydefinition", "sd", "sd.id"),
    ("strategy_versions", "research_strategyversion", "sv", "sv.id"),
    ("strategy_manifests", "research_strategyparametermanifest", "sm", "sm.id"),
    ("schedules", "operations_scheduledjob", "j", "j.id"),
)

SNAPSHOT_SECTION_FORMULA = (
    "section_hash = market_sha256((SELECT jsonb_agg(to_jsonb(<alias>) ORDER BY <order>)"
    " FROM <table> <alias>)); snapshot = market_sha256(jsonb_build_object(<section name>,"
    " <section hash>, ... in the fixed section order))"
)


def _section_sql(name, table, alias, order):
    return (
        f"  '{name}',market_sha256((SELECT jsonb_agg(to_jsonb({alias})"
        f" ORDER BY {order}) FROM {table} {alias}))"
    )


def sectioned_snapshot_sql():
    """The authoritative single-statement implementation."""
    body = ",\n".join(_section_sql(*section) for section in SNAPSHOT_SECTIONS)
    return "SELECT market_sha256(jsonb_build_object(\n" + body + "))"


def section_hash_sql(name):
    """One section's hash on its own, for the independent reconstruction."""
    for section in SNAPSHOT_SECTIONS:
        if section[0] == name:
            _, table, alias, order = section
            return (
                f"SELECT market_sha256((SELECT jsonb_agg(to_jsonb({alias})"
                f" ORDER BY {order}) FROM {table} {alias}))"
            )
    raise ValueError("unknown snapshot section")


def sectioned_snapshot(cursor):
    """Implementation A: the authoritative snapshot, one statement."""
    cursor.execute(sectioned_snapshot_sql())
    return cursor.fetchone()[0]


def sectioned_snapshot_independent(cursor):
    """Implementation B: 23 separately issued section statements, combined in
    Python under ``canonical_hash``.

    What B proves: each section hash is reproducible as its own statement rather
    than only inside the combined one; the final section-name/hash combination
    agrees across languages, Python ``canonical_hash`` against PostgreSQL
    ``market_sha256(jsonb_build_object(...))``; and a SQL NULL section hash
    surfaces as Python ``None``, confirming the JSON-null empty-section rule.

    What B does not prove: it reads the same :data:`SNAPSHOT_SECTIONS` tuple and
    the same :func:`section_hash_sql` construction as A, so it shares the section
    enumeration, the table and alias definitions, the per-section SQL and the
    ordering. An error in that shared table would appear identically in both, so
    B is not evidence that the table itself is right. That was established
    separately, by hand-transcribing all 23 sections during independent Gate 8D3
    acceptance review and reproducing this convention's pinned digests from the
    independent transcription. Both implementations also necessarily share
    PostgreSQL's ``to_jsonb`` row rendering, which is the convention's definition.
    """
    mapping = {}
    for name, _table, _alias, _order in SNAPSHOT_SECTIONS:
        cursor.execute(section_hash_sql(name))
        mapping[name] = cursor.fetchone()[0]
    return canonical_hash(mapping), mapping


# ---------------------------------------------------------------------------
# Outcome reconstruction
# ---------------------------------------------------------------------------


def _shape(observations):
    return [
        {
            "timestamp": canonical_timestamp(item.timestamp),
            "complete": item.complete,
            "volume": item.volume,
            "bid_present": item.bid_present,
            "ask_present": item.ask_present,
        }
        for item in observations
    ]


def _registration_aggregates(plan):
    """The three plan-level aggregates, under the reviewed formulas from
    ``historical_discovery._registration_hashes``."""
    from market.models import HistoricalDiscoveryAttempt

    chunks = list(plan.chunks.select_related("inventory").order_by("ordinal"))
    manifest = [
        {
            "ordinal": item.ordinal,
            "logical_discovery_key": item.logical_key,
            "canonical_request": item.canonical_request,
            "canonical_request_sha256": item.canonical_request_sha256,
        }
        for item in chunks
    ]
    semantic_rows = [
        {
            "logical_discovery_key": item.logical_key,
            "semantic_inventory_sha256": item.inventory.semantic_inventory_sha256,
        }
        for item in chunks
    ]
    attempts = (
        HistoricalDiscoveryAttempt.objects.filter(chunk__plan=plan)
        .select_related("chunk", "provider_evidence")
        .order_by("chunk__ordinal", "attempt_number")
    )
    operational_rows = [item.provider_evidence.operational_evidence_sha256 for item in attempts]
    return {
        "request_manifest_sha256": canonical_hash(manifest),
        "global_semantic_inventory_sha256": canonical_hash(semantic_rows),
        "accepted_operational_evidence_set_sha256": canonical_hash(operational_rows),
    }


def _chunk_observations(chunk):
    from market.models import HistoricalTimestampObservation

    return list(
        HistoricalTimestampObservation.objects.filter(inventory__chunk=chunk).order_by("timestamp")
    )


def _is_extended(chunk):
    return (
        chunk.granularity == "H1"
        and chunk.canonical_request.get("from") == SUCCESSOR_H1_REQUESTED_FROM
    )


def build_gate8d3_outcome():
    """The deterministic outcome body, reconstructed from raw stored rows.

    Every count and digest is recomputed here; no stored summary column is
    copied through, and no strategy output is consulted.
    """
    from market.models import (
        AuditEvent,
        HistoricalDataContract,
        HistoricalDiscoveryApproval,
        HistoricalDiscoveryAttempt,
        HistoricalDiscoveryPlan,
        HistoricalDiscoveryProviderEvidence,
        HistoricalDiscoveryRegistration,
        HistoricalTimestampInventory,
        IngestionRun,
    )

    authorization = load_committed_gate8b_authorization()
    plan_payload = build_successor_discovery_plan()
    plan = HistoricalDiscoveryPlan.objects.get(sha256=plan_payload["plan_sha256"])
    predecessor = HistoricalDiscoveryPlan.objects.get(version=DISCOVERY_V2_VERSION)

    chunks = list(plan.chunks.select_related("instrument", "inventory").order_by("ordinal"))
    if len(chunks) != EXPECTED_CHUNK_COUNT:
        raise ValueError("the successor plan does not hold its 132 governed chunks")
    predecessor_chunks = {
        (item.instrument.code, item.granularity, item.ordinal): item
        for item in predecessor.chunks.select_related("instrument", "inventory")
    }

    attempts = {
        item.chunk_id: item
        for item in HistoricalDiscoveryAttempt.objects.filter(chunk__plan=plan).select_related(
            "ingestion_run", "provider_evidence"
        )
    }
    boundary = parse_timestamp(PREDECESSOR_H1_REQUESTED_FROM)
    LAST_WARMUP_TIMESTAMP = parse_timestamp(LAST_WARMUP_TIMESTAMP_LITERAL)

    records = []
    restricted_rows = []
    predecessor_rows = []
    granularity_totals = {"D": 0, "H1": 0, "W": 0}
    total_observations = 0
    extension_observations = 0
    warmup = {}

    for chunk in chunks:
        attempt = attempts.get(chunk.pk)
        if attempt is None:
            raise ValueError(f"successor chunk ordinal {chunk.ordinal} has no attempt")
        run = attempt.ingestion_run
        evidence = attempt.provider_evidence
        inventory = chunk.inventory
        observations = _chunk_observations(chunk)
        rows = _shape(observations)
        timestamp_hash = canonical_hash([row["timestamp"] for row in rows])
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
        if (timestamp_hash, structural_hash, semantic_hash) != (
            inventory.timestamp_set_sha256,
            inventory.structural_observation_sha256,
            inventory.semantic_inventory_sha256,
        ):
            raise ValueError(f"inventory hashes do not reconstruct for ordinal {chunk.ordinal}")

        total_observations += len(rows)
        granularity_totals[chunk.granularity] += len(rows)
        counterpart = predecessor_chunks[(chunk.instrument.code, chunk.granularity, chunk.ordinal)]
        counterpart_observations = _chunk_observations(counterpart)
        counterpart_rows = _shape(counterpart_observations)

        record = {
            "ordinal": chunk.ordinal,
            "instrument": chunk.instrument.code,
            "granularity": chunk.granularity,
            "requested_from": canonical_timestamp(chunk.requested_from),
            "requested_to": canonical_timestamp(chunk.requested_to),
            "canonical_request_sha256": chunk.canonical_request_sha256,
            "logical_discovery_key": chunk.logical_key,
            "attempt_number": attempt.attempt_number,
            "run_status": run.status,
            "observation_count": len(rows),
            "timestamp_set_sha256": timestamp_hash,
            "structural_observation_sha256": structural_hash,
            "semantic_inventory_sha256": semantic_hash,
            "terminal_event_sha256": evidence.terminal_event_sha256,
            "operational_evidence_sha256": evidence.operational_evidence_sha256,
            "predecessor_logical_discovery_key": counterpart.logical_key,
            "predecessor_canonical_request_sha256": counterpart.canonical_request_sha256,
            "predecessor_observation_count": len(counterpart_rows),
        }

        if _is_extended(chunk):
            earlier = [item for item in observations if item.timestamp < boundary]
            restricted = [item for item in observations if item.timestamp >= boundary]
            restricted_shaped = _shape(restricted)
            extension_observations += len(earlier)
            # Warm-up eligibility is by completion, and an H1 candle completes
            # one hour after its own timestamp, so the last eligible timestamp
            # is one hour before the unchanged development start.
            predecessor_warmup = [
                item
                for item in counterpart_observations
                if item.complete and item.timestamp <= LAST_WARMUP_TIMESTAMP
            ]
            qualifying = [
                item
                for item in earlier
                if item.complete and item.timestamp <= LAST_WARMUP_TIMESTAMP
            ]
            record["chunk_role"] = "extended_first_h1"
            record["restricted_overlap_count"] = len(restricted_shaped)
            record["restricted_overlap_sha256"] = canonical_hash(restricted_shaped)
            record["predecessor_overlap_identical"] = (
                restricted_shaped == counterpart_rows
                and canonical_hash(restricted_shaped) == canonical_hash(counterpart_rows)
            )
            record["earlier_completed_observations"] = len(qualifying)
            warmup[chunk.instrument.code] = {
                "instrument": chunk.instrument.code,
                "logical_discovery_key": chunk.logical_key,
                "first_h1_observation_count": len(rows),
                "predecessor_overlap_count": len(restricted_shaped),
                "earlier_completed_observations": len(qualifying),
                "predecessor_warmup_observations": len(predecessor_warmup),
                "combined_completed_warmup_observations": len(qualifying) + len(predecessor_warmup),
                "required_warmup_observations": REQUIRED_H1_WARMUP_OBSERVATIONS,
                "restricted_overlap_sha256": canonical_hash(restricted_shaped),
                "missing_overlap_timestamps": len(
                    {row["timestamp"] for row in counterpart_rows}
                    - {row["timestamp"] for row in restricted_shaped}
                ),
                "extra_overlap_timestamps": len(
                    {row["timestamp"] for row in restricted_shaped}
                    - {row["timestamp"] for row in counterpart_rows}
                ),
                "volume_mismatches": sum(
                    1
                    for left, right in zip(restricted_shaped, counterpart_rows)
                    if left["volume"] != right["volume"]
                ),
                "completeness_mismatches": sum(
                    1
                    for left, right in zip(restricted_shaped, counterpart_rows)
                    if left["complete"] != right["complete"]
                ),
                "presence_mismatches": sum(
                    1
                    for left, right in zip(restricted_shaped, counterpart_rows)
                    if (left["bid_present"], left["ask_present"])
                    != (right["bid_present"], right["ask_present"])
                ),
            }
            restricted_rows.extend(restricted_shaped)
        else:
            record["chunk_role"] = "unchanged_range"
            record["content_identical_to_predecessor"] = rows == counterpart_rows
            record["predecessor_timestamp_set_sha256"] = canonical_hash(
                [row["timestamp"] for row in counterpart_rows]
            )
            record["predecessor_structural_observation_sha256"] = canonical_hash(counterpart_rows)
            restricted_rows.extend(rows)
        predecessor_rows.extend(counterpart_rows)
        records.append(record)

    aggregates = _registration_aggregates(plan)
    runs = IngestionRun.objects.filter(historical_discovery_attempt__chunk__plan=plan)
    audit_ids = [str(item.pk) for item in attempts.values()]
    body = {
        "schema": ARTIFACT_SCHEMA,
        "authority_statement": AUTHORITY_STATEMENT,
        "strategy_attestation": STRATEGY_ATTESTATION,
        "semantic_hash_statement": SEMANTIC_HASH_STATEMENT,
        "gate8b_authorization_file_sha256": AUTHORIZATION_FILE_SHA256,
        "gate8b_authorization_self_sha256": authorization["authorization_sha256"],
        "governance_migration": MIGRATION_0023_NAME,
        "governance_migration_sha256": MIGRATION_0023_SHA256,
        "predecessor_discovery_plan_version": DISCOVERY_V2_VERSION,
        "predecessor_discovery_plan_sha256": DISCOVERY_V2_PLAN_SHA256,
        "predecessor_request_manifest_sha256": DISCOVERY_V2_MANIFEST_SHA256,
        "predecessor_global_semantic_inventory_sha256": GLOBAL_SEMANTIC_INVENTORY_SHA256,
        "predecessor_completion_summary_sha256": DISCOVERY_COMPLETION_SUMMARY_SHA256,
        "predecessor_registration_configuration_sha256": (
            PREDECESSOR_REGISTRATION_CONFIGURATION_SHA256
        ),
        "predecessor_registration_report_sha256": PREDECESSOR_REGISTRATION_REPORT_SHA256,
        "successor_discovery_plan_identity": SUCCESSOR_DISCOVERY_PLAN_IDENTITY,
        "successor_discovery_plan_version": SUCCESSOR_DISCOVERY_VERSION,
        "successor_discovery_plan_sha256": plan_payload["plan_sha256"],
        "successor_request_manifest_sha256": aggregates["request_manifest_sha256"],
        "successor_global_semantic_inventory_sha256": aggregates[
            "global_semantic_inventory_sha256"
        ],
        "successor_accepted_operational_evidence_set_sha256": aggregates[
            "accepted_operational_evidence_set_sha256"
        ],
        "successor_h1_requested_from": SUCCESSOR_H1_REQUESTED_FROM,
        "predecessor_h1_requested_from": PREDECESSOR_H1_REQUESTED_FROM,
        "completion": {
            "chunks": len(chunks),
            "attempts": len(attempts),
            "distinct_attempted_chunks": len({item.chunk_id for item in attempts.values()}),
            "succeeded_runs": runs.filter(status=IngestionRun.Status.SUCCEEDED).count(),
            "provider_evidence_rows": HistoricalDiscoveryProviderEvidence.objects.filter(
                attempt__chunk__plan=plan
            ).count(),
            "accepted_inventories": HistoricalTimestampInventory.objects.filter(
                chunk__plan=plan
            ).count(),
            "success_audit_events": AuditEvent.objects.filter(
                subject_type="HistoricalDiscoveryAttempt",
                subject_id__in=audit_ids,
                event_type="market.historical_discovery_succeeded",
            ).count(),
            "attempts_beyond_first": HistoricalDiscoveryAttempt.objects.filter(
                chunk__plan=plan, attempt_number__gt=1
            ).count(),
            "failed_or_quarantined_runs": runs.filter(status__in=TERMINAL_FAILURE_STATUSES).count(),
            "running_runs": runs.filter(status=IngestionRun.Status.RUNNING).count(),
            "missing_inventories": len(chunks)
            - HistoricalTimestampInventory.objects.filter(chunk__plan=plan).count(),
            "failure_audit_events": AuditEvent.objects.filter(
                subject_type="HistoricalDiscoveryAttempt",
                subject_id__in=audit_ids,
                event_type="market.historical_discovery_failed",
            ).count(),
            "plan_sealed": plan.sealed_at is not None,
            "plan_approvals": HistoricalDiscoveryApproval.objects.filter(plan=plan).count(),
            "plan_registrations": HistoricalDiscoveryRegistration.objects.filter(plan=plan).count(),
            "successor_bound_contracts": sum(
                1
                for item in HistoricalDataContract.objects.all()
                if getattr(item, "discovery_plan_id", None) == plan.pk
            ),
        },
        "observations": {
            "total": total_observations,
            "by_granularity": dict(sorted(granularity_totals.items())),
            "restricted_predecessor_equivalent": len(restricted_rows),
            "extension_observations": extension_observations,
            "extension_per_instrument": EXPECTED_EARLIER_PER_INSTRUMENT,
            "extension_instruments": len(INSTRUMENTS),
        },
        "restricted_overlap": {
            "successor_restricted_sha256": canonical_hash(restricted_rows),
            "predecessor_sha256": canonical_hash(predecessor_rows),
            "identical": canonical_hash(restricted_rows) == canonical_hash(predecessor_rows),
            "observation_count": len(restricted_rows),
            "ordering": (
                "chunks in governed plan-ordinal order; observations within a chunk in"
                " ascending timestamp order"
            ),
        },
        "warmup_proof": [warmup[code] for code in sorted(warmup)],
        "canary_instrument": CANARY_INSTRUMENT,
        "chunk_records": records,
        "sectioned_snapshot": _snapshot_section(),
    }
    return {**body, "outcome_sha256": canonical_hash(body)}


def _snapshot_section():
    """The snapshot convention as pinned evidence, with its continuity anchors."""
    return {
        "convention": SNAPSHOT_CONVENTION,
        "section_count": len(SNAPSHOT_SECTIONS),
        "section_order": [name for name, _t, _a, _o in SNAPSHOT_SECTIONS],
        "section_formula": SNAPSHOT_SECTION_FORMULA,
        "empty_section_rule": SNAPSHOT_EMPTY_SECTION_RULE,
        "limit_statement": SNAPSHOT_LIMIT_STATEMENT,
        "comparability_statement": SNAPSHOT_COMPARABILITY_STATEMENT,
        "session_timezone": "America/Toronto",
        "django_connection_timezone": "UTC",
        "empty_sections": ["schedules"],
        "independent_reconstruction": (
            "Two implementations must agree: (A) one statement combining all 23 section"
            " hashes through market_sha256(jsonb_build_object(...)), and (B) 23 separately"
            " issued single-section statements whose results are combined in Python under"
            " canonical_hash. What B proves: that each section hash is reproducible as its"
            " own statement rather than only inside the combined one; that the final"
            " section-name/hash combination agrees across languages, Python canonical_hash"
            " against PostgreSQL market_sha256(jsonb_build_object(...)); and that a SQL NULL"
            " section hash surfaces as Python None, confirming the JSON-null empty-section"
            " representation. What B does not prove: it reads the same SNAPSHOT_SECTIONS"
            " tuple and the same section_hash_sql() construction as A, so it shares the"
            " section enumeration, the table and alias definitions, the per-section SQL"
            " construction and the ordering, and an error in that shared table would appear"
            " identically in both. The section table was instead validated by separate"
            " transcription during independent Gate 8D3 acceptance review, which rewrote all"
            " 23 sections by hand and reproduced this convention's pinned digests from that"
            " independent transcription."
        ),
        "pre_gate8d2_content_definition": (
            "Every row except the discovery attempts, runs, inventories, observations,"
            " provider evidence and attempt-scoped audit events belonging to the successor"
            " plan chunks whose logical discovery key is in the gate8d2_remainder stage of"
            " the committed Gate 8B artifact. The exclusion is expressed by logical"
            " discovery key, never by primary key, so it is reproducible from portable"
            " identities alone."
        ),
        "legacy_whole_object_pre_gate8d2_sha256": (
            "a80b1dcd9ae3297652b61b3f74a341adc288eb908ffa6a8750bc9e5a08897438"
        ),
        "sectioned_pre_gate8d2_sha256": (
            "b0405e22cb9eee52fd40bba4891bed499ef8d649f8457a7606cc196c2550c503"
        ),
        "sectioned_post_gate8d2_sha256": (
            "2d44278d1fda6046ff7c21759decc77a6c8ab966cb7ab473b316ce7131601292"
        ),
    }


def canonical_outcome_bytes(outcome=None):
    """The canonical JSON encoding this artifact is committed as."""
    outcome = outcome or build_gate8d3_outcome()
    return json.dumps(outcome, sort_keys=True, separators=(",", ":")).encode()


def gate8d3_outcome_path():
    return (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "strategy"
        / "failed-break"
        / "v1"
        / ARTIFACT_NAME
    )


def _verify_committed_outcome(*, expected_file_sha256):
    """Bytes, governed digest, parse, self-hash, canonical determinism.

    The digest is required rather than optional, so a caller cannot reach this
    without naming the bytes it expects. Only tests pass anything but the
    governed constant, and they do so to reach a layer the constant would
    shadow. Messages name at most the artifact filename.
    """
    path = gate8d3_outcome_path()
    # 1-2: the committed bytes against a digest pinned in code, never taken
    # from the document under inspection.
    try:
        committed = path.read_bytes()
    except OSError as error:
        raise ValueError(f"committed artifact {ARTIFACT_NAME} cannot be read") from error
    if hashlib.sha256(committed).hexdigest() != expected_file_sha256:
        raise ValueError(f"committed artifact {ARTIFACT_NAME} does not match its governed pin")
    # 3: parse.
    try:
        document = json.loads(committed)
    except ValueError as error:
        raise ValueError(f"committed artifact {ARTIFACT_NAME} is not valid JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"committed artifact {ARTIFACT_NAME} is not a JSON object")
    # 4: the document's own self-hash, recomputed from the committed body.
    claimed = document.get("outcome_sha256")
    if not isinstance(claimed, str):
        raise ValueError(f"committed artifact {ARTIFACT_NAME} carries no self-hash")
    body = {key: value for key, value in document.items() if key != "outcome_sha256"}
    if claimed != canonical_hash(body):
        raise ValueError(f"committed artifact {ARTIFACT_NAME} self-hash does not verify")
    # 5: the committed bytes are the canonical encoding of what they parse to,
    # so a reordered, duplicated or non-canonical document is refused here even
    # before any database is consulted.
    if committed != json.dumps(document, sort_keys=True, separators=(",", ":")).encode():
        raise ValueError(f"committed artifact {ARTIFACT_NAME} is not canonical JSON")
    return document


def load_committed_gate8d3_outcome():
    """The committed outcome artifact, accepted only when its bytes hash to the
    governed file digest, it parses, its embedded self-hash verifies against its
    own body, and its bytes are the canonical encoding of that body.

    This loader consults no database, so it is cheap and always safe to call.
    It deliberately takes no argument: there is no caller-supplied digest and no
    bypass. Deterministic regeneration against the live rows is the separate,
    explicit :func:`verify_gate8d3_outcome_against_database`.
    """
    return _verify_committed_outcome(expected_file_sha256=OUTCOME_ARTIFACT_SHA256)


def verify_gate8d3_outcome_against_database():
    """The committed artifact plus full deterministic regeneration from raw rows.

    This reconstructs every observation of the completed plan, so it is the
    expensive mode and is requested explicitly rather than folded into the
    loader. It never writes and never builds a provider client.
    """
    document = load_committed_gate8d3_outcome()
    regenerated = build_gate8d3_outcome()
    if canonical_outcome_bytes(regenerated) != gate8d3_outcome_path().read_bytes():
        raise ValueError(f"committed artifact {ARTIFACT_NAME} does not reconstruct")
    return document


def accepted_successor_registration():
    """The independently accepted successor outcome, as the registration path's
    admission profile.

    Every value is read from the committed Gate 8D3 artifact only after that
    artifact has passed its governed loader: bytes against the code-pinned file
    digest, then its embedded self-hash, then canonical form. This is Python
    provenance, not database authority — migration 0024 pins the same values as
    literals and recomputes them from raw rows, so nothing here can widen what
    PostgreSQL admits.
    """
    document = load_committed_gate8d3_outcome()
    completion = document["completion"]
    observations = document["observations"]
    if (
        completion["chunks"] != EXPECTED_CHUNK_COUNT
        or observations["total"] != EXPECTED_OBSERVATION_TOTAL
        or observations["by_granularity"] != EXPECTED_GRANULARITY_OBSERVATIONS
    ):
        raise ValueError(f"committed artifact {ARTIFACT_NAME} is not the accepted outcome")
    return {
        "plan_sha256": document["successor_discovery_plan_sha256"],
        "plan_identity": document["successor_discovery_plan_identity"],
        "plan_version": document["successor_discovery_plan_version"],
        "request_manifest_sha256": document["successor_request_manifest_sha256"],
        "global_semantic_inventory_sha256": document["successor_global_semantic_inventory_sha256"],
        "accepted_operational_evidence_set_sha256": document[
            "successor_accepted_operational_evidence_set_sha256"
        ],
        "restricted_overlap_sha256": document["restricted_overlap"]["successor_restricted_sha256"],
        "chunk_count": completion["chunks"],
        "observation_count": observations["total"],
        "outcome_artifact_sha256": OUTCOME_ARTIFACT_SHA256,
    }
