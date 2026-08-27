from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from forecasts.models import EvidenceSnapshot, Forecast, Recommendation
from market.models import Candle, IngestionRun, Instrument, SourceRegistry, TechnicalSnapshot
from operations.models import JobOccurrence, ScheduledJob
from research.models import (
    DocumentRepresentation,
    EconomicEvent,
    MacroObservation,
    PairEvidenceSnapshot,
    RawRetrieval,
    ResearchDocument,
)


@override_settings(
    DEBUG=False,
    OANDA_TOKEN="production-test-token",
    OANDA_ACCOUNT_ID="production-test-account",
    ANTHROPIC_API_KEY="",
    EODHD_API_TOKEN="",
    RECOMMENDATION_SCHEDULE_ENABLED=False,
    POSTMORTEM_INTERPRETATION_ENABLED=False,
)
class CanonicalSeedTests(TestCase):
    def test_fresh_setup_creates_canonical_registry_and_intended_schedules(self):
        call_command("seed_canonical", verbosity=0)

        self.assertEqual(
            list(Instrument.objects.values_list("code", flat=True)),
            ["EUR_USD", "GBP_USD", "EUR_GBP", "USD_CAD", "USD_JPY", "AUD_USD"],
        )
        self.assertEqual(Instrument.objects.filter(active=True).count(), 4)
        oanda = SourceRegistry.objects.get(name="OANDA v20")
        self.assertEqual(oanda.tier, SourceRegistry.Tier.ESTABLISHED)
        self.assertTrue(oanda.enabled)
        self.assertEqual(
            ScheduledJob.objects.filter(task_name="market.ingest_oanda", enabled=True).count(),
            16,
        )
        self.assertFalse(
            ScheduledJob.objects.filter(
                task_name="market.ingest_oanda",
                parameters__instrument__in=("USD_JPY", "AUD_USD"),
                enabled=True,
            ).exists()
        )
        self.assertTrue(ScheduledJob.objects.get(task_name="market.capture_oanda_terms").enabled)
        self.assertTrue(
            ScheduledJob.objects.filter(
                task_name="research.capture_pair_evidence", enabled=True
            ).exists()
        )
        self.assertFalse(
            ScheduledJob.objects.get(task_name="forecast.generate_recommendations").enabled
        )

    def test_repeated_setup_preserves_existing_next_run_times(self):
        call_command("seed_canonical", verbosity=0)
        expected = timezone.now() - timedelta(minutes=5)
        ScheduledJob.objects.update(next_run_at=expected)

        call_command("seed_canonical", verbosity=0)

        self.assertFalse(ScheduledJob.objects.exclude(next_run_at=expected).exists())

    def test_setup_creates_no_development_fixtures_or_domain_evidence(self):
        call_command("seed_canonical", verbosity=0)

        self.assertFalse(SourceRegistry.objects.filter(name="Development fixtures").exists())
        for model in (
            IngestionRun,
            Candle,
            TechnicalSnapshot,
            RawRetrieval,
            ResearchDocument,
            DocumentRepresentation,
            MacroObservation,
            EconomicEvent,
            PairEvidenceSnapshot,
            EvidenceSnapshot,
            Forecast,
            Recommendation,
            JobOccurrence,
        ):
            with self.subTest(model=model.__name__):
                self.assertEqual(model.objects.count(), 0)
        self.assertFalse(get_user_model().objects.exists())
