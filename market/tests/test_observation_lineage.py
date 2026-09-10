"""Phase 1.4 — provenance enforcement on the live observation ledger.

Every test here drives raw SQL against the database as the application role, so
it measures what migration 0029's lineage trigger actually enforces rather than
what ``market.services`` happens to write. The honest-ingestion tests assert the
opposite direction: legitimate provider behaviour must still be accepted.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import import_module

from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from forecasts.models import EvidenceSnapshot
from market.models import (
    Candle,
    CandleObservation,
    IngestionRun,
    Instrument,
    SourceRegistry,
)
from market.quality import live_interval_is_aligned
from market.services import candle_content_sha256, live_candle_completion, store_ingestion
from market.tests.factories import candle

# Canonical New York session anchors (17:00 America/New_York).
SUNDAY_SESSION = datetime(2026, 1, 4, 22, tzinfo=UTC)  # Sunday 17:00 EST -> daily start
FRIDAY_WEEK = datetime(2026, 1, 2, 22, tzinfo=UTC)  # Friday 17:00 EST -> weekly start
MONDAY_HOUR = datetime(2026, 1, 5, 8, tzinfo=UTC)  # Monday 03:00 EST -> hourly start
# Daylight-saving anchors: the spring-forward Sunday session and the weekly
# candle that spans the autumn transition (7 wall-clock days, 169 real hours).
DST_SPRING_SESSION = datetime(2026, 3, 8, 21, tzinfo=UTC)  # Sunday 17:00 EDT
DST_AUTUMN_WEEK = datetime(2025, 10, 31, 21, tzinfo=UTC)  # Friday 17:00 EDT

CONTENT_COLUMNS = (
    "complete",
    "volume",
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
)


class ObservationLineageEnforcementTests(TransactionTestCase):
    """The lineage trigger must refuse provenance the repository cannot honour."""

    def setUp(self):
        self.instrument, _ = Instrument.objects.get_or_create(
            code="USD_CAD",
            defaults={"base_currency": "USD", "quote_currency": "CAD", "display_order": 1},
        )
        self.source, _ = SourceRegistry.objects.get_or_create(
            name="OANDA v20",
            defaults={
                "tier": "established",
                "base_url": "https://developer.oanda.com",
                "acquisition_method": "v20 REST API",
                "retention_policy": "test only",
            },
        )
        self.manifest_seed = 0

    # ---- fixtures ---------------------------------------------------------

    def make_run(self, granularity, requested_from, requested_to, status=None):
        self.manifest_seed += 1
        run = IngestionRun.objects.create(
            source=self.source,
            instrument=self.instrument,
            granularity=granularity,
            requested_from=requested_from,
            requested_to=requested_to,
            parameters={"probe": self.manifest_seed},
            request_manifest_hash=f"{self.manifest_seed:064d}",
        )
        if status is not None:
            IngestionRun.objects.filter(pk=run.pk).update(status=status)
            run.refresh_from_db()
        return run

    def make_candle(
        self, timestamp, granularity, *, legacy=False, run=None, content_sha256=None, **changes
    ):
        """Create one live candle row directly, bypassing ingestion validation."""
        item = candle(timestamp, **changes)
        end = live_candle_completion(timestamp, granularity)
        run = run or self.make_run(granularity, timestamp, end)
        digest = content_sha256 or candle_content_sha256(self.instrument.code, granularity, item)
        row = Candle.objects.create(
            instrument=self.instrument,
            ingestion_run=run,
            dataset_version=None,
            granularity=granularity,
            content_sha256=None if legacy else digest,
            observed_at=None if legacy else timezone.now(),
            provenance=(Candle.Provenance.LEGACY_UNKNOWN if legacy else Candle.Provenance.OBSERVED),
            **item.__dict__,
        )
        return row, run, item

    def observation_values(self, row, run, item, **overrides):
        granularity = overrides.get("granularity", row.granularity)
        timestamp = overrides.get("timestamp", row.timestamp)
        values = {
            "instrument_id": row.instrument_id,
            "granularity": granularity,
            "timestamp": timestamp,
            "interval_end": overrides.get(
                "interval_end",
                live_candle_completion(timestamp, granularity)
                if granularity in {"M15", "H1", "H4", "D", "W"}
                else None,
            ),
            "complete": item.complete,
            "volume": item.volume,
            "bid_open": item.bid_open,
            "bid_high": item.bid_high,
            "bid_low": item.bid_low,
            "bid_close": item.bid_close,
            "ask_open": item.ask_open,
            "ask_high": item.ask_high,
            "ask_low": item.ask_low,
            "ask_close": item.ask_close,
            "source_id": self.source.pk,
            "ingestion_run_id": run.pk,
            "candle_id": row.pk,
            "kind": CandleObservation.Kind.INITIAL,
            "revision": 1,
            "supersedes_id": None,
            "differing_fields": json.dumps([]),
            "observed_at": timezone.now(),
            "created_at": timezone.now(),
        }
        values.update(overrides)
        values["content_sha256"] = overrides.get(
            "content_sha256",
            candle_content_sha256(
                self.instrument.code,
                values["granularity"],
                candle(
                    values["timestamp"],
                    **{column: values[column] for column in CONTENT_COLUMNS},
                ),
            ),
        )
        return values

    def insert_observation(self, values):
        columns = list(values)
        sql = "INSERT INTO market_candleobservation ({}) VALUES ({})".format(
            ", ".join(columns), ", ".join(["%s"] * len(columns))
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, [values[column] for column in columns])

    def assert_insert_rejected(self, values, expected=None):
        with self.assertRaises(DatabaseError) as caught, transaction.atomic():
            self.insert_observation(values)
        if expected:
            self.assertIn(expected, str(caught.exception))

    def assert_insert_accepted(self, values):
        with transaction.atomic():
            self.insert_observation(values)

    # ---- granularity and session semantics --------------------------------

    def test_daily_observation_beginning_at_noon_is_rejected(self):
        noon = datetime(2026, 1, 5, 12, tzinfo=UTC)
        row, run, item = self.make_candle(noon, "D")

        self.assert_insert_rejected(self.observation_values(row, run, item))

    def test_weekly_observation_with_a_midweek_start_is_rejected(self):
        wednesday = datetime(2026, 1, 7, 22, tzinfo=UTC)  # Wednesday 17:00 NY
        row, run, item = self.make_candle(wednesday, "W")

        self.assert_insert_rejected(self.observation_values(row, run, item))

    def test_daily_observation_on_a_friday_session_start_is_rejected(self):
        friday = datetime(2026, 1, 2, 22, tzinfo=UTC)  # Friday 17:00 NY opens the week, not a day
        row, run, item = self.make_candle(friday, "D")

        self.assert_insert_rejected(self.observation_values(row, run, item))

    def test_hourly_observation_off_the_hour_is_rejected(self):
        ragged = datetime(2026, 1, 5, 8, 30, tzinfo=UTC)
        row, run, item = self.make_candle(ragged, "H1")

        self.assert_insert_rejected(self.observation_values(row, run, item))

    def test_four_hour_observation_off_the_session_grid_is_rejected(self):
        # H4 candles start at 01/05/09/13/17/21 New York; 08:00 NY is not a start.
        off_grid = datetime(2026, 1, 5, 13, tzinfo=UTC)  # 08:00 EST
        row, run, item = self.make_candle(off_grid, "H4")

        self.assert_insert_rejected(self.observation_values(row, run, item))

    def test_canonical_session_starts_are_accepted_including_dst(self):
        for timestamp, granularity in (
            (MONDAY_HOUR, "H1"),
            (datetime(2026, 1, 5, 6, tzinfo=UTC), "H4"),  # 01:00 EST
            (SUNDAY_SESSION, "D"),
            (FRIDAY_WEEK, "W"),
            (DST_SPRING_SESSION, "D"),
            (DST_AUTUMN_WEEK, "W"),
        ):
            with self.subTest(granularity=granularity, timestamp=timestamp):
                self.assertTrue(live_interval_is_aligned(timestamp, granularity))
                row, run, item = self.make_candle(timestamp, granularity)
                self.assert_insert_accepted(self.observation_values(row, run, item))

    def test_unsupported_granularity_is_rejected(self):
        # M15 is now a supported live granularity (Phase 4); M1 remains
        # unsupported, so it still exercises the unaligned-granularity rejection.
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")

        self.assert_insert_rejected(
            self.observation_values(
                row,
                run,
                item,
                granularity="M1",
                interval_end=MONDAY_HOUR + timedelta(minutes=1),
            )
        )

    # ---- ingestion-run provenance -----------------------------------------

    def finish_run(self, run, status):
        IngestionRun.objects.filter(pk=run.pk).update(status=status, finished_at=timezone.now())

    def test_an_invented_ingestion_run_status_cannot_be_stored_at_all(self):
        """Defence in depth: the run table itself refuses statuses off the whitelist."""
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")

        with self.assertRaises(DatabaseError), transaction.atomic():
            IngestionRun.objects.filter(pk=run.pk).update(
                status="not-a-status", finished_at=timezone.now()
            )

    def test_observation_from_an_already_terminal_run_is_rejected(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")
        self.finish_run(run, IngestionRun.Status.SUCCEEDED)

        self.assert_insert_rejected(self.observation_values(row, run, item))

    def test_observation_from_a_failed_run_is_rejected(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")
        self.finish_run(run, IngestionRun.Status.FAILED)

        self.assert_insert_rejected(self.observation_values(row, run, item))

    def test_observation_from_a_running_run_is_accepted(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")

        self.assert_insert_accepted(self.observation_values(row, run, item))

    # ---- chronology -------------------------------------------------------

    def test_observation_dated_in_the_future_is_rejected(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")

        self.assert_insert_rejected(
            self.observation_values(row, run, item, observed_at=timezone.now() + timedelta(hours=6))
        )

    def test_observation_of_an_interval_that_has_not_completed_is_rejected(self):
        # A provider cannot have observed a candle before its interval closed.
        start = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
        end = live_candle_completion(start, "H1")
        run = self.make_run("H1", start, end + timedelta(hours=1))
        row, run, item = self.make_candle(start, "H1", run=run)

        self.assert_insert_rejected(self.observation_values(row, run, item))

    # ---- kind derivation ---------------------------------------------------

    def test_legacy_root_conflict_on_an_unreferenced_candle_is_rejected(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1", legacy=True)
        revised = candle(MONDAY_HOUR, volume=item.volume + 5)

        self.assert_insert_rejected(
            self.observation_values(
                row,
                run,
                revised,
                kind=CandleObservation.Kind.CONFLICT,
                differing_fields=json.dumps(["volume"]),
            )
        )

    def test_legacy_root_revision_on_an_unreferenced_candle_is_accepted(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1", legacy=True)
        revised = candle(MONDAY_HOUR, volume=item.volume + 5)

        self.assert_insert_accepted(
            self.observation_values(
                row,
                run,
                revised,
                kind=CandleObservation.Kind.REVISION,
                differing_fields=json.dumps(["volume"]),
            )
        )

    # ---- frozen candle content ---------------------------------------------

    def test_forged_candle_is_refused_at_the_database_boundary(self):
        """A live observed candle must attest its own content when inserted.

        Raw SQL reaches past save() and ORM validation, so the rejection has to
        come from the database, and it has to happen with no observation in
        sight: nothing downstream may ever be able to bind the row.
        """
        other = candle(MONDAY_HOUR, volume=999)
        forged = candle_content_sha256(self.instrument.code, "H1", other)
        item = candle(MONDAY_HOUR)
        run = self.make_run("H1", MONDAY_HOUR, live_candle_completion(MONDAY_HOUR, "H1"))
        columns = (
            "instrument_id, ingestion_run_id, granularity, timestamp, complete, volume, "
            "bid_open, bid_high, bid_low, bid_close, ask_open, ask_high, ask_low, ask_close, "
            "provenance, content_sha256, observed_at"
        )
        with self.assertRaises(DatabaseError) as caught, transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO market_candle ({columns}) VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        self.instrument.pk,
                        run.pk,
                        "H1",
                        MONDAY_HOUR,
                        item.complete,
                        item.volume,
                        item.bid_open,
                        item.bid_high,
                        item.bid_low,
                        item.bid_close,
                        item.ask_open,
                        item.ask_high,
                        item.ask_low,
                        item.ask_close,
                        Candle.Provenance.OBSERVED,
                        forged,
                        timezone.now(),
                    ],
                )
        self.assertIn("does not recompute", str(caught.exception))
        self.assertFalse(Candle.objects.filter(timestamp=MONDAY_HOUR).exists())

    def test_forged_candle_with_a_matching_forged_root_observation_is_refused(self):
        """Forging both halves consistently still cannot get past the boundary."""
        other = candle(MONDAY_HOUR, volume=999)
        forged = candle_content_sha256(self.instrument.code, "H1", other)

        with self.assertRaises(DatabaseError), transaction.atomic():
            self.make_candle(MONDAY_HOUR, "H1", content_sha256=forged)

    def test_honest_observed_candle_is_accepted(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")

        self.assertEqual(row.content_sha256, candle_content_sha256("USD_CAD", "H1", item))
        self.assert_insert_accepted(self.observation_values(row, run, item))

    def test_legacy_unattested_candle_is_still_permitted(self):
        """Legacy rows carry no hash and keep their honest unknown provenance."""
        row, _, _ = self.make_candle(MONDAY_HOUR, "H1", legacy=True)

        self.assertIsNone(row.content_sha256)
        self.assertEqual(row.provenance, Candle.Provenance.LEGACY_UNKNOWN)

    def test_fixture_candle_is_not_held_to_observed_attestation(self):
        item = candle(MONDAY_HOUR)
        run = self.make_run("H1", MONDAY_HOUR, live_candle_completion(MONDAY_HOUR, "H1"))
        row = Candle.objects.create(
            instrument=self.instrument,
            ingestion_run=run,
            dataset_version=None,
            granularity="H1",
            content_sha256=None,
            observed_at=None,
            provenance=Candle.Provenance.FIXTURE,
            **item.__dict__,
        )

        self.assertEqual(row.provenance, Candle.Provenance.FIXTURE)

    def test_root_observation_must_attest_the_candle_it_froze(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")
        divergent = candle(MONDAY_HOUR, volume=item.volume + 1)

        self.assert_insert_rejected(
            self.observation_values(row, run, divergent, volume=divergent.volume)
        )

    def test_root_observation_matching_its_candle_is_accepted(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")

        self.assert_insert_accepted(self.observation_values(row, run, item))

    # ---- differing_fields --------------------------------------------------

    def test_initial_observation_with_null_differing_fields_is_rejected(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")

        self.assert_insert_rejected(self.observation_values(row, run, item, differing_fields=None))

    def test_initial_observation_with_a_non_array_differing_fields_is_rejected(self):
        row, run, item = self.make_candle(MONDAY_HOUR, "H1")

        self.assert_insert_rejected(
            self.observation_values(row, run, item, differing_fields=json.dumps({}))
        )


class ObservationLineageHonestIngestionTests(TransactionTestCase):
    """Legitimate provider behaviour must pass every lineage check."""

    def setUp(self):
        self.instrument, _ = Instrument.objects.get_or_create(
            code="USD_CAD",
            defaults={"base_currency": "USD", "quote_currency": "CAD", "display_order": 1},
        )
        self.source, _ = SourceRegistry.objects.get_or_create(
            name="OANDA v20",
            defaults={
                "tier": "established",
                "base_url": "https://developer.oanda.com",
                "acquisition_method": "v20 REST API",
                "retention_policy": "test only",
            },
        )

    def ingest(self, items, batch, granularity="H1"):
        start = items[0].timestamp
        end = live_candle_completion(items[-1].timestamp, granularity)
        return store_ingestion(
            self.source,
            self.instrument,
            granularity,
            start,
            end,
            items,
            {"batch": batch, "requests": []},
        )

    def test_revision_changing_volume_and_a_price_together_is_accepted(self):
        """``differing_fields`` is sorted in Python; the SQL mirror must agree."""
        first = candle(MONDAY_HOUR)
        self.ingest([first], "first")

        revised = candle(MONDAY_HOUR, volume=first.volume + 7, ask_close=Decimal("1.1015"))
        run = self.ingest([revised], "revised")

        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        head = Candle.objects.get(granularity="H1").authoritative_observation()
        self.assertEqual(head.kind, CandleObservation.Kind.REVISION)
        self.assertEqual(head.revision, 2)
        self.assertEqual(head.differing_fields, ["ask_close", "volume"])

    def test_revision_changing_complete_and_a_price_together_is_accepted(self):
        first = candle(MONDAY_HOUR)
        self.ingest([first], "first")

        revised = candle(MONDAY_HOUR, bid_low=Decimal("1.0500"))
        run = self.ingest([revised], "revised")

        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        head = Candle.objects.get(granularity="H1").authoritative_observation()
        self.assertEqual(head.differing_fields, ["bid_low"])

    def test_daily_and_weekly_sessions_ingest_at_canonical_starts(self):
        daily = self.ingest([candle(SUNDAY_SESSION)], "daily", granularity="D")
        weekly = self.ingest([candle(FRIDAY_WEEK)], "weekly", granularity="W")

        self.assertEqual(daily.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(weekly.status, IngestionRun.Status.SUCCEEDED)
        daily_row = Candle.objects.get(granularity="D")
        self.assertEqual(
            daily_row.authoritative_observation().interval_end,
            datetime(2026, 1, 5, 22, tzinfo=UTC),
        )
        weekly_row = Candle.objects.get(granularity="W")
        self.assertEqual(
            weekly_row.authoritative_observation().interval_end,
            datetime(2026, 1, 9, 22, tzinfo=UTC),
        )


class SqlPythonParityTests(TransactionTestCase):
    """The SQL mirrors in migration 0029 must not drift from the Python rules.

    These are the checks that keep "one authoritative semantic definition" true
    in practice: every rule the trigger enforces in SQL is compared against the
    Python function it mirrors, over inputs chosen to break naive
    implementations (both daylight-saving transitions, signed zero, sub-unit
    magnitudes, the column's precision bounds and microsecond timestamps).
    """

    def setUp(self):
        super().setUp()
        # A preceding historical-migration test may have reversed the market graph
        # (restoring the pre-M15 SQL mirrors) and been unable to re-apply forward
        # through the documented migration-0027 guard. Re-install the current M15
        # mirrors directly so this parity check always compares against the schema
        # under test, without weakening any assertion.
        import importlib

        module = importlib.import_module("market.migrations.0031_m15_live_granularity")
        with connection.cursor() as cursor:
            cursor.execute(module.ALIGNMENT_WITH_M15)
            cursor.execute(module.COMPLETION_WITH_M15)

    def sql(self, statement, params):
        with connection.cursor() as cursor:
            cursor.execute(statement, params)
            return cursor.fetchone()[0]

    def alignment_matrix(self):
        """Every hour of both daylight-saving weeks, plus each session boundary."""
        for anchor in (
            datetime(2026, 3, 5, tzinfo=UTC),  # spring forward on 2026-03-08
            datetime(2025, 10, 29, tzinfo=UTC),  # fall back on 2025-11-02
            datetime(2026, 1, 1, tzinfo=UTC),
        ):
            for hours in range(0, 24 * 9):
                # Every quarter-hour so the M15 grid ({0,15,30,45}) is exercised
                # against the SQL mirror, alongside the session boundaries.
                for minutes in (0, 15, 30, 45):
                    yield anchor + timedelta(hours=hours, minutes=minutes)

    def test_interval_alignment_matches_python_across_dst(self):
        checked = 0
        for timestamp in self.alignment_matrix():
            for granularity in ("H1", "H4", "D", "W", "M15"):
                expected = live_interval_is_aligned(timestamp, granularity)
                actual = self.sql(
                    "SELECT market_candleobservation_live_interval_is_aligned(%s, %s)",
                    [timestamp, granularity],
                )
                self.assertEqual(
                    actual,
                    expected,
                    f"{granularity} at {timestamp.isoformat()}: SQL {actual} != Python {expected}",
                )
                checked += 1
        self.assertGreater(checked, 3000)

    def test_completion_matches_python_across_dst(self):
        for timestamp in self.alignment_matrix():
            for granularity in ("M15", "H1", "H4", "D", "W"):
                if not live_interval_is_aligned(timestamp, granularity):
                    continue
                self.assertEqual(
                    self.sql(
                        "SELECT market_candleobservation_live_completion(%s, %s)",
                        [timestamp, granularity],
                    ),
                    live_candle_completion(timestamp, granularity),
                    f"{granularity} completion at {timestamp.isoformat()}",
                )

    def test_content_hash_matches_python_at_bounds_and_precision_edges(self):
        instrument, _ = Instrument.objects.get_or_create(
            code="USD_CAD",
            defaults={"base_currency": "USD", "quote_currency": "CAD", "display_order": 1},
        )
        prices = (
            Decimal("0.000000"),
            Decimal("-0.000000"),  # signed zero: numeric normalises, Python must too
            Decimal("0.650000"),  # sub-unit magnitude: no leading zero from to_char
            Decimal("-0.650000"),
            Decimal("0.000001"),  # smallest representable step
            Decimal("999999.999999"),  # max_digits=12, decimal_places=6
            Decimal("-999999.999999"),
            Decimal("1.100000"),
        )
        timestamps = (
            MONDAY_HOUR,
            # Whole, non-zero seconds: date_part('microseconds') is the seconds
            # field times a million, so this is where a naive zero-test makes
            # SQL emit '.000000' that Python's isoformat omits.
            MONDAY_HOUR + timedelta(seconds=5),
            MONDAY_HOUR + timedelta(seconds=59),
            MONDAY_HOUR + timedelta(microseconds=1),
            MONDAY_HOUR + timedelta(microseconds=100000),
            MONDAY_HOUR + timedelta(microseconds=999999),
            DST_SPRING_SESSION,
            DST_AUTUMN_WEEK,
        )
        for price in prices:
            for timestamp in timestamps:
                for volume, complete in ((0, True), (2147483647, False)):
                    item = candle(
                        timestamp,
                        complete=complete,
                        volume=volume,
                        **{
                            column: price
                            for column in CONTENT_COLUMNS
                            if column not in ("complete", "volume")
                        },
                    )
                    expected = candle_content_sha256(instrument.code, "H1", item)
                    actual = self.sql(
                        """
                        SELECT market_candleobservation_content_sha256(
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            instrument.code,
                            "H1",
                            timestamp,
                            complete,
                            volume,
                            *[price] * 8,
                        ],
                    )
                    self.assertEqual(
                        actual,
                        expected,
                        f"price={price} ts={timestamp.isoformat()} volume={volume}",
                    )

    def test_helpers_ignore_a_hijacked_search_path(self):
        """A shadowing schema on search_path must not change any helper's answer."""
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS lineage_hijack")
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION lineage_hijack.digest(bytea, text)
                RETURNS bytea LANGUAGE sql IMMUTABLE AS $$ SELECT '\\x00'::bytea $$
                """
            )
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION lineage_hijack.market_candleobservation_canonical_price(
                    numeric) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT 'hijacked' $$
                """
            )
            cursor.execute("SET search_path = lineage_hijack, public, pg_catalog")
            hijacked = self.sql(
                """
                SELECT market_candleobservation_content_sha256(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                ["USD_CAD", "H1", MONDAY_HOUR, True, 100, *[Decimal("1.100000")] * 8],
            )
            aligned = self.sql(
                "SELECT market_candleobservation_live_interval_is_aligned(%s, %s)",
                [SUNDAY_SESSION, "D"],
            )
            cursor.execute("SET search_path = public")
            cursor.execute("DROP SCHEMA lineage_hijack CASCADE")

        item = candle(
            MONDAY_HOUR,
            **{
                column: Decimal("1.100000")
                for column in CONTENT_COLUMNS
                if column not in ("complete", "volume")
            },
        )
        self.assertEqual(hijacked, candle_content_sha256("USD_CAD", "H1", item))
        self.assertTrue(aligned)


class HistoricalKindEvaluationTests(TransactionTestCase):
    """Migration 0029 must not re-adjudicate history it cannot reconstruct.

    Only one referencing table records an insertion time (market_candleconflict
    uses auto_now_add); every other carries a business timestamp. In particular
    Recommendation.generated_at is fixed before provider.generate() is called
    and the row is inserted only after it returns, so a revision recorded
    legitimately during that window has an observed_at later than a
    generated_at whose row did not yet exist. Reading those columns as
    visibility would condemn correct history, so a revision is never
    reclassified; only provable contradictions are refused.
    """

    def setUp(self):
        self.instrument, _ = Instrument.objects.get_or_create(
            code="USD_CAD",
            defaults={"base_currency": "USD", "quote_currency": "CAD", "display_order": 1},
        )
        self.source, _ = SourceRegistry.objects.get_or_create(
            name="OANDA v20",
            defaults={
                "tier": "established",
                "base_url": "https://developer.oanda.com",
                "acquisition_method": "v20 REST API",
                "retention_policy": "test only",
            },
        )

    def ingest(self, items, batch):
        return store_ingestion(
            self.source,
            self.instrument,
            "H1",
            items[0].timestamp,
            live_candle_completion(items[-1].timestamp, "H1"),
            items,
            {"batch": batch, "requests": []},
        )

    def sql(self, statement, params=()):
        with connection.cursor() as cursor:
            cursor.execute(statement, params)
            return cursor.fetchone()[0]

    def preflight_offences(self):
        lineage = import_module("market.migrations.0029_candle_observation_lineage")
        return {message: self.sql(statement) for statement, message in lineage.POST_RENUMBER_CHECKS}

    def reference(self, row, captured_at):
        from market.models import TechnicalSnapshot

        snapshot = TechnicalSnapshot.objects.filter(instrument=self.instrument).first()
        return EvidenceSnapshot.objects.create(
            instrument=self.instrument,
            anchor_candle=row,
            technical_snapshot=snapshot,
            market_data_cutoff=captured_at,
            captured_at=captured_at,
            payload={"test": "reference"},
            sha256=f"{EvidenceSnapshot.objects.count():064d}",
        )

    def revised_candle(self):
        self.ingest([candle(MONDAY_HOUR)], "first")
        self.ingest([candle(MONDAY_HOUR, volume=250)], "revised")
        row = Candle.objects.get(granularity="H1")
        return row, row.authoritative_observation()

    def test_reference_recorded_after_the_revision_leaves_it_a_revision(self):
        row, revision = self.revised_candle()
        self.assertEqual(revision.kind, CandleObservation.Kind.REVISION)

        self.reference(row, revision.observed_at + timedelta(hours=1))

        self.assertTrue(
            self.sql("SELECT market_candleobservation_candle_is_referenced(%s)", [row.pk])
        )
        for message, offences in self.preflight_offences().items():
            self.assertEqual(offences, 0, f"0029 would have refused: {message}")

    def test_reference_whose_business_time_precedes_the_revision_is_not_visibility(self):
        """The provider-generation overlap: a business timestamp is not an insert."""
        row, revision = self.revised_candle()

        # Exactly the shape Recommendation.generated_at produces: a reference
        # whose recorded time precedes the revision, inserted afterwards.
        self.reference(row, revision.observed_at - timedelta(minutes=5))

        for message, offences in self.preflight_offences().items():
            self.assertEqual(offences, 0, f"0029 would have refused: {message}")

    def test_reference_at_exactly_the_observation_instant_is_not_visibility(self):
        row, revision = self.revised_candle()

        self.reference(row, revision.observed_at)

        for message, offences in self.preflight_offences().items():
            self.assertEqual(offences, 0, f"0029 would have refused: {message}")

    def test_a_recorded_conflict_is_preserved_even_with_no_reference_today(self):
        """Absence of a reference now does not prove absence when it was written.

        Reference tables can be truncated, so a candle nothing cites today may
        well have been cited at the time. The migration keeps the recorded kind
        rather than rewriting history it cannot reconstruct.
        """
        row, revision = self.revised_candle()
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE market_candleobservation DISABLE TRIGGER "
                "market_candleobservation_append_only"
            )
            cursor.execute(
                "UPDATE market_candleobservation SET kind = 'conflict' WHERE id = %s",
                [revision.pk],
            )
            cursor.execute(
                "ALTER TABLE market_candleobservation ENABLE TRIGGER "
                "market_candleobservation_append_only"
            )
        self.assertFalse(
            self.sql("SELECT market_candleobservation_candle_is_referenced(%s)", [row.pk])
        )

        for message, offences in self.preflight_offences().items():
            self.assertEqual(offences, 0, f"0029 would have refused: {message}")

        revision.refresh_from_db()
        self.assertEqual(revision.kind, CandleObservation.Kind.CONFLICT)

    def test_a_conflict_whose_content_agrees_with_its_candle_is_still_refused(self):
        """Content-based contradiction is provable and stays enforced.

        A conflict means the view departed from the frozen evidence, so a row
        whose own content still hashes to that evidence cannot be one, whatever
        the reference history was.
        """
        self.ingest([candle(MONDAY_HOUR)], "first")
        row = Candle.objects.get(granularity="H1")
        initial = row.authoritative_observation()
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE market_candleobservation DISABLE TRIGGER "
                "market_candleobservation_append_only"
            )
            cursor.execute(
                "UPDATE market_candleobservation SET kind = 'conflict' WHERE id = %s",
                [initial.pk],
            )
            cursor.execute(
                "ALTER TABLE market_candleobservation ENABLE TRIGGER "
                "market_candleobservation_append_only"
            )

        offences = self.preflight_offences()
        self.assertEqual(
            offences["refuses conflict rows whose content agrees with their frozen candle"], 1
        )

    def test_legacy_root_revision_is_never_re_adjudicated(self):
        run = IngestionRun.objects.create(
            source=self.source,
            instrument=self.instrument,
            granularity="H1",
            requested_from=MONDAY_HOUR,
            requested_to=live_candle_completion(MONDAY_HOUR, "H1"),
            parameters={"legacy": True},
            request_manifest_hash=f"{7:064d}",
        )
        legacy = Candle.objects.create(
            instrument=self.instrument,
            ingestion_run=run,
            dataset_version=None,
            granularity="H1",
            content_sha256=None,
            observed_at=None,
            provenance=Candle.Provenance.LEGACY_UNKNOWN,
            **candle(MONDAY_HOUR).__dict__,
        )
        self.ingest([candle(MONDAY_HOUR, volume=250)], "legacy-adoption")
        head = legacy.authoritative_observation()
        self.assertEqual(head.kind, CandleObservation.Kind.REVISION)

        self.reference(legacy, head.observed_at - timedelta(minutes=5))

        for message, offences in self.preflight_offences().items():
            self.assertEqual(offences, 0, f"0029 would have refused: {message}")

    def test_every_reference_table_is_covered_by_the_referenced_predicate(self):
        """All seven relations that can bind a candle are consulted."""
        body = self.sql(
            "SELECT prosrc FROM pg_proc WHERE proname = "
            "'market_candleobservation_candle_is_referenced'"
        )
        for relation in (
            "market_candleconflict",
            "forecasts_evidencesnapshot",
            "forecasts_forecastresolution",
            "forecasts_recommendation",
            "forecasts_recommendationresolution",
            "forecasts_papertradeentry",
            "forecasts_papertraderesult",
        ):
            self.assertIn(relation, body)
