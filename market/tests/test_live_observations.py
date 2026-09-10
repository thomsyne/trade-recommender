"""Phase 1.4 — explicit live-candle observation identity and protection."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

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
        first = datetime(2025, 11, 2, 5, tzinfo=UTC)
        second = datetime(2025, 11, 2, 6, tzinfo=UTC)
        self.assertEqual(
            registered_candle_completion(first, "H1"), registered_candle_completion(second, "H1")
        )

        ingest(self.source, self.instrument, [candle(first), candle(second)], "dst")

        ends = list(
            CandleObservation.objects.order_by("timestamp").values_list("interval_end", flat=True)
        )
        self.assertEqual(ends, [first + timedelta(hours=1), second + timedelta(hours=1)])
        self.assertEqual(live_candle_completion(first, "H1"), first + timedelta(hours=1))
        daily = datetime(2025, 11, 6, 22, tzinfo=UTC)
        self.assertEqual(
            live_candle_completion(daily, "D"), registered_candle_completion(daily, "D")
        )

    def test_multiple_granularities_and_instruments_are_independent_identities(self):
        other, _ = make_market("EUR_USD", 2)
        item = candle(START)
        four_hour = candle(datetime(2026, 1, 5, 6, tzinfo=UTC))  # 01:00 New York
        daily = candle(datetime(2026, 1, 4, 22, tzinfo=UTC))

        ingest(self.source, self.instrument, [item], "h1")
        ingest(self.source, self.instrument, [four_hour], "h4", granularity="H4")
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

    def test_sub_unit_prices_hash_identically_in_python_and_sql(self):
        # Regression: the SQL hash mirror used to_char without a leading zero,
        # so a sub-unit magnitude (e.g. AUD/USD near 0.65) produced a different
        # digest in SQL than in Python and the insert was rejected with
        # "content_sha256 does not match the stored candle content".
        from decimal import Decimal as D

        def price_scale(**changes):
            values = {
                "bid_open": D("0.650000"),
                "bid_high": D("0.652000"),
                "bid_low": D("0.648000"),
                "bid_close": D("0.651000"),
                "ask_open": D("0.650020"),
                "ask_high": D("0.652020"),
                "ask_low": D("0.648020"),
                "ask_close": D("0.651020"),
            }
            values.update(changes)
            return candle(START, **values)

        ingest(self.source, self.instrument, [price_scale()], "sub-unit")
        row = Candle.objects.get()
        self.assertEqual(row.content_sha256, candle_content_sha256("USD_CAD", "H1", price_scale()))
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) FROM market_candleobservation observation
                 JOIN market_instrument instrument ON instrument.id = observation.instrument_id
                 WHERE market_candleobservation_content_sha256(
                         instrument.code, observation.granularity, observation.timestamp,
                         observation.complete, observation.volume,
                         observation.bid_open, observation.bid_high, observation.bid_low,
                         observation.bid_close,
                         observation.ask_open, observation.ask_high, observation.ask_low,
                         observation.ask_close)
                       IS DISTINCT FROM observation.content_sha256
                """
            )
            self.assertEqual(cursor.fetchone()[0], 0)
        # A revision in the same sub-unit scale still lands on the candle chain.
        ingest(
            self.source,
            self.instrument,
            [price_scale(bid_close=D("0.650500"))],
            "sub-unit-2-revision",
        )
        self.assertEqual(
            list(CandleObservation.objects.order_by("revision").values_list("revision", flat=True)),
            [1, 2],
        )

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

    def test_legacy_row_adoption_opens_a_dense_observation_chain(self):
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

        first = CandleObservation.objects.get()
        self.assertEqual(first.candle, legacy)
        self.assertEqual(first.revision, 1)
        self.assertIsNone(first.supersedes)
        self.assertEqual(first.kind, CandleObservation.Kind.REVISION)
        legacy.refresh_from_db()
        self.assertEqual(legacy.volume, 100)
        self.assertIsNone(legacy.content_sha256)

        ingest(self.source, self.instrument, [candle(START, volume=8)], "revise-legacy-2")

        observations = list(CandleObservation.objects.order_by("revision"))
        self.assertEqual([item.revision for item in observations], [1, 2])
        self.assertEqual(observations[0].supersedes, None)
        self.assertEqual(observations[1].supersedes, observations[0])
        self.assertEqual(observations[1].kind, CandleObservation.Kind.REVISION)

    def second_source(self):
        source, _ = SourceRegistry.objects.get_or_create(
            name="Secondary provider",
            defaults={
                "tier": "established",
                "base_url": "https://example.invalid",
                "acquisition_method": "test",
                "retention_policy": "test only",
            },
        )
        return source

    def test_second_source_revision_chains_onto_the_candle_lineage(self):
        original = self.series(1)[0]
        ingest(self.source, self.instrument, [original], "first")
        frozen = Candle.objects.get()
        other = self.second_source()

        run = ingest(other, self.instrument, [candle(original.timestamp, volume=200)], "other")

        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(run.stored_count, 0)
        self.assertEqual(self.observations_recorded_by(run), {"revision": 1})
        observations = self.assert_ledger_chain(frozen, [100, 200])
        self.assertEqual(observations[1].source, other)
        self.assertEqual(observations[1].kind, CandleObservation.Kind.REVISION)
        self.assertEqual(observations[1].supersedes, observations[0])

        back = ingest(
            self.source, self.instrument, [candle(original.timestamp, volume=300)], "back"
        )

        observations = self.assert_ledger_chain(frozen, [100, 200, 300])
        self.assertEqual(observations[2].supersedes, observations[1])
        self.assertEqual(self.observations_recorded_by(back), {"revision": 1})

    def test_second_source_agreeing_with_frozen_content_records_nothing(self):
        original = self.series(1)[0]
        ingest(self.source, self.instrument, [original], "first")
        other = self.second_source()

        run = ingest(other, self.instrument, [original], "other-same")

        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(run.stored_count, 0)
        self.assertEqual(CandleObservation.objects.count(), 1)
        self.assertEqual(self.observations_recorded_by(run), {"duplicate": 1})

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
        super().setUp()
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
        # Exercise raw writes as an application role even when the disposable
        # cluster's migration owner is a superuser. Cleanup precedes DB flush.
        self.role = "test_live_" + uuid4().hex
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{self.role}" NOSUPERUSER NOLOGIN')
            cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{self.role}"')
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES "
                f'IN SCHEMA public TO "{self.role}"'
            )
            cursor.execute(
                f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{self.role}"'
            )
            cursor.execute(f'SET ROLE "{self.role}"')
        self.addCleanup(self.restore_role)

    def restore_role(self):
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
            cursor.execute(f'DROP OWNED BY "{self.role}"')
            cursor.execute(f'DROP ROLE "{self.role}"')

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

    def _assert_observation_insert_rejected(self, overrides):
        """Raw SQL insert of a CandleObservation row must be rejected by the lineage trigger.

        When content columns are overridden the row's content_sha256 is
        recomputed first, so a probe can target the check under test (chain
        shape, bounds, differing_fields, ...) instead of failing on the hash.
        """
        template = self.observation
        content_columns = (
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
        columns = (
            "instrument_id",
            "granularity",
            "timestamp",
            "interval_end",
            *content_columns,
            "source_id",
            "ingestion_run_id",
            "candle_id",
            "kind",
            "revision",
            "supersedes_id",
            "content_sha256",
            "differing_fields",
            "observed_at",
        )
        values = {
            "instrument_id": template.instrument_id,
            "granularity": template.granularity,
            "timestamp": template.timestamp,
            "interval_end": template.interval_end,
            "complete": True,
            "volume": template.volume,
            "bid_open": template.bid_open,
            "bid_high": template.bid_high,
            "bid_low": template.bid_low,
            "bid_close": template.bid_close,
            "ask_open": template.ask_open,
            "ask_high": template.ask_high,
            "ask_low": template.ask_low,
            "ask_close": template.ask_close,
            "source_id": template.source_id,
            "ingestion_run_id": template.ingestion_run_id,
            "candle_id": template.candle_id,
            "kind": template.kind,
            "revision": template.revision + 2,
            "supersedes_id": None,
            "content_sha256": template.content_sha256,
            "differing_fields": json.dumps(template.differing_fields),
            "observed_at": template.observed_at,
        }
        values.update(overrides)
        if any(column in overrides for column in content_columns):
            values["content_sha256"] = candle_content_sha256(
                self.instrument.code,
                values["granularity"],
                candle(
                    values["timestamp"],
                    **{column: values[column] for column in content_columns},
                ),
            )
        placeholders = ", ".join(["%s"] * len(columns))
        sql = "INSERT INTO market_candleobservation ({}) VALUES ({})".format(
            ", ".join(columns), placeholders
        )
        params = [values[column] for column in columns]
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)

    def test_observation_insert_with_a_revision_gap_is_rejected(self):
        head = self.row.authoritative_observation()
        self._assert_observation_insert_rejected(
            {"revision": head.revision + 2, "supersedes_id": head.pk}
        )

    def test_observation_insert_superseding_another_candle_is_rejected(self):
        other = Candle.objects.order_by("timestamp")[1].authoritative_observation()
        self._assert_observation_insert_rejected(
            {"revision": other.revision + 1, "supersedes_id": other.pk}
        )

    def test_observation_insert_root_on_an_observed_candle_is_rejected(self):
        # A second candle's initial observation already exists; opening a
        # revision chain at 1 on a candle with attested content is invalid.
        other_row = Candle.objects.order_by("timestamp")[1]
        initial = other_row.authoritative_observation()
        self._assert_observation_insert_rejected(
            {
                "candle_id": other_row.pk,
                "kind": CandleObservation.Kind.REVISION,
                "revision": 1,
                "supersedes_id": None,
                "content_sha256": initial.content_sha256,
            }
        )

    def test_observation_insert_initial_on_an_existing_candle_is_rejected(self):
        self._assert_observation_insert_rejected(
            {
                "kind": CandleObservation.Kind.INITIAL,
                "revision": 1,
                "supersedes_id": None,
            }
        )

    def test_observation_insert_with_a_tampered_hash_is_rejected(self):
        self._assert_observation_insert_rejected({"content_sha256": "0" * 64})

    def test_observation_insert_with_a_contradictory_run_source_is_rejected(self):
        other_source = SourceRegistry.objects.create(
            name="Secondary provider",
            tier="established",
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test",
        )
        self._assert_observation_insert_rejected({"source_id": other_source.pk})

    def _run(self, *, status, requested_from, requested_to, source=None, manifest):
        from market.tests.timeline import application_clock

        # Record the simulated request at its actual fixture time rather than
        # disabling a trigger and backdating an immutable run afterwards.
        with application_clock(self.observation.observed_at - timedelta(minutes=5)):
            return IngestionRun.objects.create(
                source=source or self.source,
                instrument=self.instrument,
                granularity="H1",
                requested_from=requested_from,
                requested_to=requested_to,
                parameters={},
                request_manifest_hash=manifest,
                status=status,
            )

    def test_observation_timestamp_outside_run_request_window_is_rejected(self):
        # A forged attribution would point the observation at a run whose
        # request window does not contain the candle's timestamp.
        forged = self._run(
            status=IngestionRun.Status.SUCCEEDED,
            requested_from=self.row.timestamp + timedelta(days=10),
            requested_to=self.row.timestamp + timedelta(days=10, hours=1),
            manifest="forged-window",
        )
        self._assert_observation_insert_rejected(
            {
                "ingestion_run_id": forged.pk,
                "revision": self.observation.revision + 1,
                "supersedes_id": self.observation.pk,
            }
        )

    def test_observation_referencing_a_failed_run_is_rejected(self):
        # Legitimate observations are recorded by the run that stores them,
        # which transitions running -> succeeded inside one transaction; a run
        # already recorded as failed must never acquire observations.
        failed = self._run(
            status=IngestionRun.Status.FAILED,
            requested_from=self.row.timestamp - timedelta(hours=1),
            requested_to=self.row.timestamp + timedelta(hours=1),
            manifest="forged-failed-run",
        )
        self._assert_observation_insert_rejected(
            {
                "ingestion_run_id": failed.pk,
                "revision": self.observation.revision + 1,
                "supersedes_id": self.observation.pk,
            }
        )

    def test_observation_interval_end_beyond_the_run_window_is_rejected(self):
        # The provider view a run records must complete inside its requested
        # window; an interval_end pushed past requested_to is a forged claim.
        self._assert_observation_insert_rejected(
            {
                "interval_end": self.observation.interval_end + timedelta(hours=9),
                "revision": self.observation.revision + 1,
                "supersedes_id": self.observation.pk,
            }
        )

    def test_observation_interval_end_not_matching_h1_completion_is_rejected(self):
        self._assert_observation_insert_rejected(
            {
                "interval_end": self.observation.timestamp + timedelta(hours=2),
                "revision": self.observation.revision + 1,
                "supersedes_id": self.observation.pk,
            }
        )

    def test_observation_interval_end_not_matching_daily_completion_is_rejected(self):
        # Daily candles close at 17:00 America/New_York: the completion is the
        # registered wall-clock step, not a naive UTC day.
        daily_start = datetime(2026, 1, 4, 22, tzinfo=UTC)  # Sunday 17:00 NY
        daily_end = datetime(2026, 1, 6, 22, tzinfo=UTC)
        ingest(
            self.source,
            self.instrument,
            [candle(daily_start)],
            "daily-probe",
            granularity="D",
            start=daily_start,
            end=daily_end,
        )
        daily = Candle.objects.get(granularity="D")
        head = daily.authoritative_observation()
        # A forged interval_end one hour early/late must be rejected even though
        # it stays inside the run request window.
        self._assert_observation_insert_rejected(
            {
                "candle_id": daily.pk,
                "granularity": "D",
                "timestamp": daily.timestamp,
                "interval_end": head.interval_end + timedelta(hours=1),
                "kind": CandleObservation.Kind.REVISION,
                "revision": head.revision + 1,
                "supersedes_id": head.pk,
                "bid_close": head.bid_close,
                "differing_fields": json.dumps([]),
            }
        )

    def test_observation_observed_at_not_contemporaneous_with_run_is_rejected(self):
        # A forged attribution records the observation a year before the run
        # executed; the chronology check must refuse it.
        stale = self._run(
            status=IngestionRun.Status.SUCCEEDED,
            requested_from=self.row.timestamp - timedelta(hours=1),
            requested_to=self.row.timestamp + timedelta(hours=1),
            manifest="forged-chronology",
        )
        self._assert_observation_insert_rejected(
            {
                "ingestion_run_id": stale.pk,
                "observed_at": self.observation.observed_at - timedelta(days=365),
                "revision": self.observation.revision + 1,
                "supersedes_id": self.observation.pk,
            }
        )

    def test_observation_with_fabricated_differing_fields_is_rejected(self):
        # differing_fields is a derived claim; the trigger recomputes it from
        # the content actually superseded and refuses a row that lies about it.
        head = self.observation
        self._assert_observation_insert_rejected(
            {
                "bid_close": head.bid_close + Decimal("0.000100"),
                "differing_fields": json.dumps(["ask_open"]),
                "revision": head.revision + 1,
                "supersedes_id": head.pk,
            }
        )

    def test_every_content_hash_recomputes_in_sql(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) FROM market_candleobservation observation
                 JOIN market_instrument instrument ON instrument.id = observation.instrument_id
                 WHERE market_candleobservation_content_sha256(
                         instrument.code, observation.granularity, observation.timestamp,
                         observation.complete, observation.volume,
                         observation.bid_open, observation.bid_high, observation.bid_low,
                         observation.bid_close,
                         observation.ask_open, observation.ask_high, observation.ask_low,
                         observation.ask_close)
                       IS DISTINCT FROM observation.content_sha256
                """
            )
            self.assertEqual(cursor.fetchone()[0], 0)
