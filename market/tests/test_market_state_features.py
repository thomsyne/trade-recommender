"""Phase 4 slice 3 — higher-timeframe features, hand-calculated fixtures.

Pure-function coverage over crafted Bar lists (expected values computed by hand,
never from the code under test): confirmed swings and the confirmation delay,
trend classification, HH/HL sequences, ATR, rolling volatility percentile and
regime, range/equilibrium and distance, persistence, break-of-structure (close
vs wick) and change-of-character (vs pullback). Plus an end-to-end causality
test proving a swing only appears once its right-hand bars are eligible.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from market.state import features
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.state.features import (
    Bar,
    atr_feature,
    break_of_structure_feature,
    change_of_character_feature,
    confirmed_swings,
    equilibrium_feature,
    persistence_feature,
    trend_feature,
    volatility_percentile_feature,
)
from market.tests.factories import candle
from market.tests.legacy_state_evidence import store_ingestion
from market.tests.test_live_observations import make_market

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)


def D(x):
    return Decimal(str(x))


def mk(index, high, low, close, open_=None):
    return Bar(
        timestamp=BASE + timedelta(hours=index),
        open=D(open_ if open_ is not None else close),
        high=D(high),
        low=D(low),
        close=D(close),
    )


def closes_to_bars(closes, r="0"):
    """Bars whose high/low straddle the close by ``r`` (default 0, so swing
    prices equal the closes); swing highs/lows fall exactly on the local
    maxima/minima of the close path."""
    r = D(r)
    return [
        Bar(timestamp=BASE + timedelta(hours=i), open=D(c), high=D(c) + r, low=D(c) - r, close=D(c))
        for i, c in enumerate(closes)
    ]


# Uptrend: swing lows 8,9 (HL) and swing highs 12,14 (HH).
UPTREND = [10, 9, 8, 9, 10, 12, 11, 10, 9, 10, 11, 14, 13, 12]
# Downtrend: swing highs 12,11 (LH) and swing lows 8,6 (LL).
DOWNTREND = [10, 11, 12, 11, 10, 8, 9, 10, 11, 10, 9, 6, 7, 8]
# Range: swing highs 12,14 (HH) but swing lows 8,7 (LL).
RANGE = [10, 9, 8, 9, 10, 12, 11, 10, 7, 8, 9, 14, 13, 12]


class SwingTests(TestCase):
    def test_single_confirmed_swing_high_and_low(self):
        bars = [
            mk(0, 2, 1, 1.5),
            mk(1, 3, 2, 2.5),
            mk(2, 6, 5, 5.5),  # swing high (high 6 > 2,3 left and 3,2 right... )
            mk(3, 3, 2, 2.5),
            mk(4, 2, 1, 1.5),
        ]
        swings = confirmed_swings(bars)
        self.assertEqual([(s.index, s.kind) for s in swings], [(2, "high")])

    def test_confirmation_delay_last_bars_are_not_confirmed(self):
        # The peak sits at the second-to-last index, so it lacks two right bars.
        bars = closes_to_bars([1, 2, 3, 4, 5, 9, 6])
        swings = confirmed_swings(bars)
        self.assertTrue(all(s.index <= len(bars) - 1 - features.SWING_RIGHT for s in swings))
        self.assertNotIn(5, [s.index for s in swings])  # the 9 at index 5 is unconfirmed

    def test_equal_highs_do_not_confirm_a_swing(self):
        bars = closes_to_bars([1, 2, 5, 5, 1])
        # index 2 high equals index 3 high, so strict inequality fails.
        self.assertEqual([s.index for s in confirmed_swings(bars) if s.kind == "high"], [])


class TrendTests(TestCase):
    def test_uptrend(self):
        self.assertEqual(trend_feature(closes_to_bars(UPTREND))["classification"], "uptrend")

    def test_downtrend(self):
        self.assertEqual(trend_feature(closes_to_bars(DOWNTREND))["classification"], "downtrend")

    def test_range_when_highs_and_lows_disagree(self):
        self.assertEqual(trend_feature(closes_to_bars(RANGE))["classification"], "range")

    def test_insufficient_history_is_unavailable_not_range(self):
        result = trend_feature(closes_to_bars([1, 2, 3, 2, 1]))
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["reason_code"], "insufficient_history")


class AtrTests(TestCase):
    def test_atr_is_mean_of_true_ranges(self):
        # Constant 1.0 range, closes flat: every TR = 1.0, so ATR = 1.0.
        bars = [mk(i, 10.5, 9.5, 10) for i in range(20)]
        result = atr_feature(bars)
        self.assertEqual(result["atr"], "1.000000")

    def test_atr_true_range_uses_prior_close_gap(self):
        # close jumps +2 each bar; high = close+0.5, so |high - prev_close| = 2.5
        # dominates the 1.0 intrabar range -> every TR = 2.5, ATR = 2.5.
        bars = [
            mk(i, D(10 + 2 * i) + D("0.5"), D(10 + 2 * i) - D("0.5"), D(10 + 2 * i))
            for i in range(15)
        ]
        self.assertEqual(atr_feature(bars)["atr"], "2.500000")

    def test_insufficient_history(self):
        self.assertEqual(atr_feature([mk(i, 2, 1, 1.5) for i in range(10)])["state"], "unavailable")


class VolatilityPercentileTests(TestCase):
    def test_percentile_uses_only_prior_observations(self):
        # 34 flat bars (ATR climbs to a steady 1.0), then a final high-range bar
        # lifts the current ATR above every prior ATR -> percentile 100.
        bars = [mk(i, 10.5, 9.5, 10) for i in range(35)]
        bars.append(mk(35, 40, 0, 10))  # huge true range
        result = volatility_percentile_feature(bars)
        self.assertEqual(result["state"], "available")
        self.assertEqual(result["percentile"], "100.00")

    def test_min_population_enforced(self):
        bars = [mk(i, 10.5, 9.5, 10) for i in range(20)]  # too few prior ATRs
        self.assertEqual(volatility_percentile_feature(bars)["state"], "unavailable")


class EquilibriumTests(TestCase):
    def test_midpoint_and_distance(self):
        result = equilibrium_feature(closes_to_bars(UPTREND))
        # Most recent swing high 14, swing low 9 -> midpoint 11.5; last close 12.
        self.assertEqual(result["range_high"], "14.000000")
        self.assertEqual(result["range_low"], "9.000000")
        self.assertEqual(result["midpoint"], "11.500000")
        self.assertEqual(result["distance_price"], "0.500000")


class PersistenceTests(TestCase):
    def test_counts_consecutive_bars_one_side_of_equilibrium(self):
        result = persistence_feature(closes_to_bars(UPTREND))
        self.assertEqual(result["state"], "available")
        self.assertIn(result["side"], ("above", "below"))
        self.assertGreaterEqual(result["consecutive_bars"], 1)


class BreakOfStructureTests(TestCase):
    def test_close_beyond_swing_high_is_a_break(self):
        bars = closes_to_bars(UPTREND) + [mk(14, 15.5, 14.5, 15), mk(15, 16.5, 15.5, 16)]
        result = break_of_structure_feature(bars)
        self.assertTrue(result["broken"])
        self.assertEqual(result["direction"], "up")
        self.assertEqual(result["level"], "14.000000")

    def test_wick_only_is_not_a_break(self):
        # Final bar's wick pierces 14 but its close stays below.
        bars = closes_to_bars(UPTREND) + [mk(14, 15.5, 12.5, 13), mk(15, 15.9, 12.5, 13)]
        result = break_of_structure_feature(bars)
        self.assertFalse(result["broken"])

    def test_range_has_no_established_structure(self):
        result = break_of_structure_feature(closes_to_bars(RANGE))
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["reason_code"], "no_established_structure")


class ChangeOfCharacterTests(TestCase):
    def test_close_beyond_opposing_swing_is_choch(self):
        bars = closes_to_bars(UPTREND) + [mk(14, 6.5, 5.5, 6), mk(15, 5.5, 4.5, 5)]
        result = change_of_character_feature(bars)
        self.assertTrue(result["changed"])
        self.assertEqual(result["direction"], "down")

    def test_ordinary_pullback_is_not_choch(self):
        # Close pulls back but stays above the most recent swing low (9).
        bars = closes_to_bars(UPTREND) + [mk(14, 11.5, 9.5, 10), mk(15, 11.5, 9.5, 10)]
        result = change_of_character_feature(bars)
        self.assertFalse(result["changed"])


class CausalConfirmationDelayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def store(self, starts, observed_at, batch, **close):
        candles = [candle(s, **close) for s in starts]
        with patch("market.services.timezone.now", return_value=observed_at):
            return store_ingestion(
                self.source,
                self.instrument,
                "H1",
                starts[0],
                starts[-1] + timedelta(hours=1),
                candles,
                {"batch": batch, "requests": []},
            )

    def test_swing_appears_only_after_right_bars_are_eligible(self):
        # A peak candle at 12:00 needs two later completed candles before it can
        # be a confirmed swing. Store 08:00..14:00, each observed at its close.
        start = datetime(2026, 1, 5, 8, tzinfo=UTC)
        highs = [1, 2, 5, 2, 1, 1, 1]  # peak at the third candle (10:00)
        for i, h in enumerate(highs):
            s = start + timedelta(hours=i)
            self.store(
                [s],
                observed_at=s + timedelta(hours=1),
                batch=f"h{i}",
                bid_high=Decimal(f"1.10{h}0"),
                ask_high=Decimal(f"1.10{h}2"),
            )
        defn = ensure_descriptor_definition()
        peak = start + timedelta(hours=2)  # 10:00 candle is the peak

        def swings_at(cutoff):
            snap, _ = compute_market_state(self.instrument, defn, cutoff, ["H1"])
            block = snap.output_payload["granularities"]["H1"]["higher_timeframe"]
            return [s["timestamp"] for s in block["swings"].get("swings", [])]

        # One bar after the peak: not yet confirmed.
        early = swings_at(start + timedelta(hours=4))
        self.assertNotIn(peak.astimezone(UTC).isoformat(timespec="microseconds"), early)
        # Two bars after the peak: now confirmed.
        later = swings_at(start + timedelta(hours=6))
        self.assertIn(peak.astimezone(UTC).isoformat(timespec="microseconds"), later)
