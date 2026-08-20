import hashlib
import json

from django.db import transaction
from django.utils import timezone

from market.models import (
    AuditEvent,
    Candle,
    IngestionRun,
    Instrument,
    OandaInstrumentTermsSnapshot,
    TechnicalSnapshot,
)
from market.oanda import manifest_hash
from market.quality import validate_candles
from market.technicals import calculate_technicals


@transaction.atomic
def store_ingestion(source, instrument, granularity, start, end, candle_data, manifest):
    digest = manifest_hash(manifest)
    existing = IngestionRun.objects.filter(request_manifest_hash=digest).first()
    if existing:
        return existing

    run = IngestionRun.objects.create(
        source=source,
        instrument=instrument,
        granularity=granularity,
        requested_from=start,
        requested_to=end,
        parameters={key: value for key, value in manifest.items() if key != "requests"},
        request_manifest_hash=digest,
    )
    issues = validate_candles(candle_data, granularity)
    if issues:
        run.status = IngestionRun.Status.FAILED
        run.fetched_count = len(candle_data)
        run.rejected_count = len(candle_data)
        run.failure_reason = "; ".join(f"{issue.code}@{issue.index}" for issue in issues[:20])
        run.finished_at = timezone.now()
        run.save()
        AuditEvent.objects.create(
            event_type="market.ingestion_rejected",
            actor="market.services.store_ingestion",
            subject_type="IngestionRun",
            subject_id=str(run.pk),
            payload={"issues": [issue.__dict__ for issue in issues[:20]]},
        )
        return run

    series = Candle.objects.filter(instrument=instrument, granularity=granularity)
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
                instrument=instrument, ingestion_run=run, granularity=granularity, **item.__dict__
            )
            for item in candle_data
        ]
    )
    before = Candle.objects.filter(instrument=instrument, granularity=granularity).count()
    Candle.objects.bulk_create(rows, ignore_conflicts=True)
    after = Candle.objects.filter(instrument=instrument, granularity=granularity).count()
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
    calculate_and_store_snapshot(instrument, granularity)
    return run


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
