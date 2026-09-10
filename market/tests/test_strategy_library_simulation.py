import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from django.test import SimpleTestCase

from market.calendar_policy import CalendarAttestation
from market.state.features import Bar
from market.strategy.contracts import Unavailable, encoded
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
        self.terms = OutcomeTerms(
            "d" * 64,
            "USD",
            "CAD",
            START,
            end,
            end,
            end,
            D("1.3"),
            (),
            base_currency="EUR",
            provenance="synthetic fixture",
            cost_unit="quote_per_base",
            conversion_unit="account_per_quote",
        )

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

    def test_conversion_evidence_roundtrip_preserves_exact_net(self):
        self.terms = replace(self.terms, conversion_rate=D("1.23456789"))
        body = json.loads(encoded(self.terms, exact=True))
        self.assertEqual(body["conversion_rate"], "1.23456789")
        restored = replace(self.terms, conversion_rate=D(body["conversion_rate"]))
        self.assertEqual(self.run_model(terms=restored), self.run_model())
        self.assertEqual(self.run_model().net_account, D("-3.0370370094"))

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
                "fixture",
                signal,
                1,
                D(98),
                available_at=signal.end + timedelta(minutes=15, microseconds=1),
            ),
            Unavailable,
        )
        delayed = candidate(
            "fixture", signal, 1, D(98), available_at=signal.end + timedelta(microseconds=1)
        )
        self.assertEqual(delayed.entry_at, signal.end + timedelta(minutes=15))
        history = tuple(
            bar(START + timedelta(minutes=15 * i), open="100", high="101", low="99", close="100")
            for i in range(15)
        )
        self.assertEqual(atr(history), D(2))
        self.assertIsNone(atr(history[1:]))

    def test_rollover_is_required_at_equality_and_conversion_is_pit(self):
        signal = bar(START.replace(hour=20, minute=30), close="100")
        self.setup = candidate("fixture", signal, 1, D(98), target=D(104))
        self.outcome = bar(self.setup.entry_at, low="97", high="105")
        end = self.outcome.end  # 21:00 UTC = New York 17:00 in September.
        self.terms = replace(self.terms, through_at=end, known_at=end, conversion_at=end)
        self.assertEqual(self.run_model().reason, "rollover_evidence_missing")
        self.terms = replace(self.terms, rollovers=((end, D("0.7")),))
        result = self.run_model()
        self.assertEqual(result.costs_quote, D("1.16"))
        self.assertEqual(result.net_account, D("-4.108"))
        self.assertEqual(
            self.run_model(
                terms=replace(self.terms, known_at=end + timedelta(microseconds=1))
            ).reason,
            "outcome_terms_unavailable",
        )
        self.assertEqual(
            self.run_model(terms=replace(self.terms, account_currency="USD")).reason,
            "invalid_same_currency_conversion",
        )
        self.terms = replace(self.terms, rollovers=((end, D("-0.7")),))
        self.assertEqual(self.run_model().costs_quote, D("0.46"))
        first = bar(self.setup.entry_at, low="99", high="101", close="100")
        at_rollover = bar(first.end, low="97", high="105")
        at_terms = replace(
            self.terms,
            through_at=at_rollover.end,
            known_at=at_rollover.end,
            conversion_at=at_rollover.end,
        )
        self.assertEqual(
            self.run_model((first, at_rollover), terms=at_terms).costs_quote, D("0.46")
        )
        held = bar(first.end, low="99", high="101", close="100")
        later = bar(held.end, low="97", high="105")
        later_terms = replace(
            self.terms, through_at=later.end, known_at=later.end, conversion_at=later.end
        )
        earned = self.run_model((first, held, later), terms=later_terms)
        self.assertEqual(earned.costs_quote, D("-0.24"))
        self.assertEqual(earned.net_quote, D("-1.76"))

    def test_entry_rollover_tie_requires_evidence_without_awarding_credit(self):
        signal = bar(START.replace(hour=20, minute=45), close="100")
        self.setup = candidate("fixture", signal, 1, D(98), target=D(104))
        first = bar(self.setup.entry_at, low="99", high="101", close="100")
        held = bar(first.end, low="99", high="101", close="100")
        last = bar(held.end, low="97", high="105")
        self.terms = replace(
            self.terms, through_at=last.end, known_at=last.end, conversion_at=last.end
        )
        path = (first, held, last)
        self.assertEqual(self.run_model(path).reason, "rollover_evidence_missing")
        for amount, expected_cost in (("0.7", "1.16"), ("-0.7", "0.46")):
            terms = replace(self.terms, rollovers=((self.setup.entry_at, D(amount)),))
            self.assertEqual(self.run_model(path, terms=terms).costs_quote, D(expected_cost))

    def test_later_stop_gap_is_adverse_and_target_gap_has_no_improvement(self):
        first = bar(self.setup.entry_at, low="99", high="101", close="100")
        second = bar(first.end, open="97", low="96", high="101", close="100")
        self.terms = replace(
            self.terms, through_at=second.end, known_at=second.end, conversion_at=second.end
        )
        result = self.run_model((first, second))
        self.assertEqual((result.reason, result.gross_quote), ("stop_gap", D(-3)))
        result = self.run_model(
            (first, second._replace(open=D(106), low=D(105), high=D(107), close=D(106)))
        )
        self.assertEqual((result.reason, result.gross_quote), ("target_no_improvement", D(4)))

    def test_weekend_successor_requires_reopening_and_documented_rollovers(self):
        friday = START.replace(day=11, hour=20, minute=30)
        self.setup = candidate("fixture", bar(friday, close="100"), 1, D(98), target=D(104))
        first = bar(self.setup.entry_at, low="99", high="101", close="100")
        sunday = friday.replace(day=13, hour=21, minute=0)
        second = bar(sunday, open="100", low="99", high="105", close="104")
        self.cost = replace(self.cost, valid_through=second.end)
        self.calendar = replace(
            self.calendar,
            open_intervals=((friday, first.end), (sunday, second.end)),
            closed_intervals=((first.end, sunday),),
        )
        self.terms = replace(
            self.terms,
            through_at=second.end,
            known_at=second.end,
            conversion_at=second.end,
            rollovers=tuple((first.end + timedelta(days=i), D(0)) for i in range(3)),
        )
        result = self.run_model((first, second))
        self.assertEqual((result.reason, result.gross_quote), ("target_no_improvement", D(4)))
        self.assertEqual(
            self.run_model((first, bar(sunday + timedelta(minutes=15)))).reason,
            "outcome_interval_gap",
        )
        self.assertEqual(
            self.run_model((first, second), terms=replace(self.terms, rollovers=())).reason,
            "rollover_evidence_missing",
        )
