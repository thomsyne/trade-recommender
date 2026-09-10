"""Asymmetric clocks and DST contracts; expectations are hand-derived."""

from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from market.availability import (
    first_known_at,
    live_candle_completion,
    observation_available_at,
)
from market.quality import registered_candle_completion


class AvailabilityTests(SimpleTestCase):
    def test_recording_is_a_distinct_later_boundary_and_equality_is_available(self):
        end = datetime(2026, 1, 5, 9, tzinfo=UTC)
        observed = end + timedelta(minutes=2)
        recorded = end + timedelta(minutes=17)
        self.assertEqual(first_known_at(observed, recorded), recorded)
        self.assertEqual(first_known_at(recorded, observed), recorded)
        self.assertEqual(first_known_at(observed), observed)
        available = observation_available_at(end, observed, recorded)
        self.assertEqual(available, recorded)
        self.assertFalse(available <= recorded - timedelta(microseconds=1))
        self.assertTrue(available <= recorded)
        self.assertEqual(observation_available_at(recorded, end, observed), recorded)

    def test_fall_back_does_not_merge_live_hours_or_reinterpret_legacy_hours(self):
        first = datetime(2026, 11, 1, 5, tzinfo=UTC)
        second = datetime(2026, 11, 1, 6, tzinfo=UTC)
        self.assertEqual(live_candle_completion(first, "H1"), second)
        self.assertEqual(live_candle_completion(second, "H1"), datetime(2026, 11, 1, 7, tzinfo=UTC))
        self.assertEqual(
            registered_candle_completion(first, "H1"), datetime(2026, 11, 1, 7, tzinfo=UTC)
        )

    def test_weekly_close_preserves_wall_clock_across_spring_dst(self):
        start = datetime(2026, 3, 6, 22, tzinfo=UTC)
        self.assertEqual(live_candle_completion(start, "W"), datetime(2026, 3, 13, 21, tzinfo=UTC))
