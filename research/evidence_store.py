"""Explicit, dormant Phase 7 persistence. No automatic ingestion or delivery hook."""

import hashlib
import json
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree
from django.db import connection, transaction
from django.utils import timezone

from research.evidence_quality import (
    VERSION,
    build_packet,
    classify_change,
    digest,
    iso,
    permission,
    replay,
    require,
    validate_representation,
    validate_review,
)
from research.models import (
    EvidenceConflict,
    EvidenceContextResult,
    EvidenceIncident,
    EvidenceLegacyAdmission,
    EvidenceRightsReview,
    ExactEvidence,
    FrozenEvidencePacket,
    ResearchDiscrepancy,
)
from research.parsers import parse_feed


def _lock():
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        require(cursor.fetchone()[0] == "read committed", "requires_read_committed")
        cursor.execute("SELECT pg_advisory_xact_lock(7007001)")


def _append(model, payload, **identity):
    row, _ = model.objects.get_or_create(
        digest=digest(payload), defaults={"payload": payload, **identity}
    )
    require(row.payload == payload, "identity_collision")
    # SQL stamps knowledge time; never let caller time backdate discovery.
    row.refresh_from_db()
    return row


@transaction.atomic
def review_rights(source, payload):
    _lock()
    validate_review(payload)
    require(payload["source_id"] == source.pk, "wrong_source")
    # Serialize prospective review chains per source, independently of processor.
    type(source).objects.select_for_update().get(pk=source.pk)
    prior = (
        EvidenceRightsReview.objects.filter(source=source, payload__processor=payload["processor"])
        .order_by("-recorded_at", "-pk")
        .first()
    )
    existing = EvidenceRightsReview.objects.filter(digest=digest(payload)).first()
    if existing:
        return existing
    require(payload["supersedes"] == (prior.digest if prior else None), "rights_chain")
    return _append(EvidenceRightsReview, payload, source=source)


def news_timestamp_precision(body, matches):
    """Inspect the original timestamp, not the parser's UTC fallback datetime."""
    precisions = set()
    for node in ElementTree.fromstring(body).iter():
        if node.tag.rsplit("}", 1)[-1] not in {"item", "entry"}:
            continue
        if parse_feed(ElementTree.tostring(node))[0] not in matches:
            continue
        raw = next(
            (
                child.text
                for child in node
                if child.tag.rsplit("}", 1)[-1] in {"pubDate", "published", "updated", "date"}
                and child.text
            ),
            "",
        ).strip()
        precision = "unknown"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            precision = "date_only"
        elif re.search(r"\d{2}:\d{2}:\d{2}", raw):
            try:
                try:
                    parsed = parsedate_to_datetime(raw)
                except (TypeError, ValueError):
                    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    precision = "provider_exact"
            except ValueError:
                pass
        precisions.add(precision)
    return precisions.pop() if len(precisions) == 1 else "unknown"


def verify_representation(
    payload,
    retrieval,
    *,
    document=None,
    observation=None,
    replay_only=False,
    admitted_macro_label=None,
):
    validate_representation(payload)
    require(payload["retrieval_id"] == retrieval.pk, "wrong_retrieval")
    require(
        payload["retrieval_sha256"]
        == retrieval.body_sha256
        == hashlib.sha256(bytes(retrieval.body)).hexdigest(),
        "retrieval_hash",
    )
    if not replay_only:
        require(payload["source_id"] == retrieval.source_policy.source_id, "wrong_source")
    require(payload["retrieved_at"] == iso(retrieval.fetched_at), "retrieval_time")
    require(payload["content_type"] == retrieval.content_type, "content_type")
    if document:
        require(
            payload["document_id"] == document.pk and payload["observation_id"] is None,
            "cross_document",
        )
        if not replay_only:
            require(
                payload["canonical_hash"] == document.canonical_hash
                and payload["canonical_url"] == document.canonical_url,
                "canonical_identity",
            )
            require(
                payload["first_observed_at"] == iso(document.first_observed_at), "observation_time"
            )
        matches = [
            item
            for item in parse_feed(bytes(retrieval.body))
            if item.item_id == payload["source_item_id"]
            and item.url == payload["canonical_url"]
            and item.title == payload["headline"]
            and item.summary == payload["supplied_summary"]
            and (iso(item.published_at) if item.published_at else None) == payload["published_at"]
        ]
        require(bool(matches) and payload["normalized_fact"] == "", "unproven_representation")
        precision = news_timestamp_precision(bytes(retrieval.body), matches)
        require(
            payload["quality"]["timestamp_precision"] in {precision, "unknown"},
            "timestamp_provenance",
        )
    else:
        require(
            observation is not None
            and payload["observation_id"] == observation.pk
            and payload["document_id"] is None,
            "wrong_observation",
        )
        require(observation.retrieval_id == retrieval.pk, "wrong_retrieval")
        require(
            payload["canonical_hash"]
            == digest(["macro", observation.series_id, observation.observation_period.isoformat()]),
            "macro_identity",
        )
        require(
            payload["canonical_url"] == retrieval.url
            and payload["first_observed_at"] == iso(retrieval.fetched_at),
            "macro_provenance",
        )
        require(
            payload["source_item_id"] == str(observation.pk)
            and payload["normalized_fact"] == observation.normalized_value,
            "observation_value",
        )
        label = admitted_macro_label if replay_only else observation.series.label
        require(
            label is not None
            and payload["headline"] == label
            and payload["supplied_summary"] == "",
            "observation_label",
        )
        precision = {"provider": "provider_exact", "retrieval": "retrieval_only"}.get(
            observation.availability_precision, "unknown"
        )
        require(
            payload["quality"]["timestamp_precision"] in {precision, "unknown"},
            "timestamp_provenance",
        )
        require(payload["published_at"] == iso(observation.available_at), "observation_time")


