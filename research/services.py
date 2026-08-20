import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from django.db import transaction

from market.models import AuditEvent, Candle, Instrument, TechnicalSnapshot
from research.fetch import fetch
from research.models import (
    DocumentRepresentation,
    EconomicEvent,
    MacroObservation,
    MacroSeries,
    PairEvidenceSnapshot,
    RawRetrieval,
    ResearchDiscrepancy,
    ResearchDocument,
)
from research.parsers import (
    ParseRejected,
    parse_eodhd_events,
    parse_feed,
    parse_macro,
    parse_official_calendar,
)


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
    payload = series.request_payload or None
    if series.parser == series.Parser.BLS_JSON:
        year = (now or datetime.now(UTC)).year
        payload = {
            "seriesid": [series.provider_series_id],
            "startyear": str(year - 2),
            "endyear": str(year),
        }
    options = {
        "transport": transport,
        "now": now,
        "method": series.request_method,
        "json_body": payload,
    }
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
                available_at=item.available_at or result.fetched_at,
                vintage_at=result.fetched_at,
                revision_sequence=(previous.revision_sequence + 1) if previous else 0,
                availability_precision=(
                    MacroObservation.AvailabilityPrecision.PROVIDER
                    if item.available_at
                    else MacroObservation.AvailabilityPrecision.RETRIEVAL
                ),
                provider_status=item.provider_status,
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


def ingest_eodhd_calendar(policy, api_token, *, transport=None, resolver=None, now=None):
    observed_at = now or datetime.now(UTC)
    query = urlencode(
        {
            "api_token": api_token,
            "fmt": "json",
            "from": (observed_at.date() - timedelta(days=2)).isoformat(),
            "to": (observed_at.date() + timedelta(days=7)).isoformat(),
            "limit": 1000,
            "offset": 0,
        }
    )
    options = {
        "transport": transport,
        "now": now,
        "sensitive_query_keys": ("api_token",),
    }
    if resolver is not None:
        options["resolver"] = resolver
    result = fetch(policy, f"https://eodhd.com/api/economic-events?{query}", **options)
    try:
        parsed_values = parse_eodhd_events(result.body)
        if len(parsed_values) >= 1000:
            raise ParseRejected("Economic calendar reached its pagination boundary")
        values = [item for item in parsed_values if item.country in {"CA", "US", "GB", "EU"}]
    except (ParseRejected, ValueError, KeyError, TypeError):
        with transaction.atomic():
            retrieval = _store_raw(
                policy,
                result,
                quality=RawRetrieval.Quality.QUARANTINED,
                quality_reason="Economic calendar parsing failed closed",
            )
            _audit("research.calendar_quarantined", retrieval, {})
        raise
    with transaction.atomic():
        retrieval = _store_raw(policy, result)
        created = 0
        for item in values:
            identity = _digest(
                f"{item.country}|{item.event_type}|{item.event_at.isoformat()}|{item.period}"
            )
            payload = {
                "actual": _decimal_text(item.actual),
                "estimate": _decimal_text(item.estimate),
                "previous": _decimal_text(item.previous),
                "comparison": item.comparison,
            }
            fingerprint = _digest(json.dumps(payload, sort_keys=True))
            _, was_created = EconomicEvent.objects.get_or_create(
                provider_event_key=identity,
                payload_fingerprint=fingerprint,
                defaults={
                    "retrieval": retrieval,
                    "event_at": item.event_at,
                    "country": item.country,
                    "event_type": item.event_type,
                    "comparison": item.comparison,
                    "period": item.period,
                    "actual": item.actual,
                    "estimate": item.estimate,
                    "previous": item.previous,
                    "first_observed_at": result.fetched_at,
                },
            )
            created += int(was_created)
        _audit("research.calendar_ingested", retrieval, {"events": len(values), "created": created})
    return retrieval


