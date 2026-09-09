from datetime import timedelta
from types import MethodType

from django.test import TestCase

from forecasts.lifecycle import project_lifecycle
from forecasts.paper import resolve_paper_trade
from forecasts.portfolio import assess_recommendation_batch
from forecasts.recommendations import generate_recommendation
from forecasts.sizing import size_recommendation
from forecasts.tests.test_recommendations import FakeProvider, hourly_candle
from market.tests.factories import candle


class ExecutionBoundaryTests(TestCase):
    def setUp(self):
        from forecasts.tests.test_frozen_evidence import FrozenEvidenceTests

        self.daily = MethodType(FrozenEvidenceTests.daily, self)
        FrozenEvidenceTests.setUp(self)
        with self.timeline.at(self.now):
            self.rec = generate_recommendation(
                self.instrument, provider=FakeProvider(), generated_at=self.now
            )
            size_recommendation(self.rec, sized_at=self.now)
            assess_recommendation_batch([self.rec], generated_at=self.now)
        self.assertEqual(project_lifecycle(self.rec)["state"], "admitted_awaiting_entry")

    def endpoint(self):
        return self.timeline.ingest(
            self.source,
            self.instrument,
            "D",
            [candle(self.timeline.session(5))],
            manifest={"test": "exact-endpoint-with-session-gaps", "requests": []},
        )

    def test_entry_then_hourly_gap_closes_missing_without_fabricated_result(self):
        first = self.timeline.hours_after(self.rec.generated_at, 1)[0]
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [hourly_candle(first)],
            manifest={"test": "entry-only", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(self.timeline.after(run)):
            resolve_paper_trade(self.rec)
        self.assertEqual(project_lifecycle(self.rec)["state"], "entered")
        endpoint = self.endpoint()
        with self.timeline.at(self.timeline.after(endpoint)):
            resolve_paper_trade(self.rec)
        state = project_lifecycle(self.rec)
        self.assertEqual(state["state"], "missing_data")
        self.assertIsNotNone(state["entry_id"])
        self.assertIsNone(state["result_id"])
        self.assertTrue(state["terminal"])

    def test_preentry_gap_is_expired_unobserved_not_notactivated(self):
        second = self.timeline.hours_after(self.rec.generated_at, 2)[1]
        self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [hourly_candle(second)],
            manifest={"test": "missing-first-hour", "requests": []},
            requested_from=self.rec.generated_at,
        )
        endpoint = self.endpoint()
        with self.timeline.at(self.timeline.after(endpoint)):
            resolve_paper_trade(self.rec)
        state = project_lifecycle(self.rec)
        self.assertEqual(state["state"], "expired_unobserved")
        self.assertIsNone(state["entry_id"])
        self.assertIsNone(state["result_id"])

    def test_future_hourly_observation_cannot_activate_before_availability(self):
        first = self.timeline.hours_after(self.rec.generated_at, 1)[0]
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [hourly_candle(first)],
            manifest={"test": "future-observation", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(run.finished_at - timedelta(microseconds=1)):
            self.assertIsNone(resolve_paper_trade(self.rec))
        self.assertIsNone(project_lifecycle(self.rec)["entry_id"])
        with self.timeline.at(run.finished_at):
            resolve_paper_trade(self.rec)
        self.assertEqual(project_lifecycle(self.rec)["state"], "entered")

    def test_execution_shared_trigger_tables_accept_facts_and_reject_mismatches(self):
        import json

        from django.db import DatabaseError, connection, transaction

        from forecasts.models import (
            PortfolioAdmissionEvent,
            PortfolioCohortMember,
            PortfolioSelectionMember,
        )

        facts = [
            (
                "forecasts_portfoliocohortmember",
                PortfolioCohortMember.objects.get(recommendation=self.rec),
                {"eligible": False},
                "membership_evidence_mismatch",
            ),
            (
                "forecasts_portfolioselectionmember",
                PortfolioSelectionMember.objects.get(recommendation=self.rec),
                {"selection_id": 9999999},
                "selection_membership_required",
            ),
            (
                "forecasts_portfolioadmissionevent",
                PortfolioAdmissionEvent.objects.get(recommendation=self.rec),
                {"cohort_id": 9999999},
                "admission_selection_required",
            ),
        ]
        first = self.timeline.hours_after(self.rec.generated_at, 1)[0]
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [hourly_candle(first)],
            manifest={"test": "trigger-matrix-entry", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(self.timeline.after(run)):
            resolve_paper_trade(self.rec)
        self.rec.refresh_from_db()
        facts.append(
            (
                "forecasts_papertradeentry",
                self.rec.paper_entry,
                {"execution_side": "bid"},
                "entry_evidence_mismatch",
            )
        )
        # An adverse second hour crosses the frozen stop, producing a real result.
        from dataclasses import replace
        from decimal import Decimal

        next_hour = self.timeline.hours_after(self.rec.generated_at, 2)[1]
        bar = hourly_candle(next_hour)
        bar = replace(bar, bid_low=Decimal("1.000000"), ask_low=Decimal("1.000200"))
        run = self.timeline.ingest(
            self.source,
            self.instrument,
            "H1",
            [bar],
            manifest={"test": "trigger-matrix-result", "requests": []},
            requested_from=self.rec.generated_at,
        )
        with self.timeline.at(self.timeline.after(run)):
            resolve_paper_trade(self.rec)
        self.rec.refresh_from_db()
        facts.append(
            (
                "forecasts_papertraderesult",
                self.rec.paper_result,
                {"entry_id": 9999999},
                "result_entry_required",
            )
        )
        facts.append(
            (
                "forecasts_papertraderesult",
                self.rec.paper_result,
                {"horizon_candle_id": self.rec.target_occurrence.reference_candle_id},
                "paper_endpoint_mismatch",
            )
        )
        for table, fact, changes, code in facts:
            self.assertIsNotNone(fact.pk)
            with (
                self.subTest(table=table),
                self.assertRaisesMessage(DatabaseError, code),
                transaction.atomic(),
            ):
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table},to_jsonb(r)||%s::jsonb)).* FROM {table} r WHERE id=%s",
                        [json.dumps({"id": 9400001, **changes}), fact.pk],
                    )
