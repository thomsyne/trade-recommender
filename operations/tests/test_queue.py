from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from operations.models import (
    DeliveryAttempt,
    JobOccurrence,
    OutboxMessage,
    ProviderBudget,
    ScheduledJob,
)
from operations.services import (
    claim_next_job,
    claim_outbox,
    enqueue_due_jobs,
    enqueue_outbox,
    finish_job,
    finish_outbox,
    mark_provider_budget_uncertain,
    reserve_provider_budget,
    settle_provider_budget,
)


class DurableQueueTests(TestCase):
    def test_scheduler_enqueues_each_occurrence_once_and_advances_schedule(self):
        now = timezone.now()
        job = ScheduledJob.objects.create(
            name="test",
            task_name="test.task",
            interval_seconds=3600,
            next_run_at=now - timedelta(minutes=1),
        )

        first = enqueue_due_jobs(now)
        second = enqueue_due_jobs(now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(JobOccurrence.objects.count(), 1)
        job.refresh_from_db()
        self.assertGreater(job.next_run_at, now)

    def test_worker_claims_atomically_and_retries_with_backoff(self):
        now = timezone.now()
        occurrence = JobOccurrence.objects.create(
            idempotency_key="one", task_name="test.task", scheduled_for=now, available_at=now
        )

        claimed = claim_next_job(now)
        self.assertEqual(claimed.pk, occurrence.pk)
        self.assertEqual(claimed.status, JobOccurrence.Status.RUNNING)
        self.assertIsNone(claim_next_job(now))

        finish_job(claimed, RuntimeError("temporary"))
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, JobOccurrence.Status.QUEUED)
        self.assertGreater(claimed.available_at, now)

    def test_expired_lease_terminal_failure_and_wrong_owner(self):
        now = timezone.now()
        occurrence = JobOccurrence.objects.create(
            idempotency_key="expired",
            task_name="test.task",
            scheduled_for=now,
            available_at=now,
            status=JobOccurrence.Status.RUNNING,
            attempts=1,
            max_attempts=1,
            lease_owner="dead",
            lease_expires_at=now - timedelta(seconds=1),
        )
        self.assertIsNone(claim_next_job("new", now))
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, JobOccurrence.Status.FAILED)

        queued = JobOccurrence.objects.create(
            idempotency_key="owned", task_name="test.task", scheduled_for=now, available_at=now
        )
        claimed = claim_next_job("owner", now)
        self.assertEqual(claimed.pk, queued.pk)
        self.assertFalse(finish_job(claimed, "other"))

    def test_ownerless_running_occurrence_from_rolling_upgrade_is_recovered(self):
        now = timezone.now()
        occurrence = JobOccurrence.objects.create(
            idempotency_key="legacy-running",
            task_name="test.task",
            scheduled_for=now,
            available_at=now,
            status=JobOccurrence.Status.RUNNING,
            attempts=1,
            error_code="legacy_claim",
            error_summary="Legacy worker did not establish a lease",
        )

        claimed = claim_next_job("current-worker", now)

        self.assertEqual(claimed.pk, occurrence.pk)
        self.assertEqual(claimed.status, JobOccurrence.Status.RUNNING)
        self.assertEqual(claimed.attempts, 2)
        self.assertEqual(claimed.lease_owner, "current-worker")
        self.assertEqual(claimed.error_code, "")

    def test_daily_schedule_advances_by_local_date_across_dst(self):
        zone = ZoneInfo("America/Toronto")
        due = timezone.datetime(2026, 3, 7, 19, 0, tzinfo=zone).astimezone(ZoneInfo("UTC"))
        job = ScheduledJob.objects.create(
            name="daily",
            task_name="test.task",
            schedule_type=ScheduledJob.ScheduleType.DAILY,
            timezone_name="America/Toronto",
            local_time=time(19),
            next_run_at=due,
        )
        enqueue_due_jobs(due)
        job.refresh_from_db()
        self.assertEqual(job.next_run_at.astimezone(zone).hour, 19)
        self.assertEqual((job.next_run_at - due).total_seconds(), 23 * 3600)

    def test_latest_policy_collapses_missed_intervals(self):
        now = timezone.now()
        ScheduledJob.objects.create(
            name="latest",
            task_name="test.task",
            interval_seconds=60,
            next_run_at=now - timedelta(minutes=3),
        )
        occurrence = enqueue_due_jobs(now)[0]
        self.assertEqual(occurrence.skipped_count, 3)

    def test_large_interval_backlog_is_bounded(self):
        now = timezone.now()
        job = ScheduledJob.objects.create(
            name="large-backlog",
            task_name="test.task",
            interval_seconds=1,
            missed_run_policy=ScheduledJob.MissedRunPolicy.ALL,
            next_run_at=now - timedelta(days=30),
        )

        occurrences = enqueue_due_jobs(now)

        self.assertEqual(len(occurrences), 1000)
        self.assertEqual(occurrences[0].skipped_count, 30 * 24 * 60 * 60 + 1 - 1000)
        job.refresh_from_db()
        self.assertGreater(job.next_run_at, now)

    def test_outbox_deduplicates_and_recovers_expired_claim(self):
        now = timezone.now()
        first = enqueue_outbox("mail:1", "email", "digest", {}, not_before=now)
        self.assertEqual(first.pk, enqueue_outbox("mail:1", "email", "other", {}).pk)
        claimed = claim_outbox("dead", now)
        OutboxMessage.objects.filter(pk=claimed.pk).update(
            lease_expires_at=now - timedelta(seconds=1)
        )
        recovered = claim_outbox("live", now)
        self.assertEqual(recovered.pk, first.pk)
        self.assertTrue(finish_outbox(recovered, "live", DeliveryAttempt.Outcome.SUCCEEDED))
        self.assertEqual(first.delivery_attempts.count(), 2)
        first_attempt = first.delivery_attempts.get(attempt_number=1)
        self.assertEqual(first_attempt.outcome, DeliveryAttempt.Outcome.UNCERTAIN)
        self.assertEqual(first_attempt.error_code, "lease_expired")

    def test_budget_reservations_are_idempotent_and_conservative(self):
        ProviderBudget.objects.create(
            provider="anthropic",
            purpose="review",
            daily_cap_usd=Decimal("2"),
            monthly_cap_usd=Decimal("3"),
        )
        first = reserve_provider_budget("anthropic", "review", "request:1", "1.25")
        self.assertEqual(
            first.pk, reserve_provider_budget("anthropic", "review", "request:1", "1.25").pk
        )
        self.assertIsNone(reserve_provider_budget("anthropic", "review", "request:2", "1.00"))
        self.assertTrue(settle_provider_budget(first, "0.50"))
        second = reserve_provider_budget("anthropic", "review", "request:2", "1.00")
        self.assertIsNotNone(second)
        self.assertTrue(mark_provider_budget_uncertain(second))


class BudgetConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_reservations_cannot_exceed_cap(self):
        ProviderBudget.objects.create(
            provider="anthropic",
            purpose="recommendation",
            daily_cap_usd=Decimal("1.5000"),
            monthly_cap_usd=Decimal("1.5000"),
        )

        def reserve(key):
            close_old_connections()
            try:
                row = reserve_provider_budget(
                    "anthropic", "recommendation", key, Decimal("1.000000")
                )
                return row is not None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reserve, ("concurrent:1", "concurrent:2")))

        self.assertEqual(sorted(results), [False, True])
