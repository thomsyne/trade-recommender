"""Discriminating regressions for the independent F1–F7 counterexamples."""

import json
import math
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from forecasts.integrity import report
from forecasts.models import Recommendation, TargetResolution
from forecasts.services import classify_change
from forecasts.targets import RESOLUTION_METHOD, reconcile_targets, resolve_target, target_endpoint
from market.models import Candle
from market.quality import registered_candle_completion
from market.tests.factories import candle


class ReviewBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from forecasts.tests_phase3.test_database import ProspectiveDatabaseTests

        ProspectiveDatabaseTests.setUpTestData.__func__(cls)

    def prepare(self):
        from forecasts.tests_phase3.test_database import ProspectiveDatabaseTests

        return ProspectiveDatabaseTests.prepare(self)

    def directional(self):
        from forecasts.tests_phase3.test_database import ProspectiveDatabaseTests

        return ProspectiveDatabaseTests.directional(self)

    def test_half_even_target_and_endpoint_both_tie_directions(self):
        for index, ask, expected in [
            (20, "1.101201", "1.101100"),
            (21, "1.101203", "1.101102"),
            (22, "1.101202", "1.101101"),
        ]:
            with self.subTest(ask=ask), transaction.atomic():
                run = self.timeline.ingest(
                    self.source,
                    self.instrument,
                    "D",
                    [
                        candle(
                            self.sessions[index],
                            bid_close=Decimal("1.101000"),
                            ask_close=Decimal(ask),
                        )
                    ],
                    manifest={"test": "precision", "requests": []},
                )
                now = self.timeline.after(run, seconds=2)
                with self.timeline.at(now):
                    target, control = reconcile_targets(self.instrument, as_of=now)
                self.assertEqual(target.reference_midpoint, Decimal(expected))
                self.assertEqual(control.reference_midpoint, Decimal(expected))
                run = self.timeline.ingest(
                    self.source,
                    self.instrument,
                    "D",
                    [
                        candle(
                            self.sessions[index + 5],
                            bid_close=Decimal("1.101000"),
                            ask_close=Decimal(ask),
                        )
                    ],
                    manifest={"test": "endpoint-precision", "requests": []},
                )
                result = resolve_target(target, as_of=self.timeline.after(run))
                self.assertEqual(result.endpoint_midpoint, Decimal(expected))
                self.assertEqual(result.midpoint_change, Decimal(0))
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT phase3_price(%s)", [(Decimal("1.101000") + Decimal(ask)) / 2]
                    )
                    self.assertEqual(cursor.fetchone()[0], Decimal(expected))
                transaction.set_rollback(True)

    def endpoint_values(self, target):
        self.timeline.ingest(
            self.source,
            self.instrument,
            "D",
            [candle(s) for s in self.sessions[20:25]],
            manifest={"test": "availability", "requests": []},
        )
        endpoint = Candle.objects.get(
            instrument=self.instrument, granularity="D", timestamp=self.sessions[24]
        )
        midpoint = endpoint.midpoint_close.quantize(Decimal(".000001"), rounding=ROUND_HALF_EVEN)
        return endpoint, dict(
            target=target,
            outcome=classify_change(midpoint - target.reference_midpoint, target.neutral_band),
            horizon_candle=endpoint,
            horizon_content_sha256=endpoint.content_sha256,
            endpoint_midpoint=midpoint,
            midpoint_change=midpoint - target.reference_midpoint,
            resolution_method=RESOLUTION_METHOD,
            idempotency_key="availability",
        )

    def test_endpoint_availability_before_at_after_orm_and_sql(self):
        _, target, _ = self.prepare()
        endpoint, values = self.endpoint_values(target)
        for delta in [-1, 0, 1]:
            with self.subTest(delta=delta), transaction.atomic():
                values["resolved_at"] = endpoint.ingestion_run.finished_at + timedelta(
                    microseconds=delta
                )
                if delta < 0:
                    with self.assertRaisesMessage(ValidationError, "shared_endpoint_mismatch"):
                        TargetResolution.objects.create(**values)
                    with (
                        self.assertRaisesMessage(DatabaseError, "shared_endpoint_mismatch"),
                        transaction.atomic(),
                    ):
                        TargetResolution.objects.bulk_create([TargetResolution(**values)])
                else:
                    self.assertIsNotNone(TargetResolution.objects.create(**values).pk)
                transaction.set_rollback(True)

    def test_post_cutover_downgrade_and_supplied_audit_time_rejected(self):
        now, rec = self.directional()
        for version in [1, 2, 3]:
            for backdate in [False, True]:
                changes = {
                    "id": 990001,
                    "idempotency_key": "downgrade",
                    "contract_version": version,
                    "target_occurrence_id": None,
                    "control_forecast_id": None,
                    "recorded_at": "2000-01-01T00:00:00Z",
                }
                if backdate:
                    changes["generated_at"] = (now - timedelta(days=1)).isoformat()
                with (
                    self.subTest(version=version, backdate=backdate),
                    self.assertRaisesMessage(DatabaseError, "prospective_contract_downgrade"),
                    transaction.atomic(),
                ):
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "INSERT INTO forecasts_recommendation SELECT (jsonb_populate_record(NULL::forecasts_recommendation,to_jsonb(r)||%s::jsonb)).* FROM forecasts_recommendation r WHERE id=%s",
                            [json.dumps(changes), rec.pk],
                        )
                copy = Recommendation.objects.get(pk=rec.pk)
                copy.pk = None
                copy.contract_version = version
                with self.assertRaisesMessage(ValidationError, "prospective_contract_downgrade"):
                    copy.clean()

    def test_past_report_ignores_future_missing_at_before_after_boundary(self):
        now, target, _ = self.prepare()
        maturity = registered_candle_completion(
            target_endpoint(target.reference_candle.timestamp, 5), "D"
        )
        before = report(as_of=now)
        resolve_target(target, as_of=maturity)
        self.assertEqual(report(as_of=now), before)
        for instant in [
            maturity - timedelta(microseconds=1),
            maturity,
            maturity + timedelta(microseconds=1),
        ]:
            with self.subTest(instant=instant):
                self.assertEqual(report(as_of=instant)["total"], 0)


