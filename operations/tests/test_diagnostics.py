"""Phase 1.5 — safe failure diagnostics, job-state projection and provider accounting."""

from datetime import timedelta
from decimal import Decimal

import httpx
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.utils import timezone

from market.models import Instrument
from market.oanda import OandaError
from operations.accounting import provider_accounts
from operations.diagnostics import classify_failure, redact, task_stage
from operations.job_state import project_job_state
from operations.models import (
    JobOccurrence,
    ProviderBudget,
    ProviderBudgetReservation,
    ScheduledJob,
    TaskFailure,
)
from operations.services import (
    claim_next_job,
    finish_job,
    record_reservation_outcome,
    reserve_provider_budget,
    settle_provider_budget,
)
from research.models import ProviderEvaluation


class RedactionTests(TestCase):
    def test_tokens_credentials_urls_and_environment_text_are_redacted(self):
        text = (
            "Authorization: Bearer sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789 failed; "
            "POSTGRES_PASSWORD=super-secret-value while calling "
            "https://user:pa55word@api.example.com/v1?token=abcdef0123456789abcdef0123456789abcdef01 "
            "with AKIAABCDEFGHIJKLMNOP and eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"
        )
        redacted = redact(text)
        for secret in (
            "sk-ant-api03",
            "super-secret-value",
            "pa55word",
            "abcdef0123456789abcdef0123456789abcdef01",
            "AKIAABCDEFGHIJKLMNOP",
            "eyJhbGciOiJIUzI1NiJ9",
        ):
            self.assertNotIn(secret, redacted)
        self.assertIn("[redacted]", redacted)
        self.assertIn("api.example.com", redacted)
        self.assertLessEqual(len(redacted), 240)
        self.assertEqual(redact(None), "")
        self.assertEqual(redact("word " * 200)[-1], "…")

    def test_canonical_credential_shapes_are_redacted(self):
        # Each shape carries a marker that must never survive redaction, whether
        # redacted directly or carried inside a classified provider message.
        shapes = {
            "authorization_bearer_short": ("Authorization: Bearer short-BEARER456", "BEARER456"),
            "authorization_bearer_symbols": (
                "Authorization: Bearer ab+cd/ef=BEARER457==",
                "BEARER457",
            ),
            "authorization_basic": (
                "Authorization: Basic dXNlcjpCQVNJQzQ1OA==",
                "dXNlcjpCQVNJQzQ1OA",
            ),
            "authorization_equals": ("authorization=Bearer BEARER459", "BEARER459"),
            "proxy_authorization": ("Proxy-Authorization: Basic UFJPWFk0NjA=", "UFJPWFk0NjA"),
            "bearer_without_header": ("Bearer BEARER461", "BEARER461"),
            "key": ("key=should-not-appear-KEY111", "KEY111"),
            "pwd": ("pwd=PWD222", "PWD222"),
            "pass": ("pass=PASS333", "PASS333"),
            "client_secret": ("client_secret=CS444", "CS444"),
            "access_token_query": ("https://api.example.com/v1?access_token=AT555", "AT555"),
            "mixed_case_env": ("Postgres_Password=PGP666", "PGP666"),
            "url_userinfo_token_only": (
                "https://ghp_should-not-appear-GHP222@github.com/x",
                "GHP222",
            ),
            "url_userinfo_password": ("https://alice:pa55w0rd-PW789@host/x", "PW789"),
            "short_sk": ("sk-abc", "sk-abc"),
            "aws_secret_with_slash": (
                "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                "wJalrXUtnFEMI",
            ),
            "bare_aws_secret": ("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI"),
            "x_api_key_header": ("x-api-key: XAPI777", "XAPI777"),
            "json_api_key": ('{"api_key": "JSON888"}', "JSON888"),
            "token_colon": ("token: TOK999", "TOK999"),
            "cookie_header": ("Cookie: sessionid=SESS000", "SESS000"),
            "upper_env": ("OANDA_TOKEN=should-not-appear-ENV000", "ENV000"),
        }
        for name, (shape, marker) in shapes.items():
            with self.subTest(name):
                self.assertIn(marker, shape)
                direct = redact(f"failed: {shape} then continued")
                self.assertNotIn(marker, direct, direct)
                self.assertIn("[redacted]", direct)
                classified = classify_failure(
                    OandaError(f"OANDA returned HTTP 401: {shape}", failure_kind="auth")
                ).summary
                self.assertNotIn(marker, classified, classified)
        # Benign provider text with no separator or credential is left readable.
        benign = "OANDA returned HTTP 401: Insufficient authorization to perform request."
        self.assertEqual(redact(benign), benign)
        self.assertIn("api.example.com", redact("https://api.example.com/v1?access_token=x"))

    def test_known_exception_types_map_to_stable_codes(self):
        cases = (
            (ValueError("OANDA_TOKEN is not configured"), "configuration_missing", False),
            (ValueError("Postmortem interpretation is disabled"), "feature_disabled", False),
            (ValueError("Unknown task: x"), "unknown_task", False),
            (
                ValidationError("Recommendation cites unavailable evidence"),
                "validation_rejected",
                False,
            ),
            (DatabaseError("connection dropped password=hunter2"), "database_error", True),
            (
                OandaError("OANDA returned HTTP 401", failure_kind="auth"),
                "provider_oanda_auth",
                False,
            ),
            (httpx.ConnectTimeout("timed out"), "provider_timeout", True),
            (httpx.ConnectError("refused"), "provider_network", True),
            (
                RuntimeError("Recommendation batch incomplete — USD_CAD: token=abc"),
                "batch_incomplete",
                True,
            ),
            (RuntimeError("Anthropic request failed with HTTP 529"), "provider_http", True),
        )
        for error, code, retryable in cases:
            diagnostic = classify_failure(error)
            self.assertEqual(diagnostic.code, code, error)
            self.assertEqual(diagnostic.retryable, retryable, error)
            self.assertEqual(diagnostic.exception_type, type(error).__name__)
            self.assertNotIn("hunter2", diagnostic.summary)
            self.assertNotIn("token=abc", diagnostic.summary)

    def test_unknown_exception_type_withholds_its_message(self):
        class ProviderLeak(Exception):
            pass

        diagnostic = classify_failure(ProviderLeak("response body: {api_key: 'sk-secret'}"))

        self.assertEqual(diagnostic.code, "unclassified_exception")
        self.assertEqual(diagnostic.exception_type, "ProviderLeak")
        self.assertEqual(
            diagnostic.summary, "ProviderLeak: details withheld (unclassified exception)"
        )
        self.assertNotIn("sk-secret", diagnostic.summary)

    def test_task_stage_annotates_the_first_stage_only(self):
        with self.assertRaises(RuntimeError) as caught:
            with task_stage("outer"):
                with task_stage("provider_fetch"):
                    raise RuntimeError("boom")
        self.assertEqual(classify_failure(caught.exception).stage, "provider_fetch")


