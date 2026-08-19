import hashlib

from django.db import transaction

from market.models import AuditEvent
from research.fetch import fetch
from research.models import (
    DocumentRepresentation,
    MacroObservation,
    RawRetrieval,
    ResearchDiscrepancy,
    ResearchDocument,
)
from research.parsers import ParseRejected, parse_feed, parse_macro


def ingest_feed(policy, url, *, transport=None, resolver=None, now=None):
    options = {"transport": transport, "now": now}
    if resolver is not None:
        options["resolver"] = resolver
    result = fetch(policy, url, **options)
    try:
        items = parse_feed(result.body)
    except ParseRejected:
        with transaction.atomic():
            retrieval = _store_raw(
                policy,
                result,
                quality=RawRetrieval.Quality.QUARANTINED,
                quality_reason="Feed parsing failed closed",
            )
            _audit("research.feed_quarantined", retrieval, {})
        raise
    with transaction.atomic():
        retrieval = _store_raw(policy, result)
        created = 0
        for item in items:
            canonical_hash = _digest(item.url)
            quality = (
                ResearchDocument.Quality.VERIFIED
                if item.published_at
                else ResearchDocument.Quality.QUARANTINED
            )
            document, document_created = ResearchDocument.objects.get_or_create(
                canonical_hash=canonical_hash,
                defaults={
                    "canonical_url": item.url,
                    "title": item.title,
                    "published_at": item.published_at,
                    "first_observed_at": result.fetched_at,
                    "quality": quality,
                    "quality_reason": ""
                    if item.published_at
                    else "No trustworthy publication timestamp",
                },
            )
            dedup_key = _digest(f"{policy.pk}:{item.item_id}")
            representation, representation_created = DocumentRepresentation.objects.get_or_create(
                dedup_key=dedup_key,
                defaults={
                    "document": document,
                    "retrieval": retrieval,
                    "source_item_id": item.item_id,
                    "source_title": item.title,
                    "source_published_at": item.published_at,
                    "summary": item.summary,
                },
            )
            if representation_created:
                created += 1
                prior = document.representations.exclude(pk=representation.pk).first()
                if prior:
                    _discrepancy(
                        ResearchDiscrepancy.Kind.DUPLICATE,
                        f"document:{canonical_hash}",
                        prior.retrieval,
                        retrieval,
                        {"dedup_key": dedup_key},
                        result.fetched_at,
                    )
            if not document_created and (
                document.title != item.title or document.published_at != item.published_at
            ):
                _discrepancy(
                    ResearchDiscrepancy.Kind.CONFLICT,
                    f"document:{canonical_hash}",
                    document.representations.first().retrieval,
                    retrieval,
                    {
                        "canonical_title": document.title,
                        "observed_title": item.title,
                        "canonical_published_at": _iso(document.published_at),
                        "observed_published_at": _iso(item.published_at),
                    },
                    result.fetched_at,
                )
                ResearchDocument.objects.filter(pk=document.pk).update(
                    quality=ResearchDocument.Quality.CONFLICT,
                    quality_reason="Source representations disagree; canonical value was preserved",
                )
        _audit("research.feed_ingested", retrieval, {"items": len(items), "created": created})
    return retrieval


def ingest_macro(series, *, transport=None, resolver=None, now=None):
    options = {"transport": transport, "now": now}
    if resolver is not None:
        options["resolver"] = resolver
    result = fetch(series.source_policy, series.url, **options)
    try:
        values = parse_macro(series, result.body)
    except (ParseRejected, ValueError, KeyError, TypeError):
        with transaction.atomic():
            retrieval = _store_raw(
                series.source_policy,
                result,
                quality=RawRetrieval.Quality.QUARANTINED,
                quality_reason="Macro parsing failed closed",
            )
            _audit("research.macro_quarantined", retrieval, {"series": series.code})
        raise
    with transaction.atomic():
        retrieval = _store_raw(series.source_policy, result)
        created = 0
        for item in values:
            existing = MacroObservation.objects.filter(
                series=series, observation_period=item.period
            ).order_by("-revision_sequence")
            exact = existing.filter(normalized_value=item.normalized_value).first()
            if exact:
                continue
            previous = existing.first()
            MacroObservation.objects.create(
                series=series,
                retrieval=retrieval,
                observation_period=item.period,
                value=item.value,
                normalized_value=item.normalized_value,
                available_at=result.fetched_at,
                vintage_at=result.fetched_at,
                revision_sequence=(previous.revision_sequence + 1) if previous else 0,
                availability_precision=MacroObservation.AvailabilityPrecision.RETRIEVAL,
            )
            created += 1
            if previous:
                _discrepancy(
                    ResearchDiscrepancy.Kind.REVISION,
                    f"macro:{series.code}:{item.period.isoformat()}",
                    previous.retrieval,
                    retrieval,
                    {"previous": previous.normalized_value, "observed": item.normalized_value},
                    result.fetched_at,
                )
        _audit(
            "research.macro_ingested", retrieval, {"observations": len(values), "created": created}
        )
    return retrieval


def _store_raw(policy, result, *, quality=RawRetrieval.Quality.ACCEPTED, quality_reason=""):
    return RawRetrieval.objects.create(
        source_policy=policy,
        url=result.url,
        request_fingerprint=_digest(result.url),
        fetched_at=result.fetched_at,
        http_status=result.status_code,
        content_type=result.content_type,
        byte_count=len(result.body),
        body_sha256=result.body_sha256,
        body=result.body,
        etag=result.etag,
        last_modified=result.last_modified,
        quality=quality,
        quality_reason=quality_reason,
        retention_decision=f"retained under {policy.retention_class}",
    )


def _discrepancy(kind, key, earlier, later, detail, observed_at):
    if earlier.pk == later.pk:
        return None
    return ResearchDiscrepancy.objects.create(
        kind=kind,
        entity_key=key,
        earlier_retrieval=earlier,
        later_retrieval=later,
        detail=detail,
        observed_at=observed_at,
    )


def _audit(event_type, retrieval, payload):
    AuditEvent.objects.create(
        event_type=event_type,
        actor="research.services",
        subject_type="RawRetrieval",
        subject_id=str(retrieval.pk),
        payload={"body_sha256": retrieval.body_sha256, **payload},
    )


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _iso(value):
    return value.isoformat() if value else None
