from django.db import transaction
from django.utils import timezone

from market.models import AuditEvent, Candle, IngestionRun, TechnicalSnapshot
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

    rows = [
        Candle(instrument=instrument, ingestion_run=run, granularity=granularity, **item.__dict__)
        for item in candle_data
    ]
    before = Candle.objects.filter(instrument=instrument, granularity=granularity).count()
    Candle.objects.bulk_create(rows, ignore_conflicts=True)
    after = Candle.objects.filter(instrument=instrument, granularity=granularity).count()
    run.status = IngestionRun.Status.SUCCEEDED
    run.fetched_count = len(rows)
    run.stored_count = after - before
    run.finished_at = timezone.now()
    run.save()
    AuditEvent.objects.create(
        event_type="market.ingestion_succeeded",
        actor="market.services.store_ingestion",
        subject_type="IngestionRun",
        subject_id=str(run.pk),
        payload={"fetched": run.fetched_count, "stored": run.stored_count, "manifest": digest},
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
