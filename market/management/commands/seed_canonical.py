from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from market.models import Instrument, SourceRegistry
from operations.models import ScheduledJob

INSTRUMENTS = (
    (Instrument.Code.EUR_USD, "EUR", "USD", 1),
    (Instrument.Code.GBP_USD, "GBP", "USD", 2),
    (Instrument.Code.EUR_GBP, "EUR", "GBP", 3),
    (Instrument.Code.USD_CAD, "USD", "CAD", 4),
    (Instrument.Code.USD_JPY, "USD", "JPY", 5),
    (Instrument.Code.AUD_USD, "AUD", "USD", 6),
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
        SourceRegistry.objects.update_or_create(
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

        # Vacate legacy display-order slots before applying the registered six-pair order.
        for code, _base, _quote, order in INSTRUMENTS:
            Instrument.objects.filter(code=code).update(display_order=30_000 + order)

        for code, base, quote, order in INSTRUMENTS:
            Instrument.objects.update_or_create(
                code=code,
                defaults={
                    "base_currency": base,
                    "quote_currency": quote,
                    "display_order": order,
                    "active": code in PROSPECTIVE_INSTRUMENT_CODES,
                },
            )
            for granularity, interval in (
                ("H1", 3_600),
                ("H4", 14_400),
                ("D", 86_400),
                ("W", 604_800),
            ):
                _upsert_job(
                    name=f"OANDA {code} {granularity}",
                    task_name="market.ingest_oanda",
                    parameters={"instrument": code, "granularity": granularity},
                    interval=interval,
                    enabled=bool(settings.OANDA_TOKEN),
                )

        _upsert_job(
            name="OANDA account terms",
            task_name="market.capture_oanda_terms",
            parameters={},
            interval=3_600,
            enabled=bool(settings.OANDA_TOKEN and settings.OANDA_ACCOUNT_ID),
        )
        call_command("seed_research", verbosity=options.get("verbosity", 1))
        self.stdout.write(self.style.SUCCESS("canonical production registry ready"))


def _upsert_job(*, name, task_name, parameters, interval, enabled):
    job, _ = ScheduledJob.objects.get_or_create(
        name=name,
        defaults={
            "task_name": task_name,
            "parameters": parameters,
            "interval_seconds": interval,
            "next_run_at": timezone.now() + timedelta(seconds=interval),
            "enabled": enabled,
        },
    )
    job.task_name = task_name
    job.parameters = parameters
    job.interval_seconds = interval
    job.enabled = enabled
    job.save(update_fields=("task_name", "parameters", "interval_seconds", "enabled"))
