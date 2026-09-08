"""Phase 1.1/1.5/1.6 — readiness depends on genuine last success; operations page semantics."""

import os
import tempfile
from datetime import UTC, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from operations.models import JobOccurrence, ScheduledJob, TaskFailure


def write_state(directory, name, **values):
    with open(os.path.join(directory, name), "w") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def iso(delta):
    return (timezone.now() - delta).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReadinessBackupStateTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="phase1-readiness-")

    def ready(self):
        with override_settings(
            READINESS_BACKUP_STATE_DIR=self.directory,
            READINESS_BACKUP_MARKER=os.path.join(self.directory, "last-backup"),
            READINESS_BACKUP_MAX_AGE_HOURS=8,
            APP_SOURCE_REVISION="abc123def456",
        ):
            return self.client.get(reverse("ready"))

    def test_fresh_success_is_ready_and_reports_safe_detail(self):
        write_state(
            self.directory,
            "backup-last-success",
            completed_at=iso(timedelta(hours=1)),
            attempted_at=iso(timedelta(hours=1)),
            object_key="postgres/20260907T120000Z.sql.gz",
            sha256="a" * 64,
            size_bytes=1234,
        )
        write_state(
            self.directory,
            "backup-last-attempt",
            attempted_at=iso(timedelta(hours=1)),
            outcome="success",
        )

        response = self.ready()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertNotIn("backup", body["checks"])
        self.assertEqual(body["backup"]["state"], "fresh")
        self.assertEqual(body["backup"]["last_attempt_outcome"], "success")
        self.assertEqual(body["revision"], "abc123def456")
        self.assertNotIn("object_key", body["backup"])
        self.assertNotIn(self.directory, response.content.decode())

    def test_stale_success_fails_readiness(self):
        write_state(self.directory, "backup-last-success", completed_at=iso(timedelta(hours=10)))
        response = self.ready()
        self.assertEqual(response.status_code, 503)
        self.assertIn("backup", response.json()["checks"])
        self.assertEqual(response.json()["backup"]["state"], "stale")

    def test_recent_failure_after_valid_success_stays_ready_but_is_visible(self):
        write_state(self.directory, "backup-last-success", completed_at=iso(timedelta(hours=2)))
        write_state(
            self.directory,
            "backup-last-attempt",
            attempted_at=iso(timedelta(hours=1)),
            outcome="failure",
            stage="upload",
            category="upload_failed",
        )
        write_state(
            self.directory,
            "backup-last-failure",
            failed_at=iso(timedelta(hours=1)),
            stage="upload",
            category="upload_failed",
            exit_status=1,
        )

        response = self.ready()

        self.assertEqual(response.status_code, 200)
        body = response.json()["backup"]
        self.assertEqual(body["state"], "fresh")
        self.assertEqual(body["warning"], "last_attempt_failed")
        self.assertEqual(body["last_attempt_outcome"], "failure")
        self.assertEqual(body["last_failure_category"], "upload_failed")

    def test_no_successful_backup_fails_readiness(self):
        response = self.ready()
        self.assertEqual(response.status_code, 503)
        self.assertIn("backup", response.json()["checks"])
        self.assertEqual(response.json()["backup"]["state"], "missing")

    def test_legacy_marker_only_is_honoured_for_pre_upgrade_hosts(self):
        marker = os.path.join(self.directory, "last-backup")
        with open(marker, "w") as stream:
            stream.write("2026-09-07T12:00:00Z\n")
        response = self.ready()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["backup"]["source"], "legacy_marker")

    def test_tampered_state_values_are_dropped_not_rendered(self):
        write_state(
            self.directory,
            "backup-last-success",
            completed_at=iso(timedelta(hours=1)),
            object_key="<script>alert(1)</script>",
        )
        response = self.ready()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<script>", response.content.decode())


