from datetime import UTC, datetime

from django.test import SimpleTestCase

from forecasts.costs import financing_days_between


class FinancingCalendarTests(SimpleTestCase):
    def test_wednesday_rollover_counts_three_financing_days(self):
        start = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
        end = datetime(2026, 8, 19, 23, 0, tzinfo=UTC)

        self.assertEqual(financing_days_between(start, end), 3)

    def test_weekend_has_no_separate_rollover_charge(self):
        start = datetime(2026, 8, 21, 22, 0, tzinfo=UTC)
        end = datetime(2026, 8, 23, 22, 0, tzinfo=UTC)

        self.assertEqual(financing_days_between(start, end), 0)

    def test_nonpositive_holding_window_has_no_financing_days(self):
        instant = datetime(2026, 8, 19, 21, 0, tzinfo=UTC)

        self.assertEqual(financing_days_between(instant, instant), 0)
