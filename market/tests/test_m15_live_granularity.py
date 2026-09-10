"""Phase 4 prerequisite — M15 live granularity contract and calendar.

These tests exercise the M15 slice in isolation: alignment on the quarter-hour
grid, absolute 15-minute completion (including across New York DST), canonical
flooring, the FX weekend successor, the deliberate separation of the supported
ledger set from the canonical *scheduled* set (so the Phase 2 job inventory is
unchanged), observation persistence and append-only revision, and the provider
request path with a synthetic client (no real provider call).

Expected values are hand-derived from the New York FX calendar, not imported
from the implementation under test.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase

from market.live_acquisition import (
    LIVE_INTERVALS,
    SUPPORTED_LIVE_INTERVALS,
    canonical_live_start,
    complete_live_intervals,
)
from market.models import Candle, CandleObservation, IngestionRun
from market.quality import (
    LIVE_GRANULARITIES,
    SCHEDULED_LIVE_GRANULARITIES,
    live_interval_is_aligned,
    registered_successor,
)
from market.services import live_candle_completion, store_ingestion
from market.tests.factories import candle
from market.tests.test_live_observations import make_market

# A quarter past 12:00 UTC on a Monday: an aligned M15 start on an open session.
MON_1200 = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


def m15_series(start, n):
    """``n`` consecutive completed M15 candles from ``start`` (15-minute steps)."""
    return [candle(start + timedelta(minutes=15 * i)) for i in range(n)]


class M15ConstantsTests(TestCase):
    def test_supported_set_includes_m15_scheduled_set_does_not(self):
        self.assertIn("M15", LIVE_GRANULARITIES)
        self.assertNotIn("M15", SCHEDULED_LIVE_GRANULARITIES)

    def test_scheduled_inventory_intervals_are_unchanged(self):
        # LIVE_INTERVALS drives the canonical schedule inventory; it must stay
        # exactly H1/H4/D/W so Phase 4 adds no schedule expectation.
        self.assertEqual(set(LIVE_INTERVALS), {"H1", "H4", "D", "W"})
        self.assertEqual(
            LIVE_INTERVALS,
            {"H1": 3600, "H4": 14400, "D": 86400, "W": 604800},
        )

    def test_supported_intervals_add_m15(self):
        self.assertEqual(SUPPORTED_LIVE_INTERVALS["M15"], 900)
        self.assertEqual(set(SUPPORTED_LIVE_INTERVALS), {"M15", "H1", "H4", "D", "W"})


class M15AlignmentTests(TestCase):
    def test_quarter_hours_are_aligned(self):
        for minute in (0, 15, 30, 45):
            ts = MON_1200.replace(minute=minute)
            self.assertTrue(live_interval_is_aligned(ts, "M15"), minute)

    def test_off_grid_minutes_and_subminute_are_not_aligned(self):
        for minute in (1, 5, 7, 14, 16, 29, 31, 44, 59):
            ts = MON_1200.replace(minute=minute)
            self.assertFalse(live_interval_is_aligned(ts, "M15"), minute)
        self.assertFalse(live_interval_is_aligned(MON_1200.replace(second=1), "M15"))
        self.assertFalse(live_interval_is_aligned(MON_1200.replace(microsecond=1), "M15"))

    def test_hourly_alignment_is_unchanged_by_m15(self):
        self.assertTrue(live_interval_is_aligned(MON_1200, "H1"))
        self.assertFalse(live_interval_is_aligned(MON_1200.replace(minute=15), "H1"))
        self.assertFalse(live_interval_is_aligned(MON_1200.replace(minute=30), "H4"))

    def test_unsupported_subhour_granularity_is_never_aligned(self):
        self.assertFalse(live_interval_is_aligned(MON_1200, "M1"))
        self.assertFalse(live_interval_is_aligned(MON_1200, "M5"))


class M15CompletionTests(TestCase):
    def test_completion_is_absolute_fifteen_minutes(self):
        self.assertEqual(live_candle_completion(MON_1200, "M15"), MON_1200 + timedelta(minutes=15))

    def test_completion_across_spring_forward_is_absolute(self):
        # 2026-03-08 02:00 America/New_York springs forward; an M15 interval that
        # spans the transition is still exactly 15 real minutes long.
        start = datetime(2026, 3, 8, 6, 45, tzinfo=UTC)  # 01:45 EST
        self.assertTrue(live_interval_is_aligned(start, "M15"))
        self.assertEqual(
            live_candle_completion(start, "M15"), datetime(2026, 3, 8, 7, 0, tzinfo=UTC)
        )


class M15CanonicalStartTests(TestCase):
    def test_floors_to_quarter_hour(self):
        for minute, expected in ((7, 0), (14, 0), (23, 15), (30, 30), (44, 30), (59, 45)):
            got = canonical_live_start(MON_1200.replace(minute=minute, second=40), "M15")
            self.assertEqual(got, MON_1200.replace(minute=expected))

    def test_aligned_start_is_returned_unchanged(self):
        aligned = MON_1200.replace(minute=45)
        self.assertEqual(canonical_live_start(aligned, "M15"), aligned)

    def test_requires_aware_timestamp(self):
        with self.assertRaises(ValueError):
            canonical_live_start(datetime(2026, 1, 5, 12, 7), "M15")


class M15WeekendTests(TestCase):
    def test_successor_jumps_the_fx_weekend(self):
        # Last M15 before the Friday 17:00 New York close opens at 16:45; the next
        # market-active interval is the Sunday 17:00 reopen.
        fri_1645 = datetime(2026, 1, 9, 21, 45, tzinfo=UTC)  # 16:45 EST Friday
        self.assertTrue(live_interval_is_aligned(fri_1645, "M15"))
        successor = registered_successor(fri_1645, "M15")
        local = successor.astimezone(ZoneInfo("America/New_York"))
        self.assertEqual((local.weekday(), local.hour, local.minute), (6, 17, 0))

    def test_within_session_successor_is_next_quarter_hour(self):
        self.assertEqual(registered_successor(MON_1200, "M15"), MON_1200 + timedelta(minutes=15))


class M15CoverageTests(TestCase):
    def test_complete_live_intervals_are_quarter_hourly(self):
        start = MON_1200
        end = MON_1200 + timedelta(hours=1)
        expected = tuple(start + timedelta(minutes=15 * i) for i in range(4))
        self.assertEqual(complete_live_intervals(start, end, "M15"), expected)

    def test_coverage_beginning_in_weekend_closure_skips_to_reopen(self):
        # Sunday 15:00 EST is still closed; the FX week reopens at 17:00 New York
        # (22:00 UTC in January). Coverage must omit the closed quarter-hours.
        start = datetime(2026, 1, 11, 20, 0, tzinfo=UTC)  # Sun 15:00 EST, closed
        reopen = datetime(2026, 1, 11, 22, 0, tzinfo=UTC)  # Sun 17:00 EST, open
        end = reopen + timedelta(minutes=30)
        self.assertEqual(
            complete_live_intervals(start, end, "M15"),
            (reopen, reopen + timedelta(minutes=15)),
        )


class M15PersistenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def store(self, candles, batch):
        start = candles[0].timestamp
        end = candles[-1].timestamp + timedelta(minutes=15)
        return store_ingestion(
            self.source,
            self.instrument,
            "M15",
            start,
            end,
            candles,
            {"batch": batch, "requests": []},
        )

    def test_m15_candles_persist_with_observation_lineage(self):
        run = self.store(m15_series(MON_1200, 4), "first")
        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        rows = Candle.objects.filter(instrument=self.instrument, granularity="M15")
        self.assertEqual(rows.count(), 4)
        for row in rows:
            head = row.authoritative_observation()
            self.assertEqual(head.revision, 1)
            self.assertEqual(head.interval_end, row.timestamp + timedelta(minutes=15))

    def test_m15_revision_is_append_only(self):
        self.store(m15_series(MON_1200, 1), "first")
        row = Candle.objects.get(instrument=self.instrument, granularity="M15")
        # A later provider view with a different (still OHLC-valid) close appends
        # revision 2 without rewriting the frozen row or revision 1.
        revised = candle(MON_1200, bid_close=Decimal("1.1015"), ask_close=Decimal("1.1017"))
        self.store([revised], "revised")
        observations = CandleObservation.objects.filter(candle=row).order_by("revision")
        self.assertEqual([o.revision for o in observations], [1, 2])
        self.assertEqual(observations[1].kind, CandleObservation.Kind.REVISION)
        # Revision 1 content is preserved (append-only), not rewritten.
        self.assertEqual(observations[0].bid_close, Decimal("1.1010"))
        row.refresh_from_db()
        self.assertEqual(row.bid_close, Decimal("1.1010"))


class M15ProviderPathTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def test_ingest_task_accepts_m15_with_synthetic_provider(self):
        from market.models import Instrument, SourceRegistry
        from operations.tasks import ingest_oanda

        Instrument.objects.filter(code=self.instrument.code).update(ingestion_enabled=True)
        SourceRegistry.objects.filter(name="OANDA v20").update(enabled=True)
        candles = m15_series(MON_1200, 4)
        manifest = {"batch": "m15", "requests": []}
        with patch("operations.tasks.OandaClient") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.fetch_candles.return_value = (candles, manifest)
            run = ingest_oanda(
                {
                    "instrument": self.instrument.code,
                    "granularity": "M15",
                    "from": MON_1200.isoformat(),
                    "to": (MON_1200 + timedelta(hours=1)).isoformat(),
                }
            )
        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        # The provider was asked for M15 candles; no real network client was used.
        self.assertEqual(client.fetch_candles.call_args.args[1], "M15")
        self.assertEqual(
            Candle.objects.filter(instrument=self.instrument, granularity="M15").count(), 4
        )

    def test_cli_does_not_expose_m15(self):
        # M15 is a programmatic capability only; the operational CLI restricts its
        # granularity choices to the scheduled set, so M15 is not activatable there.
        from django.core.management import CommandError, load_command_class

        command = load_command_class("operations", "ingest_oanda")
        parser = command.create_parser("manage.py", "ingest_oanda")
        with self.assertRaises((CommandError, SystemExit)):
            parser.parse_args([self.instrument.code, "M15"])