@override_settings(
    DEBUG=True,
    OANDA_TOKEN="",
    OANDA_ACCOUNT_ID="",
    ANTHROPIC_API_KEY="",
    EODHD_API_TOKEN="",
    POSTMORTEM_INTERPRETATION_ENABLED=False,
    RECOMMENDATION_SCHEDULE_ENABLED=False,
    APP_SOURCE_REVISION="feedfacecafebeef",
)
class OperationsPageSemanticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.user = get_user_model().objects.get(username="owner")
        job = ScheduledJob.objects.get(task_name="research.capture_pair_evidence")
        now = timezone.now()
        failed = JobOccurrence.objects.create(
            idempotency_key="failed-batch",
            scheduled_job=job,
            task_name=job.task_name,
            scheduled_for=now - timedelta(hours=3),
            available_at=now - timedelta(hours=3),
            status=JobOccurrence.Status.FAILED,
            attempts=3,
            max_attempts=3,
            error_code="batch_incomplete",
            error_summary="Recommendation batch incomplete",
        )
        TaskFailure.objects.create(
            occurrence=failed,
            attempt_number=3,
            task_name=job.task_name,
            error_code="batch_incomplete",
            category="provider",
            stage="recommendation_batch",
            exception_type="RuntimeError",
            summary="Recommendation batch incomplete — USD_CAD: [redacted]",
            terminal=True,
            occurred_at=now - timedelta(hours=3),
        )
        JobOccurrence.objects.create(
            idempotency_key="recovered-batch",
            scheduled_job=job,
            task_name=job.task_name,
            scheduled_for=now - timedelta(hours=1),
            available_at=now - timedelta(hours=1),
            status=JobOccurrence.Status.SUCCEEDED,
            attempts=1,
        )
        # Attempt 1 failed, attempt 2 of the same occurrence succeeded.
        retried = JobOccurrence.objects.create(
            idempotency_key="retried-batch",
            scheduled_job=job,
            task_name=job.task_name,
            scheduled_for=now - timedelta(minutes=30),
            available_at=now - timedelta(minutes=30),
            status=JobOccurrence.Status.SUCCEEDED,
            attempts=2,
            max_attempts=3,
        )
        cls.retried_failure = TaskFailure.objects.create(
            occurrence=retried,
            attempt_number=1,
            task_name=job.task_name,
            error_code="provider_timeout",
            category="network",
            stage="provider_fetch",
            exception_type="ReadTimeout",
            summary="ReadTimeout: provider request timed out",
            terminal=False,
            occurred_at=now - timedelta(minutes=29),
        )

    def failure_row(self, content, failure):
        rows = [
            chunk for chunk in content.split("<tr>") if f"#{failure.occurrence_id}</small>" in chunk
        ]
        self.assertEqual(len(rows), 1, failure.occurrence_id)
        return rows[0]

    def test_failure_recovered_within_its_own_occurrence_is_labelled_recovered_on_retry(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("operations"))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        row = self.failure_row(content, self.retried_failure)
        self.assertIn("RECOVERED ON RETRY", row)
        self.assertNotIn("RETRYABLE", row)
        self.assertNotIn("RECOVERED LATER", row)
        self.assertNotIn("TERMINAL", row)
        # The terminal failure recovered by a later occurrence keeps its own label.
        terminal = TaskFailure.objects.get(occurrence__idempotency_key="failed-batch")
        self.assertIn("RECOVERED LATER", self.failure_row(content, terminal))

    def test_operations_page_reports_honest_states_and_accessible_semantics(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("operations"))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("WAITING FOR CREDENTIAL", content)
        self.assertContains(response, "DISABLED — INTENTIONAL")
        self.assertContains(response, "DISABLED — CAPABILITY")
        self.assertContains(response, "DISABLED — CONFIGURATION")
        self.assertContains(response, "Postmortem interpretation is intentionally disabled")
        self.assertContains(response, "unavailable under the current subscription")
        self.assertContains(response, "outside the prospective pair scope")
        self.assertContains(response, "OANDA_TOKEN is not configured")
        self.assertNotIn("stuck", content.lower())
        self.assertContains(response, "RECOVERED LATER")
        self.assertContains(response, "batch_incomplete")
        self.assertContains(response, "Running revision and schema")
        self.assertContains(response, "feedfacecafe")
        self.assertContains(response, "MIGRATIONS APPLIED")
        self.assertContains(response, "Live candle series")
        self.assertContains(response, "BACKUP MISSING")
        self.assertContains(response, "Reserved, settled, and validated are different populations")
        self.assertContains(response, 'role="status"')
        self.assertContains(response, 'scope="col"')
        self.assertContains(response, '<caption class="visually-hidden">')
        self.assertContains(response, 'aria-labelledby="schedule-heading"')
        self.assertNotIn("/var/lib/trade-recommender", content)
