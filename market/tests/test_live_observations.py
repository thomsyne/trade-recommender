"""Phase 1.4 — explicit live-candle observation identity and protection."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase

from market.models import (
    AuditEvent,
    Candle,
    CandleObservation,
    IngestionRun,
    Instrument,
    SourceRegistry,
    TechnicalSnapshot,
)
from market.quality import registered_candle_completion
from market.services import (
    calculate_and_store_snapshot,
    candle_content_sha256,
    live_candle_completion,
    store_ingestion,
    technical_source_set_sha256,
)
from market.tests.factories import candle

START = datetime(2026, 1, 5, 8, tzinfo=UTC)


def make_market(code="USD_CAD", order=1):
    instrument, _ = Instrument.objects.get_or_create(
        code=code,
        defaults={"base_currency": code[:3], "quote_currency": code[4:], "display_order": order},
    )
    source, _ = SourceRegistry.objects.get_or_create(
        name="OANDA v20",
        defaults={
            "tier": "established",
            "base_url": "https://developer.oanda.com",
            "acquisition_method": "v20 REST API",
            "retention_policy": "test only",
        },
    )
    return instrument, source


def ingest(source, instrument, candles, batch, granularity="H1", start=None, end=None):
    step = {"H1": timedelta(hours=1), "H4": timedelta(hours=4), "D": timedelta(days=1)}[granularity]
    start = start or candles[0].timestamp
    end = end or candles[-1].timestamp + step
    return store_ingestion(
        source,
        instrument,
        granularity,
        start,
        end,
        candles,
        {"batch": batch, "requests": []},
    )


class LiveObservationIdentityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def series(self, count=3, **changes):
        return [candle(START + timedelta(hours=index), **changes) for index in range(count)]

    def test_first_insertion_records_initial_observations_with_identity(self):
        run = ingest(self.source, self.instrument, self.series(), "first")

        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(run.stored_count, 3)
        rows = list(Candle.objects.order_by("timestamp"))
        self.assertEqual(len(rows), 3)
        for row, item in zip(rows, self.series(), strict=True):
            self.assertEqual(row.provenance, Candle.Provenance.OBSERVED)
            self.assertEqual(row.content_sha256, candle_content_sha256("USD_CAD", "H1", item))
            self.assertIsNotNone(row.observed_at)
            observation = row.authoritative_observation()
            self.assertEqual(observation.kind, CandleObservation.Kind.INITIAL)
            self.assertEqual(observation.revision, 1)
            self.assertIsNone(observation.supersedes)
            self.assertEqual(observation.content_sha256, row.content_sha256)
            self.assertEqual(observation.interval_end, row.timestamp + timedelta(hours=1))
            self.assertEqual(observation.source, self.source)
            self.assertEqual(observation.ingestion_run, run)
        audit = AuditEvent.objects.get(event_type="market.ingestion_succeeded")
        self.assertEqual(audit.payload["observations"], {"initial": 3})

    def test_exact_retry_is_idempotent(self):
        ingest(self.source, self.instrument, self.series(), "first")

        retry = ingest(self.source, self.instrument, self.series(), "retry")

        self.assertEqual(retry.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(retry.stored_count, 0)
        self.assertEqual(Candle.objects.count(), 3)
        self.assertEqual(CandleObservation.objects.count(), 3)
        audit = AuditEvent.objects.get(subject_id=str(retry.pk))
        self.assertEqual(audit.payload["observations"], {"duplicate": 3})

    def test_incomplete_observation_is_invalid_and_complete_arrival_is_initial(self):
        rejected = ingest(self.source, self.instrument, self.series(1, complete=False), "bad")
        self.assertEqual(rejected.status, IngestionRun.Status.FAILED)
        self.assertEqual(Candle.objects.count(), 0)
        self.assertEqual(CandleObservation.objects.count(), 0)

        accepted = ingest(self.source, self.instrument, self.series(1), "good")

        self.assertEqual(accepted.stored_count, 1)
        self.assertEqual(CandleObservation.objects.get().kind, CandleObservation.Kind.INITIAL)

    def test_complete_then_changed_complete_records_revision_without_rewriting_row(self):
        original = self.series(1)[0]
        ingest(self.source, self.instrument, [original], "first")
        frozen = Candle.objects.get()
        changed = candle(original.timestamp, bid_close=original.bid_close + Decimal("0.0001"))

        run = ingest(self.source, self.instrument, [changed], "revised")

        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(run.stored_count, 0)
        frozen.refresh_from_db()
        self.assertEqual(frozen.bid_close, original.bid_close)
        self.assertEqual(frozen.content_sha256, candle_content_sha256("USD_CAD", "H1", original))
        observations = list(frozen.observations.order_by("revision"))
        self.assertEqual([item.revision for item in observations], [1, 2])
        revision = observations[1]
        self.assertEqual(revision.kind, CandleObservation.Kind.REVISION)
        self.assertEqual(revision.supersedes, observations[0])
        self.assertEqual(revision.differing_fields, ["bid_close"])
        self.assertEqual(revision.bid_close, changed.bid_close)
        self.assertEqual(revision.content_sha256, candle_content_sha256("USD_CAD", "H1", changed))
        self.assertEqual(frozen.authoritative_observation(), revision)
        audit = AuditEvent.objects.get(
            subject_id=str(run.pk), event_type="market.ingestion_succeeded"
        )
        self.assertEqual(audit.payload["observations"], {"revision": 1})
        self.assertFalse(
            AuditEvent.objects.filter(event_type="market.live_candle_conflict").exists()
        )

    def test_bid_only_ask_only_and_high_low_close_revisions_are_distinct(self):
        original = self.series(1)[0]
        ingest(self.source, self.instrument, [original], "first")
        bid_only = candle(original.timestamp, bid_low=original.bid_low - Decimal("0.0003"))
        ask_only = candle(original.timestamp, ask_high=original.ask_high + Decimal("0.0003"))
        hlc = candle(
            original.timestamp,
            bid_high=original.bid_high + Decimal("0.0005"),
            bid_low=original.bid_low - Decimal("0.0005"),
            bid_close=original.bid_close + Decimal("0.0002"),
            ask_high=original.ask_high + Decimal("0.0005"),
            ask_low=original.ask_low - Decimal("0.0005"),
            ask_close=original.ask_close + Decimal("0.0002"),
        )

        for batch, item in (("bid", bid_only), ("ask", ask_only), ("hlc", hlc)):
            ingest(self.source, self.instrument, [item], batch)

        observations = list(CandleObservation.objects.order_by("revision"))
        self.assertEqual([item.revision for item in observations], [1, 2, 3, 4])
        self.assertEqual(observations[1].differing_fields, ["bid_low"])
        self.assertEqual(observations[2].differing_fields, ["ask_high"])
        self.assertEqual(
            observations[3].differing_fields,
            ["ask_close", "ask_high", "ask_low", "bid_close", "bid_high", "bid_low"],
        )
        self.assertEqual(observations[2].supersedes, observations[1])
        self.assertEqual(observations[3].supersedes, observations[2])
        self.assertEqual(Candle.objects.count(), 1)
        self.assertEqual(Candle.objects.get().bid_low, original.bid_low)

    def assert_ledger_chain(self, row, expected_volumes):
        """Dense revisions, an unbroken ``supersedes`` chain, latest row authoritative."""
        observations = list(row.observations.order_by("revision"))
        self.assertEqual(
            [item.revision for item in observations], list(range(1, len(observations) + 1))
        )
        self.assertEqual([item.volume for item in observations], expected_volumes)
        self.assertIsNone(observations[0].supersedes)
        for previous, observation in zip(observations, observations[1:], strict=False):
            self.assertEqual(observation.supersedes, previous)
        self.assertEqual(row.authoritative_observation(), observations[-1])
        return observations

    def ledger_rows(self):
        return list(
            CandleObservation.objects.order_by("id").values_list(
                "id", "revision", "content_sha256", "supersedes_id", "kind", "volume"
            )
        )

    def observations_recorded_by(self, run):
        return AuditEvent.objects.get(
            subject_id=str(run.pk), event_type="market.ingestion_succeeded"
        ).payload["observations"]

    def test_out_of_order_and_repeated_revisions_are_idempotent(self):
        original = self.series(1)[0]
        revision_a = candle(original.timestamp, volume=101)
        revision_b = candle(original.timestamp, volume=102)
        ingest(self.source, self.instrument, [original], "first")
        ingest(self.source, self.instrument, [revision_a], "a")

        repeat = ingest(self.source, self.instrument, [revision_a], "a-again")
        back_to_original = ingest(self.source, self.instrument, [original], "original-again")
        original_repeated = ingest(self.source, self.instrument, [original], "original-twice")
        newer = ingest(self.source, self.instrument, [revision_b], "b")

        self.assertEqual(self.observations_recorded_by(repeat), {"duplicate_revision": 1})
        # Returning to the frozen content is a change of the provider's view and
        # is recorded, so the latest view is never misreported as revision A.
        self.assertEqual(self.observations_recorded_by(back_to_original), {"revision": 1})
        self.assertEqual(self.observations_recorded_by(original_repeated), {"duplicate": 1})
        self.assertEqual(self.observations_recorded_by(newer), {"revision": 1})
        frozen = Candle.objects.get()
        observations = self.assert_ledger_chain(frozen, [100, 101, 100, 102])
        self.assertEqual(observations[2].content_sha256, frozen.content_sha256)
        self.assertEqual(observations[2].differing_fields, [])
        self.assertEqual(observations[2].kind, CandleObservation.Kind.REVISION)
        self.assertEqual(frozen.volume, 100)

    def test_reobserving_a_superseded_revision_appends_instead_of_failing(self):
        # Provider content A -> B -> A: the third view equals an earlier, superseded revision.
        original = self.series(1)[0]
        ingest(self.source, self.instrument, [original], "first")
        ingest(self.source, self.instrument, [candle(START, volume=200)], "a")
        ingest(self.source, self.instrument, [candle(START, volume=300)], "b")
        frozen = Candle.objects.get()
        before = self.ledger_rows()

        run = ingest(self.source, self.instrument, [candle(START, volume=200)], "a-again")

        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(run.stored_count, 0)
        self.assertEqual(self.observations_recorded_by(run), {"revision": 1})
        observations = self.assert_ledger_chain(frozen, [100, 200, 300, 200])
        self.assertEqual(observations[3].content_sha256, observations[1].content_sha256)
        self.assertEqual(observations[3].kind, CandleObservation.Kind.REVISION)
        self.assertEqual(observations[3].differing_fields, ["volume"])
        self.assertEqual(observations[3].ingestion_run, run)
        # Nothing already in the ledger was deleted or rewritten.
        self.assertEqual(self.ledger_rows()[: len(before)], before)
        frozen.refresh_from_db()
        self.assertEqual(frozen.volume, 100)
        self.assertEqual(frozen.content_sha256, candle_content_sha256("USD_CAD", "H1", original))

    def test_alternating_revisions_record_every_change_of_view(self):
        # A -> B -> A -> B, then back to the frozen content.
        original = self.series(1)[0]
        ingest(self.source, self.instrument, [original], "first")
        for batch, volume in (("a", 200), ("b", 300), ("a2", 200), ("b2", 300)):
            run = ingest(self.source, self.instrument, [candle(START, volume=volume)], batch)
            self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED, batch)
            self.assertEqual(self.observations_recorded_by(run), {"revision": 1}, batch)
        frozen = Candle.objects.get()
        observations = self.assert_ledger_chain(frozen, [100, 200, 300, 200, 300])
        self.assertEqual(observations[3].content_sha256, observations[1].content_sha256)
        self.assertEqual(observations[4].content_sha256, observations[2].content_sha256)
        self.assertEqual(
            [item.kind for item in observations[1:]], [CandleObservation.Kind.REVISION] * 4
        )

        reverted = ingest(self.source, self.instrument, [original], "back-to-frozen")

        observations = self.assert_ledger_chain(frozen, [100, 200, 300, 200, 300, 100])
        self.assertEqual(observations[5].content_sha256, frozen.content_sha256)
        self.assertEqual(observations[5].differing_fields, [])
        self.assertEqual(self.observations_recorded_by(reverted), {"revision": 1})
        self.assertEqual(Candle.objects.count(), 1)
        self.assertFalse(
            AuditEvent.objects.filter(event_type="market.live_candle_conflict").exists()
        )

    def test_flip_flopped_candle_and_new_candle_in_one_batch_store_the_new_candle(self):
        original = self.series(1)[0]
        ingest(self.source, self.instrument, [original], "first")
        ingest(self.source, self.instrument, [candle(START, volume=200)], "a")
        ingest(self.source, self.instrument, [candle(START, volume=300)], "b")
        window = [candle(START, volume=200), candle(START + timedelta(hours=1))]

        run = ingest(self.source, self.instrument, window, "poll-window")

        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(run.stored_count, 1)
        self.assertEqual(self.observations_recorded_by(run), {"revision": 1, "initial": 1})
        rows = list(Candle.objects.order_by("timestamp"))
        self.assertEqual([row.timestamp for row in rows], [START, START + timedelta(hours=1)])
        self.assert_ledger_chain(rows[0], [100, 200, 300, 200])
        new_observation = self.assert_ledger_chain(rows[1], [100])[0]
        self.assertEqual(new_observation.kind, CandleObservation.Kind.INITIAL)
        self.assertEqual(new_observation.ingestion_run, run)

    def test_retry_of_a_flip_flop_batch_is_a_no_op(self):
        original = self.series(1)[0]
        ingest(self.source, self.instrument, [original], "first")
        ingest(self.source, self.instrument, [candle(START, volume=200)], "a")
        ingest(self.source, self.instrument, [candle(START, volume=300)], "b")
        window = [candle(START, volume=200), candle(START + timedelta(hours=1))]
        ingest(self.source, self.instrument, window, "poll-window")
        before = self.ledger_rows()

        retry = ingest(self.source, self.instrument, window, "poll-window-retry")
        retry_again = ingest(self.source, self.instrument, window, "poll-window-retry-2")

        for run in (retry, retry_again):
            self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
            self.assertEqual(run.stored_count, 0)
            self.assertEqual(
                self.observations_recorded_by(run), {"duplicate_revision": 1, "duplicate": 1}
            )
        self.assertEqual(self.ledger_rows(), before)
        self.assertEqual(Candle.objects.count(), 2)
        self.assert_ledger_chain(Candle.objects.get(timestamp=START), [100, 200, 300, 200])

    def test_late_historical_arrival_is_labelled_not_interpolated(self):
        later = [candle(START + timedelta(hours=index)) for index in (2, 3)]
        ingest(self.source, self.instrument, later, "later")

        run = ingest(self.source, self.instrument, self.series(2), "late")

        self.assertEqual(run.stored_count, 2)
        kinds = dict(CandleObservation.objects.values_list("timestamp", "kind"))
        self.assertEqual(kinds[START], CandleObservation.Kind.LATE_ARRIVAL)
        self.assertEqual(kinds[START + timedelta(hours=1)], CandleObservation.Kind.LATE_ARRIVAL)
        self.assertEqual(kinds[START + timedelta(hours=2)], CandleObservation.Kind.INITIAL)
        self.assertEqual(Candle.objects.count(), 4)

    def test_invalid_chronology_and_ohlc_reject_the_batch(self):
        reversed_batch = list(reversed(self.series(2)))
        impossible = [candle(START, bid_low=Decimal("1.2000"))]

        first = ingest(self.source, self.instrument, reversed_batch, "reversed", start=START)
        second = ingest(self.source, self.instrument, impossible, "impossible")

        self.assertEqual(first.status, IngestionRun.Status.FAILED)
        self.assertIn("non_monotonic_timestamp", first.failure_reason)
        self.assertEqual(second.status, IngestionRun.Status.FAILED)
        self.assertIn("impossible_ohlc", second.failure_reason)
        self.assertEqual(Candle.objects.count(), 0)
        self.assertEqual(CandleObservation.objects.count(), 0)

    def test_dst_fall_back_hours_keep_distinct_completions(self):
        first = datetime(2026, 11, 1, 5, tzinfo=UTC)
        second = datetime(2026, 11, 1, 6, tzinfo=UTC)
        self.assertEqual(
            registered_candle_completion(first, "H1"), registered_candle_completion(second, "H1")
        )

        ingest(self.source, self.instrument, [candle(first), candle(second)], "dst")

        ends = list(
            CandleObservation.objects.order_by("timestamp").values_list("interval_end", flat=True)
        )
        self.assertEqual(ends, [first + timedelta(hours=1), second + timedelta(hours=1)])
        self.assertEqual(live_candle_completion(first, "H1"), first + timedelta(hours=1))
        daily = datetime(2026, 11, 5, 22, tzinfo=UTC)
        self.assertEqual(
            live_candle_completion(daily, "D"), registered_candle_completion(daily, "D")
        )

    def test_multiple_granularities_and_instruments_are_independent_identities(self):
        other, _ = make_market("EUR_USD", 2)
        item = candle(START)
        daily = candle(datetime(2026, 1, 4, 22, tzinfo=UTC))

        ingest(self.source, self.instrument, [item], "h1")
        ingest(self.source, self.instrument, [item], "h4", granularity="H4")
        ingest(self.source, self.instrument, [daily], "d", granularity="D")
        ingest(self.source, other, [item], "other")

        hashes = set(Candle.objects.values_list("content_sha256", flat=True))
        self.assertEqual(len(hashes), 4)
        self.assertEqual(CandleObservation.objects.filter(kind="initial").count(), 4)
        self.assertNotEqual(
            candle_content_sha256("USD_CAD", "H1", item),
            candle_content_sha256("USD_CAD", "H4", item),
        )
        self.assertNotEqual(
            candle_content_sha256("USD_CAD", "H1", item),
            candle_content_sha256("EUR_USD", "H1", item),
        )
        daily_row = Candle.objects.get(granularity="D")
        self.assertEqual(
            daily_row.authoritative_observation().interval_end,
            daily.timestamp + timedelta(days=1),
        )

    def test_content_hash_is_deterministic_and_sensitive_to_every_field(self):
        item = candle(START)
        baseline = candle_content_sha256("USD_CAD", "H1", item)
        self.assertEqual(baseline, candle_content_sha256("USD_CAD", "H1", candle(START)))
        for field in (
            "volume",
            "bid_open",
            "bid_high",
            "bid_low",
            "bid_close",
            "ask_open",
            "ask_high",
            "ask_low",
            "ask_close",
        ):
            value = getattr(item, field)
            changed = candle(
                START, **{field: value + (1 if field == "volume" else Decimal("0.000001"))}
            )
            self.assertNotEqual(baseline, candle_content_sha256("USD_CAD", "H1", changed), field)
        ingest(self.source, self.instrument, [item], "hash")
        self.assertEqual(Candle.objects.get().content_sha256, baseline)

    def test_direct_rows_carry_honest_unknown_provenance_and_cannot_be_rewritten(self):
        run = IngestionRun.objects.create(
            source=self.source,
            instrument=self.instrument,
            granularity="H1",
            requested_from=START,
            requested_to=START + timedelta(hours=1),
            parameters={},
            request_manifest_hash="direct",
            status=IngestionRun.Status.SUCCEEDED,
        )
        row = Candle.objects.create(
            instrument=self.instrument,
            ingestion_run=run,
            granularity="H1",
            **candle(START).__dict__,
        )

        self.assertEqual(row.provenance, Candle.Provenance.LEGACY_UNKNOWN)
        self.assertIsNone(row.content_sha256)
        self.assertIsNone(row.observed_at)
        row.bid_close = row.bid_close + Decimal("0.0001")
        with self.assertRaisesMessage(ValidationError, "append-only"):
            row.save()
        with self.assertRaisesMessage(ValidationError, "append-only"):
            row.delete()

    def test_revision_of_legacy_row_is_recorded_as_revision_two(self):
        run = IngestionRun.objects.create(
            source=self.source,
            instrument=self.instrument,
            granularity="H1",
            requested_from=START,
            requested_to=START + timedelta(hours=1),
            parameters={},
            request_manifest_hash="legacy",
            status=IngestionRun.Status.SUCCEEDED,
        )
        legacy = Candle.objects.create(
            instrument=self.instrument,
            ingestion_run=run,
            granularity="H1",
            **candle(START).__dict__,
        )

        ingest(self.source, self.instrument, [candle(START, volume=7)], "revise-legacy")

        observation = CandleObservation.objects.get()
        self.assertEqual(observation.candle, legacy)
        self.assertEqual(observation.revision, 2)
        self.assertIsNone(observation.supersedes)
        self.assertEqual(observation.kind, CandleObservation.Kind.REVISION)
        legacy.refresh_from_db()
        self.assertEqual(legacy.volume, 100)
        self.assertIsNone(legacy.content_sha256)

    def test_no_silent_deletion_across_revisions(self):
        ingest(self.source, self.instrument, self.series(), "first")
        ids = set(Candle.objects.values_list("id", flat=True))

        ingest(self.source, self.instrument, self.series(volume=5), "revise-all")

        self.assertEqual(set(Candle.objects.values_list("id", flat=True)), ids)
        self.assertEqual(CandleObservation.objects.count(), 6)


class TechnicalSnapshotVersioningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def test_snapshot_is_bound_to_source_set_and_appended_not_rewritten(self):
        candles = [candle(START + timedelta(hours=index)) for index in range(6)]
        ingest(self.source, self.instrument, candles, "first")
        first = TechnicalSnapshot.objects.get()

        self.assertEqual(first.algorithm_version, "technicals-v1")
        self.assertEqual(first.provenance, TechnicalSnapshot.Provenance.OBSERVED)
        self.assertEqual(
            first.source_candle_set_sha256,
            technical_source_set_sha256(
                "USD_CAD", "H1", list(Candle.objects.order_by("timestamp", "id"))
            ),
        )
        # Same inputs -> idempotent.
        self.assertEqual(calculate_and_store_snapshot(self.instrument, "H1"), first)
        # A provider revision does not change the frozen candle set, so the
        # bound snapshot is unchanged and no row is rewritten.
        ingest(self.source, self.instrument, [candle(START, volume=9)], "revise")
        self.assertEqual(TechnicalSnapshot.objects.count(), 1)
        # New evidence appends a new calculation; the earlier one survives.
        ingest(self.source, self.instrument, [candle(START + timedelta(hours=6))], "more")
        self.assertEqual(TechnicalSnapshot.objects.count(), 2)
        first.refresh_from_db()
        self.assertEqual(first.candle_count, 6)
        latest = TechnicalSnapshot.objects.first()
        self.assertEqual(latest.candle_count, 7)
        self.assertNotEqual(latest.source_candle_set_sha256, first.source_candle_set_sha256)

    def test_snapshot_rows_are_immutable_in_django(self):
        ingest(self.source, self.instrument, [candle(START)], "first")
        snapshot = TechnicalSnapshot.objects.get()
        snapshot.atr_14 = Decimal("9")
        with self.assertRaisesMessage(ValidationError, "append-only"):
            snapshot.save()
        with self.assertRaisesMessage(ValidationError, "append-only"):
            snapshot.delete()


class LiveEvidenceDatabaseProtectionTests(TransactionTestCase):
    """The application role cannot bypass the protections through raw SQL."""

    def setUp(self):
        self.instrument, self.source = make_market()
        ingest(
            self.source,
            self.instrument,
            [candle(START + timedelta(hours=i)) for i in range(3)],
            "db",
        )
        self.row = Candle.objects.order_by("timestamp").first()
        self.observation = self.row.authoritative_observation()
        self.snapshot = TechnicalSnapshot.objects.get()

    def test_connection_role_is_not_a_superuser(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('is_superuser')")
            self.assertEqual(cursor.fetchone()[0], "off")

    def assert_rejected(self, sql, params=()):
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)

    def test_live_candle_update_and_delete_are_rejected(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            Candle.objects.filter(pk=self.row.pk).update(bid_close=Decimal("1.2"))
        with self.assertRaises(DatabaseError), transaction.atomic():
            Candle.objects.filter(pk=self.row.pk).delete()
        self.assert_rejected(
            "UPDATE market_candle SET volume = volume + 1 WHERE id = %s", [self.row.pk]
        )
        self.assert_rejected("DELETE FROM market_candle WHERE id = %s", [self.row.pk])
        self.row.refresh_from_db()
        self.assertEqual(self.row.volume, 100)

    def test_observation_update_delete_and_truncate_are_rejected(self):
        self.assert_rejected(
            "UPDATE market_candleobservation SET volume = 1 WHERE id = %s", [self.observation.pk]
        )
        self.assert_rejected(
            "DELETE FROM market_candleobservation WHERE id = %s", [self.observation.pk]
        )
        self.assert_rejected("TRUNCATE market_candleobservation")
        self.assertEqual(CandleObservation.objects.count(), 3)

    def test_technical_snapshot_update_delete_and_truncate_are_rejected(self):
        self.assert_rejected(
            "UPDATE market_technicalsnapshot SET atr_14 = 1 WHERE id = %s", [self.snapshot.pk]
        )
        self.assert_rejected(
            "DELETE FROM market_technicalsnapshot WHERE id = %s", [self.snapshot.pk]
        )
        self.assert_rejected("TRUNCATE market_technicalsnapshot")
        self.assertEqual(TechnicalSnapshot.objects.count(), 1)

    def test_fixture_rows_remain_deletable_only_through_provenance(self):
        fixture = SourceRegistry.objects.create(
            name="Development fixtures",
            tier="quarantine",
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test",
        )
        other, _ = make_market("EUR_USD", 2)
        ingest(fixture, other, [candle(START)], "fixture")
        fixture_row = Candle.objects.get(instrument=other)
        self.assertEqual(fixture_row.provenance, Candle.Provenance.FIXTURE)
        self.assertFalse(CandleObservation.objects.filter(instrument=other).exists())
        Candle.objects.filter(pk=fixture_row.pk).delete()
        self.assertFalse(Candle.objects.filter(pk=fixture_row.pk).exists())

    def test_concurrent_ingestion_cannot_create_contradictory_state(self):
        batch = [candle(START + timedelta(hours=i)) for i in range(3, 6)]

        def run(batch_name):
            close_old_connections()
            try:
                instrument = Instrument.objects.get(code="USD_CAD")
                source = SourceRegistry.objects.get(name="OANDA v20")
                result = ingest(source, instrument, batch, batch_name)
                return (result.status, result.stored_count)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, ("concurrent-a", "concurrent-b")))

        self.assertEqual({status for status, _ in results}, {IngestionRun.Status.SUCCEEDED})
        self.assertEqual(sorted(stored for _, stored in results), [0, 3])
        self.assertEqual(
            Candle.objects.filter(timestamp__gte=START + timedelta(hours=3)).count(), 3
        )
        self.assertEqual(
            CandleObservation.objects.filter(timestamp__gte=START + timedelta(hours=3)).count(), 3
        )
