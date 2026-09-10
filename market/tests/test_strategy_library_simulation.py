from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from django.test import SimpleTestCase

from market.calendar_policy import CalendarAttestation
from market.state.features import Bar
from market.strategy.contracts import Unavailable
from market.strategy.costs import CostEvidence
from market.strategy.setups import atr, candidate
from market.strategy.simulation import OutcomeTerms, simulate

START = datetime(2026, 9, 10, 10, tzinfo=UTC)


def bar(start=START, *, open="100", high="104", low="99", close="102"):
    end = start + timedelta(minutes=15)
    return Bar(start, D(open), D(high), D(low), D(close), end, D("0.2"), "M15", end, 1, "b" * 64)


class SimulationTests(SimpleTestCase):
    def setUp(self):
        self.setup = candidate("fixture", bar(close="100"), 1, D(98), target=D(104))
        self.outcome = bar(self.setup.entry_at, low="97", high="105")
        self.cost = CostEvidence(
            "fixture",
            "synthetic",
            "1",
            "c" * 64,
            "USD",
            START,
            START,
            START + timedelta(days=1),
            D("0.2"),
            D("0.03"),
            D("0.1"),
            D(0),
            0,
        )
        self.calendar = CalendarAttestation(
            "1",
            "https://example.test/fixture",
            "fixture",
            START,
            ((START, START + timedelta(days=1)),),
            (),
        )
        end = self.outcome.end
        self.terms = OutcomeTerms("d" * 64, "USD", "CAD", START, end, end, end, D("1.3"), ())

    def run_model(self, bars=None, **kwargs):
        return simulate(
            self.setup,
            bars or (self.outcome,),
            **(
                {
                    "cost": self.cost,
                    "calendar": self.calendar,
                    "profile": "fixture",
                    "terms": self.terms,
                }
                | kwargs
            ),
        )

    def test_dual_hit_is_adverse_and_net_is_not_gross(self):
        result = self.run_model()
        self.assertEqual(result.reason, "stop_adverse_path")
        self.assertEqual(result.gross_quote, D(-2))
        self.assertEqual(result.costs_quote, D("0.46"))
        self.assertEqual(result.net_quote, D("-2.46"))
        self.assertEqual(result.net_account, D("-3.198"))
        self.assertEqual(result.entry, D("100.2"))
        self.assertEqual(result.exit, D("97.8"))
        self.assertEqual(self.run_model((self.outcome, bar(self.outcome.end, low="1"))), result)

    def test_missingness_is_not_a_zero_cost_fill(self):
        for kwargs, reason in (
            ({"cost": None}, "cost_unavailable"),
            ({"calendar": None}, "calendar_unavailable"),
            ({"terms": None}, "outcome_terms_unavailable"),
            ({"cost": replace(self.cost, latency_seconds=1)}, "latency_misses_next_open"),
            ({"cost": replace(self.cost, financing_reserve=None)}, "incomplete_cost_evidence"),
        ):
            self.assertEqual(self.run_model(**kwargs).reason, reason)
        self.assertEqual(self.run_model((bar(self.outcome.end),)).reason, "next_interval_missing")

    def test_gaps_short_mirror_and_target_not_improved(self):
        self.assertEqual(
            self.run_model((self.outcome._replace(open=D(97)),)).reason,
            "entry_gap_outside_geometry",
        )
        self.setup = candidate("fixture", bar(close="100"), -1, D(102), target=D(96))
        result = self.run_model((bar(self.setup.entry_at, high="103", low="95"),))
        self.assertEqual(result.gross_quote, D(-2))
        result = self.run_model((bar(self.setup.entry_at, high="101", low="94"),))
        self.assertEqual(result.gross_quote, D(4))

    def test_late_confirmation_and_atr_true_range(self):
        signal = bar()
        self.assertIsInstance(
            candidate(
                "fixture", signal, 1, D(98), available_at=signal.end + timedelta(microseconds=1)
            ),
            Unavailable,
        )
        history = tuple(
            bar(START + timedelta(minutes=15 * i), open="100", high="101", low="99", close="100")
            for i in range(15)
        )
        self.assertEqual(atr(history), D(2))
        self.assertIsNone(atr(history[1:]))
