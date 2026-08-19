from datetime import UTC, datetime, timedelta, timezone

from django.test import SimpleTestCase

from market.quality import validate_candles
from market.tests.factories import candle


class CandleQualityTests(SimpleTestCase):
    def test_valid_complete_bid_ask_candles_pass(self):
        start = datetime(2026, 1, 5, tzinfo=UTC)
        candles = [candle(start + timedelta(hours=4 * index)) for index in range(4)]

        self.assertEqual(validate_candles(candles, "H4"), [])

    def test_detects_duplicate_impossible_crossed_and_incomplete_data(self):
        timestamp = datetime(2026, 1, 5, tzinfo=UTC)
        candles = [
            candle(timestamp),
            candle(
                timestamp,
                complete=False,
                bid_low=candle().bid_high,
                bid_close=candle().ask_close + 1,
            ),
        ]

        codes = {issue.code for issue in validate_candles(candles, "H4")}

        self.assertTrue(
            {
                "duplicate_timestamp",
                "non_monotonic_timestamp",
                "incomplete_candle",
                "impossible_ohlc",
                "crossed_bid_ask",
            }.issubset(codes)
        )

    def test_detects_non_utc_and_unexpected_gap_but_allows_weekend_gap(self):
        monday = datetime(2026, 1, 5, tzinfo=timezone(timedelta(hours=-5)))
        issues = validate_candles([candle(monday), candle(monday + timedelta(hours=12))], "H4")
        self.assertIn("timestamp_not_utc", {issue.code for issue in issues})
        self.assertIn("unexpected_gap", {issue.code for issue in issues})

        friday = datetime(2026, 1, 9, 20, tzinfo=UTC)
        sunday = datetime(2026, 1, 11, 22, tzinfo=UTC)
        weekend = validate_candles([candle(friday), candle(sunday)], "H4")
        self.assertNotIn("unexpected_gap", {issue.code for issue in weekend})

        thursday = datetime(2026, 1, 8, 22, tzinfo=UTC)
        daily_weekend = validate_candles([candle(thursday), candle(sunday)], "D")
        self.assertNotIn("unexpected_gap", {issue.code for issue in daily_weekend})

        daily_non_weekend = validate_candles(
            [candle(thursday - timedelta(days=1)), candle(sunday)], "D"
        )
        self.assertIn("unexpected_gap", {issue.code for issue in daily_non_weekend})