class TaskFailureRecordTests(TestCase):
    def occurrence(self, key="one", max_attempts=3):
        now = timezone.now()
        return JobOccurrence.objects.create(
            idempotency_key=key,
            task_name="market.ingest_oanda",
            scheduled_for=now,
            available_at=now,
            max_attempts=max_attempts,
        )

    def test_retry_then_success_keeps_the_failure_record(self):
        self.occurrence()
        claimed = claim_next_job("worker", timezone.now())
        with self.assertRaises(OandaError) as caught:
            with task_stage("provider_fetch"):
                raise OandaError("OANDA returned HTTP 503", failure_kind="http")
        finish_job(claimed, "worker", error=caught.exception)
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, JobOccurrence.Status.QUEUED)
        self.assertEqual(claimed.error_code, "provider_oanda_http")
        failure = TaskFailure.objects.get()
        self.assertEqual(failure.attempt_number, 1)
        self.assertEqual(failure.stage, "provider_fetch")
        self.assertFalse(failure.terminal)
        self.assertEqual(failure.task_name, "market.ingest_oanda")

        JobOccurrence.objects.filter(pk=claimed.pk).update(available_at=timezone.now())
        again = claim_next_job("worker", timezone.now())
        self.assertEqual(again.pk, claimed.pk)
        self.assertEqual(again.error_code, "")
        finish_job(again, "worker")
        again.refresh_from_db()
        self.assertEqual(again.status, JobOccurrence.Status.SUCCEEDED)
        self.assertEqual(TaskFailure.objects.count(), 1)
        failure.summary = "rewritten"
        with self.assertRaises(ValidationError):
            failure.save()
        with self.assertRaises(ValidationError):
            failure.delete()

    def test_repeated_terminal_failures_are_recorded_per_attempt(self):
        self.occurrence(max_attempts=2)
        for attempt in (1, 2):
            claimed = claim_next_job("worker", timezone.now())
            JobOccurrence.objects.filter(pk=claimed.pk)
            finish_job(claimed, "worker", error=ValueError("OANDA_TOKEN is not configured"))
            JobOccurrence.objects.filter(pk=claimed.pk).update(available_at=timezone.now())
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, JobOccurrence.Status.FAILED)
        failures = list(TaskFailure.objects.order_by("attempt_number"))
        self.assertEqual([f.attempt_number for f in failures], [1, 2])
        self.assertEqual([f.terminal for f in failures], [False, True])
        self.assertEqual({f.error_code for f in failures}, {"configuration_missing"})
        self.assertEqual(claimed.error_summary, "OANDA_TOKEN is not configured")

    def test_expired_lease_records_a_failure(self):
        now = timezone.now()
        JobOccurrence.objects.create(
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
        claim_next_job("new", now)
        failure = TaskFailure.objects.get()
        self.assertEqual(failure.error_code, "lease_expired")
        self.assertEqual(failure.stage, "lease")
        self.assertTrue(failure.terminal)


@override_settings(
    OANDA_TOKEN="",
    OANDA_ACCOUNT_ID="",
    ANTHROPIC_API_KEY="",
    EODHD_API_TOKEN="",
    POSTMORTEM_INTERPRETATION_ENABLED=False,
    RECOMMENDATION_SCHEDULE_ENABLED=False,
)
class JobStateProjectionTests(TestCase):
    def job(self, name="job", task="test.task", enabled=True, parameters=None, **changes):
        values = {
            "name": name,
            "task_name": task,
            "parameters": parameters or {},
            "interval_seconds": 3600,
            "next_run_at": timezone.now() + timedelta(hours=1),
            "enabled": enabled,
        }
        values.update(changes)
        return ScheduledJob.objects.create(**values)

    def occurrence(self, job, status, *, attempts=0, offset=0, **changes):
        now = timezone.now() + timedelta(minutes=offset)
        values = {
            "idempotency_key": f"{job.pk}:{offset}",
            "scheduled_job": job,
            "task_name": job.task_name,
            "scheduled_for": now,
            "available_at": now,
            "status": status,
            "attempts": attempts,
        }
        values.update(changes)
        return JobOccurrence.objects.create(**values)

    def test_enabled_states(self):
        now = timezone.now()
        scheduled = self.job("scheduled")
        self.assertEqual(project_job_state(scheduled, now=now).state, "scheduled")

        queued = self.job("queued")
        self.occurrence(queued, JobOccurrence.Status.QUEUED)
        self.assertEqual(project_job_state(queued, now=now).state, "queued")

        running = self.job("running")
        self.occurrence(running, JobOccurrence.Status.RUNNING, attempts=1, heartbeat_at=now)
        self.assertEqual(project_job_state(running, now=now).state, "running")

        stale = self.job("stale")
        self.occurrence(
            stale,
            JobOccurrence.Status.RUNNING,
            attempts=1,
            heartbeat_at=now - timedelta(minutes=30),
        )
        self.assertEqual(project_job_state(stale, now=now).state, "stale")

        retrying = self.job("retrying")
        self.occurrence(retrying, JobOccurrence.Status.QUEUED, attempts=1, available_at=now)
        state = project_job_state(retrying, now=now)
        self.assertEqual(state.state, "retrying")
        self.assertIn("retry 2 of 3", state.reason)

        failed = self.job("failed")
        self.occurrence(failed, JobOccurrence.Status.FAILED, attempts=3, error_code="provider_http")
        state = project_job_state(failed, now=now)
        self.assertEqual(state.state, "failed")
        self.assertIn("provider_http", state.reason)

        recovered = self.job("recovered")
        self.occurrence(recovered, JobOccurrence.Status.FAILED, attempts=3, offset=-120)
        self.occurrence(recovered, JobOccurrence.Status.SUCCEEDED, attempts=1, offset=-60)
        state = project_job_state(recovered, now=now)
        self.assertEqual(state.state, "recovered")
        self.assertIsNotNone(state.recovered_by)

        overdue = self.job("overdue", next_run_at=now - timedelta(hours=2))
        state = project_job_state(overdue, now=now)
        self.assertEqual(state.state, "stale")
        self.assertIn("Overdue", state.reason)

    def test_disabled_states_are_data_driven_not_credential_labels(self):
        now = timezone.now()
        postmortem = self.job("postmortem", "forecast.interpret_postmortems", enabled=False)
        state = project_job_state(postmortem, now=now)
        self.assertEqual(state.state, "disabled_intentional")
        self.assertIn("intentionally disabled", state.reason)
        self.assertEqual(state.label, "DISABLED — INTENTIONAL")

        ProviderEvaluation.objects.create(
            category="economic-calendar",
            provider="EODHD",
            status=ProviderEvaluation.Status.REJECTED,
            evidence_url="https://eodhd.com/",
            pricing_status="n/a",
            timestamp_semantics="n/a",
            revision_support="n/a",
            retention_rights="n/a",
            reliability_result="NOT SELECTED — FREE KEY EXCLUDES ECONOMIC EVENTS",
            next_check="n/a",
        )
        eodhd = self.job("eodhd", "research.ingest_eodhd_calendar", enabled=False)
        state = project_job_state(eodhd, now=now)
        self.assertEqual(state.state, "disabled_capability")
        self.assertIn("subscription", state.reason)

        Instrument.objects.create(
            code="USD_JPY", base_currency="USD", quote_currency="JPY", display_order=5, active=False
        )
        Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=4, active=True
        )
        out_of_scope = self.job(
            "jpy", "market.ingest_oanda", enabled=False, parameters={"instrument": "USD_JPY"}
        )
        self.assertEqual(project_job_state(out_of_scope, now=now).state, "disabled_intentional")
        no_token = self.job(
            "cad", "market.ingest_oanda", enabled=False, parameters={"instrument": "USD_CAD"}
        )
        state = project_job_state(no_token, now=now)
        self.assertEqual(state.state, "disabled_configuration")
        self.assertIn("OANDA_TOKEN", state.reason)

        recommendations = self.job("rec", "forecast.generate_recommendations", enabled=False)
        self.assertEqual(project_job_state(recommendations, now=now).state, "disabled_intentional")
        terms = self.job("terms", "market.capture_oanda_terms", enabled=False)
        self.assertEqual(project_job_state(terms, now=now).state, "disabled_configuration")
        for state in (project_job_state(job, now=now) for job in ScheduledJob.objects.all()):
            self.assertNotIn("credential", state.label.lower())
            self.assertNotIn("stuck", state.reason.lower())


