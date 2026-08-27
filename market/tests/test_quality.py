from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from market.quality import expected_candle_timestamps, validate_candles
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

    def test_one_missing_interval_is_an_unexpected_gap(self):
        start = datetime(2026, 1, 5, tzinfo=UTC)
        issues = validate_candles([candle(start), candle(start + timedelta(hours=2))], "H1")
        self.assertIn("unexpected_gap", {issue.code for issue in issues})

    def test_daily_and_weekly_new_york_alignment_accepts_dst_boundaries(self):
        new_york = ZoneInfo("America/New_York")
        daily = [
            candle(datetime(2026, 3, day, 17, tzinfo=new_york).astimezone(UTC)) for day in (5, 8)
        ]
        spring_weeks = [
            candle(datetime(2026, 3, day, 17, tzinfo=new_york).astimezone(UTC)) for day in (6, 13)
        ]
        fall_weeks = [
            candle(datetime(2026, month, day, 17, tzinfo=new_york).astimezone(UTC))
            for month, day in ((10, 30), (11, 6))
        ]
        for granularity, candles in (
            ("D", daily),
            ("W", spring_weeks),
            ("W", fall_weeks),
        ):
            with self.subTest(granularity=granularity, candles=candles):
                self.assertEqual(
                    validate_candles(candles, granularity, require_registered_alignment=True),
                    [],
                )

    def test_required_daily_and_weekly_ranges_preserve_new_york_dst_alignment(self):
        new_york = ZoneInfo("America/New_York")
        daily_start = datetime(2026, 3, 5, 17, tzinfo=new_york).astimezone(UTC)
        daily_end = datetime(2026, 3, 9, 17, tzinfo=new_york).astimezone(UTC)
        weekly_start = datetime(2026, 3, 6, 17, tzinfo=new_york).astimezone(UTC)
        weekly_end = datetime(2026, 3, 13, 17, tzinfo=new_york).astimezone(UTC)

        self.assertEqual(
            expected_candle_timestamps(daily_start, daily_end, "D"),
            (
                daily_start,
                datetime(2026, 3, 8, 17, tzinfo=new_york).astimezone(UTC),
            ),
        )
        self.assertEqual(
            expected_candle_timestamps(weekly_start, weekly_end, "W"),
            (weekly_start,),
        )
