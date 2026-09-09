"""Phase 4 slice 4 — support/resistance and structure, hand-calculated fixtures.

Pure-function coverage: volatility-normalized zone clustering, zone identities
that depend only on the rounded boundaries (never on row id or order), the
distinct-test count that treats consecutive candles inside a zone as one
approach, equal/clustered levels, displacement supply/demand proxy candidates
(with and without continuation), and consolidation/breakout. Plus an end-to-end
test that the structure block and prior-day extreme appear in a snapshot.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from market.services import store_ingestion
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.state.features import Bar
from market.state.structure import (
    _zone_id,
    _zone_test_count,
    consolidation_state,
    displacement_candidates,
    equal_levels,
    prior_period_extreme,
    support_resistance_zones,
)
from market.tests.factories import candle
from market.tests.test_live_observations import make_market

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
ATR1 = Decimal("1.0")


def D(x):
    return Decimal(str(x))


def flat_bars(closes):
    """Bars with high == low == close, so confirmed-swing prices equal closes."""
    return [
        Bar(timestamp=BASE + timedelta(hours=i), open=D(c), high=D(c), low=D(c), close=D(c))
        for i, c in enumerate(closes)
    ]


def ohlc(index, o, h, low, c):
    return Bar(
        timestamp=BASE + timedelta(hours=index), open=D(o), high=D(h), low=D(low), close=D(c)
    )


# Swing highs at 10, 10.2, 15; swing lows at 8, 8.
ZONE_CLOSES = [8, 9, 10, 9, 8, 9, 10.2, 9, 8, 13, 15, 13, 11]


class ZoneTests(TestCase):
    def test_zones_cluster_within_c_atr(self):
        result = support_resistance_zones(flat_bars(ZONE_CLOSES), ATR1)
        self.assertEqual(result["state"], "available")
        ranges = [(z["range_low"], z["range_high"]) for z in result["zones"]]
        # margin = 0.25*1.0 = 0.25: 10 and 10.2 merge; 8,8 merge; 15 alone.
        self.assertIn(("10.000000", "10.200000"), ranges)
        self.assertIn(("8.000000", "8.000000"), ranges)
        self.assertIn(("15.000000", "15.000000"), ranges)
        merged = next(z for z in result["zones"] if z["range_low"] == "10.000000")
        self.assertEqual(merged["member_count"], 2)

    def test_zone_id_depends_only_on_boundaries(self):
        self.assertEqual(_zone_id(D(10), D("10.2")), _zone_id(D("10.0"), D("10.20")))
        self.assertNotEqual(_zone_id(D(10), D("10.2")), _zone_id(D(10), D("10.3")))
        self.assertEqual(len(_zone_id(D(10), D("10.2"))), 64)

    def test_distinct_tests_count_separate_approaches(self):
        # Touch 10 twice with a far excursion (to 5) between; consecutive inside once.
        bars = flat_bars([10, 10, 5, 10, 10])
        self.assertEqual(_zone_test_count(bars, D(10), D(10), Decimal("0.25")), 2)

    def test_shallow_exit_does_not_recount(self):
        # Leaving by less than the margin then returning is still one test.
        bars = flat_bars([10, Decimal("10.1"), 10])
        self.assertEqual(_zone_test_count(bars, D(10), D(10), Decimal("0.25")), 1)

    def test_atr_unavailable(self):
        self.assertEqual(
            support_resistance_zones(flat_bars(ZONE_CLOSES), None)["reason_code"], "atr_unavailable"
        )


class EqualLevelTests(TestCase):
    def test_equal_highs_within_tolerance(self):
        # Swing highs 10.0 and 10.05 are within 0.1*ATR; a third at 15 is not.
        closes = [8, 9, 10, 9, 8, 9, Decimal("10.05"), 9, 8, 13, 15, 13, 11]
        result = equal_levels(flat_bars(closes), ATR1)
        self.assertEqual(len(result["equal_highs"]), 1)
        self.assertEqual(result["equal_highs"][0]["count"], 2)


class DisplacementTests(TestCase):
    def test_bullish_displacement_is_a_demand_candidate(self):
        bars = [ohlc(0, 10, 12, 10, 12), ohlc(1, 12, 13, 12, 13)]  # body 2 >= 1.5, continues up
        result = displacement_candidates(bars, ATR1)
        self.assertEqual(result["candidates"][0]["kind"], "demand_candidate")
        self.assertEqual(result["candidates"][0]["origin_low"], "10.000000")
        self.assertEqual(result["candidates"][0]["origin_high"], "12.000000")

    def test_bearish_displacement_is_a_supply_candidate(self):
        bars = [ohlc(0, 12, 12, 10, 10), ohlc(1, 10, 10, 9, 9)]  # body 2 down, continues down
        result = displacement_candidates(bars, ATR1)
        self.assertEqual(result["candidates"][0]["kind"], "supply_candidate")

    def test_no_continuation_is_not_a_candidate(self):
        bars = [ohlc(0, 10, 12, 10, 12), ohlc(1, 12, 12, 11, 11)]  # displaces up, then reverses
        self.assertEqual(displacement_candidates(bars, ATR1)["candidates"], [])

    def test_small_body_is_not_displacement(self):
        bars = [ohlc(0, 10, 11, 10, 11), ohlc(1, 11, 12, 11, 12)]  # body 1 < 1.5
        self.assertEqual(displacement_candidates(bars, ATR1)["candidates"], [])


class ConsolidationTests(TestCase):
    def test_breakout_above_a_tight_range(self):
        bars = flat_bars([10] * 20 + [12])  # 20 flat bars (range 0), then a close above
        result = consolidation_state(bars, ATR1)
        self.assertFalse(result["in_consolidation"])
        self.assertEqual(result["breakout"], "up")

    def test_wide_base_is_not_consolidation(self):
        bars = flat_bars(list(range(20)) + [21])  # range 19 >> 1.5*ATR
        self.assertFalse(consolidation_state(bars, ATR1)["in_consolidation"])


class PriorExtremeTests(TestCase):
    def test_extreme_of_period_bars(self):
        result = prior_period_extreme([ohlc(0, 10, 15, 8, 12)])
        self.assertEqual(result["high"], "15.000000")
        self.assertEqual(result["low"], "8.000000")


class StructureEndToEndTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def store_daily(self, sessions, observed_at, batch):
        candles = [candle(s) for s in sessions]
        with patch("market.services.timezone.now", return_value=observed_at):
            return store_ingestion(
                self.source,
                self.instrument,
                "D",
                sessions[0],
                sessions[-1] + timedelta(days=1),
                candles,
                {"batch": batch, "requests": []},
            )

    def test_structure_block_and_prior_day_appear(self):
        from market.tests.factories import daily_sessions

        sessions = daily_sessions(3, before=datetime(2026, 2, 2, tzinfo=UTC))
        self.store_daily(sessions, observed_at=sessions[-1] + timedelta(days=1), batch="d")
        defn = ensure_descriptor_definition()
        cutoff = sessions[-1] + timedelta(days=1)
        snap, _ = compute_market_state(self.instrument, defn, cutoff, ["D"])
        block = snap.output_payload["granularities"]["D"]
        self.assertIn("structure", block)
        self.assertIn("support_resistance_zones", block["structure"])
        prior_day = snap.output_payload["prior_extremes"]["prior_day"]
        self.assertEqual(prior_day["state"], "available")
