"""Regression counterexamples from the independent review of 644e541."""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from forecasts.integrity import report
from forecasts.lifecycle import project_lifecycle, transition
from forecasts.models import Candle, PaperTradeResult, TargetResolution
from forecasts.paper import _entry_fill, resolve_paper_trade
from forecasts.targets import resolve_target, target_endpoint
from forecasts.tests.test_recommendations import hourly_candle, open_market_hours
from market.quality import registered_candle_completion
from market.tests.factories import candle


class ObservableEvidenceTests(TestCase):
    def setUp(self):
        from forecasts.tests_phase3.test_execution_boundaries import ExecutionBoundaryTests

        ExecutionBoundaryTests.setUp(self)
        self.target = self.rec.target_occurrence
        self.endpoint = target_endpoint(self.target.reference_candle.timestamp, 5)
        self.maturity = registered_candle_completion(self.endpoint, "D")

    def hours(self, *, hit=False, low="1.3498"):
        bars = [
            hourly_candle(h, ask_low=Decimal(low), bid_low=Decimal(low) - Decimal(".0002"))
            for h in open_market_hours(self.rec.generated_at, self.maturity)
        ]
        if hit:
            bars[1] = hourly_candle(
                bars[1].timestamp, bid_high=Decimal("2"), ask_high=Decimal("2.0002")
            )
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            bars,
            manifest={"test": "observable-hours", "requests": []},
            requested_from=self.rec.generated_at,
        )
        return run

    def daily_endpoint(self):
        return self.timeline.ingest(
            self.source,
            self.instrument,
            "D",
            [candle(self.endpoint)],
            manifest={"test": "observable-endpoint", "requests": []},
        )

    def missing(self, at):
        return TargetResolution(
            target=self.target,
            outcome="missing",
            resolution_method=self.target.resolution_method,
            resolved_at=at,
            idempotency_key="observable-missing",
            details={"schema_version": 1},
        )

    def nonactivated(self, at):
        return PaperTradeResult(
            recommendation=self.rec,
            outcome="not_activated",
            resolved_at=at,
            horizon_candle=Candle.objects.get(
                instrument=self.instrument, granularity="D", timestamp=self.endpoint
            ),
            details={"schema_version": 1},
        )

    def raw_insert(self, obj):
        # Serialize a complete unsaved record; do not call save/full_clean/bulk_create.
        values = {}
        for field in obj._meta.concrete_fields:
            value = getattr(obj, field.attname)
            if not field.primary_key:
                values[field.column] = value
        table = obj._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table}, "
                f"%s::jsonb || jsonb_build_object('id',nextval(pg_get_serial_sequence('{table}','id'))))).* RETURNING id",
                [json.dumps(values, default=str)],
            )
            return cursor.fetchone()[0]

    def test_delayed_recovery_preserves_target_with_or_without_daily_endpoint(self):
        run = self.hours(hit=True)
        at = self.timeline.after(run)
        for endpoint_present in (True, False):
            with self.subTest(endpoint=endpoint_present), transaction.atomic():
                if endpoint_present:
                    at = max(at, self.timeline.after(self.daily_endpoint()))
                with self.timeline.at(at):
                    result = resolve_paper_trade(self.rec)
                    self.assertEqual(result.outcome, "target")
                    self.assertEqual(project_lifecycle(self.rec)["state"], "target_hit")
                    self.assertEqual(resolve_paper_trade(self.rec).pk, result.pk)
                self.assertEqual(
                    result.exit_candle.timestamp,
                    self.timeline.hours_after(self.rec.generated_at, 2)[1],
                )
                transaction.set_rollback(True)

    def test_hourly_cutoff_and_missing_evidence_remain_fail_closed(self):
        run = self.hours(hit=True)
        with transaction.atomic():
            with self.timeline.at(run.finished_at - timedelta(microseconds=1)):
                self.assertIsNone(resolve_paper_trade(self.rec))
                self.assertEqual(project_lifecycle(self.rec)["state"], "missing_data")
                self.assertFalse(PaperTradeResult.objects.filter(recommendation=self.rec).exists())
            transaction.set_rollback(True)
        with self.timeline.at(run.finished_at):
            self.assertEqual(resolve_paper_trade(self.rec).outcome, "target")

    def test_no_hourly_or_daily_evidence_is_missing(self):
        with self.timeline.at(self.maturity):
            self.assertIsNone(resolve_paper_trade(self.rec))
            self.assertEqual(project_lifecycle(self.rec)["state"], "missing_data")

    def test_already_entered_recovery_and_adverse_precedence_without_daily(self):
        first = self.timeline.hours_after(self.rec.generated_at, 1)[0]
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [hourly_candle(first)],
            manifest={"test": "prior-entry", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(self.timeline.after(run)):
            resolve_paper_trade(self.rec)
            self.assertEqual(project_lifecycle(self.rec)["state"], "entered")
        for stop in (False, True):
            with self.subTest(stop=stop), transaction.atomic():
                bars = [
                    hourly_candle(h)
                    for h in open_market_hours(self.rec.generated_at, self.maturity)
                ]
                bars[1] = hourly_candle(
                    bars[1].timestamp,
                    bid_high=Decimal("2"),
                    ask_high=Decimal("2.0002"),
                    **({"bid_low": Decimal("1"), "ask_low": Decimal("1.0002")} if stop else {}),
                )
                run = self.timeline.ingest(
                    self.source,
                    self.instrument,
                    "H1",
                    bars,
                    manifest={"test": "prior-entry-recovery", "requests": []},
                    requested_from=self.rec.generated_at,
                )
                with self.timeline.at(self.timeline.after(run)):
                    result = resolve_paper_trade(self.rec)
                    self.assertEqual(result.outcome, "invalidated" if stop else "target")
                    self.assertEqual(result.details["same_candle_target_and_stop"], stop)
                transaction.set_rollback(True)

    def test_post_maturity_target_touch_is_not_execution_evidence(self):
        self.hours()
        late = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [hourly_candle(self.maturity, bid_high=Decimal("2"), ask_high=Decimal("2.0002"))],
            manifest={"test": "late-touch", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(self.timeline.after(late)):
            resolve_paper_trade(self.rec)
            projection = project_lifecycle(self.rec)
            self.assertEqual(projection["state"], "missing_data")
            self.assertIsNotNone(projection["entry_id"])
            self.assertIsNone(projection["result_id"])

    def test_nonactivation_rejects_trigger_and_equality_in_orm_and_sql(self):
        for low in ("1.3498", "1.3500"):
            with self.subTest(low=low), transaction.atomic():
                run = self.hours(low=low)
                at = max(self.timeline.after(run), self.timeline.after(self.daily_endpoint()))
                first = Candle.objects.filter(granularity="H1").order_by("timestamp").first()
                self.assertEqual(self.rec.entry_level, Decimal("1.3500"))
                self.assertIsNotNone(_entry_fill(self.rec, first))
                result = self.nonactivated(at)
                for writer in ("orm", "transition", "sql"):
                    with (
                        self.subTest(writer=writer),
                        self.assertRaisesMessage(
                            DatabaseError if writer == "sql" else ValidationError,
                            "nonactivation_contradicts_entry_evidence",
                        ),
                        transaction.atomic(),
                    ):
                        if writer == "orm":
                            result.save()
                        elif writer == "sql":
                            self.raw_insert(result)
                        else:
                            transition(
                                self.rec,
                                "expired_not_activated",
                                reason_code="paper_result",
                                source=result,
                                occurred_at=at,
                            )
                transaction.set_rollback(True)

    def test_complete_nontriggering_evidence_accepts_nonactivation_in_orm_and_sql(self):
        run = self.hours(low="1.350001")
        at = max(self.timeline.after(run), self.timeline.after(self.daily_endpoint()))
        for raw in (False, True):
            with self.subTest(raw=raw), transaction.atomic():
                result = self.nonactivated(at)
                if raw:
                    result = PaperTradeResult.objects.get(pk=self.raw_insert(result))
                else:
                    result.save()
                transition(
                    self.rec,
                    "expired_not_activated",
                    reason_code="paper_result",
                    source=result,
                    occurred_at=at,
                )
                self.assertEqual(project_lifecycle(self.rec)["state"], "expired_not_activated")
                transaction.set_rollback(True)

    def test_python_sql_activation_matrix_uses_condition_and_execution_side(self):
        import copy

        from forecasts.lifecycle import initialize, validate_expiry_result

        run = self.hours(low="1.350001")
        at = max(self.timeline.after(run), self.timeline.after(self.daily_endpoint()))
        for action, condition, boundary in (
            ("buy", "at_or_below", "1.350001"),
            ("sell", "at_or_below", "1.349801"),
            ("buy", "at_or_above", "1.352200"),
            ("sell", "at_or_above", "1.352000"),
        ):
            for equality in (True, False):
                with (
                    self.subTest(action=action, condition=condition, equality=equality),
                    transaction.atomic(),
                ):
                    rec = copy.copy(self.rec)
                    rec.pk = None
                    rec._state = copy.copy(self.rec._state)
                    rec._state.adding = True
                    rec.action, rec.entry_condition = action, condition
                    delta = Decimal("0") if equality else Decimal(".000001")
                    rec.entry_level = Decimal(boundary) + (
                        delta if condition == "at_or_above" else -delta
                    )
                    direction = Decimal(".01") if action == "buy" else Decimal("-.01")
                    rec.target_level = rec.entry_level + direction
                    rec.invalidation_level = rec.entry_level - direction
                    rec.idempotency_key = f"matrix:{action}:{condition}:{equality}"
                    rec.save()
                    initialize(rec)
                    result = self.nonactivated(at)
                    result.recommendation = rec
                    if equality:
                        with self.assertRaisesMessage(
                            ValidationError, "nonactivation_contradicts_entry_evidence"
                        ):
                            validate_expiry_result(result)
                    else:
                        validate_expiry_result(result)
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT phase3_observable_activation(%s,%s)", [rec.pk, at])
                        self.assertEqual(cursor.fetchone()[0], equality)
                    transaction.set_rollback(True)

    def test_missing_endpoint_availability_cutoff_orm_and_sql(self):
        run = self.daily_endpoint()
        for offset in (-1, 0, 1):
            at = run.finished_at + timedelta(microseconds=offset)
            for raw in (False, True):
                with self.subTest(offset=offset, raw=raw), transaction.atomic():
                    result = self.missing(at)
                    if offset < 0:
                        if raw:
                            self.raw_insert(result)
                        else:
                            result.save()
                        self.assertEqual(report(as_of=at)["total"], 0)
                        self.assertEqual(report(as_of=run.finished_at)["total"], 0)
                    else:
                        with (
                            self.assertRaisesMessage(
                                DatabaseError if raw else ValidationError,
                                "available_endpoint_marked_missing",
                            ),
                            transaction.atomic(),
                        ):
                            self.raw_insert(result) if raw else result.save()
                    transaction.set_rollback(True)
        self.assertNotEqual(resolve_target(self.target, as_of=run.finished_at).outcome, "missing")

    def test_truly_absent_endpoint_accepts_missing_orm_and_sql(self):
        for raw in (False, True):
            with self.subTest(raw=raw), transaction.atomic():
                result = self.missing(self.maturity)
                self.raw_insert(result) if raw else result.save()
                self.assertEqual(report(as_of=self.maturity)["total"], 0)
                transaction.set_rollback(True)

    def test_integrity_reports_pre_enforcement_missing_contradiction_read_only(self):
        run = self.daily_endpoint()
        at = self.timeline.after(run)
        # Substitute only the historical row at the read boundary; all endpoint
        # evidence and the validator are real. No immutable constraint is disabled.
        forged = self.missing(at)
        target = type(self.target).objects.get(pk=self.target.pk)
        target._state.fields_cache["resolution"] = forged
        with patch("forecasts.integrity.TargetOccurrence.objects.filter") as query:
            query.return_value.order_by.return_value.iterator.return_value = [target]
            from django.test.utils import CaptureQueriesContext

            with CaptureQueriesContext(connection) as queries:
                result = report(as_of=at)
            self.assertIn("shared_resolution_invalid", result["violations"])
            for query in queries:
                self.assertNotRegex(
                    query["sql"], r"(?i)\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE)\b"
                )
