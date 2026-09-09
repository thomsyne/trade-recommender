"""Phase 4 slice 6 — ORB and FVG, hand-calculated fixtures.

FVG three-candle proxy geometry (bullish/bearish/equality, middle-candle
direction and displacement, fill), and ORB from the completed first M15 candle
(range, breakout vs wick, spread-normalization) plus session UTC conversion and
the opening-interval-missing rule (the next M15 candle is never substituted).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from market.services import store_ingestion
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.state.features import Bar
from market.state.fvg import find_fvgs
from market.state.orb import opening_range
from market.state.sessions import most_recent_completed_orb_open, session_open_utc
from market.tests.factories import candle
from market.tests.test_live_observations import make_market

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
ATR1 = Decimal("1.0")
PIP = Decimal("0.0001")


def D(x):
    return Decimal(str(x))


def ohlc(i, o, h, low, c):
    return Bar(timestamp=BASE + timedelta(hours=i), open=D(o), high=D(h), low=D(low), close=D(c))


class FvgGeometryTests(TestCase):
    def test_bullish_gap(self):
        bars = [ohlc(0, 9, 10, 9, 9.5), ohlc(1, 10, 13, 10, 13), ohlc(2, 12, 14, 11, 13)]
        result = find_fvgs(bars, ATR1, PIP)
        self.assertEqual(len(result["fvgs"]), 1)
        gap = result["fvgs"][0]
        self.assertEqual(gap["direction"], "bullish")
        self.assertEqual((gap["gap_low"], gap["gap_high"]), ("10.000000", "11.000000"))
        self.assertEqual(gap["gap_pips"], "10000.0")
        self.assertEqual(gap["spread_normalized"]["state"], "unavailable")

    def test_bearish_gap(self):
        bars = [ohlc(0, 14, 15, 13, 14), ohlc(1, 13, 13, 10, 10), ohlc(2, 11, 12, 10, 11)]
        result = find_fvgs(bars, ATR1, PIP)
        self.assertEqual(result["fvgs"][0]["direction"], "bearish")
        self.assertEqual(
            (result["fvgs"][0]["gap_low"], result["fvgs"][0]["gap_high"]),
            ("12.000000", "13.000000"),
        )

    def test_equality_is_no_gap(self):
        bars = [ohlc(0, 9, 11, 9, 10), ohlc(1, 10, 13, 10, 13), ohlc(2, 12, 14, 11, 13)]
        self.assertEqual(find_fvgs(bars, ATR1, PIP)["fvgs"], [])  # c1.high 11 not < c3.low 11

    def test_middle_candle_wrong_direction(self):
        bars = [ohlc(0, 9, 10, 9, 9.5), ohlc(1, 13, 13, 10, 10), ohlc(2, 12, 14, 11, 13)]
        self.assertEqual(find_fvgs(bars, ATR1, PIP)["fvgs"], [])  # c2 closes down

    def test_insufficient_displacement(self):
        bars = [ohlc(0, 9, 10, 9, 9.5), ohlc(1, 10, 11, 10, D("10.5")), ohlc(2, 12, 14, 11, 13)]
        self.assertEqual(find_fvgs(bars, ATR1, PIP)["fvgs"], [])  # body 0.5 < 1.0*ATR

    def test_partial_and_full_fill(self):
        base = [ohlc(0, 9, 10, 9, 9.5), ohlc(1, 10, 13, 10, 13), ohlc(2, 12, 14, 11, 13)]
        half = base + [ohlc(3, 11, 11, D("10.5"), 11)]  # dips to 10.5 into [10,11]
        self.assertEqual(find_fvgs(half, ATR1, PIP)["fvgs"][0]["partial_fill_pct"], "50.0")
        full = base + [ohlc(3, 11, 11, 9, D("9.5"))]  # closes below gap_low 10
        self.assertTrue(find_fvgs(full, ATR1, PIP)["fvgs"][0]["full_fill"])


class SessionConversionTests(TestCase):
    def test_new_york_and_london_open_convert_to_utc(self):
        ny_open, _, _ = session_open_utc(datetime(2026, 1, 6).date(), "new_york")
        self.assertEqual(ny_open, datetime(2026, 1, 6, 13, 0, tzinfo=UTC))  # 08:00 EST
        ldn_open, _, _ = session_open_utc(datetime(2026, 1, 6).date(), "london")
        self.assertEqual(ldn_open, datetime(2026, 1, 6, 8, 0, tzinfo=UTC))  # 08:00 GMT

    def test_most_recent_open_requires_completion(self):
        # Cutoff before 08:15 NY falls back to the previous weekday's session.
        before = datetime(2026, 1, 6, 13, 10, tzinfo=UTC)  # 08:10 EST, not yet complete
        utc_open, local_open, _ = most_recent_completed_orb_open(before, "new_york")
        self.assertEqual(local_open.date(), datetime(2026, 1, 5).date())  # Monday


class OpeningRangeTests(TestCase):
    def test_breakout_up_and_spread_normalization(self):
        opening = ohlc(0, 10, D("10.4"), 10, D("10.2"))  # ORH 10.4, ORL 10
        session = [ohlc(1, D("10.2"), D("10.6"), D("10.2"), D("10.5"))]  # closes above ORH
        result = opening_range(
            opening,
            session,
            ATR1,
            Decimal("0.1"),
            session_name="new_york",
            local_open=datetime(2026, 1, 5, 8, tzinfo=UTC),
            tzinfo=UTC,
        )
        self.assertEqual(result["orh"], "10.400000")
        self.assertEqual(result["breakout"], "up")
        self.assertEqual(result["range_spread"], "4.000000")  # range 0.4 / spread 0.1

    def test_wick_only_breach_is_distinct(self):
        opening = ohlc(0, 10, D("10.4"), 10, D("10.2"))
        session = [
            ohlc(1, D("10.2"), D("10.9"), D("10.2"), D("10.3"))
        ]  # wick over ORH, closes inside
        result = opening_range(
            opening,
            session,
            ATR1,
            Decimal("0.1"),
            session_name="new_york",
            local_open=datetime(2026, 1, 5, 8, tzinfo=UTC),
            tzinfo=UTC,
        )
        self.assertIsNone(result["breakout"])
        self.assertTrue(result["wick_only_breach"])


class OrbEndToEndTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def store_m15(self, starts, observed_at, batch):
        candles = [candle(s) for s in starts]
        with patch("market.services.timezone.now", return_value=observed_at):
            return store_ingestion(
                self.source,
                self.instrument,
                "M15",
                starts[0],
                starts[-1] + timedelta(minutes=15),
                candles,
                {"batch": batch, "requests": []},
            )

    def test_ny_orb_available_london_opening_missing(self):
        # New York 08:00 EST on 2026-01-06 = 13:00 UTC; store the opening M15 there.
        ny_open = datetime(2026, 1, 6, 13, 0, tzinfo=UTC)
        starts = [ny_open + timedelta(minutes=15 * i) for i in range(3)]
        for i, s in enumerate(starts):
            self.store_m15([s], observed_at=s + timedelta(minutes=15), batch=f"m{i}")
        defn = ensure_descriptor_definition()
        cutoff = ny_open + timedelta(hours=1)
        snap, _ = compute_market_state(self.instrument, defn, cutoff, ["M15"])
        orb = snap.output_payload["opening_range"]
        self.assertEqual(orb["new_york"]["state"], "available")
        self.assertEqual(
            orb["new_york"]["opening_candle"], ny_open.isoformat(timespec="microseconds")
        )
        # London 08:00 GMT = 08:00 UTC had no stored opening candle -> not substituted.
        self.assertEqual(orb["london"]["reason_code"], "opening_interval_missing")