@transaction.atomic
def store_representation(payload, *, retrieval, storage_review, document=None, observation=None):
    _lock()
    verify_representation(payload, retrieval, document=document, observation=observation)
    if document is not None:
        admit_legacy_conflicts(document)
    require(payload["storage_review_sha256"] == storage_review.digest, "wrong_rights_identity")
    now = timezone.now()
    latest = (
        EvidenceRightsReview.objects.filter(
            source_id=payload["source_id"], payload__processor="local"
        )
        .order_by("-recorded_at", "-pk")
        .first()
    )
    require(latest == storage_review, "superseded_rights")
    for field in ("headline", "supplied_summary", "normalized_fact", "url_attribution"):
        if field == "url_attribution" or payload[field]:
            require(
                permission(
                    storage_review.payload,
                    source_id=payload["source_id"],
                    field=field,
                    use="private_storage",
                    processor="local",
                    cutoff=now,
                )
                == "allowed",
                "storage_rights_blocked",
            )
    return _append(
        ExactEvidence,
        payload,
        document=document,
        observation=observation,
        retrieval=retrieval,
        storage_review=storage_review,
    )


@transaction.atomic
def record_conflict(earlier, later, *, declaration=None):
    change = classify_change(earlier.payload, later.payload, declaration)
    payload = {"version": VERSION, "earlier": earlier.digest, "later": later.digest, **change}
    return _append(EvidenceConflict, payload, earlier=earlier, later=later)


def legacy_admission_payload(discrepancy):
    return {
        "version": VERSION,
        "discrepancy_id": discrepancy.pk,
        "document": discrepancy.entity_key.removeprefix("document:"),
        "legacy_observed_at": iso(discrepancy.observed_at),
        "historical_arrival": "unknown",
    }


@transaction.atomic
def admit_legacy_conflicts(document):
    """Explicit opt-in discovery. Invoke before choosing a future packet cutoff.

    No hook is installed on legacy ingestion. observed_at remains a legacy claim;
    only this database-stamped admission is prospective Phase7 knowledge.
    """
    _lock()
    rows = []
    for discrepancy in ResearchDiscrepancy.objects.filter(
        kind="conflict", entity_key="document:" + document.canonical_hash
    ).order_by("pk"):
        rows.append(
            _append(
                EvidenceLegacyAdmission,
                legacy_admission_payload(discrepancy),
                discrepancy=discrepancy,
            )
        )
    return rows


