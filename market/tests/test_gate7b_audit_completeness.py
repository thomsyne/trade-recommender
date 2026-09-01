"""Commit-time audit-evidence existence for governed replacement acquisition.

Migration 0021 validates audit events when they are inserted. These tests
cover the deferred constraint trigger that additionally requires the two
governed events to exist when a Gate 7B run becomes terminal, and prove the
guarantee stays inert for v1 acquisition, discovery and prospective runs.
"""

import json
from datetime import UTC, timedelta
from unittest.mock import patch

from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from market.historical_acquisition import (
    begin_historical_attempt,
    resolve_stale_historical_attempt,
    run_historical_chunk,
    stable_hash,
)
from market.historical_discovery import run_discovery_chunk
from market.models import (
    AuditEvent,
    Candle,
    HistoricalDatasetPlan,
    HistoricalIngestionAttempt,
    IngestionManifest,
    IngestionRun,
    Instrument,
)
from market.provider_observed_canary import ACQUISITION_CANARY_LOGICAL_KEY
from market.quality import expected_candle_timestamps
from market.services import DatasetQualityError, store_ingestion
from market.tests.factories import candle
from market.tests.test_gate4_full_discovery import Gate4FixtureTestCase, WaveSuccessClient
from market.tests.test_gate7a_acquisition_canary import CanaryClient, Gate7AFixtureTestCase
from market.tests.test_historical_acquisition import (
    FailingClient,
    FakeClient,
    HistoricalFixtureMixin,
)
from market.tests.test_replacement_canary_activation import MIGRATION_0021, migrate_to

COMPLETENESS_MESSAGE = "replacement acquisition terminal commit requires its audit evidence"
INSERT_MESSAGE = "replacement acquisition audit evidence rejected"
COMPLETENESS_FUNCTION = "market_enforce_acquisition_audit_completeness"
COMPLETENESS_TRIGGER = "market_acquisition_audit_complete"


class DroppingCanaryClient:
    """The canary transport with its final sealed observation withheld."""

    def __init__(self, inner):
        self.inner = inner

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def fetch_historical_chunk(self, *args, **kwargs):
        candles, manifest = self.inner.fetch_historical_chunk(*args, **kwargs)
        return candles[:-1], manifest


class Gate7BAuditFixture(Gate7AFixtureTestCase):
    """Gate 7A replacement lineage under migration 0021, with no acquisition
    attempt yet: the smallest state that carries a governed chunk."""

    retention_policy = "gate7b audit completeness fixture"

    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0021)

    def running_canary_run(self):
        attempt, created = begin_historical_attempt(ACQUISITION_CANARY_LOGICAL_KEY)
        assert created and attempt.ingestion_run.status == IngestionRun.Status.RUNNING
        return attempt, attempt.ingestion_run

    def raw_event(self, cursor, event_type, subject_type, subject_id, payload):
        cursor.execute(
            """INSERT INTO market_auditevent
               (event_type,actor,subject_type,subject_id,payload,occurred_at)
               VALUES (%s,'gate7b-completeness-probe',%s,%s,%s::jsonb,now())""",
            [event_type, subject_type, str(subject_id), json.dumps(payload)],
        )

    def fail_run(self, cursor, run_id):
        cursor.execute(
            """UPDATE market_ingestionrun
               SET status='failed', failure_reason='probe', finished_at=now()
               WHERE id=%s""",
            [run_id],
        )

    def canonical_manifest_payload(self, attempt):
        """The manifest lineage the immediate run guard requires for a
        succeeded governed run, so the probe reaches the deferred trigger."""
        chunk = attempt.chunk
        return {
            "instrument": chunk.instrument.code,
            "granularity": chunk.granularity,
            "from": chunk.requested_from.astimezone(UTC).isoformat(),
            "to": chunk.requested_to.astimezone(UTC).isoformat(),
            "price": "BA",
            "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
            "smooth": False,
            "dailyAlignment": 17,
            "alignmentTimezone": "America/New_York",
            "weeklyAlignment": "Friday",
            "includeFirst": True,
            "complete_only": True,
            "historical_logical_key": chunk.logical_key,
            "historical_attempt": attempt.attempt_number,
            "requests": [
                {
                    "endpoint_identity": (
                        f"oanda-v20-practice:GET:/v3/instruments/{chunk.instrument.code}/candles"
                    ),
                    "http_method": "GET",
                    "oanda_environment": "practice",
                    "http_status": 200,
                    "provider_request_id": "completeness-probe",
                    "canonical_request_sha256": chunk.canonical_request_sha256,
                }
            ],
        }

    def failure_payload(self, attempt, error_code="PROBE"):
        return {
            "schema_version": 1,
            "error_code": error_code,
            "logical_chunk_key": attempt.chunk.logical_key,
            "attempt_id": attempt.pk,
        }

    def rejected_payload(self, attempt, error_code="PROBE"):
        return {
            "schema_version": 1,
            "error_code": error_code,
            "failure_stage": "probe",
            "logical_chunk_key": attempt.chunk.logical_key,
            "attempt_id": attempt.pk,
        }

    def assert_rejected_at_commit(self, work):
        """Run work in its own transaction and require the deferred trigger to
        reject it at COMMIT, leaving a usable connection behind."""
        with self.assertRaises(DatabaseError) as caught, transaction.atomic():
            with connection.cursor() as cursor:
                work(cursor)
        self.assertIn(COMPLETENESS_MESSAGE, str(caught.exception))
        connection.close()