class CoverageReviewTests(TestCase):
    def setUp(self):
        from forecasts.tests_phase3.test_execution_boundaries import ExecutionBoundaryTests

        ExecutionBoundaryTests.setUp(self)

    def test_premature_or_malformed_coverage_rejected_at_source_and_transition(self):
        from forecasts.models import PaperLifecycleEvent

        maturity = registered_candle_completion(
            target_endpoint(self.rec.target_occurrence.reference_candle.timestamp, 5), "D"
        )
        for instant in [self.now + timedelta(seconds=1), maturity - timedelta(microseconds=1)]:
            values = dict(
                recommendation=self.rec,
                state="expired_unobserved",
                reason_code="hourly_coverage_unavailable",
                details={"schema_version": 1},
                occurred_at=instant,
            )
            with self.subTest(instant=instant):
                with self.assertRaisesMessage(ValidationError, "coverage_before_target_maturity"):
                    PaperLifecycleEvent.objects.create(**values)
                with (
                    self.assertRaisesMessage(DatabaseError, "coverage_before_target_maturity"),
                    transaction.atomic(),
                ):
                    PaperLifecycleEvent.objects.bulk_create([PaperLifecycleEvent(**values)])
        for details in [
            None,
            [],
            "unsafe-body",
            {},
            {"schema_version": True},
            {"schema_version": 2},
        ]:
            with self.subTest(details=details), self.assertRaises(ValidationError):
                PaperLifecycleEvent.objects.create(
                    recommendation=self.rec,
                    state="expired_unobserved",
                    reason_code="hourly_coverage_unavailable",
                    details=details,
                    occurred_at=maturity,
                )

    def test_valid_maturity_gap_and_early_cancellation_have_distinct_proof(self):
        from forecasts.lifecycle import transition
        from forecasts.models import PaperLifecycleEvent

        maturity = registered_candle_completion(
            target_endpoint(self.rec.target_occurrence.reference_candle.timestamp, 5), "D"
        )
        for state, reason, instant in [
            ("expired_unobserved", "hourly_coverage_unavailable", maturity),
            ("cancelled", "owner_cancelled", self.now + timedelta(seconds=1)),
        ]:
            with self.subTest(state=state), transaction.atomic():
                fact = PaperLifecycleEvent.objects.create(
                    recommendation=self.rec,
                    state=state,
                    reason_code=reason,
                    details={"schema_version": 1},
                    occurred_at=instant,
                )
                self.assertEqual(
                    transition(
                        self.rec, state, reason_code=reason, source=fact, occurred_at=instant
                    ).state,
                    state,
                )
                transaction.set_rollback(True)


