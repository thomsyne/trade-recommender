import math
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from market.models import Instrument, SourceRegistry
from market.oanda import CandleData
from market.services import store_ingestion
from operations.models import ScheduledJob

INSTRUMENTS = (
    (Instrument.Code.USD_CAD, "USD", "CAD", 1, Decimal("1.371000")),
    (Instrument.Code.GBP_USD, "GBP", "USD", 2, Decimal("1.296000")),
    (Instrument.Code.EUR_GBP, "EUR", "GBP", 3, Decimal("0.856000")),
    (Instrument.Code.EUR_USD, "EUR", "USD", 4, Decimal("1.109000")),
)


class Command(BaseCommand):
    help = "Seed canonical instruments and clearly labelled development fixtures"

    def handle(self, *args, **options):
        oanda, _ = SourceRegistry.objects.update_or_create(
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
        fixture, _ = SourceRegistry.objects.update_or_create(
            name="Development fixtures",
            defaults={
                "tier": SourceRegistry.Tier.QUARANTINE,
                "base_url": "https://example.invalid/fixtures",
                "acquisition_method": "Deterministic local generator",
                "retention_policy": "Development only; never market evidence.",
                "llm_processing_allowed": False,
                "enabled": settings.DEBUG,
            },
        )

        now = datetime(2026, 8, 15, 21, tzinfo=UTC)
        for code, base, quote, order, initial in INSTRUMENTS:
            instrument, _ = Instrument.objects.update_or_create(
                code=code,
                defaults={
                    "base_currency": base,
                    "quote_currency": quote,
                    "display_order": order,
                    "active": True,
                },
            )
            if settings.DEBUG:
                self._seed_candles(fixture, instrument, "D", now, initial, 48)
                self._seed_candles(fixture, instrument, "H4", now, initial, 72)
            for granularity, interval in (("H4", 14_400), ("D", 86_400)):
                job, _ = ScheduledJob.objects.get_or_create(
                    name=f"OANDA {code} {granularity}",
                    defaults={
                        "task_name": "market.ingest_oanda",
                        "parameters": {"instrument": code, "granularity": granularity},
                        "interval_seconds": interval,
                        "next_run_at": timezone.now() + timedelta(seconds=interval),
                        "enabled": bool(settings.OANDA_TOKEN),
                    },
                )
                job.task_name = "market.ingest_oanda"
                job.parameters = {"instrument": code, "granularity": granularity}
                job.interval_seconds = interval
                job.enabled = bool(settings.OANDA_TOKEN)
                job.save(update_fields=("task_name", "parameters", "interval_seconds", "enabled"))

        password = os.getenv("DEMO_OWNER_PASSWORD", "orb-demo-only")
        if settings.DEBUG:
            user, created = get_user_model().objects.get_or_create(
                username="owner", defaults={"is_staff": True, "is_superuser": True}
            )
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write("created development owner account")
        self.stdout.write(self.style.SUCCESS("canonical market data ready"))

    def _seed_candles(self, source, instrument, granularity, end, initial, count):
        delta = timedelta(days=1) if granularity == "D" else timedelta(hours=4)
        start = end - delta * count
        spread = Decimal("0.000120")
        candles = []
        for index in range(count):
            timestamp = start + delta * index
            wave = Decimal(str(math.sin(index / 4))) * Decimal("0.0022")
            drift = Decimal(index) * Decimal("0.000025")
            midpoint_open = initial + wave + drift
            midpoint_close = (
                initial + Decimal(str(math.sin((index + 0.7) / 4))) * Decimal("0.0022") + drift
            )
            high = max(midpoint_open, midpoint_close) + Decimal("0.0008")
            low = min(midpoint_open, midpoint_close) - Decimal("0.0008")
            half = spread / 2
            candles.append(
                CandleData(
                    timestamp=timestamp,
                    complete=True,
                    volume=100 + index,
                    bid_open=midpoint_open - half,
                    bid_high=high - half,
                    bid_low=low - half,
                    bid_close=midpoint_close - half,
                    ask_open=midpoint_open + half,
                    ask_high=high + half,
                    ask_low=low + half,
                    ask_close=midpoint_close + half,
                )
            )
        manifest = {
            "source": "deterministic-fixture-v1",
            "instrument": instrument.code,
            "granularity": granularity,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "price": "BA",
            "smooth": False,
            "alignmentTimezone": "America/New_York",
            "dailyAlignment": 17,
            "requests": [],
        }
        store_ingestion(source, instrument, granularity, start, end, candles, manifest)