class DeferredAuditEvidenceTests(Gate7BAuditFixture):
    def test_eventless_terminal_transitions_are_rejected_at_commit(self):
        attempt, run = self.running_canary_run()

        # 1. running -> failed carrying no audit evidence at all.
        self.assert_rejected_at_commit(lambda cursor: self.fail_run(cursor, run.pk))
        run.refresh_from_db()
        self.assertEqual(run.status, IngestionRun.Status.RUNNING)
        self.assertEqual(AuditEvent.objects.filter(subject_id=str(attempt.pk)).count(), 0)

        # 2. running -> succeeded carrying no audit evidence, with the manifest
        # the immediate run guard requires already present.
        def succeed_without_events(cursor):
            payload = self.canonical_manifest_payload(attempt)
            IngestionManifest.objects.create(
                ingestion_run=run,
                dataset_version=attempt.chunk.dataset_version,
                payload=payload,
                sha256=stable_hash(payload),
            )
            cursor.execute(
                """UPDATE market_ingestionrun
                   SET status='succeeded', fetched_count=0, stored_count=0, finished_at=now()
                   WHERE id=%s""",
                [run.pk],
            )

        self.assert_rejected_at_commit(succeed_without_events)
        run.refresh_from_db()
        self.assertEqual(run.status, IngestionRun.Status.RUNNING)
        self.assertFalse(IngestionManifest.objects.filter(ingestion_run=run).exists())

    def test_single_scope_evidence_is_rejected_at_commit(self):
        attempt, run = self.running_canary_run()

        # 3. run-scoped rejection only.
        def run_scoped_only(cursor):
            self.fail_run(cursor, run.pk)
            self.raw_event(
                cursor,
                "market.ingestion_rejected",
                "IngestionRun",
                run.pk,
                self.rejected_payload(attempt),
            )

        self.assert_rejected_at_commit(run_scoped_only)

        # 4. attempt-scoped failure only.
        def attempt_scoped_only(cursor):
            self.fail_run(cursor, run.pk)
            self.raw_event(
                cursor,
                "market.historical_ingestion_failed",
                "HistoricalIngestionAttempt",
                attempt.pk,
                self.failure_payload(attempt),
            )

        self.assert_rejected_at_commit(attempt_scoped_only)
        run.refresh_from_db()
        self.assertEqual(run.status, IngestionRun.Status.RUNNING)
        self.assertEqual(AuditEvent.objects.filter(subject_id=str(run.pk)).count(), 0)

    def test_wrong_type_foreign_subject_and_conflicting_evidence_are_rejected(self):
        attempt, run = self.running_canary_run()
        other_run = IngestionRun.objects.exclude(pk=run.pk).first()
        self.assertIsNotNone(other_run)

        # 5a. events belonging to another run and a forged attempt subject.
        def foreign_and_forged(cursor):
            self.fail_run(cursor, run.pk)
            self.raw_event(
                cursor,
                "market.ingestion_rejected",
                "IngestionRun",
                other_run.pk,
                self.rejected_payload(attempt),
            )
            self.raw_event(
                cursor,
                "market.historical_ingestion_failed",
                "HistoricalIngestionAttempt",
                999999,
                self.failure_payload(attempt),
            )

        self.assert_rejected_at_commit(foreign_and_forged)

        # 5b. a success evidence type paired with a failed terminal state.
        def wrong_type_for_state(cursor):
            self.fail_run(cursor, run.pk)
            self.raw_event(
                cursor,
                "market.ingestion_rejected",
                "IngestionRun",
                run.pk,
                self.rejected_payload(attempt),
            )
            cursor.execute("ALTER TABLE market_auditevent DISABLE TRIGGER USER")
            self.raw_event(
                cursor,
                "market.replacement_canary_succeeded",
                "HistoricalIngestionAttempt",
                attempt.pk,
                {"logical_key": attempt.chunk.logical_key},
            )
            cursor.execute("ALTER TABLE market_auditevent ENABLE TRIGGER USER")

        self.assert_rejected_at_commit(wrong_type_for_state)

        # 6. success and failure evidence coexisting on one attempt.
        def conflicting_evidence(cursor):
            self.fail_run(cursor, run.pk)
            self.raw_event(
                cursor,
                "market.ingestion_rejected",
                "IngestionRun",
                run.pk,
                self.rejected_payload(attempt),
            )
            cursor.execute("ALTER TABLE market_auditevent DISABLE TRIGGER USER")
            self.raw_event(
                cursor,
                "market.historical_ingestion_failed",
                "HistoricalIngestionAttempt",
                attempt.pk,
                self.failure_payload(attempt),
            )
            self.raw_event(
                cursor,
                "market.replacement_acquisition_succeeded",
                "HistoricalIngestionAttempt",
                attempt.pk,
                {"logical_key": attempt.chunk.logical_key},
            )
            cursor.execute("ALTER TABLE market_auditevent ENABLE TRIGGER USER")

        self.assert_rejected_at_commit(conflicting_evidence)
        run.refresh_from_db()
        self.assertEqual(run.status, IngestionRun.Status.RUNNING)
        self.assertEqual(AuditEvent.objects.filter(actor="gate7b-completeness-probe").count(), 0)

    def test_deferred_trigger_is_installed_with_the_reviewed_shape(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT t.tgdeferrable, t.tginitdeferred, t.tgtype, t.tgconstraint <> 0,
                          c.relname, p.proname
                   FROM pg_trigger t
                   JOIN pg_class c ON c.oid=t.tgrelid
                   JOIN pg_proc p ON p.oid=t.tgfoid
                   WHERE t.tgname=%s AND NOT t.tgisinternal""",
                [COMPLETENESS_TRIGGER],
            )
            rows = cursor.fetchall()
        self.assertEqual(len(rows), 1)
        deferrable, initially_deferred, tgtype, is_constraint, table, function = rows[0]
        self.assertTrue(deferrable)
        self.assertTrue(initially_deferred)
        self.assertTrue(is_constraint)
        self.assertEqual(table, "market_ingestionrun")
        self.assertEqual(function, COMPLETENESS_FUNCTION)
        # row-level (1) AFTER (not 2) UPDATE (16)
        self.assertTrue(tgtype & 1)
        self.assertFalse(tgtype & 2)
        self.assertTrue(tgtype & 16)


class GovernedTerminalEvidenceTests(Gate7BAuditFixture):
    def smallest_seeded_chunk(self):
        """Seal observations for exactly one small non-canary chunk."""
        chunk = (
            self.plan.chunks.select_related("discovery_inventory")
            .exclude(logical_key=ACQUISITION_CANARY_LOGICAL_KEY)
            .order_by("expected_observation_count")
            .first()
        )
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_historicaltimestampobservation DISABLE TRIGGER USER")
            try:
                cursor.execute(
                    """INSERT INTO market_historicaltimestampobservation
                       (inventory_id, timestamp, complete, volume, bid_present, ask_present)
                       SELECT i.id, c.requested_from + make_interval(hours => g.n),
                              true, 100 + g.n %% 251, true, true
                       FROM market_historicaltimestampinventory i
                       JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
                       CROSS JOIN LATERAL generate_series(1, i.observation_count - 1) AS g(n)
                       WHERE i.id=%s""",
                    [chunk.discovery_inventory_id],
                )
            finally:
                cursor.execute(
                    "ALTER TABLE market_historicaltimestampobservation ENABLE TRIGGER USER"
                )
        return chunk

    def assert_two_scope_evidence(self, attempt, *, succeeded, evidence_type):
        run = IngestionRun.objects.get(pk=attempt.ingestion_run_id)
        self.assertEqual(
            run.status,
            IngestionRun.Status.SUCCEEDED if succeeded else IngestionRun.Status.FAILED,
        )
        run_events = list(
            AuditEvent.objects.filter(subject_type="IngestionRun", subject_id=str(run.pk))
        )
        attempt_events = list(
            AuditEvent.objects.filter(
                subject_type="HistoricalIngestionAttempt", subject_id=str(attempt.pk)
            )
        )
        self.assertEqual(len(run_events), 1)
        self.assertEqual(len(attempt_events), 1)
        self.assertEqual(
            run_events[0].event_type,
            "market.ingestion_succeeded" if succeeded else "market.ingestion_rejected",
        )
        self.assertEqual(attempt_events[0].event_type, evidence_type)
        self.assertNotEqual(run_events[0].subject_type, attempt_events[0].subject_type)
        return run_events[0], attempt_events[0]

    def test_application_success_commits_exactly_two_scope_events(self):
        # 7a. the canary keeps its Gate 7A evidence type.
        run_historical_chunk(ACQUISITION_CANARY_LOGICAL_KEY, self.canary_client())
        canary_attempt = HistoricalIngestionAttempt.objects.get(
            chunk__logical_key=ACQUISITION_CANARY_LOGICAL_KEY
        )
        run_event, evidence = self.assert_two_scope_evidence(
            canary_attempt,
            succeeded=True,
            evidence_type="market.replacement_canary_succeeded",
        )
        manifest = IngestionManifest.objects.get(ingestion_run=canary_attempt.ingestion_run_id)
        self.assertEqual(run_event.payload["manifest"], manifest.sha256)
        self.assertEqual(evidence.payload["ingestion_manifest_sha256"], manifest.sha256)

        # 7b. a Gate 7B chunk records the acquisition evidence type.
        chunk = self.smallest_seeded_chunk()
        run_historical_chunk(chunk.logical_key, CanaryClient(chunk))
        attempt = HistoricalIngestionAttempt.objects.get(chunk__logical_key=chunk.logical_key)
        self.assert_two_scope_evidence(
            attempt,
            succeeded=True,
            evidence_type="market.replacement_acquisition_succeeded",
        )
        self.assertEqual(
            Candle.objects.filter(ingestion_run=attempt.ingestion_run_id).count(),
            chunk.expected_observation_count,
        )

        # 10. duplicate and conflicting post-terminal insertions stay rejected.
        for event_type, subject_type, subject_id, payload in (
            (
                "market.replacement_acquisition_succeeded",
                "HistoricalIngestionAttempt",
                attempt.pk,
                AuditEvent.objects.get(
                    subject_type="HistoricalIngestionAttempt", subject_id=str(attempt.pk)
                ).payload,
            ),
            (
                "market.historical_ingestion_failed",
                "HistoricalIngestionAttempt",
                attempt.pk,
                {"error_code": "X", "logical_chunk_key": chunk.logical_key},
            ),
            (
                "market.ingestion_succeeded",
                "IngestionRun",
                attempt.ingestion_run_id,
                {"fetched": 1, "stored": 1, "manifest": "x"},
            ),
        ):
            with self.assertRaises(DatabaseError) as caught:
                with transaction.atomic(), connection.cursor() as cursor:
                    self.raw_event(cursor, event_type, subject_type, subject_id, payload)
            self.assertIn(INSERT_MESSAGE, str(caught.exception))

        # 11. the accepted Gate 7A canary evidence is untouched by all of it.
        canary_events = AuditEvent.objects.filter(
            subject_type="HistoricalIngestionAttempt", subject_id=str(canary_attempt.pk)
        )
        self.assertEqual(canary_events.count(), 1)
        self.assertEqual(canary_events.get().payload, evidence.payload)

    def test_application_failure_commits_exactly_two_scope_events(self):
        # 8. a drifted provider response fails the run with both events.
        with self.assertRaises(DatasetQualityError):
            run_historical_chunk(
                ACQUISITION_CANARY_LOGICAL_KEY,
                DroppingCanaryClient(self.canary_client()),
            )
        attempt = HistoricalIngestionAttempt.objects.get(
            chunk__logical_key=ACQUISITION_CANARY_LOGICAL_KEY
        )
        run_event, evidence = self.assert_two_scope_evidence(
            attempt, succeeded=False, evidence_type="market.historical_ingestion_failed"
        )
        self.assertEqual(evidence.payload["error_code"], "TIMESTAMP_SET_MISMATCH")
        self.assertEqual(run_event.payload["error_code"], evidence.payload["error_code"])
        self.assertEqual(Candle.objects.filter(ingestion_run=attempt.ingestion_run_id).count(), 0)

    def test_persistence_failure_recovery_commits_evidence_after_rollback(self):
        # 9. the persistence transaction rolls back; the sanitized failure
        # transaction becomes terminal and must carry both events.
        with (
            patch(
                "market.historical_acquisition.store_ingestion",
                side_effect=DatasetQualityError("forced persistence failure"),
            ),
            self.assertRaises(DatasetQualityError),
        ):
            run_historical_chunk(ACQUISITION_CANARY_LOGICAL_KEY, self.canary_client())
        attempt = HistoricalIngestionAttempt.objects.get(
            chunk__logical_key=ACQUISITION_CANARY_LOGICAL_KEY
        )
        self.assert_two_scope_evidence(
            attempt, succeeded=False, evidence_type="market.historical_ingestion_failed"
        )
        self.assertEqual(Candle.objects.filter(ingestion_run=attempt.ingestion_run_id).count(), 0)
        self.assertFalse(
            IngestionManifest.objects.filter(ingestion_run=attempt.ingestion_run_id).exists()
        )

    def test_governed_stale_resolution_records_its_required_evidence(self):
        attempt, run = self.running_canary_run()
        with patch(
            "market.historical_acquisition.timezone.now",
            return_value=run.started_at + timedelta(hours=3),
        ):
            resolve_stale_historical_attempt(
                attempt.pk, timedelta(hours=2), "worker lease verified absent"
            )
        run.refresh_from_db()
        self.assertEqual(run.status, IngestionRun.Status.FAILED)
        self.assertEqual(
            AuditEvent.objects.filter(
                subject_type="IngestionRun",
                subject_id=str(run.pk),
                event_type="market.ingestion_rejected",
            ).count(),
            1,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                subject_type="HistoricalIngestionAttempt",
                subject_id=str(attempt.pk),
                event_type="market.historical_ingestion_failed",
            )
            .get()
            .payload["error_code"],
            "STALE_ATTEMPT_RESOLVED",
        )


class UngovernedTerminalCompatibilityTests(HistoricalFixtureMixin, TransactionTestCase):
    """The deferred guarantee must not reach outside Gate 7B."""

    def test_v1_acquisition_terminal_transitions_are_unchanged(self):
        # 12. a v1 chunk has no replacement contract lineage: one run-scoped
        # event and no attempt-scoped provider-observed evidence.
        plan, _ = self.plan()
        chunk = plan.chunks.first()
        run_historical_chunk(chunk.logical_key, FakeClient())
        attempt = HistoricalIngestionAttempt.objects.get(chunk=chunk)
        run = attempt.ingestion_run
        self.assertIsNone(chunk.data_contract_sha256)
        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(
            AuditEvent.objects.filter(subject_type="IngestionRun", subject_id=str(run.pk)).count(),
            1,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                subject_type="HistoricalIngestionAttempt", subject_id=str(attempt.pk)
            ).count(),
            0,
        )

        # a v1 failure stays single-event too.
        other = plan.chunks.exclude(pk=chunk.pk).first()
        with self.assertRaises(Exception):
            run_historical_chunk(other.logical_key, FailingClient())
        failed = HistoricalIngestionAttempt.objects.get(chunk=other)
        self.assertEqual(failed.ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertEqual(
            AuditEvent.objects.filter(
                subject_type="IngestionRun", subject_id=str(failed.ingestion_run_id)
            ).count(),
            0,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                subject_type="HistoricalIngestionAttempt", subject_id=str(failed.pk)
            ).count(),
            1,
        )

        # a v1 stale resolution keeps its single stale event.
        third = plan.chunks.exclude(pk__in=[chunk.pk, other.pk]).first()
        stale, _ = begin_historical_attempt(third.logical_key)
        with patch(
            "market.historical_acquisition.timezone.now",
            return_value=stale.ingestion_run.started_at + timedelta(hours=3),
        ):
            resolve_stale_historical_attempt(stale.pk, timedelta(hours=2), "v1 lease absent")
        self.assertEqual(
            [
                event.event_type
                for event in AuditEvent.objects.filter(
                    subject_type="HistoricalIngestionAttempt", subject_id=str(stale.pk)
                )
            ],
            ["market.historical_attempt_stale_failed"],
        )

    def test_prospective_ingestion_terminal_transition_is_unchanged(self):
        # 14. prospective ingestion carries no historical attempt at all.
        instrument = Instrument.objects.get(code="EUR_USD")
        start = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
        end = start + timedelta(hours=2)
        candles = [candle(item) for item in expected_candle_timestamps(start, end, "H1")]
        run = store_ingestion(
            self.source,
            instrument,
            "H1",
            start,
            end,
            candles,
            {"instrument": instrument.code, "granularity": "H1"},
        )
        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertIsNone(run.dataset_version_id)
        self.assertFalse(HistoricalIngestionAttempt.objects.filter(ingestion_run=run).exists())
        self.assertEqual(
            AuditEvent.objects.filter(
                subject_type="IngestionRun",
                subject_id=str(run.pk),
                event_type="market.ingestion_succeeded",
            ).count(),
            1,
        )


class DiscoveryTerminalCompatibilityTests(Gate4FixtureTestCase):
    """13. a discovery run transitions under 0021 exactly as before."""

    retention_policy = "gate7b audit discovery compatibility"

    def test_discovery_terminal_transition_is_unchanged(self):
        chunk = self.remaining[0]
        run_discovery_chunk(chunk.logical_key, WaveSuccessClient(self.replacement))
        attempt = chunk.attempts.get()
        run = attempt.ingestion_run
        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        # discovery carries its own attempt table and its own evidence type,
        # so the acquisition completeness trigger never engages.
        self.assertFalse(HistoricalIngestionAttempt.objects.filter(ingestion_run=run).exists())
        self.assertEqual(
            AuditEvent.objects.filter(
                subject_type="HistoricalDiscoveryAttempt",
                subject_id=str(attempt.pk),
                event_type="market.historical_discovery_succeeded",
            ).count(),
            1,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                subject_type="IngestionRun",
                subject_id=str(run.pk),
                event_type__in=("market.ingestion_succeeded", "market.ingestion_rejected"),
            ).count(),
            0,
        )
