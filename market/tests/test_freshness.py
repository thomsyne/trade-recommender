"""Phase 1.5 — candle freshness that separates interval start, completion, retrieval and polling.

The calendar anchors sit in September 2025 rather than a future September: the
lineage trigger added in migration 0029 refuses an observation of an interval
that has not completed yet, so a fixture dated ahead of the clock would be
storing evidence no provider could have produced. The scenario is unchanged --
every date moved back exactly 52 weeks, preserving weekday and daylight saving.
"""

from datetime import UTC, datetime, timedelta

from django.test import TestCase

from market.freshness import latest_expected_completion, series_freshness
from market.models import Candle, Instrument, SourceRegistry
from market.services import store_ingestion
from market.tests.factories import candle
from operations.models import ScheduledJob


class FreshnessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        cls.source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="test only",
        )

    def store(self, granularity, timestamps):
        step = {
            "H1": timedelta(hours=1),
            "H4": timedelta(hours=4),
            "D": timedelta(days=1),
            "W": timedelta(weeks=1),
        }[granularity]
        run = store_ingestion(
            self.source,
            self.instrument,
            granularity,
            timestamps[0],
            timestamps[-1] + step,
            [candle(value) for value in timestamps],
            {"batch": f"{granularity}-{timestamps[0].isoformat()}", "requests": []},
        )
        return run

    def job(self, granularity, interval, next_run_at):
        return ScheduledJob.objects.create(
            name=f"OANDA USD_CAD {granularity}",
            task_name="market.ingest_oanda",
            parameters={"instrument": "USD_CAD", "granularity": granularity},
            interval_seconds=interval,
            next_run_at=next_run_at,
        )

    def test_expected_completion_respects_weekend_and_new_york_close(self):
        saturday = datetime(2025, 9, 13, 12, tzinfo=UTC)
        self.assertEqual(
            latest_expected_completion(saturday, "D"), datetime(2025, 9, 12, 21, tzinfo=UTC)
        )
        self.assertEqual(
            latest_expected_completion(saturday, "W"), datetime(2025, 9, 12, 21, tzinfo=UTC)
        )
        self.assertEqual(
            latest_expected_completion(saturday, "H1"), datetime(2025, 9, 12, 21, tzinfo=UTC)
        )
        self.assertEqual(
            latest_expected_completion(saturday, "H4"), datetime(2025, 9, 12, 21, tzinfo=UTC)
        )
        wednesday = datetime(2025, 9, 10, 15, 30, tzinfo=UTC)
        self.assertEqual(
            latest_expected_completion(wednesday, "H1"), datetime(2025, 9, 10, 15, tzinfo=UTC)
        )
        self.assertEqual(
            latest_expected_completion(wednesday, "H4"), datetime(2025, 9, 10, 13, tzinfo=UTC)
        )
        self.assertEqual(
            latest_expected_completion(wednesday, "D"), datetime(2025, 9, 9, 21, tzinfo=UTC)
        )

    def test_weekend_daily_candle_is_fresh_and_next_candle_is_sunday_open(self):
        thursday_start = datetime(2025, 9, 11, 21, tzinfo=UTC)
        self.store("D", [thursday_start])
        job = self.job("D", 86_400, datetime(2025, 9, 13, 22, tzinfo=UTC))

        row = series_freshness(
            self.instrument, "D", now=datetime(2025, 9, 13, 12, tzinfo=UTC), job=job
        )

        self.assertEqual(row.latest_interval_start, thursday_start)
        self.assertEqual(row.latest_completion, datetime(2025, 9, 12, 21, tzinfo=UTC))
        self.assertEqual(row.next_interval_start, datetime(2025, 9, 14, 21, tzinfo=UTC))
        self.assertEqual(row.next_completion, datetime(2025, 9, 15, 21, tzinfo=UTC))
        self.assertEqual(row.next_poll_at, job.next_run_at)
        self.assertTrue(row.fresh)
        self.assertEqual(row.state, "fresh")

    def test_weekly_freshness_follows_friday_close_and_polling_interval(self):
        week_start = datetime(2025, 9, 5, 21, tzinfo=UTC)
        self.store("W", [week_start])
        job = self.job("W", 604_800, datetime(2025, 9, 16, tzinfo=UTC))

        fresh = series_freshness(
            self.instrument, "W", now=datetime(2025, 9, 13, tzinfo=UTC), job=job
        )
        tolerated = series_freshness(
            self.instrument, "W", now=datetime(2025, 9, 21, tzinfo=UTC), job=job
        )
        stale = series_freshness(
            self.instrument, "W", now=datetime(2025, 9, 27, 12, tzinfo=UTC), job=job
        )

        self.assertEqual(fresh.latest_completion, datetime(2025, 9, 12, 21, tzinfo=UTC))
        self.assertTrue(fresh.fresh)
        self.assertTrue(tolerated.fresh)
        self.assertIn("collection interval has not elapsed", tolerated.reason)
        self.assertFalse(stale.fresh)
        self.assertEqual(stale.state, "stale")

    def test_interval_start_completion_and_retrieval_are_reported_separately(self):
        start = datetime(2025, 9, 10, 13, tzinfo=UTC)
        self.store("H1", [start])
        stored = Candle.objects.get()

        row = series_freshness(self.instrument, "H1", now=datetime(2025, 9, 10, 14, 30, tzinfo=UTC))

        self.assertEqual(row.latest_interval_start, start)
        self.assertEqual(row.latest_completion, start + timedelta(hours=1))
        self.assertEqual(row.retrieved_at, stored.observed_at)
        self.assertIsNotNone(stored.observed_at)
        self.assertNotEqual(row.retrieved_at, row.latest_interval_start)
        self.assertNotEqual(row.retrieved_at, row.latest_completion)
        self.assertNotEqual(row.latest_interval_start, row.latest_completion)
        self.assertTrue(row.fresh)
        self.assertIsNone(row.next_poll_at)

    def test_weekday_hourly_series_goes_stale_after_interval_and_grace(self):
        self.store("H1", [datetime(2025, 9, 10, 12, tzinfo=UTC)])
        job = self.job("H1", 3_600, datetime(2025, 9, 10, 16, tzinfo=UTC))

        # Stored 12:00 candle completes 13:00; the next candle completes 14:00 and the
        # hourly job has until 15:15 (interval plus grace) to store it.
        within = series_freshness(
            self.instrument, "H1", now=datetime(2025, 9, 10, 14, 50, tzinfo=UTC), job=job
        )
        stale = series_freshness(
            self.instrument, "H1", now=datetime(2025, 9, 10, 15, 30, tzinfo=UTC), job=job
        )

        self.assertTrue(within.fresh)
        self.assertFalse(stale.fresh)
        self.assertIn("not stored after one polling interval", stale.reason)

    def test_missing_series_is_reported_as_no_data(self):
        row = series_freshness(self.instrument, "H4", now=datetime(2025, 9, 10, 15, tzinfo=UTC))
        self.assertEqual(row.state, "missing")
        self.assertEqual(row.label, "NO DATA")
