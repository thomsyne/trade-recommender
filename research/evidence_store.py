"""Explicit, dormant Phase 7 persistence. No automatic ingestion or delivery hook."""

import hashlib

from django.db import transaction
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
    EvidenceIncident,
    EvidenceRightsReview,
    ExactEvidence,
    FrozenEvidencePacket,
)
from research.parsers import parse_feed


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


def verify_representation(payload, retrieval, *, document=None, observation=None):
    validate_representation(payload)
    require(payload["retrieval_id"] == retrieval.pk, "wrong_retrieval")
    require(
        payload["retrieval_sha256"]
        == retrieval.body_sha256
        == hashlib.sha256(bytes(retrieval.body)).hexdigest(),
        "retrieval_hash",
    )
    require(payload["source_id"] == retrieval.source_policy.source_id, "wrong_source")
    require(payload["retrieved_at"] == iso(retrieval.fetched_at), "retrieval_time")
    require(payload["content_type"] == retrieval.content_type, "content_type")
    if document:
        require(
            payload["document_id"] == document.pk and payload["observation_id"] is None,
            "cross_document",
        )
        require(
            payload["canonical_hash"] == document.canonical_hash
            and payload["canonical_url"] == document.canonical_url,
            "canonical_identity",
        )
        require(payload["first_observed_at"] == iso(document.first_observed_at), "observation_time")
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
    else:
        require(
            observation is not None
            and payload["observation_id"] == observation.pk
            and payload["document_id"] is None,
            "wrong_observation",
        )
        require(observation.retrieval_id == retrieval.pk, "wrong_retrieval")
        require(
            payload["source_item_id"] == str(observation.pk)
            and payload["normalized_fact"] == observation.normalized_value,
            "observation_value",
        )
        require(
            payload["headline"] == observation.series.label and payload["supplied_summary"] == "",
            "observation_label",
        )
        require(payload["published_at"] == iso(observation.available_at), "observation_time")


@transaction.atomic
def store_representation(payload, *, retrieval, storage_review, document=None, observation=None):
    verify_representation(payload, retrieval, document=document, observation=observation)
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


@transaction.atomic
def freeze_packet(instrument, *, cutoff, required_ids=()):
    """Universe = ALL exact evidence known by cutoff; SQL verifies completeness.

    Nothing invokes this on import, ingestion, recommendation or a schedule.
    Unknown rights and legacy material that lacks exact representations stay out.
    """
    require(cutoff <= timezone.now(), "future_cutoff")
    required_ids = sorted(required_ids)
    candidates = []
    rows = ExactEvidence.objects.filter(recorded_at__lte=cutoff).order_by("digest")
    for row in rows:
        rights = (
            EvidenceRightsReview.objects.filter(
                source_id=row.payload["source_id"],
                payload__processor="anthropic",
                recorded_at__lte=cutoff,
            )
            .order_by("-recorded_at", "-pk")
            .first()
        )
        events = EvidenceConflict.objects.filter(
            earlier__payload__canonical_hash=row.payload["canonical_hash"], recorded_at__lte=cutoff
        ).order_by("digest")
        candidates.append(
            {
                "id": row.digest,
                "representation": row.payload,
                "known_at": iso(row.recorded_at),
                "rights": rights.payload if rights else None,
                "rights_known_at": iso(rights.recorded_at) if rights else None,
                "conflicts": [
                    {
                        "digest": e.digest,
                        "known_at": iso(e.recorded_at),
                        "class": e.payload["class"],
                        "changed_fields": e.payload["changed_fields"],
                    }
                    for e in events
                ],
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


def audit_integrity():
    counts = {}
    for model in (
        EvidenceRightsReview,
        ExactEvidence,
        EvidenceConflict,
        FrozenEvidencePacket,
        EvidenceIncident,
    ):
        count = 0
        for row in model.objects.iterator():
            require(row.digest == digest(row.payload), "stored_digest")
            if model is EvidenceRightsReview:
                validate_review(row.payload)
            elif model is ExactEvidence:
                verify_representation(
                    row.payload, row.retrieval, document=row.document, observation=row.observation
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
                replay(row.payload)
            else:
                require(row.payload == incident_payload(row.conflict), "incident_replay")
            count += 1
        counts[model.__name__] = count
    return counts
