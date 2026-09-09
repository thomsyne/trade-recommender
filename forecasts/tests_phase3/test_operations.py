from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from forecasts.operations import reconcile
from forecasts.schedules import recurring_schedules_collide, schedule_errors, seed_schedules
from operations.models import ScheduledJob


class ScheduleTests(TestCase):
    def test_seed_is_disabled_idempotent_and_preserves_deadlines(self):
        seed_schedules()
        before = list(
            ScheduledJob.objects.filter(task_name="forecast.reconcile_target_lifecycle")
            .order_by("pk")
            .values("pk", "next_run_at", "enabled", "parameters", "missed_run_policy")
        )
        self.assertEqual(len(before), 4)
        self.assertTrue(
            all(not r["enabled"] and r["missed_run_policy"] == "latest" for r in before)
        )
        seed_schedules()
        self.assertEqual(
            before,
            list(
                ScheduledJob.objects.filter(task_name="forecast.reconcile_target_lifecycle")
                .order_by("pk")
                .values("pk", "next_run_at", "enabled", "parameters", "missed_run_policy")
            ),
        )
        self.assertEqual(schedule_errors(), [])

    def test_malformed_identity_safe_and_collision_is_recurring(self):
        seed_schedules()
        jobs = list(
            ScheduledJob.objects.filter(task_name="forecast.reconcile_target_lifecycle").order_by(
                "pk"
            )
        )
        a, b = jobs[:2]
        b.next_run_at = a.next_run_at + timedelta(hours=2)
        self.assertTrue(recurring_schedules_collide(a, b))
        b.next_run_at += timedelta(microseconds=1)
        self.assertFalse(recurring_schedules_collide(a, b))
        a.parameters = ["DO_NOT_RENDER"]
        a.save(update_fields=["parameters"])
        errors = schedule_errors()
        self.assertEqual(errors, [{"id": a.pk, "code": "malformed_reconciliation_identity"}])
        self.assertNotIn("DO_NOT_RENDER", str(errors))
        with self.assertRaises(ValidationError):
            seed_schedules()

    def test_ingestion_only_identity_is_rejected_without_work(self):
        with patch("forecasts.targets.reconcile_targets") as work:
            for parameters in (
                {"instrument": "USD_JPY"},
                {"instrument": ["EUR_USD"]},
                [],
                {"instrument": "EUR_USD", "extra": "x"},
            ):
                with self.subTest(parameters=parameters), self.assertRaises(ValidationError):
                    reconcile(parameters)
        work.assert_not_called()
