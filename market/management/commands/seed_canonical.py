from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from market.live_acquisition import LIVE_INTERVALS
from market.live_schedules import duplicate_schedule_errors
from market.models import Instrument, SourceRegistry
from operations.models import ScheduledJob

INSTRUMENTS = (
    (Instrument.Code.EUR_USD, "EUR", "USD", 1),
    (Instrument.Code.GBP_USD, "GBP", "USD", 2),
    (Instrument.Code.EUR_GBP, "EUR", "GBP", 3),
    (Instrument.Code.USD_CAD, "USD", "CAD", 4),
    (Instrument.Code.USD_JPY, "USD", "JPY", 5),
    (Instrument.Code.AUD_USD, "AUD", "USD", 6),
    (Instrument.Code.USD_CHF, "USD", "CHF", 7),
    (Instrument.Code.NZD_USD, "NZD", "USD", 8),
    (Instrument.Code.EUR_JPY, "EUR", "JPY", 9),
    (Instrument.Code.GBP_JPY, "GBP", "JPY", 10),
    (Instrument.Code.AUD_JPY, "AUD", "JPY", 11),
    (Instrument.Code.AUD_CAD, "AUD", "CAD", 12),
)
PROSPECTIVE_INSTRUMENT_CODES = {
    Instrument.Code.EUR_USD,
    Instrument.Code.GBP_USD,
    Instrument.Code.EUR_GBP,
    Instrument.Code.USD_CAD,
}


class Command(BaseCommand):
    help = "Seed canonical production instruments, sources, and durable schedules"

    @transaction.atomic
    def handle(self, *args, **options):
        # Serialize concurrent canonical seeders without touching evidence.
        from django.db import connection

        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(724102)")
        duplicate_errors = duplicate_schedule_errors()
        if duplicate_errors:
            raise CommandError("; ".join(duplicate_errors))
        source, _ = SourceRegistry.objects.get_or_create(
            name="OANDA v20",
            defaults={
                "tier": SourceRegistry.Tier.ESTABLISHED,
                "base_url": "https://developer.oanda.com/",
                "terms_url": "https://www.oanda.com/terms/",
                "acquisition_method": "v20 REST API",
                "retention_policy": "Private market-data research; terms review required before export.",
                "llm_processing_allowed": False,
                "enabled": bool(settings.OANDA_TOKEN),
            },
        )

        _save_changed(source, {"enabled": bool(settings.OANDA_TOKEN)})

        # Vacate only changed legacy slots; ordinary reseeds do not rewrite rows.
        for code, _base, _quote, order in INSTRUMENTS:
            Instrument.objects.filter(code=code).exclude(display_order=order).update(
                display_order=30_000 + order
            )

        for code, base, quote, order in INSTRUMENTS:
            instrument, _ = Instrument.objects.get_or_create(
                code=code,
                defaults={
                    "base_currency": base,
                    "quote_currency": quote,
                    "display_order": order,
                    "active": code in PROSPECTIVE_INSTRUMENT_CODES,
                    "ingestion_enabled": True,
                },
            )
            _save_changed(
                instrument,
                {
                    "base_currency": base,
                    "quote_currency": quote,
                    "display_order": order,
                    "active": code in PROSPECTIVE_INSTRUMENT_CODES,
                },
            )
            for granularity, interval in LIVE_INTERVALS.items():
                _upsert_job(
                    name=f"OANDA {code} {granularity}",
                    task_name="market.ingest_oanda",
                    parameters={"instrument": code, "granularity": granularity},
                    interval=interval,
                    enabled=bool(source.enabled and instrument.ingestion_enabled),
                    stagger_slot=(order - 1) * 4 + tuple(LIVE_INTERVALS).index(granularity),
                )

        _upsert_job(
            name="OANDA account terms",
            task_name="market.capture_oanda_terms",
            parameters={},
            interval=3_600,
            enabled=bool(settings.OANDA_TOKEN and settings.OANDA_ACCOUNT_ID),
        )
        from forecasts.schedules import seed_schedules

        seed_schedules()
        call_command("seed_research", verbosity=options.get("verbosity", 1))
        self.stdout.write(self.style.SUCCESS("canonical production registry ready"))


def _save_changed(row, values):
    changed = [key for key, value in values.items() if getattr(row, key) != value]
    for key in changed:
        setattr(row, key, values[key])
    if changed:
        row.save(update_fields=changed)


def _upsert_job(*, name, task_name, parameters, interval, enabled, stagger_slot=None):
    # Distinct minute phases survive hourly polling cycles across granularities.
    delay = (
        interval
        if stagger_slot is None
        else (
            60 * (stagger_slot + 1) + 3600 * ((interval - 3600) * (stagger_slot + 1) // (49 * 3600))
        )
    )
    job, _ = ScheduledJob.objects.get_or_create(
        name=name,
        defaults={
            "task_name": task_name,
            "parameters": parameters,
            "interval_seconds": interval,
            "next_run_at": timezone.now() + timedelta(seconds=delay),
            "enabled": enabled,
        },
    )
    _save_changed(
        job,
        {
            "task_name": task_name,
            "parameters": parameters,
            "interval_seconds": interval,
            "enabled": enabled,
            "schedule_type": ScheduledJob.ScheduleType.INTERVAL,
            "timezone_name": "UTC",
            "local_time": None,
            **(
                {"missed_run_policy": ScheduledJob.MissedRunPolicy.LATEST}
                if stagger_slot is not None
                else {}
            ),
        },
    )