class SignedIntervalTests(SimpleTestCase):
    def test_signed_support_and_unsigned_compatibility(self):
        from forecasts.experiments import _cluster_interval

        for count in [1, 2, 50, 100]:
            for delta in [Decimal(-2) / 3, Decimal(0), Decimal(2) / 3]:
                clusters = {i: [delta] for i in range(count)}
                low, high = _cluster_interval(
                    clusters,
                    confidence=Decimal(".95"),
                    value_range=Decimal(4) / 3,
                    support_low=-Decimal(2) / 3,
                )
                self.assertLessEqual(low, high)
                width = Decimal(4) / 3 * Decimal(str(math.sqrt(math.log(40) / (2 * count))))
                self.assertEqual(
                    low,
                    max(-Decimal(2) / 3, delta.quantize(Decimal(".000001")) - width).quantize(
                        Decimal(".000001")
                    ),
                )
                self.assertEqual(
                    high,
                    min(Decimal(2) / 3, delta.quantize(Decimal(".000001")) + width).quantize(
                        Decimal(".000001")
                    ),
                )
            low, high = _cluster_interval(
                {i: [Decimal(".2")] for i in range(count)},
                confidence=Decimal(".95"),
                value_range=Decimal(2) / 3,
            )
            self.assertGreaterEqual(low, 0)
            self.assertLessEqual(high, Decimal(".666667"))


class RecurrenceReviewTests(TestCase):
    def test_corrupt_population_reports_without_arithmetic_or_data_leak(self):
        from forecasts.schedules import TASK, seed_schedules
        from operations.models import ScheduledJob

        for interval in [None, 0]:
            with self.subTest(interval=interval), transaction.atomic():
                for code in ["EUR_USD", "GBP_USD"]:
                    ScheduledJob.objects.create(
                        name="Phase3 reconcile " + code,
                        task_name=TASK,
                        parameters={"instrument": code},
                        interval_seconds=interval,
                        next_run_at=timezone.now(),
                        enabled=True,
                        missed_run_policy="latest",
                    )
                value = report()
                self.assertEqual(value["violations"]["malformed_recurrence"], 2)
                with self.assertRaisesMessage(ValidationError, "reconciliation_schedule_integrity"):
                    seed_schedules()
                transaction.set_rollback(True)

    def test_unequal_intervals_eventually_collide_and_microseconds_do_not(self):
        from types import SimpleNamespace

        from forecasts.schedules import recurring_schedules_collide

        now = timezone.now()
        a = SimpleNamespace(schedule_type="interval", interval_seconds=6, next_run_at=now)
        b = SimpleNamespace(
            schedule_type="interval", interval_seconds=10, next_run_at=now + timedelta(seconds=4)
        )
        self.assertTrue(recurring_schedules_collide(a, b))  # first shared deadline:24seconds
        b.next_run_at += timedelta(microseconds=1)
        self.assertFalse(recurring_schedules_collide(a, b))


class LegacyCutoverReviewTests(TestCase):
    def setUp(self):
        from forecasts.tests.test_experiments import ExperimentHealthTests

        ExperimentHealthTests.setUp(self)

    def test_pre_effective_legacy_insert_overwrites_supplied_audit_time(self):
        from forecasts.experiments import ensure_champion_era
        from forecasts.tests.test_recommendations import FakeProvider

        with (
            patch("forecasts.recommendations.CONTRACT_VERSION", 4),
            override_settings(RECOMMENDATION_METHOD_VERSION=2),
        ):
            ensure_champion_era(
                FakeProvider(), starts_at=timezone.now() + timedelta(days=30), register=True
            )
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO forecasts_recommendation SELECT (jsonb_populate_record(NULL::forecasts_recommendation,to_jsonb(r)||%s::jsonb)).* FROM forecasts_recommendation r WHERE id=%s RETURNING recorded_at",
                [
                    json.dumps(
                        {
                            "id": 990002,
                            "idempotency_key": "pre-effective-legacy",
                            "recorded_at": "2000-01-01T00:00:00Z",
                        }
                    ),
                    self.base.pk,
                ],
            )
            recorded = cursor.fetchone()[0]
        self.assertGreater(recorded, timezone.now() - timedelta(minutes=1))
        self.assertEqual(Recommendation.objects.get(pk=990002).contract_version, 3)
        self.base.refresh_from_db()
        self.assertEqual(self.base.contract_version, 3)
        self.assertFalse(self.base.lifecycle_events.exists())


