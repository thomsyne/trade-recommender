from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

from django.test import SimpleTestCase

from market.state.sessions import session_open_utc
from market.strategy.contracts import SetupCandidate
from market.strategy.orb import opening_range
from market.tests.test_strategy_library_simulation import bar


class OrbTests(SimpleTestCase):
    def inputs(self, tail=()):
        start = datetime(2026, 9, 10, 7, tzinfo=UTC)
        prefix = tuple(
            bar(start - timedelta(minutes=15 * i), open="100", high="101", low="99", close="100")
            for i in reversed(range(15))
        )
        return SimpleNamespace(series=lambda _: prefix + tail, payload={}), start

    def run_orb(self, inputs, variant="orb-m15-confirmed-v1", day=date(2026, 9, 10)):
        return opening_range(inputs, session="london", session_date=day, variant=variant)

    def test_wick_and_close_are_distinct_and_next_interval_only(self):
        _, start = self.inputs()
        signal = bar(start + timedelta(minutes=15), open="100", high="103", low="100", close="101")
        inputs, _ = self.inputs((signal,))
        self.assertEqual(self.run_orb(inputs).reason, "no_confirmation_before_expiry")
        wick = self.run_orb(inputs, "orb-m15-wick-v1")
        self.assertIsInstance(wick, SetupCandidate)
        self.assertEqual(wick.entry_at, signal.end)
        inputs, _ = self.inputs((signal._replace(close=D("102")),))
        result = self.run_orb(inputs)
        self.assertEqual(result.stop, D("98.5"))
        self.assertEqual(result.target, D(109))
        self.assertNotEqual(result.strategy, wick.strategy)

    def test_missing_open_gap_weekend_and_dst(self):
        inputs, start = self.inputs()
        self.assertEqual(
            self.run_orb(SimpleNamespace(series=lambda _: (), payload={})).reason,
            "opening_interval_missing",
        )
        self.assertEqual(self.run_orb(inputs, day=date(2026, 9, 12)).reason, "weekend_session")
        missing, _ = self.inputs((bar(start + timedelta(minutes=30)),))
        self.assertEqual(self.run_orb(missing).reason, "session_gap")
        self.assertEqual(session_open_utc(date(2026, 3, 9), "new_york")[0].hour, 12)
        self.assertEqual(session_open_utc(date(2026, 3, 9), "london")[0].hour, 8)
        self.assertEqual(session_open_utc(date(2026, 3, 30), "london")[0].hour, 7)

    def test_fvg_is_not_inferred_from_a_close_and_first_attempt_is_terminal(self):
        _, start = self.inputs()
        signal = bar(start + timedelta(minutes=15), close="102")
        inputs, _ = self.inputs((signal, bar(signal.end, close="103")))
        self.assertEqual(
            self.run_orb(inputs, "orb-m15-fvg-v1").reason, "same_direction_fvg_unavailable"
        )
        inputs, _ = self.inputs((signal._replace(spread=None), bar(signal.end, close="103")))
        self.assertEqual(self.run_orb(inputs).reason, "confirmation_spread_unavailable_or_wide")