class ProviderAccountingTests(TestCase):
    def setUp(self):
        self.budget = ProviderBudget.objects.create(
            provider="anthropic",
            purpose="recommendation",
            daily_cap_usd=Decimal("2"),
            monthly_cap_usd=Decimal("40"),
        )

    def test_reservation_settlement_and_outcome_populations_stay_distinct(self):
        validated = reserve_provider_budget(
            "anthropic",
            "recommendation",
            "recommendation:key-1",
            "0.01",
            requested_model="claude-sonnet-5",
            pricing_version="anthropic-standard-2026-08-10",
        )
        self.assertEqual(validated.outcome, ProviderBudgetReservation.Outcome.PENDING)
        self.assertEqual(validated.requested_model, "claude-sonnet-5")
        settle_provider_budget(
            validated, "0.005", returned_model="claude-sonnet-5", usage_identity="msg_1"
        )
        self.assertTrue(
            record_reservation_outcome(validated, ProviderBudgetReservation.Outcome.VALIDATED)
        )
        self.assertFalse(
            record_reservation_outcome(validated, ProviderBudgetReservation.Outcome.REJECTED)
        )
        rejected = reserve_provider_budget(
            "anthropic", "recommendation", "recommendation:key-2", "0.01", requested_model="m"
        )
        settle_provider_budget(rejected, "0.004", returned_model="")
        record_reservation_outcome(rejected, ProviderBudgetReservation.Outcome.REJECTED)
        reserved = reserve_provider_budget(
            "anthropic", "recommendation", "recommendation:key-3", "0.02"
        )
        legacy = ProviderBudgetReservation.objects.create(
            budget=self.budget,
            idempotency_key="recommendation:legacy",
            estimated_usd=Decimal("0.01"),
            actual_usd=Decimal("0.003"),
            status=ProviderBudgetReservation.Status.SETTLED,
        )
        self.assertEqual(legacy.outcome, "")
        self.assertFalse(
            record_reservation_outcome(legacy, ProviderBudgetReservation.Outcome.VALIDATED)
        )
        legacy.refresh_from_db()
        self.assertEqual(legacy.outcome, "")
        self.assertEqual(legacy.returned_model, "")

        today = next(a for a in provider_accounts() if a.period == "today")
        self.assertEqual(today.reserved_count, 1)
        self.assertEqual(today.reserved_estimate_usd, Decimal("0.02"))
        self.assertEqual(today.settled_count, 3)
        self.assertEqual(today.settled_cost_usd, Decimal("0.012"))
        self.assertEqual(today.validated_count, 1)
        self.assertEqual(today.rejected_count, 1)
        self.assertEqual(today.failed_paid_count, 1)
        self.assertEqual(today.failed_paid_usd, Decimal("0.004"))
        self.assertEqual(today.outcome_not_recorded_count, 1)
        self.assertEqual(today.settled_without_recommendation, 3)
        self.assertEqual(today.committed_usd, Decimal("0.032"))
        rejected.refresh_from_db()
        self.assertEqual(rejected.returned_model, "")
        self.assertEqual(reserved.outcome, ProviderBudgetReservation.Outcome.PENDING)
