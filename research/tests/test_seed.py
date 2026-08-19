from django.core.management import call_command
from django.test import TestCase

from operations.models import ScheduledJob
from research.models import MacroSeries, ProviderEvaluation, SourcePolicy


class ResearchSeedTests(TestCase):
    def test_seed_is_idempotent_and_leaves_calendar_provider_unselected(self):
        call_command("seed_research", verbosity=0)
        call_command("seed_research", verbosity=0)

        self.assertEqual(SourcePolicy.objects.count(), 5)
        self.assertEqual(MacroSeries.objects.count(), 4)
        self.assertEqual(ScheduledJob.objects.filter(task_name__startswith="research.").count(), 8)
        evaluation = ProviderEvaluation.objects.get(provider="Trading Economics")
        self.assertEqual(evaluation.status, ProviderEvaluation.Status.CANDIDATE)
        self.assertIn("Unverified", evaluation.pricing_status)
