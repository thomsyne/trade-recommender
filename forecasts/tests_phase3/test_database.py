from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from forecasts.experiments import ensure_champion_era
from forecasts.lifecycle import project_lifecycle
from forecasts.models import (
    Forecast,
    TargetOccurrence,
    TargetResolution,
)
from forecasts.recommendations import generate_recommendation, resolve_recommendation
from forecasts.services import resolve_forecast
from forecasts.targets import reconcile_targets, resolve_target
from forecasts.tests.test_recommendations import FakeProvider, evidence, output


class ProspectiveDatabaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from forecasts.tests.test_services import ForecastServiceTests

        cls._store_daily_batch = classmethod(ForecastServiceTests._store_daily_batch.__func__)
        ForecastServiceTests.setUpTestData.__func__(cls)

    def prepare(self):
        now = self.timeline.poll_instant([self.sessions[19]], "D") + timedelta(seconds=2)
        with self.timeline.at(now):
            target, control = reconcile_targets(self.instrument, as_of=now)
            evidence(self.instrument, now, prospective=False)
            ensure_champion_era(FakeProvider(), starts_at=now, register=True)
        return now, target, control

    def test_target_and_control_retries_do_not_duplicate(self):
        now, target, control = self.prepare()
        with self.timeline.at(now + timedelta(seconds=1)):
            again = reconcile_targets(self.instrument)
        self.assertEqual((target.pk, control.pk), (again[0].pk, again[1].pk))
        self.assertEqual(TargetOccurrence.objects.count(), 1)
        self.assertEqual(Forecast.objects.filter(target_occurrence=target).count(), 1)

    def test_missing_control_blocks_before_provider_spend(self):
        now = self.timeline.poll_instant([self.sessions[19]], "D") + timedelta(seconds=2)
        evidence(self.instrument, now, prospective=False)
        provider = FakeProvider()
        with patch("forecasts.recommendations._reserve_recommendation_budget") as reserve:
            with self.assertRaisesMessage(ValidationError, "exact_prospective_control_required"):
                generate_recommendation(self.instrument, provider=provider, generated_at=now)
        reserve.assert_not_called()
        self.assertEqual(provider.calls, 0)

    def test_model_and_control_share_one_endpoint_and_abstention_has_no_hit(self):
        now, target, control = self.prepare()
        with self.timeline.at(now + timedelta(seconds=1)):
            rec = generate_recommendation(
                self.instrument,
                provider=FakeProvider(output(action="abstain", abstention_reason="No setup")),
                generated_at=now + timedelta(seconds=1),
            )
        self.assertEqual(project_lifecycle(rec)["state"], "abstained")
        self.assertIsNone(resolve_target(target, as_of=now))
        self.timeline.ingest(
            self.source,
            self.instrument,
            "D",
            [
                __import__("market.tests.factories", fromlist=["candle"]).candle(s)
                for s in self.sessions[20:25]
            ],
            manifest={"test": "phase3-endpoint", "requests": []},
        )
        a = resolve_forecast(control)
        b = resolve_recommendation(rec)
        self.assertEqual(a.target_resolution_id, b.target_resolution_id)
        self.assertEqual(a.horizon_candle.timestamp, self.sessions[24])
        self.assertEqual(a.outcome, b.outcome)
        self.assertIsNone(b.directional_hit)
        self.assertEqual(TargetResolution.objects.count(), 1)

    def test_governed_records_reject_mutation_and_truncate(self):
        _, target, _ = self.prepare()
        for sql in [
            "UPDATE forecasts_targetoccurrence SET neutral_band=0 WHERE id=%s",
            "DELETE FROM forecasts_targetoccurrence WHERE id=%s",
            "TRUNCATE forecasts_targetoccurrence CASCADE",
        ]:
            with self.subTest(sql=sql), self.assertRaises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, [target.pk] if "%s" in sql else None)

    def test_raw_control_mismatch_is_rejected(self):
        _, target, control = self.prepare()
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO forecasts_forecast SELECT (jsonb_populate_record(NULL::forecasts_forecast, to_jsonb(f) || %s::jsonb)).* FROM forecasts_forecast f WHERE id=%s",
                    ['{"id":9000001,"idempotency_key":"wrong-band","neutral_band":0}', control.pk],
                )

    def directional(self):
        now, target, control = self.prepare()
        with self.timeline.at(now + timedelta(seconds=1)):
            rec = generate_recommendation(
                self.instrument, provider=FakeProvider(), generated_at=now + timedelta(seconds=1)
            )
        return now, rec

    def test_directional_has_durable_disposition_and_ineligible_reason(self):
        from forecasts.portfolio import assess_recommendation_batch

        now, rec = self.directional()
        self.assertEqual(project_lifecycle(rec)["state"], "awaiting_portfolio_assessment")
        self.assertEqual(rec.portfolio_disposition.kind, "requires_assessment")
        with self.timeline.at(now + timedelta(seconds=2)):
            assess_recommendation_batch([rec])
        projected = project_lifecycle(rec)
        self.assertEqual(projected["state"], "portfolio_ineligible")
        self.assertEqual(projected["reason_code"], "policy_not_effective")
        self.assertIsNone(projected["entry_id"])

    def test_admission_chain_and_illegal_entry_transition(self):
        from forecasts.lifecycle import transition
        from forecasts.models import PortfolioPolicyActivation
        from forecasts.portfolio import assess_recommendation_batch
        from forecasts.sizing import POLICY_VERSION, size_recommendation

        now, rec = self.directional()
        with self.assertRaisesMessage(ValidationError, "illegal_lifecycle_transition"):
            transition(rec, "entered", reason_code="adversarial")
        with (
            self.timeline.at(now + timedelta(seconds=2)),
            patch("forecasts.portfolio.POLICY_KEY", "synthetic-phase3-policy"),
            patch("forecasts.sizing.POLICY_KEY", "synthetic-phase3-policy"),
        ):
            PortfolioPolicyActivation.objects.create(
                policy_key="synthetic-phase3-policy",
                policy_version=POLICY_VERSION,
                effective_at=now,
            )
            size_recommendation(rec)
            cohort = assess_recommendation_batch([rec])
        self.assertEqual(project_lifecycle(rec)["state"], "admitted_awaiting_entry")
        cohort.refresh_from_db()
        self.assertEqual(cohort.closure.reason_code, "selection_recorded")
        self.assertEqual(rec.lifecycle_events.count(), 3)

    def test_raw_terminal_source_and_conflicting_chain_rejected(self):
        import json

        _, rec = self.directional()
        event = rec.lifecycle_events.first()
        for changes in [
            dict(id=9000002, state="entered", predecessor_id=event.pk, idempotency_key="b" * 64),
            dict(id=9000003, state="abstained", predecessor_id=event.pk, idempotency_key="c" * 64),
        ]:
            with (
                self.subTest(changes=changes),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
            ):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO forecasts_recommendationlifecycleevent SELECT (jsonb_populate_record(NULL::forecasts_recommendationlifecycleevent, to_jsonb(e)||%s::jsonb)).* FROM forecasts_recommendationlifecycleevent e WHERE id=%s",
                        [json.dumps(changes), event.pk],
                    )

    def test_invalid_semantic_hash_cannot_bypass_application(self):
        import json

        _, target, _ = self.prepare()
        for field, value in [
            ("identity_sha256", "e" * 64),
            ("definition_sha256", "f" * 64),
            ("information_cutoff", (target.information_cutoff + timedelta(seconds=1)).isoformat()),
            ("reference_content_sha256", "f" * 64),
        ]:
            with self.subTest(field=field), self.assertRaises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO forecasts_targetoccurrence SELECT (jsonb_populate_record(NULL::forecasts_targetoccurrence,to_jsonb(t)||%s::jsonb)).* FROM forecasts_targetoccurrence t WHERE id=%s",
                        [json.dumps({"id": 9000004, field: value}), target.pk],
                    )

    def test_integrity_report_is_read_only_and_legacy_separate(self):
        from django.test.utils import CaptureQueriesContext

        from forecasts.integrity import report

        now, rec = self.directional()
        with CaptureQueriesContext(connection) as queries:
            first = report(as_of=now + timedelta(seconds=1))
            second = report(as_of=now + timedelta(seconds=1))
        self.assertEqual(first, second)
        self.assertEqual(first["total"], 0)
        self.assertFalse(
            any(
                q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for q in queries
            )
        )

    def test_sql_issuance_window_rejects_mature_control_and_model(self):
        import json

        from forecasts.targets import target_endpoint
        from market.quality import registered_candle_completion

        now, rec = self.directional()
        target = rec.target_occurrence
        deadline = registered_candle_completion(
            target_endpoint(target.reference_candle.timestamp, target.horizon_sessions), "D"
        )
        for table, row, field in [
            ("forecasts_forecast", rec.control_forecast_id, "issued_at"),
            ("forecasts_recommendation", rec.pk, "generated_at"),
        ]:
            for instant in [deadline, deadline + timedelta(microseconds=1)]:
                changes = {
                    "id": 9200001,
                    "idempotency_key": "mature-control",
                    field: instant.isoformat(),
                }
                if table == "forecasts_recommendation":
                    changes.pop("idempotency_key")
                with (
                    self.subTest(table=table, instant=instant),
                    self.assertRaisesMessage(DatabaseError, "issuance_outside_target_window"),
                    transaction.atomic(),
                ):
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table}, to_jsonb(r)||%s::jsonb)).* FROM {table} r WHERE id=%s",
                            [json.dumps(changes), row],
                        )

    def test_unassessed_retry_expires_at_exact_owner_window(self):
        from forecasts.lifecycle import reconcile_lifecycle

        now, rec = self.directional()
        deadline = rec.generated_at + timedelta(hours=24)
        with patch("forecasts.portfolio.assess_recommendation_batch", return_value=None):
            reconcile_lifecycle(as_of=deadline - timedelta(microseconds=1))
        self.assertEqual(
            project_lifecycle(rec, as_of=deadline - timedelta(microseconds=1))["state"],
            "awaiting_portfolio_assessment",
        )
        reconcile_lifecycle(as_of=deadline)
        self.assertEqual(project_lifecycle(rec, as_of=deadline)["state"], "cancelled")
        self.assertEqual(
            project_lifecycle(rec, as_of=deadline)["reason_code"], "assessment_window_expired"
        )
        count = rec.lifecycle_events.count()
        reconcile_lifecycle(as_of=deadline + timedelta(hours=1))
        self.assertEqual(rec.lifecycle_events.count(), count)

    def test_app_missing_resolution_rejects_immature_target(self):
        from forecasts.targets import RESOLUTION_METHOD

        now, target, _ = self.prepare()
        with self.assertRaises(ValidationError):
            TargetResolution.objects.create(
                target=target,
                outcome="missing",
                resolution_method=RESOLUTION_METHOD,
                resolved_at=now,
                idempotency_key="immature-missing",
            )

    def test_all_new_record_types_reject_update_delete_and_truncate(self):
        from forecasts.models import PortfolioPolicyActivation
        from forecasts.portfolio import assess_recommendation_batch
        from forecasts.sizing import size_recommendation
        from forecasts.targets import target_endpoint
        from market.quality import registered_candle_completion

        now, rec = self.directional()
        with (
            self.timeline.at(now + timedelta(seconds=2)),
            patch("forecasts.portfolio.POLICY_KEY", "immutable-fixture"),
            patch("forecasts.sizing.POLICY_KEY", "immutable-fixture"),
        ):
            PortfolioPolicyActivation.objects.create(
                policy_key="immutable-fixture", policy_version=1, effective_at=now
            )
            size_recommendation(rec)
            assess_recommendation_batch([rec])
        target = rec.target_occurrence
        resolve_target(
            target,
            as_of=registered_candle_completion(
                target_endpoint(target.reference_candle.timestamp, 5), "D"
            ),
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for table in [
            "targetoccurrence",
            "targetresolution",
            "recommendationlifecycleevent",
            "portfoliodisposition",
            "cohortclosure",
        ]:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT count(*) FROM forecasts_{table}")
                self.assertGreater(cursor.fetchone()[0], 0)
            for statement in [
                f"UPDATE forecasts_{table} SET id=id",
                f"DELETE FROM forecasts_{table}",
                f"TRUNCATE forecasts_{table} CASCADE",
            ]:
                with (
                    self.subTest(statement=statement),
                    self.assertRaisesMessage(DatabaseError, "governed_record_immutable"),
                    transaction.atomic(),
                ):
                    with connection.cursor() as cursor:
                        cursor.execute(statement)

    def test_shared_resolution_trigger_branches_validate_both_prediction_tables(self):
        import json

        from forecasts.targets import target_endpoint
        from market.quality import registered_candle_completion

        now, rec = self.directional()
        target = rec.target_occurrence
        maturity = registered_candle_completion(
            target_endpoint(target.reference_candle.timestamp, 5), "D"
        )
        with self.timeline.at(maturity):
            forecast_result = resolve_forecast(rec.control_forecast)
            recommendation_result = resolve_recommendation(rec)
        for table, result in [
            ("forecasts_forecastresolution", forecast_result),
            ("forecasts_recommendationresolution", recommendation_result),
        ]:
            self.assertEqual(result.outcome, "missing")
            self.assertIsNone(result.brier_score)
            for changes, code in [
                ({"target_resolution_id": None}, "shared_resolution_required"),
                ({"brier_score": "0.1"}, "unscored_brier_forbidden"),
            ]:
                with (
                    self.subTest(table=table, code=code),
                    self.assertRaisesMessage(DatabaseError, code),
                    transaction.atomic(),
                ):
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table},to_jsonb(r)||%s::jsonb)).* FROM {table} r WHERE id=%s",
                            [json.dumps({"id": 9300001, **changes}), result.pk],
                        )

    def test_control_readiness_missing_incompatible_and_exact_are_read_only(self):
        from django.test.utils import CaptureQueriesContext

        from forecasts.services import issue_baselines
        from forecasts.targets import control_readiness

        now = self.timeline.poll_instant([self.sessions[19]], "D") + timedelta(seconds=2)
        with self.timeline.at(now):
            evidence(self.instrument, now, prospective=False)
            with CaptureQueriesContext(connection) as queries:
                self.assertIn("Missing control", control_readiness(self.instrument, as_of=now))
            self.assertFalse(
                any(
                    q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                    for q in queries
                )
            )
            issue_baselines(self.instrument, issued_at=now)
            self.assertIn("Incompatible control", control_readiness(self.instrument, as_of=now))
            reconcile_targets(self.instrument, as_of=now)
            self.assertEqual(
                control_readiness(self.instrument, as_of=now), "Exact prospective control available"
            )
