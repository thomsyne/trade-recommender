import hashlib
import json

from django.db import transaction
from django.utils import timezone

from market.models import (
    AuditEvent,
    Candle,
    CandleConflict,
    DataQualityIncident,
    IngestionManifest,
    IngestionRun,
    Instrument,
    OandaInstrumentTermsSnapshot,
    TechnicalSnapshot,
)
from market.oanda import manifest_hash
from market.quality import validate_candles
from market.technicals import calculate_technicals


@transaction.atomic
def store_ingestion(
    source, instrument, granularity, start, end, candle_data, manifest, dataset_version=None
):
    digest = manifest_hash(manifest)
    run, created = IngestionRun.objects.get_or_create(
        request_manifest_hash=digest,
        dataset_version=dataset_version,
        defaults={
            "source": source,
            "instrument": instrument,
            "granularity": granularity,
            "requested_from": start,
            "requested_to": end,
            "parameters": {key: value for key, value in manifest.items() if key != "requests"},
        },
    )
    if not created:
        return run
    ingestion_manifest = None
    if dataset_version:
        ingestion_manifest = IngestionManifest.objects.create(
            ingestion_run=run,
            dataset_version=dataset_version,
            payload=manifest,
            sha256=digest,
        )
    issues = validate_candles(candle_data, granularity)
    if issues:
        run.status = IngestionRun.Status.FAILED
        run.fetched_count = len(candle_data)
        run.rejected_count = len(candle_data)
        run.failure_reason = "; ".join(f"{issue.code}@{issue.index}" for issue in issues[:20])
        run.finished_at = timezone.now()
        run.save()
        if dataset_version:
            details = {"issues": [issue.__dict__ for issue in issues[:20]]}
            DataQualityIncident.objects.create(
                dataset_version=dataset_version,
                ingestion_run=run,
                code="candle_validation_failed",
                details=details,
                evidence_sha256=_json_hash(details),
            )
        AuditEvent.objects.create(
            event_type="market.ingestion_rejected",
            actor="market.services.store_ingestion",
            subject_type="IngestionRun",
            subject_id=str(run.pk),
            payload={"issues": [issue.__dict__ for issue in issues[:20]]},
        )
        return run

    if dataset_version:
        existing_by_key = {
            row.timestamp: row
            for row in Candle.objects.select_for_update().filter(
                dataset_version=dataset_version,
                instrument=instrument,
                granularity=granularity,
                timestamp__in=[item.timestamp for item in candle_data],
            )
        }
        conflicts = []
        for item in candle_data:
            prior = existing_by_key.get(item.timestamp)
            incoming_payload = _candle_payload(item)
            if prior and _candle_payload(prior) != incoming_payload:
                existing_payload = _candle_payload(prior)
                conflicts.append(
                    CandleConflict(
                        dataset_version=dataset_version,
                        ingestion_manifest=ingestion_manifest,
                        existing_candle=prior,
                        existing_payload_sha256=_json_hash(existing_payload),
                        incoming_payload_sha256=_json_hash(incoming_payload),
                        differing_fields=sorted(
                            field
                            for field in set(existing_payload) | set(incoming_payload)
                            if existing_payload.get(field) != incoming_payload.get(field)
                        ),
                        incoming_payload=incoming_payload,
                    )
                )
        if conflicts:
            CandleConflict.objects.bulk_create(conflicts)
            incident_details = {
                "conflict_count": len(conflicts),
                "incoming_payload_sha256": sorted(
                    conflict.incoming_payload_sha256 for conflict in conflicts
                ),
            }
            DataQualityIncident.objects.create(
                dataset_version=dataset_version,
                ingestion_run=run,
                code="candle_conflict",
                details=incident_details,
                evidence_sha256=_json_hash(incident_details),
            )
            run.status = IngestionRun.Status.QUARANTINED
            run.fetched_count = len(candle_data)
            run.rejected_count = len(candle_data)
            run.failure_reason = "incoming batch conflicts with governed dataset"
            run.finished_at = timezone.now()
            run.save()
            return run

    series = Candle.objects.filter(
        instrument=instrument, granularity=granularity, dataset_version=dataset_version
    )
    fixture_rows = series.filter(ingestion_run__source__name="Development fixtures")
    replaced_fixture_count = 0
    discard_fixture_batch = (
        source.name == "Development fixtures"
        and series.exclude(ingestion_run__source=source).exists()
    )
    if source.name != "Development fixtures":
        replaced_fixture_count = fixture_rows.count()
        if replaced_fixture_count:
            fixture_rows.delete()
            TechnicalSnapshot.objects.filter(
                instrument=instrument, granularity=granularity
            ).delete()

    rows = (
        []
        if discard_fixture_batch
        else [
            Candle(
                instrument=instrument,
                ingestion_run=run,
                dataset_version=dataset_version,
                granularity=granularity,
                **item.__dict__,
            )
            for item in candle_data
            if not dataset_version or item.timestamp not in existing_by_key
        ]
    )
    before = series.count()
    Candle.objects.bulk_create(rows, ignore_conflicts=dataset_version is None)
    after = series.count()
    run.status = IngestionRun.Status.SUCCEEDED
    run.fetched_count = len(candle_data)
    run.stored_count = after - before
    run.finished_at = timezone.now()
    run.save()
    AuditEvent.objects.create(
        event_type="market.ingestion_succeeded",
        actor="market.services.store_ingestion",
        subject_type="IngestionRun",
        subject_id=str(run.pk),
        payload={
            "fetched": run.fetched_count,
            "stored": run.stored_count,
            "manifest": digest,
            "replaced_fixture_candles": replaced_fixture_count,
            "discarded_fixture_batch": discard_fixture_batch,
        },
    )
    if dataset_version is None:
        calculate_and_store_snapshot(instrument, granularity)
    return run


