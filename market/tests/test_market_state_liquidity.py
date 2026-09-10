"""Phase 4 slice 5 — liquidity proxies, hand-calculated fixtures.

Sweep (wick-through-and-reclaim) vs acceptance (completed close beyond, not
reclaimed) — the two must be mutually distinguishable. Expected values are
derived by hand.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.test import TestCase

from market.state.features import Bar
from market.state.liquidity import (
    detect_acceptance,
    detect_sweep,
    liquidity_context,
)

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
ATR1 = Decimal("1.0")
LEVEL = Decimal("10")


def D(x):
    return Decimal(str(x))


def ohlc(i, o, h, low, c):
    return Bar(timestamp=BASE + timedelta(hours=i), open=D(o), high=D(h), low=D(low), close=D(c))


def flat(closes):
    return [Bar(BASE + timedelta(hours=i), D(c), D(c), D(c), D(c)) for i, c in enumerate(closes)]


class SweepTests(TestCase):
    def test_wick_above_and_reclaim_is_a_sweep(self):
        bars = [ohlc(0, 9, 10.5, 9, 9.5)]  # wick to 10.5, closes back to 9.5
        sweep = detect_sweep(bars, ATR1, LEVEL, "above", level_id="lid")
        self.assertIsNotNone(sweep)
        self.assertEqual(sweep["sweep_depth_atr"], "0.500000")
        self.assertEqual(sweep["reclaim_bars"], 0)

    def test_shallow_wick_is_not_a_sweep(self):
        bars = [ohlc(0, 9, D("10.05"), 9, 9.5)]  # penetration 0.05 < 0.1*ATR
        self.assertIsNone(detect_sweep(bars, ATR1, LEVEL, "above", level_id="lid"))

    def test_close_beyond_is_not_a_sweep(self):
        bars = [ohlc(0, 10, 11, 10, 11)]  # closes above -> acceptance, not a sweep
        self.assertIsNone(detect_sweep(bars, ATR1, LEVEL, "above", level_id="lid"))

    def test_sweep_below_support(self):
        bars = [ohlc(0, 11, 11, D("9.5"), D("10.5"))]  # wick to 9.5, closes back above 10
        sweep = detect_sweep(bars, ATR1, LEVEL, "below", level_id="lid")
        self.assertIsNotNone(sweep)
        self.assertEqual(sweep["side"], "below")


class AcceptanceTests(TestCase):
    def test_close_beyond_not_reclaimed_is_acceptance(self):
        # The accepting close (bar 0) needs the full 3-interval window to elapse
        # with no reclaim before acceptance is declared.
        bars = [ohlc(i, 11, 12, 11, D("11.5")) for i in range(4)]
        self.assertIsNotNone(detect_acceptance(bars, ATR1, LEVEL, "above", level_id="lid"))

    def test_pending_before_window_matures_is_not_acceptance(self):
        # Close beyond with fewer than the window's bars after it is still pending.
        bars = [ohlc(0, 10, 11, 10, 11), ohlc(1, 11, 12, 11, D("11.5"))]
        self.assertIsNone(detect_acceptance(bars, ATR1, LEVEL, "above", level_id="lid"))

    def test_close_beyond_then_reclaimed_is_not_acceptance(self):
        bars = [ohlc(0, 10, 11, 10, 11)] + [ohlc(i, 11, 11, 9, D("9.5")) for i in range(1, 4)]
        self.assertIsNone(detect_acceptance(bars, ATR1, LEVEL, "above", level_id="lid"))

    def test_a_sweep_bar_is_not_an_acceptance(self):
        bars = [ohlc(0, 9, 10.5, 9, 9.5)]  # wick above, closes back
        self.assertIsNone(detect_acceptance(bars, ATR1, LEVEL, "above", level_id="lid"))


class LiquidityContextTests(TestCase):
    def test_sweep_of_the_nearest_swing_high(self):
        # Swing high forms at 10 (index 2); a later bar wicks above and reclaims.
        bars = flat([8, 9, 10, 9, 8]) + [ohlc(5, 9, D("10.5"), 9, 9), ohlc(6, 9, 9, 9, 9)]
        result = liquidity_context(bars, ATR1, "EUR_USD", "H1")
        self.assertEqual(result["state"], "available")
        self.assertEqual(result["resistance_level"], "10.000000")
        self.assertIsNotNone(result["sweep_above"])

    def test_atr_unavailable(self):
        self.assertEqual(
            liquidity_context(flat([8, 9, 10, 9, 8]), None, "EUR_USD", "H1")["reason_code"],
            "atr_unavailable",
        )
