from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from operations.models import JobOccurrence, ScheduledJob
from operations.services import claim_next_job, enqueue_due_jobs, finish_job


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