def _candle_payload(candle):
    fields = (
        "timestamp",
        "complete",
        "volume",
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
    )
    return {
        field: (
            value.isoformat()
            if field == "timestamp"
            else format(value, ".6f")
            if field.startswith(("bid_", "ask_"))
            else str(value)
        )
        for field in fields
        if (value := getattr(candle, field)) is not None
    }


def _json_hash(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def calculate_and_store_snapshot(instrument, granularity):
    candles = list(
        Candle.objects.filter(instrument=instrument, granularity=granularity).order_by("timestamp")
    )
    if not candles:
        return None
    values = calculate_technicals(candles)
    snapshot, _ = TechnicalSnapshot.objects.update_or_create(
        instrument=instrument,
        granularity=granularity,
        as_of=candles[-1].timestamp,
        defaults={"candle_count": len(candles), **values.__dict__},
    )
    return snapshot


@transaction.atomic
def store_oanda_terms(payload, account_id, captured_at=None):
    captured_at = (captured_at or timezone.now()).replace(minute=0, second=0, microsecond=0)
    account_fingerprint = hashlib.sha256(account_id.encode()).hexdigest()
    snapshots = []
    created_count = 0
    for item in payload["instruments"]:
        instrument = Instrument.objects.get(code=item["name"])
        financing = item["financing"]
        normalized = {
            "instrument": item["name"],
            "account_currency": payload["account_currency"],
            "financing": financing,
            "commission": item.get("commission"),
            "marginRate": item["marginRate"],
            "pipLocation": item["pipLocation"],
            "manifest": payload["manifest"],
        }
        response_sha256 = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        snapshot, created = OandaInstrumentTermsSnapshot.objects.get_or_create(
            instrument=instrument,
            environment=payload["manifest"]["environment"],
            account_fingerprint=account_fingerprint,
            captured_at=captured_at,
            defaults={
                "account_currency": payload["account_currency"],
                "long_financing_rate": financing["longRate"],
                "short_financing_rate": financing["shortRate"],
                "financing_days": financing["financingDaysOfWeek"],
                "commission": item.get("commission") or {},
                "commission_supplied": item.get("commission") is not None,
                "margin_rate": item["marginRate"],
                "pip_location": item["pipLocation"],
                "response_sha256": response_sha256,
            },
        )
        created_count += created
        snapshots.append(snapshot)
    if created_count:
        AuditEvent.objects.create(
            event_type="market.oanda_terms_captured",
            actor="market.services.store_oanda_terms",
            subject_type="OandaInstrumentTermsSnapshot",
            subject_id=captured_at.isoformat(),
            payload={
                "instrument_count": len(snapshots),
                "environment": payload["manifest"]["environment"],
                "commission_supplied_count": sum(item.commission_supplied for item in snapshots),
            },
        )
    return snapshots