class TargetSemanticReviewTests(TestCase):
    setUpTestData = classmethod(ReviewBoundaryTests.setUpTestData.__func__)
    prepare = ReviewBoundaryTests.prepare
    directional = ReviewBoundaryTests.directional
    endpoint_values = ReviewBoundaryTests.endpoint_values

    def test_identity_depends_on_semantics_not_insertion_ids(self):
        import copy

        from forecasts.targets import identity_digest, target_material

        _, target, _ = self.prepare()
        original = target_material(target)
        other = copy.copy(target)
        other.pk = 98765
        self.assertEqual(target_material(other), original)
        for field, value in [
            ("resolution_method", "registered-session-endpoint-v3"),
            ("neutral_rule", "other-neutral-rule"),
            ("horizon_sessions", 6),
        ]:
            other = copy.copy(target)
            setattr(other, field, value)
            self.assertNotEqual(identity_digest(target_material(other)), identity_digest(original))
        contract = copy.copy(target.target_contract)
        contract.pk = 87654
        other = copy.copy(target)
        other.target_contract = contract
        self.assertEqual(target_material(other), original)
        contract.version += 1
        self.assertNotEqual(target_material(other), original)

    def test_wrong_horizon_and_unscored_endpoint_shapes_reject(self):
        _, target, _ = self.prepare()
        endpoint, values = self.endpoint_values(target)
        values["resolved_at"] = endpoint.ingestion_run.finished_at
        for changes, code in [
            ({"horizon_candle": target.reference_candle}, "shared_endpoint_mismatch"),
            ({"outcome": "missing"}, "unscored_endpoint_forbidden"),
            ({"outcome": "cancelled"}, "unscored_endpoint_forbidden"),
        ]:
            with self.subTest(changes=changes), self.assertRaisesMessage(ValidationError, code):
                TargetResolution.objects.create(**(values | changes))
        for outcome in ["missing", "cancelled"]:
            with self.subTest(outcome=outcome), transaction.atomic():
                result = TargetResolution.objects.create(
                    target=target,
                    outcome=outcome,
                    resolution_method=RESOLUTION_METHOD,
                    resolved_at=values["resolved_at"],
                    idempotency_key="shape-" + outcome,
                )
                self.assertIsNone(result.endpoint_midpoint)
                self.assertEqual(result.horizon_content_sha256, "")
                transaction.set_rollback(True)

    def test_second_mechanical_method_cannot_satisfy_exact_control(self):
        _, rec = self.directional()
        import copy

        from forecasts.targets import comparable_control

        control = copy.copy(rec.control_forecast)
        control.method = "other-method"
        rec.control_forecast = control
        self.assertFalse(comparable_control(rec))
        with (
            self.assertRaisesMessage(DatabaseError, "control_target_mismatch"),
            transaction.atomic(),
        ):
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO forecasts_forecast SELECT (jsonb_populate_record(NULL::forecasts_forecast,to_jsonb(r)||%s::jsonb)).* FROM forecasts_forecast r WHERE id=%s",
                    [
                        json.dumps(
                            {
                                "id": 980001,
                                "method": "other-method",
                                "idempotency_key": "other-method",
                            }
                        ),
                        control.pk,
                    ],
                )

    def test_sql_weekly_dependence_forgery_rejects_at_owning_boundary(self):
        _, rec = self.directional()
        sample = rec.experiment_samples.get()
        with (
            self.assertRaisesMessage(DatabaseError, "target_dependence_identity_mismatch"),
            transaction.atomic(),
        ):
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO forecasts_experimentsample SELECT (jsonb_populate_record(NULL::forecasts_experimentsample,to_jsonb(r)||%s::jsonb)).* FROM forecasts_experimentsample r WHERE id=%s",
                    [
                        json.dumps(
                            {"id": 980002, "dependence_cluster_key": "forged-independent-cluster"}
                        ),
                        sample.pk,
                    ],
                )


class DedicatedTaskReviewTests(TestCase):
    setUpTestData = classmethod(ReviewBoundaryTests.setUpTestData.__func__)
    prepare = ReviewBoundaryTests.prepare

    def test_latest_downtime_failed_control_retry_and_expired_lease(self):
        from forecasts.schedules import TASK
        from forecasts.targets import reconcile_targets as actual_reconcile
        from operations.models import JobOccurrence, ScheduledJob
        from operations.services import claim_next_job, enqueue_due_jobs, finish_job
        from operations.tasks import execute_task

        now, target, control = self.prepare()
        ScheduledJob.objects.create(
            name="Phase3 reconcile USD_CAD",
            task_name=TASK,
            parameters={"instrument": "USD_CAD"},
            interval_seconds=3600,
            next_run_at=now - timedelta(hours=24),
            enabled=True,
            missed_run_policy="latest",
        )
        with self.timeline.at(now):
            self.assertEqual(len(enqueue_due_jobs(now)), 1)
            self.assertEqual(enqueue_due_jobs(now), [])
            self.assertEqual(JobOccurrence.objects.count(), 1)
            first = claim_next_job("first", now)
            with patch(
                "forecasts.targets.reconcile_targets",
                side_effect=RuntimeError("unsafe-provider-body"),
            ):
                try:
                    execute_task(first.task_name, first.parameters)
                except ValidationError as error:
                    self.assertIn("target_control", str(error))
                    self.assertNotIn("unsafe-provider-body", str(error))
                    finish_job(first, "first", error=error)
                else:
                    self.fail("control failure was not surfaced")
        first.refresh_from_db()
        self.assertEqual(first.status, "queued")
        with self.timeline.at(first.available_at):
            retry = claim_next_job("second", first.available_at)
            with patch("forecasts.targets.reconcile_targets", wraps=actual_reconcile) as controls:
                execute_task(retry.task_name, retry.parameters)
            controls.assert_called_once()
            self.assertTrue(finish_job(retry, "second"))
        self.assertEqual(JobOccurrence.objects.get(pk=first.pk).status, "succeeded")
        self.assertEqual(target.controls.count(), 1)
        late = JobOccurrence.objects.create(
            idempotency_key="phase3-dead-lease",
            task_name=TASK,
            parameters={"instrument": "USD_CAD"},
            scheduled_for=now,
            available_at=now,
            status="running",
            attempts=1,
            lease_owner="dead",
            lease_expires_at=now - timedelta(seconds=1),
        )
        with self.timeline.at(now):
            recovered = claim_next_job("replacement", now)
            self.assertEqual(recovered.pk, late.pk)
            execute_task(recovered.task_name, recovered.parameters)
            self.assertFalse(finish_job(recovered, "dead"))
            self.assertTrue(finish_job(recovered, "replacement"))
        self.assertEqual(target.controls.count(), 1)


