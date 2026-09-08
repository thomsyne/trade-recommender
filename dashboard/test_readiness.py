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


def attempt_id(seed):
    """A stable attempt identity; every record of one attempt shares it."""
    return f"101-{seed}-20260907T120000Z"


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

    def test_malformed_success_record_is_not_read_as_a_success(self):
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(1),
            completed_at="not-a-timestamp",
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
        )
        write_state(
            self.directory,
            "backup-last-attempt",
            attempt_id=attempt_id(1),
            object_key="postgres/20260907T120000Z.sql.gz",
            outcome="success",
            stage="record",
        )

        response = self.ready()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["backup"]["state"], "success_malformed")

    def test_success_belonging_to_an_unresolved_attempt_is_not_committed(self):
        # backup.sh publishes the success detail before committing, and keeps
        # its in-progress evidence when the commit fails.
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(7),
            completed_at=iso(timedelta(minutes=2)),
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
        )
        write_state(
            self.directory,
            "backup-in-progress",
            attempt_id=attempt_id(7),
            started_at=iso(timedelta(minutes=3)),
            object_key="postgres/20260907T120000Z.sql.gz",
            stage="record",
        )

        response = self.ready()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["backup"]["state"], "uncommitted")

    def test_future_dated_success_is_rejected(self):
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(2),
            completed_at=iso(-timedelta(hours=3)),
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
        )
        write_state(
            self.directory,
            "backup-last-attempt",
            attempt_id=attempt_id(2),
            object_key="postgres/20260907T120000Z.sql.gz",
            outcome="success",
            stage="record",
        )

        response = self.ready()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["backup"]["state"], "future_dated")

    def test_fresh_success_is_ready_and_reports_safe_detail(self):
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(1),
            completed_at=iso(timedelta(hours=1)),
            attempted_at=iso(timedelta(hours=1)),
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
            size_bytes=1234,
        )
        write_state(
            self.directory,
            "backup-last-attempt",
            attempt_id=attempt_id(1),
            attempted_at=iso(timedelta(hours=1)),
            object_key="postgres/20260907T120000Z.sql.gz",
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
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(1),
            completed_at=iso(timedelta(hours=10)),
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
        )
        write_state(
            self.directory,
            "backup-last-attempt",
            attempt_id=attempt_id(1),
            object_key="postgres/20260907T120000Z.sql.gz",
            outcome="success",
            stage="record",
        )

        response = self.ready()
        self.assertEqual(response.status_code, 503)
        self.assertIn("backup", response.json()["checks"])
        self.assertEqual(response.json()["backup"]["state"], "stale")

    def test_recent_failure_after_valid_success_stays_ready_but_is_visible(self):
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(1),
            completed_at=iso(timedelta(hours=2)),
            attempted_at=iso(timedelta(hours=2)),
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
        )
        write_state(
            self.directory,
            "backup-last-attempt",
            attempt_id=attempt_id(2),
            attempted_at=iso(timedelta(hours=1)),
            object_key="postgres/20260907T120000Z.sql.gz",
            outcome="failure",
            stage="upload",
            category="upload_failed",
        )
        write_state(
            self.directory,
            "backup-last-failure",
            attempt_id=attempt_id(2),
            failed_at=iso(timedelta(hours=1)),
            attempted_at=iso(timedelta(hours=1)),
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

    def test_success_contradicted_by_failed_attempt_record_is_not_trusted(self):
        # Pre-fix backup.sh could publish a success and then have an interrupt
        # overwrite the same attempt with outcome=failure. Readiness must not
        # trust the orphaned success timestamp.
        attempted_at = iso(timedelta(hours=1))
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(1),
            completed_at=attempted_at,
            attempted_at=attempted_at,
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
            size_bytes=1234,
        )
        write_state(
            self.directory,
            "backup-last-attempt",
            attempt_id=attempt_id(1),
            attempted_at=attempted_at,
            object_key="postgres/20260907T120000Z.sql.gz",
            outcome="failure",
            stage="record",
            category="interrupted",
        )
        write_state(
            self.directory,
            "backup-last-failure",
            attempt_id=attempt_id(1),
            failed_at=attempted_at,
            attempted_at=attempted_at,
            stage="record",
            category="interrupted",
            exit_status=143,
        )

        response = self.ready()

        self.assertEqual(response.status_code, 503)
        self.assertIn("backup", response.json()["checks"])
        self.assertEqual(response.json()["backup"]["state"], "contradicted")

    def test_success_contradicted_by_failure_of_the_same_attempt_is_not_trusted(self):
        # The failure record alone contradicts the success even when no attempt
        # record was parsed (e.g. a partially written pre-fix state directory).
        attempted_at = iso(timedelta(hours=1))
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(1),
            completed_at=attempted_at,
            attempted_at=attempted_at,
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
            size_bytes=1234,
        )
        write_state(
            self.directory,
            "backup-last-failure",
            attempt_id=attempt_id(1),
            failed_at=attempted_at,
            attempted_at=attempted_at,
            stage="record",
            category="interrupted",
            exit_status=143,
        )

        response = self.ready()

        self.assertEqual(response.status_code, 503)
        self.assertIn("backup", response.json()["checks"])
        self.assertEqual(response.json()["backup"]["state"], "contradicted")

    def test_same_second_distinct_attempts_are_not_conflated(self):
        # Two attempts that started in the same second (the pre-fix collision
        # that corrupted the state protocol) carry distinct attempt_ids: the
        # older genuine success must not be contradicted by the other attempt's
        # failure merely because their attempted_at values match.
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(1),
            completed_at=iso(timedelta(hours=2)),
            attempted_at=iso(timedelta(hours=2)),
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
            size_bytes=1234,
        )
        same_second = iso(timedelta(hours=1))
        write_state(
            self.directory,
            "backup-last-attempt",
            attempt_id=attempt_id(2),
            attempted_at=same_second,
            object_key="postgres/20260907T120000Z.sql.gz",
            outcome="failure",
            stage="dump",
            category="dump_failed",
        )
        write_state(
            self.directory,
            "backup-last-failure",
            attempt_id=attempt_id(2),
            failed_at=same_second,
            attempted_at=same_second,
            stage="dump",
            category="dump_failed",
            exit_status=1,
        )

        response = self.ready()

        self.assertEqual(response.status_code, 200)
        body = response.json()["backup"]
        self.assertEqual(body["state"], "fresh")
        self.assertEqual(body["warning"], "last_attempt_failed")

    def test_failure_of_a_later_attempt_keeps_an_older_genuine_success(self):
        # A failed attempt that is newer than the last success is a warning,
        # not a contradiction: the success and failure belong to different
        # attempted_at values.
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(1),
            completed_at=iso(timedelta(hours=2)),
            attempted_at=iso(timedelta(hours=2)),
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
        )
        write_state(
            self.directory,
            "backup-last-attempt",
            attempt_id=attempt_id(2),
            attempted_at=iso(timedelta(hours=1)),
            object_key="postgres/20260907T120000Z.sql.gz",
            outcome="failure",
            stage="upload",
            category="upload_failed",
        )
        write_state(
            self.directory,
            "backup-last-failure",
            attempt_id=attempt_id(2),
            failed_at=iso(timedelta(hours=1)),
            attempted_at=iso(timedelta(hours=1)),
            stage="upload",
            category="upload_failed",
            exit_status=1,
        )

        response = self.ready()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["backup"]["state"], "fresh")

    def test_committed_success_without_a_published_success_file_is_reported(self):
        # The new producer commits the attempt record before publishing the
        # success file; if it is interrupted inside that window the committed
        # attempt stands but readiness must not invent a success timestamp.
        attempted_at = iso(timedelta(hours=1))
        write_state(
            self.directory,
            "backup-last-attempt",
            attempt_id=attempt_id(1),
            attempted_at=attempted_at,
            object_key="postgres/20260907T120000Z.sql.gz",
            outcome="success",
            stage="record",
            category="none",
        )

        response = self.ready()

        self.assertEqual(response.status_code, 503)
        self.assertIn("backup", response.json()["checks"])
        self.assertEqual(response.json()["backup"]["state"], "success_missing")
        self.assertEqual(response.json()["backup"]["last_attempt_outcome"], "success")

    def test_no_successful_backup_fails_readiness(self):
        response = self.ready()
        self.assertEqual(response.status_code, 503)
        self.assertIn("backup", response.json()["checks"])
        self.assertEqual(response.json()["backup"]["state"], "missing")

    def test_recent_in_progress_attempt_is_reported_but_not_stale(self):
        # A backup that started within the readiness window is honest progress:
        # readiness keeps the last genuine success green and reports the run.
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(1),
            completed_at=iso(timedelta(hours=1)),
            attempted_at=iso(timedelta(hours=1)),
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
            size_bytes=1234,
        )
        write_state(
            self.directory,
            "backup-last-attempt",
            attempt_id=attempt_id(1),
            object_key="postgres/20260907T120000Z.sql.gz",
            outcome="success",
            stage="record",
        )
        write_state(
            self.directory,
            "backup-in-progress",
            attempt_id=attempt_id(2),
            started_at=iso(timedelta(minutes=1)),
            attempted_at=iso(timedelta(minutes=1)),
            object_key="postgres/20260907T120000Z.sql.gz",
            stage="dump",
        )

        response = self.ready()

        self.assertEqual(response.status_code, 200)
        body = response.json()["backup"]
        self.assertEqual(body["state"], "fresh")
        self.assertTrue(body["attempt_in_progress"])

    def test_stale_in_progress_attempt_fails_readiness(self):
        # A durable in-progress record older than the readiness window means the
        # previous attempt died without a terminal outcome; readiness must say so.
        write_state(
            self.directory,
            "backup-last-success",
            attempt_id=attempt_id(1),
            completed_at=iso(timedelta(hours=1)),
            attempted_at=iso(timedelta(hours=1)),
            object_key="postgres/20260907T120000Z.sql.gz",
            version_id="v-fixture-1",
            sha256="a" * 64,
            size_bytes=1234,
        )
        write_state(
            self.directory,
            "backup-in-progress",
            attempt_id=attempt_id(2),
            started_at=iso(timedelta(hours=20)),
            attempted_at=iso(timedelta(hours=20)),
            object_key="postgres/20260907T120000Z.sql.gz",
            stage="upload",
        )

        response = self.ready()

        self.assertEqual(response.status_code, 503)
        self.assertIn("backup", response.json()["checks"])
        self.assertEqual(response.json()["backup"]["state"], "attempt_stale")

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
            attempt_id=attempt_id(1),
            completed_at=iso(timedelta(hours=1)),
            object_key="<script>alert(1)</script>",
            version_id="v-fixture-1",
            sha256="a" * 64,
        )
        response = self.ready()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["backup"]["state"], "success_partial")
        self.assertNotIn("<script>", response.content.decode())
        self.assertNotIn("alert(1)", response.content.decode())


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

        # A second scheduled job runs the SAME task for a different series. Its
        # success must not launder the first job's failure.
        other_job = ScheduledJob.objects.create(
            name="EUR_USD pair evidence (sibling series)",
            task_name=job.task_name,
            parameters={"instrument": "EUR_USD", "granularity": "H4"},
            interval_seconds=14_400,
            next_run_at=now + timedelta(hours=1),
        )
        stranded = JobOccurrence.objects.create(
            idempotency_key="stranded-other-series",
            scheduled_job=other_job,
            task_name=other_job.task_name,
            parameters=other_job.parameters,
            scheduled_for=now - timedelta(hours=4),
            available_at=now - timedelta(hours=4),
            status=JobOccurrence.Status.FAILED,
            attempts=3,
            max_attempts=3,
        )
        cls.stranded_failure = TaskFailure.objects.create(
            occurrence=stranded,
            attempt_number=3,
            task_name=other_job.task_name,
            error_code="provider_timeout",
            category="network",
            stage="provider_fetch",
            exception_type="ReadTimeout",
            summary="ReadTimeout: provider request timed out",
            terminal=True,
            occurred_at=now - timedelta(hours=4),
        )

    def failure_row(self, content, failure):
        rows = [
            chunk for chunk in content.split("<tr>") if f"#{failure.occurrence_id}</small>" in chunk
        ]
        self.assertEqual(len(rows), 1, failure.occurrence_id)
        return rows[0]

    def test_a_sibling_jobs_success_does_not_mark_another_series_recovered(self):
        """Recovery is per scheduled job, not per task name."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("operations"))
        content = response.content.decode()

        row = self.failure_row(content, self.stranded_failure)
        self.assertIn("TERMINAL", row)
        self.assertNotIn("RECOVERED", row)

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


@override_settings(
    DEBUG=True,
    OANDA_TOKEN="",
    OANDA_ACCOUNT_ID="",
    ANTHROPIC_API_KEY="",
    EODHD_API_TOKEN="",
    POSTMORTEM_INTERPRETATION_ENABLED=False,
    RECOMMENDATION_SCHEDULE_ENABLED=False,
)
class JobRecoveryProjectionTests(TestCase):
    """Recovery is the newest success for the work, not whichever row came last."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.user = get_user_model().objects.get(username="owner")
        cls.now = timezone.now()
        cls.job = ScheduledJob.objects.create(
            name="OANDA multi-series ingest",
            task_name="market.ingest_oanda",
            parameters={"instrument": "USD_CAD", "granularity": "H1"},
            interval_seconds=3600,
            next_run_at=cls.now + timedelta(hours=1),
        )

    def occurrence(self, key, *, status, offset, parameters, job="__scheduled__"):
        # An explicit job=None means an ad-hoc occurrence, which is not the same
        # as omitting the argument.
        return JobOccurrence.objects.create(
            idempotency_key=key,
            scheduled_job=self.job if job == "__scheduled__" else job,
            task_name=self.job.task_name,
            parameters=parameters,
            scheduled_for=self.now - timedelta(hours=offset),
            available_at=self.now - timedelta(hours=offset),
            status=status,
            attempts=1,
        )

    def failure(self, occurrence, *, offset):
        return TaskFailure.objects.create(
            occurrence=occurrence,
            attempt_number=1,
            task_name=occurrence.task_name,
            error_code="provider_timeout",
            category="network",
            stage="provider_fetch",
            exception_type="ReadTimeout",
            summary="ReadTimeout: provider request timed out",
            terminal=True,
            occurred_at=self.now - timedelta(hours=offset),
        )

    def failure_row(self, content, failure):
        rows = [
            chunk for chunk in content.split("<tr>") if f"#{failure.occurrence_id}</small>" in chunk
        ]
        self.assertEqual(len(rows), 1, failure.occurrence_id)
        return rows[0]

    def page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("operations"))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_newest_success_across_parameter_groups_decides_recovery(self):
        # One scheduled job, two parameter groups. The older group's success
        # must not be the one that survives the collapse to job identity.
        failed = self.occurrence(
            "multi-failed",
            status=JobOccurrence.Status.FAILED,
            offset=6,
            parameters={"instrument": "USD_CAD", "granularity": "H1"},
        )
        record = self.failure(failed, offset=6)
        self.occurrence(
            "multi-old-success",
            status=JobOccurrence.Status.SUCCEEDED,
            offset=8,
            parameters={"granularity": "H4", "instrument": "EUR_USD"},
        )
        self.occurrence(
            "multi-new-success",
            status=JobOccurrence.Status.SUCCEEDED,
            offset=1,
            parameters={"instrument": "USD_CAD", "granularity": "H1"},
        )

        row = self.failure_row(self.page(), record)

        self.assertIn("RECOVERED LATER", row)

    def test_only_older_successes_leave_the_failure_unrecovered(self):
        failed = self.occurrence(
            "older-only-failed",
            status=JobOccurrence.Status.FAILED,
            offset=2,
            parameters={"instrument": "USD_CAD", "granularity": "H1"},
        )
        record = self.failure(failed, offset=2)
        # Two groups, both older than the failure, in an order that would make
        # last-write-wins pick either one.
        self.occurrence(
            "older-a",
            status=JobOccurrence.Status.SUCCEEDED,
            offset=9,
            parameters={"granularity": "H1", "instrument": "USD_CAD"},
        )
        self.occurrence(
            "older-b",
            status=JobOccurrence.Status.SUCCEEDED,
            offset=5,
            parameters={"instrument": "GBP_USD", "granularity": "H4"},
        )

        row = self.failure_row(self.page(), record)

        self.assertNotIn("RECOVERED", row)
        self.assertIn("TERMINAL", row)

    def test_key_order_does_not_split_an_ad_hoc_identity(self):
        adhoc_failed = self.occurrence(
            "adhoc-failed",
            status=JobOccurrence.Status.FAILED,
            offset=4,
            parameters={"instrument": "USD_CAD", "granularity": "H1"},
            job=None,
        )
        record = self.failure(adhoc_failed, offset=4)
        self.occurrence(
            "adhoc-success",
            status=JobOccurrence.Status.SUCCEEDED,
            offset=1,
            parameters={"granularity": "H1", "instrument": "USD_CAD"},
            job=None,
        )

        row = self.failure_row(self.page(), record)

        self.assertIn("RECOVERED LATER", row)

    def test_absent_parameters_are_not_the_same_identity_as_empty_ones(self):
        adhoc_failed = self.occurrence(
            "adhoc-empty-failed",
            status=JobOccurrence.Status.FAILED,
            offset=4,
            parameters={},
            job=None,
        )
        record = self.failure(adhoc_failed, offset=4)
        self.occurrence(
            "adhoc-other-success",
            status=JobOccurrence.Status.SUCCEEDED,
            offset=1,
            parameters={"instrument": "USD_CAD"},
            job=None,
        )

        row = self.failure_row(self.page(), record)

        self.assertNotIn("RECOVERED", row)

    def test_a_sibling_scheduled_job_does_not_recover_this_one(self):
        sibling = ScheduledJob.objects.create(
            name="OANDA sibling series",
            task_name=self.job.task_name,
            parameters={"instrument": "EUR_USD", "granularity": "H4"},
            interval_seconds=14_400,
            next_run_at=self.now + timedelta(hours=1),
        )
        failed = self.occurrence(
            "sibling-failed",
            status=JobOccurrence.Status.FAILED,
            offset=4,
            parameters=self.job.parameters,
        )
        record = self.failure(failed, offset=4)
        self.occurrence(
            "sibling-success",
            status=JobOccurrence.Status.SUCCEEDED,
            offset=1,
            parameters=sibling.parameters,
            job=sibling,
        )

        row = self.failure_row(self.page(), record)

        self.assertNotIn("RECOVERED", row)