def ingest_official_calendar(policy, parser, url, *, transport=None, resolver=None, now=None):
    observed_at = now or datetime.now(UTC)
    options = {"transport": transport, "now": now}
    if resolver is not None:
        options["resolver"] = resolver
    result = fetch(policy, url, **options)
    try:
        parsed_values = parse_official_calendar(parser, result.body)
        window_start = observed_at - timedelta(days=7)
        window_end = observed_at + timedelta(days=550)
        values = [item for item in parsed_values if window_start <= item.event_at <= window_end]
        if not values:
            raise ParseRejected(
                "Official calendar contains no events in the bounded forward window"
            )
    except (ParseRejected, ValueError, KeyError, TypeError):
        with transaction.atomic():
            retrieval = _store_raw(
                policy,
                result,
                quality=RawRetrieval.Quality.QUARANTINED,
                quality_reason="Official calendar parsing failed closed",
            )
            _audit("research.calendar_quarantined", retrieval, {"parser": parser})
        raise
    series_by_code = {
        item.code: item
        for item in MacroSeries.objects.filter(
            code__in={item.series_code for item in values if item.series_code}
        )
    }
    with transaction.atomic():
        retrieval = _store_raw(policy, result)
        created = 0
        for item in values:
            identity = _digest(f"{policy.slug}|{item.provider_event_key}")
            payload = {
                "event_at": item.event_at.isoformat(),
                "event_type": item.event_type,
                "period": item.period,
                "source_url": item.source_url,
                "status": item.status,
                "time_precision": item.time_precision,
                "series_code": item.series_code,
            }
            fingerprint = _digest(json.dumps(payload, sort_keys=True))
            _, was_created = EconomicEvent.objects.get_or_create(
                provider_event_key=identity,
                payload_fingerprint=fingerprint,
                defaults={
                    "retrieval": retrieval,
                    "series": series_by_code.get(item.series_code),
                    "event_at": item.event_at,
                    "time_precision": item.time_precision,
                    "country": item.country,
                    "event_type": item.event_type,
                    "source_url": item.source_url,
                    "status": item.status,
                    "comparison": item.comparison,
                    "period": item.period,
                    "actual": None,
                    "estimate": None,
                    "previous": None,
                    "first_observed_at": result.fetched_at,
                },
            )
            created += int(was_created)
        _audit(
            "research.calendar_ingested",
            retrieval,
            {"events": len(values), "created": created, "parser": parser},
        )
    return retrieval