class FinalLifecycleBoundaryTests(TestCase):
    setUp = CoverageReviewTests.setUp

    def test_future_cancellation_does_not_change_earlier_report(self):
        from forecasts.lifecycle import transition
        from forecasts.models import PaperLifecycleEvent

        before = report(as_of=self.now)
        at = self.now + timedelta(seconds=2)
        fact = PaperLifecycleEvent.objects.create(
            recommendation=self.rec,
            state="cancelled",
            reason_code="owner_cancelled",
            details={"schema_version": 1},
            occurred_at=at,
        )
        transition(
            self.rec, "cancelled", reason_code="owner_cancelled", source=fact, occurred_at=at
        )
        self.assertEqual(report(as_of=self.now), before)
        self.assertEqual(report(as_of=at)["total"], 0)

    def test_revocation_valid_before_entry_and_invalid_after_entry(self):
        from forecasts.lifecycle import transition
        from forecasts.models import PaperLifecycleEvent, PortfolioAdmissionEvent
        from forecasts.paper import resolve_paper_trade
        from forecasts.tests.test_recommendations import hourly_candle

        original = self.rec.portfolio_admission_events.get()
        values = dict(
            recommendation=self.rec,
            cohort=original.cohort,
            selection=original.selection,
            state="revoked",
            reason_code="owner_withdrew",
            occurred_at=self.now + timedelta(seconds=1),
        )
        with transaction.atomic():
            event = PortfolioAdmissionEvent.objects.create(**values)
            self.assertEqual(
                transition(
                    self.rec,
                    "admission_revoked",
                    reason_code="owner_withdrew",
                    source=event,
                    occurred_at=event.occurred_at,
                ).state,
                "admission_revoked",
            )
            transaction.set_rollback(True)
        first = self.timeline.hours_after(self.rec.generated_at, 1)[0]
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [hourly_candle(first)],
            manifest={"test": "entered-revocation", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(self.timeline.after(run)):
            resolve_paper_trade(self.rec)
        values["occurred_at"] = self.timeline.after(run, seconds=2)
        with self.assertRaisesMessage(ValidationError, "revocation_requires_pending_admission"):
            PortfolioAdmissionEvent.objects.create(**values)
        with (
            self.assertRaisesMessage(DatabaseError, "revocation_requires_pending_admission"),
            transaction.atomic(),
        ):
            PortfolioAdmissionEvent.objects.bulk_create([PortfolioAdmissionEvent(**values)])
        with self.assertRaisesMessage(ValidationError, "invalid_cancellation_evidence"):
            PaperLifecycleEvent.objects.create(
                recommendation=self.rec,
                state="cancelled",
                reason_code="owner_cancelled",
                details={"schema_version": 1},
                occurred_at=values["occurred_at"],
            )


class PersistedSemanticReviewTests(TestCase):
    setUpTestData = classmethod(ReviewBoundaryTests.setUpTestData.__func__)
    prepare = ReviewBoundaryTests.prepare
    directional = ReviewBoundaryTests.directional
    endpoint_values = ReviewBoundaryTests.endpoint_values

    def test_registered_contract_versions_and_duplicate_identity_sql(self):
        from forecasts.models import TargetContract, TargetOccurrence
        from forecasts.targets import identity_digest, target_material

        _, target, _ = self.prepare()
        fields = {f.name: getattr(target, f.name) for f in target._meta.fields if not f.primary_key}
        for changed in [
            {"version": 31},
            {"version": 32, "horizon_sessions": 6},
            {"version": 33, "definition": {"event": "distinct"}},
        ]:
            with self.subTest(changed=changed):
                contract = TargetContract.objects.create(
                    **{
                        f.name: changed.get(f.name, getattr(target.target_contract, f.name))
                        for f in target.target_contract._meta.fields
                        if not f.primary_key and f.name != "created_at"
                    }
                )
                candidate = TargetOccurrence(
                    **(
                        fields
                        | {
                            "target_contract": contract,
                            "horizon_sessions": contract.horizon_sessions,
                            "definition_sha256": identity_digest(contract.definition),
                        }
                    )
                )
                candidate.identity_sha256 = identity_digest(target_material(candidate))
                candidate.save()
                self.assertNotEqual(candidate.identity_sha256, target.identity_sha256)
                with (
                    self.assertRaisesMessage(DatabaseError, "identity_sha256"),
                    transaction.atomic(),
                ):
                    TargetOccurrence.objects.bulk_create(
                        [
                            TargetOccurrence(
                                **{
                                    f.name: getattr(candidate, f.name)
                                    for f in candidate._meta.fields
                                    if not f.primary_key
                                }
                            )
                        ]
                    )
        for method in ["registered-session-endpoint-v1", "registered-session-endpoint-v3"]:
            candidate = TargetOccurrence(**(fields | {"resolution_method": method}))
            candidate.identity_sha256 = identity_digest(target_material(candidate))
            with self.assertRaisesMessage(ValidationError, "invalid_target_identity"):
                candidate.save()
            with (
                self.assertRaisesMessage(DatabaseError, "invalid_target_identity"),
                transaction.atomic(),
            ):
                TargetOccurrence.objects.bulk_create([candidate])

    def test_wrong_horizon_and_unscored_shapes_sql(self):
        _, target, _ = self.prepare()
        endpoint, values = self.endpoint_values(target)
        values["resolved_at"] = endpoint.ingestion_run.finished_at
        for changes, code in [
            ({"horizon_candle": target.reference_candle}, "shared_endpoint_mismatch"),
            ({"outcome": "missing"}, "unscored_endpoint_forbidden"),
            ({"outcome": "cancelled"}, "unscored_endpoint_forbidden"),
            ({"horizon_candle": None}, "scored_endpoint_required"),
        ]:
            with (
                self.subTest(changes=changes),
                self.assertRaisesMessage(DatabaseError, code),
                transaction.atomic(),
            ):
                TargetResolution.objects.bulk_create([TargetResolution(**(values | changes))])

    def test_registered_christmas_calendar_endpoint_python_sql(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # The registered FX calendar retains Christmas weekday sessions; it has
        # weekend/NY-close rules, not an undocumented bank-holiday exclusion.
        reference = datetime(2025, 12, 24, 17, tzinfo=ZoneInfo("America/New_York"))
        expected = datetime(2025, 12, 25, 17, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(target_endpoint(reference, 1), expected)
        with connection.cursor() as cursor:
            cursor.execute("SELECT phase3_endpoint(%s,1)", [reference])
            self.assertEqual(cursor.fetchone()[0], expected)


class CorruptRecurrenceShapeTests(SimpleTestCase):
    def test_all_recurrence_value_types_are_validated_before_arithmetic(self):
        from types import SimpleNamespace

        from forecasts.schedules import recurring_schedules_collide

        values = dict(schedule_type="interval", interval_seconds=6, next_run_at=timezone.now())
        valid = SimpleNamespace(**values)
        cases = [
            {"interval_seconds": value} for value in [None, False, True, 0, -1, "6", [], {}, 6.0]
        ]
        cases += [
            {"next_run_at": value}
            for value in [None, "unsafe-body", [], {}, 1, timezone.now().replace(tzinfo=None)]
        ]
        cases += [{"schedule_type": "daily"}]
        for changes in cases:
            with (
                self.subTest(changes=changes),
                self.assertRaisesMessage(ValidationError, "malformed_recurrence"),
            ):
                recurring_schedules_collide(SimpleNamespace(**(values | changes)), valid)
        long_period = SimpleNamespace(**(values | {"interval_seconds": 2**62}))
        self.assertTrue(recurring_schedules_collide(long_period, valid))


class EndpointSourceShapeTests(TestCase):
    setUpTestData = classmethod(ReviewBoundaryTests.setUpTestData.__func__)
    prepare = ReviewBoundaryTests.prepare

    def test_failed_incomplete_and_unfinished_endpoint_orm_and_sql(self):
        from market.models import IngestionRun

        _, target, _ = self.prepare()
        timestamp = target_endpoint(target.reference_candle.timestamp, 5)
        available = registered_candle_completion(timestamp, "D") + timedelta(minutes=1)
        for index, (status, complete, finished) in enumerate(
            [("failed", True, available), ("succeeded", False, available), ("running", True, None)]
        ):
            with self.subTest(status=status, complete=complete), transaction.atomic():
                original = target.reference_candle.ingestion_run
                run = IngestionRun.objects.create(
                    **{
                        f.name: getattr(original, f.name)
                        for f in original._meta.fields
                        if not f.primary_key
                        and f.name
                        not in {"started_at", "status", "finished_at", "request_manifest_hash"}
                    },
                    status=status,
                    finished_at=finished,
                    request_manifest_hash=str(index + 7) * 64,
                )
                from market.services import candle_content_sha256

                endpoint = Candle(
                    **{
                        f.name: getattr(target.reference_candle, f.name)
                        for f in target.reference_candle._meta.fields
                        if not f.primary_key
                        and f.name not in {"timestamp", "complete", "ingestion_run"}
                    },
                    timestamp=timestamp,
                    complete=complete,
                    ingestion_run=run,
                )
                endpoint.content_sha256 = candle_content_sha256(self.instrument.code, "D", endpoint)
                if not complete:
                    from forecasts.targets import validate_resolution

                    endpoint.pk = 987654  # Query-boundary counterfactual; never persisted.
                    with self.assertRaisesMessage(ValidationError, "shared_endpoint_mismatch"):
                        validate_resolution(
                            TargetResolution(
                                target=target,
                                outcome="neutral",
                                horizon_candle=endpoint,
                                horizon_content_sha256=endpoint.content_sha256,
                                endpoint_midpoint=target.reference_midpoint,
                                midpoint_change=Decimal(0),
                                resolution_method=RESOLUTION_METHOD,
                                resolved_at=available,
                            )
                        )
                    endpoint.pk = None
                    # SQL rejects incomplete candles at the earlier owning source
                    # constraint; no bypass is added to reach a later trigger.
                    with (
                        self.assertRaisesMessage(DatabaseError, "stored_candles_complete"),
                        transaction.atomic(),
                    ):
                        endpoint.save()
                    transaction.set_rollback(True)
                    continue
                endpoint.save()
                values = dict(
                    target=target,
                    outcome="neutral",
                    horizon_candle=endpoint,
                    horizon_content_sha256=endpoint.content_sha256,
                    endpoint_midpoint=target.reference_midpoint,
                    midpoint_change=Decimal(0),
                    resolution_method=RESOLUTION_METHOD,
                    resolved_at=available,
                    idempotency_key="invalid-endpoint-source",
                )
                with self.assertRaisesMessage(ValidationError, "shared_endpoint_mismatch"):
                    TargetResolution.objects.create(**values)
                with (
                    self.assertRaisesMessage(DatabaseError, "shared_endpoint_mismatch"),
                    transaction.atomic(),
                ):
                    TargetResolution.objects.bulk_create([TargetResolution(**values)])
                transaction.set_rollback(True)


class SampleMethodBoundaryTests(TestCase):
    setUpTestData = classmethod(ReviewBoundaryTests.setUpTestData.__func__)
    prepare = ReviewBoundaryTests.prepare
    directional = ReviewBoundaryTests.directional

    def test_wrong_method_sample_cannot_enter_other_registered_era(self):
        from forecasts.experiments import ensure_champion_era
        from forecasts.models import ExperimentSample
        from forecasts.tests.test_recommendations import FakeProvider

        now, rec = self.directional()

        class OtherProvider(FakeProvider):
            model = "other-sample-model"

        with self.timeline.at(now), override_settings(RECOMMENDATION_METHOD_VERSION=42):
            other = ensure_champion_era(OtherProvider(), starts_at=now, register=True)
        sample = rec.experiment_samples.get()
        values = {f.name: getattr(sample, f.name) for f in sample._meta.fields if not f.primary_key}
        values["era"] = other
        with self.assertRaisesMessage(ValidationError, "provider identity"):
            ExperimentSample.objects.create(**values)
        with (
            self.assertRaisesMessage(DatabaseError, "prospective_era_mismatch"),
            transaction.atomic(),
        ):
            ExperimentSample.objects.bulk_create([ExperimentSample(**values)])
        self.assertEqual(rec.experiment_samples.count(), 1)


class ReconciliationOperationalMatrixTests(TestCase):
    setUpTestData = classmethod(ReviewBoundaryTests.setUpTestData.__func__)
    prepare = ReviewBoundaryTests.prepare

    def test_real_dedicated_task_executes_every_stage_in_order(self):
        from contextlib import ExitStack
        from importlib import import_module

        from forecasts.operations import reconcile

        now, _, _ = self.prepare()
        calls = []
        paths = [
            ("forecasts.targets", "reconcile_targets"),
            ("forecasts.services", "resolve_due_forecasts"),
            ("forecasts.recommendations", "resolve_due_recommendations"),
            ("forecasts.lifecycle", "reconcile_lifecycle"),
            ("forecasts.paper", "resolve_due_paper_trades"),
            ("forecasts.experiments", "refresh_all_experiments"),
        ]
        with self.timeline.at(now), ExitStack() as stack:
            for module, name in paths:
                original = getattr(import_module(module), name)

                def wrapper(*args, _name=name, _original=original, **kwargs):
                    calls.append(_name)
                    return _original(*args, **kwargs)

                stack.enter_context(patch(module + "." + name, side_effect=wrapper))
            reconcile({"instrument": "USD_CAD"})
        self.assertEqual(
            calls,
            [
                "reconcile_targets",
                "resolve_due_forecasts",
                "resolve_due_recommendations",
                "reconcile_lifecycle",
                "resolve_due_paper_trades",
                "reconcile_lifecycle",
                "refresh_all_experiments",
            ],
        )

    def test_malformed_identity_types_emit_bounded_readonly_json_and_fail_seeding(self):
        from io import StringIO

        from django.core.management import CommandError, call_command
        from django.db.models import JSONField, Value
        from django.test.utils import CaptureQueriesContext

        from forecasts.schedules import TASK, seed_schedules
        from operations.models import ScheduledJob

        values = [
            None,
            [],
            True,
            1,
            "unsafe-body" * 10000,
            {},
            {"instrument": []},
            {"instrument": "USD_CAD", "extra": "unsafe-body"},
            {"instrument": "XAU_USD"},
        ]
        for index, parameters in enumerate(values):
            with self.subTest(index=index), transaction.atomic():
                ScheduledJob.objects.create(
                    name="Phase3 reconcile USD_CAD",
                    task_name=TASK,
                    parameters=Value(None, output_field=JSONField())
                    if parameters is None
                    else parameters,
                    interval_seconds=3600,
                    next_run_at=timezone.now(),
                    enabled=False,
                )
                out = StringIO()
                with (
                    CaptureQueriesContext(connection) as queries,
                    self.assertRaisesMessage(CommandError, "prospective_contract_violations"),
                ):
                    call_command("report_phase3_integrity", stdout=out)
                result = json.loads(out.getvalue())
                self.assertEqual(result["violations"]["malformed_reconciliation_identity"], 1)
                self.assertNotIn("unsafe-body", out.getvalue())
                self.assertLess(len(out.getvalue()), 2000)
                for query in queries:
                    self.assertRegex(
                        query["sql"],
                        r'^\s*(SELECT |DECLARE "_django_curs_\w+" NO SCROLL CURSOR FOR SELECT )',
                    )
                with self.assertRaisesMessage(ValidationError, "reconciliation_schedule_integrity"):
                    seed_schedules()
                transaction.set_rollback(True)
        self.assertEqual(report()["total"], 0)


class ActualFutureFactCutoffTests(TestCase):
    setUp = CoverageReviewTests.setUp

    def test_later_entry_result_shared_and_both_derived_scores_preserve_past_report(self):
        from forecasts.paper import resolve_paper_trade
        from forecasts.recommendations import resolve_recommendation
        from forecasts.services import resolve_forecast
        from forecasts.tests.test_recommendations import hourly_candle

        cutoff = self.now + timedelta(seconds=1)
        before = report(as_of=cutoff)
        self.assertEqual(before["total"], 0)
        first = self.timeline.hours_after(self.rec.generated_at, 1)[0]
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [
                hourly_candle(first),
                hourly_candle(
                    first + timedelta(hours=1),
                    bid_high=Decimal("1.3602"),
                    ask_high=Decimal("1.3604"),
                ),
            ],
            manifest={"test": "future-result-cutoff", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(self.timeline.after(run)):
            result = resolve_paper_trade(self.rec)
        self.assertEqual(result.outcome, "target")
        self.assertEqual(report(as_of=cutoff), before)
        endpoint = target_endpoint(self.rec.reference_candle.timestamp, 5)
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "D",
            [candle(endpoint)],
            manifest={"test": "future-shared-derived-cutoff", "requests": []},
        )
        with self.timeline.at(self.timeline.after(run)):
            model = resolve_recommendation(self.rec)
            control = resolve_forecast(self.rec.control_forecast)
        self.assertEqual(model.target_resolution_id, control.target_resolution_id)
        self.assertGreater(model.resolved_at, cutoff)
        self.assertGreater(control.resolved_at, cutoff)
        self.assertEqual(report(as_of=cutoff), before)
