from django.core.management import call_command
from django.test import TestCase, override_settings

from operations.models import ScheduledJob
from research.models import MacroSeries, ProviderEvaluation, SourcePolicy


class ResearchSeedTests(TestCase):
    @override_settings(
        ANTHROPIC_API_KEY="configured-but-not-authorized",
        EODHD_API_TOKEN="",
        RECOMMENDATION_SCHEDULE_ENABLED=False,
    )
    def test_seed_is_idempotent_and_leaves_calendar_provider_unselected(self):
        call_command("seed_research", verbosity=0)
        call_command("seed_research", verbosity=0)

        self.assertEqual(SourcePolicy.objects.count(), 18)
        self.assertEqual(MacroSeries.objects.count(), 27)
        self.assertEqual(ScheduledJob.objects.filter(task_name__startswith="research.").count(), 46)
        self.assertEqual(
            MacroSeries.objects.filter(indicator__in=("cpi", "unemployment", "gdp", "housing"))
            .values("source_policy__jurisdiction", "indicator")
            .distinct()
            .count(),
            16,
        )
        calendar_job = ScheduledJob.objects.get(task_name="research.ingest_eodhd_calendar")
        self.assertFalse(calendar_job.enabled)
        self.assertEqual(SourcePolicy.objects.get(slug="eodhd-calendar").state, "disabled")
        self.assertEqual(
            ScheduledJob.objects.filter(
                task_name="research.ingest_official_calendar", enabled=True
            ).count(),
            8,
        )
        self.assertTrue(
            ScheduledJob.objects.filter(
                task_name="research.capture_pair_evidence", enabled=True
            ).exists()
        )
        self.assertFalse(
            ScheduledJob.objects.get(task_name="forecast.generate_recommendations").enabled
        )
        self.assertEqual(
            MacroSeries.objects.filter(
                indicator__in=(
                    MacroSeries.Indicator.EQUITY,
                    MacroSeries.Indicator.VOLATILITY,
                    MacroSeries.Indicator.CRYPTO,
                    MacroSeries.Indicator.COMMODITY,
                    MacroSeries.Indicator.YIELD,
                    MacroSeries.Indicator.DOLLAR,
                )
            ).count(),
            7,
        )
        selected = ProviderEvaluation.objects.get(provider="Official statistical agencies")
        self.assertEqual(selected.status, ProviderEvaluation.Status.SELECTED)
        eodhd = ProviderEvaluation.objects.get(provider="EODHD")
        self.assertEqual(eodhd.status, ProviderEvaluation.Status.REJECTED)
        evaluation = ProviderEvaluation.objects.get(provider="Trading Economics")
        self.assertEqual(evaluation.status, ProviderEvaluation.Status.CANDIDATE)
        self.assertIn("No public price", evaluation.pricing_status)