@transaction.atomic
def capture_pair_evidence(instrument, *, now=None):
    captured_at = now or datetime.now(UTC)
    jurisdictions = {
        "USD": "US",
        "CAD": "CA",
        "GBP": "GB",
        "EUR": "EU",
    }
    pair_jurisdictions = {
        jurisdictions[instrument.base_currency],
        jurisdictions[instrument.quote_currency],
    }
    anchor = (
        Candle.objects.filter(
            instrument=instrument,
            granularity="H4",
            timestamp__lt=captured_at,
            ingestion_run__finished_at__lte=captured_at,
        )
        .select_related("ingestion_run__source")
        .order_by("-timestamp")
        .first()
    )
    if not anchor:
        raise ValueError(f"No H4 market evidence exists for {instrument.code}")

    technicals = []
    for granularity in ("H4", "D"):
        snapshot = (
            TechnicalSnapshot.objects.filter(
                instrument=instrument,
                granularity=granularity,
                as_of__lt=captured_at,
                calculated_at__lte=captured_at,
            )
            .order_by("-as_of")
            .first()
        )
        if snapshot:
            technicals.append(
                {
                    "id": snapshot.pk,
                    "granularity": granularity,
                    "as_of": snapshot.as_of.isoformat(),
                    "atr_14": _decimal_text(snapshot.atr_14),
                    "ewma_20": _decimal_text(snapshot.ewma_20),
                    "support": _decimal_text(snapshot.support),
                    "resistance": _decimal_text(snapshot.resistance),
                }
            )

    context_indicators = {
        MacroSeries.Indicator.EQUITY,
        MacroSeries.Indicator.VOLATILITY,
        MacroSeries.Indicator.CRYPTO,
        MacroSeries.Indicator.COMMODITY,
        MacroSeries.Indicator.YIELD,
        MacroSeries.Indicator.DOLLAR,
    }
    macro_values = []
    series_rows = MacroSeries.objects.filter(enabled=True).select_related("source_policy__source")
    for series in series_rows:
        if (
            series.source_policy.jurisdiction not in pair_jurisdictions
            and series.indicator not in context_indicators
        ):
            continue
        observation = series.observations.filter(
            available_at__lte=captured_at,
            vintage_at__lte=captured_at,
            retrieval__fetched_at__lte=captured_at,
        ).first()
        if not observation:
            continue
        macro_values.append(
            {
                "series": series.code,
                "label": series.label,
                "indicator": series.indicator,
                "jurisdiction": series.source_policy.jurisdiction,
                "value": observation.normalized_value,
                "unit": series.unit,
                "period": observation.observation_period.isoformat(),
                "available_at": observation.available_at.isoformat(),
                "vintage_at": observation.vintage_at.isoformat(),
                "observation_id": observation.pk,
                "retrieval_id": observation.retrieval_id,
                "source": series.source_policy.source.name,
            }
        )

    event_rows = list(
        EconomicEvent.objects.filter(
            country__in=pair_jurisdictions,
            first_observed_at__lte=captured_at,
            event_at__gte=captured_at - timedelta(days=1),
            event_at__lte=captured_at + timedelta(days=45),
        )
        .select_related("retrieval__source_policy__source")
        .order_by("provider_event_key", "-first_observed_at")
    )
    latest_events = {}
    for event in event_rows:
        latest_events.setdefault(event.provider_event_key, event)
    events = [
        {
            "id": event.pk,
            "country": event.country,
            "title": event.event_type,
            "event_at": event.event_at.isoformat(),
            "time_precision": event.time_precision,
            "period": event.period,
            "first_observed_at": event.first_observed_at.isoformat(),
            "retrieval_id": event.retrieval_id,
            "source": event.retrieval.source_policy.source.name,
            "source_url": event.source_url,
            "consensus": None,
        }
        for event in sorted(latest_events.values(), key=lambda value: value.event_at)
    ]

    cutoff_start = captured_at - timedelta(hours=72)
    representations = (
        DocumentRepresentation.objects.filter(
            retrieval__source_policy__jurisdiction__in=pair_jurisdictions | {"ZZ"},
            retrieval__fetched_at__lte=captured_at,
            document__first_observed_at__lte=captured_at,
            document__published_at__gte=cutoff_start,
            document__published_at__lte=captured_at,
        )
        .select_related("document", "retrieval__source_policy__source")
        .order_by("-document__published_at", "-document__first_observed_at")
    )
    news = []
    seen_documents = set()
    for representation in representations:
        if representation.document_id in seen_documents:
            continue
        seen_documents.add(representation.document_id)
        source = representation.retrieval.source_policy.source
        news.append(
            {
                "document_id": representation.document_id,
                "title": representation.document.title,
                "url": representation.document.canonical_url,
                "published_at": _iso(representation.document.published_at),
                "first_observed_at": representation.document.first_observed_at.isoformat(),
                "summary": representation.summary,
                "source": source.name,
                "source_tier": source.tier,
                "model_eligible": source.llm_processing_allowed,
            }
        )
        if len(news) == 20:
            break

    payload = {
        "schema": "pair-evidence-v1",
        "instrument": instrument.code,
        "currencies": [instrument.base_currency, instrument.quote_currency],
        "jurisdictions": sorted(pair_jurisdictions),
        "market": {
            "anchor_candle_id": anchor.pk,
            "as_of": anchor.timestamp.isoformat(),
            "midpoint_close": _decimal_text(anchor.midpoint_close),
            "source": anchor.ingestion_run.source.name,
            "manifest": anchor.ingestion_run.request_manifest_hash,
        },
        "technicals": technicals,
        "macro_and_intermarket": sorted(macro_values, key=lambda value: value["series"]),
        "upcoming_events": events,
        "recent_news": news,
        "boundaries": {
            "read_only": True,
            "forecast_write_authorized": False,
            "consensus_inferred": False,
            "news_window_hours": 72,
        },
    }
    digest = _digest(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    existing = PairEvidenceSnapshot.objects.filter(sha256=digest).first()
    if existing:
        return existing
    snapshot = PairEvidenceSnapshot.objects.create(
        instrument=instrument,
        information_cutoff=captured_at,
        payload=payload,
        sha256=digest,
        captured_at=captured_at,
    )
    AuditEvent.objects.create(
        event_type="research.pair_evidence_captured",
        actor="research.services.capture_pair_evidence",
        subject_type="PairEvidenceSnapshot",
        subject_id=str(snapshot.pk),
        payload={
            "instrument": instrument.code,
            "sha256": snapshot.sha256,
            "macro_values": len(macro_values),
            "events": len(events),
            "news": len(news),
        },
    )
    return snapshot


def capture_all_pair_evidence(*, now=None):
    captured_at = now or datetime.now(UTC)
    return [
        capture_pair_evidence(instrument, now=captured_at)
        for instrument in Instrument.objects.filter(active=True)
    ]


def _store_raw(policy, result, *, quality=RawRetrieval.Quality.ACCEPTED, quality_reason=""):
    return RawRetrieval.objects.create(
        source_policy=policy,
        url=result.url,
        request_fingerprint=result.request_fingerprint,
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


def _decimal_text(value):
    return format(value.normalize(), "f") if value is not None else None