@transaction.atomic
def freeze_packet(instrument, *, cutoff, required_ids=()):
    """Universe = ALL exact evidence known by cutoff; SQL verifies completeness.

    Nothing invokes this on import, ingestion, recommendation or a schedule.
    Unknown rights and legacy material that lacks exact representations stay out.
    """
    _lock()
    require(cutoff <= timezone.now(), "future_cutoff")
    required_ids = sorted(required_ids)
    candidates = []
    rows = ExactEvidence.objects.filter(recorded_at__lte=cutoff).order_by("digest")
    for row in rows:
        verify_representation(
            row.payload,
            row.retrieval,
            document=row.document,
            observation=row.observation,
            replay_only=True,
            admitted_macro_label=row.admitted_macro_label,
        )
        rights = (
            EvidenceRightsReview.objects.filter(
                source_id=row.payload["source_id"],
                payload__processor="anthropic",
                recorded_at__lte=cutoff,
            )
            .order_by("-recorded_at", "-pk")
            .first()
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT phase7_conflicts(%s,%s)", [row.payload["canonical_hash"], cutoff]
            )
            events = cursor.fetchone()[0]
            if isinstance(events, str):
                events = json.loads(events)
        candidates.append(
            {
                "id": row.digest,
                "representation": row.payload,
                "known_at": iso(row.recorded_at),
                "rights": rights.payload if rights else None,
                "rights_known_at": iso(rights.recorded_at) if rights else None,
                "conflicts": events,
                "role": "required" if row.digest in required_ids else "contextual",
            }
        )
    payload = build_packet(
        instrument=instrument.code,
        cutoff=iso(cutoff),
        candidates=candidates,
        required_ids=required_ids,
    )
    replay(payload)
    return _append(FrozenEvidencePacket, payload, instrument=instrument, cutoff=cutoff)


def incident_payload(conflict):
    # Include changed value fingerprints: distinct material changes cannot collapse.
    fields = sorted(conflict.payload["changed_fields"])
    values = {
        field: [conflict.earlier.payload[field], conflict.later.payload[field]] for field in fields
    }
    return {
        "version": VERSION,
        "document": conflict.earlier.payload["canonical_hash"],
        "class": conflict.payload["class"],
        "fields": fields,
        "change_sha256": digest(values),
        "window": int(conflict.recorded_at.timestamp()) // 86400,
        "message": "Evidence discrepancy recorded; review required.",
    }


@transaction.atomic
def record_incident(conflict):
    """Logical identity only. Existing discrepancies and delivery systems untouched."""
    return _append(EvidenceIncident, incident_payload(conflict), conflict=conflict)


@transaction.atomic
def notify_incident(conflict):
    """Explicit admin/test delivery seam; never called by ingestion or packet creation."""
    from operations.notifications import create_owner_notification

    incident = record_incident(conflict)
    return create_owner_notification(
        idempotency_key="phase7-evidence:" + incident.digest,
        kind="evidence_discrepancy",
        severity="warning",
        title="Evidence discrepancy requires review",
        body="An immutable evidence discrepancy was recorded. Review its qualified evidence before use.",
        action_path="",
        subject_type="phase7_evidence_incident",
        subject_id=str(incident.pk),
    )


def load_frozen_packet(packet_id):
    """Replay only frozen identities and immutable retrieval bytes, not current policies."""
    packet = FrozenEvidencePacket.objects.get(pk=packet_id)
    require(packet.digest == digest(packet.payload), "stored_digest")
    replay(packet.payload)
    for entry in packet.payload["entries"]:
        candidate = entry["candidate"]
        row = ExactEvidence.objects.get(digest=candidate["id"])
        require(row.payload == candidate["representation"], "stored_representation")
        verify_representation(
            row.payload,
            row.retrieval,
            document=row.document,
            observation=row.observation,
            replay_only=True,
            admitted_macro_label=row.admitted_macro_label,
        )
    return packet


def audit_integrity():
    from forecasts.evidence_context import replay_context_result

    counts = {}
    for model in (
        EvidenceRightsReview,
        ExactEvidence,
        EvidenceConflict,
        FrozenEvidencePacket,
        EvidenceIncident,
        EvidenceContextResult,
        EvidenceLegacyAdmission,
    ):
        count = 0
        for row in model.objects.iterator():
            require(row.digest == digest(row.payload), "stored_digest")
            if model is EvidenceRightsReview:
                validate_review(row.payload)
            elif model is ExactEvidence:
                verify_representation(
                    row.payload,
                    row.retrieval,
                    document=row.document,
                    observation=row.observation,
                    replay_only=True,
                    admitted_macro_label=row.admitted_macro_label,
                )
            elif model is EvidenceConflict:
                declaration = (
                    row.payload["class"]
                    if row.payload["class"]
                    in {"provider_correction", "material_disagreement", "retraction"}
                    else None
                )
                change = classify_change(row.earlier.payload, row.later.payload, declaration)
                require(all(row.payload[k] == v for k, v in change.items()), "conflict_replay")
            elif model is FrozenEvidencePacket:
                load_frozen_packet(row.pk)
            elif model is EvidenceContextResult:
                replay_context_result(row)
            elif model is EvidenceLegacyAdmission:
                require(row.payload == legacy_admission_payload(row.discrepancy), "legacy_replay")
            else:
                require(row.payload == incident_payload(row.conflict), "incident_replay")
            count += 1
        counts[model.__name__] = count
    return counts
