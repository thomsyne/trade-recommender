from django.core.management import call_command
from django.test import TestCase

from operations.models import ScheduledJob
from research.models import MacroSeries, ProviderEvaluation, SourcePolicy


class ResearchSeedTests(TestCase):
    def test_seed_is_idempotent_and_leaves_calendar_provider_unselected(self):
        call_command("seed_research", verbosity=0)
        call_command("seed_research", verbosity=0)

        self.assertEqual(SourcePolicy.objects.count(), 11)
        self.assertEqual(MacroSeries.objects.count(), 20)
        self.assertEqual(ScheduledJob.objects.filter(task_name__startswith="research.").count(), 25)
        self.assertEqual(
            MacroSeries.objects.exclude(indicator="policy_rate")
            .values("source_policy__jurisdiction", "indicator")
            .distinct()
            .count(),
            16,
        )
        calendar_job = ScheduledJob.objects.get(task_name="research.ingest_eodhd_calendar")
        self.assertFalse(calendar_job.enabled)
        self.assertEqual(SourcePolicy.objects.get(slug="eodhd-calendar").state, "disabled")
        eodhd = ProviderEvaluation.objects.get(provider="EODHD")
        self.assertIn("NOT CONNECTED", eodhd.reliability_result)
        evaluation = ProviderEvaluation.objects.get(provider="Trading Economics")
        self.assertEqual(evaluation.status, ProviderEvaluation.Status.CANDIDATE)
        self.assertIn("No public price", evaluation.pricing_status)
