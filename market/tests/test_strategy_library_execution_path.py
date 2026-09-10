"""Real snapshot → evaluation → simulation persistence, using preserved legacy clocks."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.calendar_policy import CalendarAttestation
from market.models import CandleObservation
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.strategy.persistence import (
    calculate,
    calculate_simulation,
    load_snapshot,
    simulation_integrity,
)
from market.strategy.simulation import OutcomeTerms
from market.tests.factories import candle
from market.tests.historical_database import HistoricalDatabaseMixin
from market.tests.test_live_observations import make_market
from market.tests.test_strategy_library_trend import cost
from market.tests.timeline import EvidenceTimeline


class ExecutionPathTests(HistoricalDatabaseMixin, TransactionTestCase):
    historical_market_migration = "0035_"

    def test_successful_simulation_and_gapped_cutoff_suffix_replay(self):
        instrument, source = make_market("EUR_USD")
        opening = datetime(2026, 1, 5, 8, tzinfo=UTC)
        decision_at = opening + timedelta(minutes=31)
        ended = opening + timedelta(hours=1)
        suffix_at = opening + timedelta(hours=2)
        timeline = EvidenceTimeline()
        # Runtime model projection only: before 0036 this column did not exist.
        # Normal historical ingestion and forward migration preserve real legacy
        # observed_at; no trigger or persisted evidence is disabled/rewritten.
        fields = CandleObservation._meta.local_fields
        CandleObservation._meta.local_fields = [f for f in fields if f.name != "recorded_at"]
        CandleObservation._meta._expire_cache()
        try:
            prefix = [candle(opening - timedelta(minutes=15 * i)) for i in range(14, -1, -1)]
            prefix.append(
                candle(
                    opening + timedelta(minutes=15),
                    bid_close=D("1.103"),
                    ask_close=D("1.1032"),
                    bid_high=D("1.104"),
                    ask_high=D("1.1042"),
                )
            )
            timeline.ingest(source, instrument, "M15", prefix, at=decision_at)
            trade = [
                candle(opening + timedelta(minutes=30)),
                candle(
                    opening + timedelta(minutes=45),
                    bid_open=D("1.103"),
                    ask_open=D("1.1032"),
                    bid_low=D("1.09"),
                    ask_low=D("1.0902"),
                    bid_high=D("1.12"),
                    ask_high=D("1.1202"),
                ),
            ]
            timeline.ingest(
                source,
                instrument,
                "M15",
                trade,
                at=ended + timedelta(minutes=1),
                manifest={"batch": "trade", "requests": []},
            )
            timeline.ingest(
                source,
                instrument,
                "M15",
                [candle(opening + timedelta(minutes=90))],
                at=suffix_at,
                manifest={"batch": "suffix", "requests": []},
            )
        finally:
            CandleObservation._meta.local_fields = fields
            CandleObservation._meta._expire_cache()
        MigrationExecutor(connection).migrate([("market", "0040_strategy_contract_corrections")])
        definition = ensure_descriptor_definition()
        decision, _ = compute_market_state(instrument, definition, decision_at, ["M15"])
        outcome, _ = compute_market_state(
            instrument, definition, ended + timedelta(minutes=1), ["M15"]
        )
        suffix, _ = compute_market_state(instrument, definition, suffix_at, ["M15"])
        evaluation, _ = calculate(decision.pk, "orb-m15-confirmed-v1:london")
        self.assertEqual(evaluation.output["outputs"][0]["schema"], "phase5/setup-v1")
        self.assertIn(
            opening + timedelta(minutes=30),
            [b.timestamp for b in load_snapshot(outcome.pk).series("M15", outcome=True)],
            list(CandleObservation.objects.values("timestamp", "observed_at", "recorded_at")),
        )
        evidence = replace(
            cost(evaluation.definition.strategy, ".0002"),
            known_at=decision_at,
            valid_from=opening,
            valid_through=suffix_at,
        )
        calendar = CalendarAttestation(
            "1", "https://example.test/synthetic", "fixture", opening, ((opening, suffix_at),), ()
        )
        terms = OutcomeTerms(
            "d" * 64,
            "USD",
            "CAD",
            opening,
            ended,
            ended,
            ended,
            D("1.3"),
            (),
            base_currency="EUR",
            provenance="synthetic legacy clock fixture",
            cost_unit="quote_per_base",
            conversion_unit="account_per_quote",
        )
        record, created = calculate_simulation(
            evaluation.pk,
            outcome.pk,
            cost=evidence,
            calendar=calendar,
            profile="fixture",
            terms=terms,
        )
        self.assertTrue(created)
        self.assertEqual(record.output["reason"], "stop_adverse_path")
        self.assertLess(D(record.output["net_quote"]), 0)
        self.assertEqual(simulation_integrity()["violations"], [])
        self.assertEqual(
            calculate_simulation(
                evaluation.pk,
                outcome.pk,
                cost=evidence,
                calendar=calendar,
                profile="fixture",
                terms=terms,
            ),
            (record, False),
        )
        import json

        from market.strategy.contracts import encoded
        from market.strategy.persistence import setup_from_payload
        from market.strategy.simulation import simulate

        frozen = load_snapshot(suffix.pk)
        self.assertEqual(frozen.series("M15"), ())
        modeled = simulate(
            setup_from_payload(evaluation.output["outputs"][0]),
            frozen.series("M15", outcome=True),
            cost=evidence,
            calendar=calendar,
            profile="fixture",
            terms=terms,
        )
        self.assertEqual(json.loads(encoded(modeled)), record.output)
        # Attempt uniqueness forbids a second persisted trade even with a longer
        # outcome snapshot; original persisted replay remains unchanged.
        with self.assertRaisesMessage(ValueError, "attempt_already_simulated"):
            calculate_simulation(
                evaluation.pk,
                suffix.pk,
                cost=evidence,
                calendar=calendar,
                profile="fixture",
                terms=terms,
            )
        self.assertEqual(simulation_integrity()["violations"], [])
