from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase, TransactionTestCase

from market.models import (
    AuditEvent,
    Candle,
    CandleConflict,
    DatasetVersion,
    IngestionRun,
    Instrument,
    SourceRegistry,
    TechnicalSnapshot,
)
from market.services import (
    DatasetQualityError,
    RequiredCandleRange,
    assert_dataset_usable,
    assert_dataset_window_usable,
    store_ingestion,
)
from market.tests.factories import candle


class IngestionServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        cls.source = SourceRegistry.objects.create(
            name="fixture",
            tier="quarantine",
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test only",
        )

    def test_valid_ingestion_is_idempotent_and_calculates_snapshot(self):
        start = datetime(2026, 1, 5, tzinfo=UTC)
        end = start + timedelta(hours=24)
        candles = [candle(start + timedelta(hours=4 * index)) for index in range(6)]
        manifest = {"request": "fixed", "requests": []}

        first = store_ingestion(self.source, self.instrument, "H4", start, end, candles, manifest)
        second = store_ingestion(self.source, self.instrument, "H4", start, end, candles, manifest)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(Candle.objects.count(), 6)
        self.assertEqual(TechnicalSnapshot.objects.get().candle_count, 6)
        self.assertEqual(AuditEvent.objects.get().event_type, "market.ingestion_succeeded")

    def test_invalid_batch_fails_closed_and_stores_no_candles(self):
        start = datetime(2026, 1, 5, tzinfo=UTC)
        bad = candle(start, complete=False)

        run = store_ingestion(
            self.source,
            self.instrument,
            "H4",
            start,
            start + timedelta(hours=4),
            [bad],
            {"bad": True},
        )

        self.assertEqual(run.status, IngestionRun.Status.FAILED)
        self.assertEqual(Candle.objects.count(), 0)
        self.assertIn("incomplete_candle", run.failure_reason)

    def test_empty_governed_dataset_is_not_usable(self):
        dataset = DatasetVersion.objects.create(
            name="empty",
            version="1",
            source=self.source,
            manifest_sha256="e" * 64,
        )

        with self.assertRaisesMessage(DatasetQualityError, "no governed candles"):
            assert_dataset_usable(dataset)

    def test_required_range_detects_gap_across_successful_manifests(self):
        dataset = DatasetVersion.objects.create(
            name="cross-manifest-gap",
            version="1",
            source=self.source,
            manifest_sha256="g" * 64,
        )
        start = datetime(2026, 1, 5, tzinfo=UTC)
        for index, timestamp in enumerate((start, start + timedelta(hours=2))):
            run = store_ingestion(
                self.source,
                self.instrument,
                "H1",
                timestamp,
                timestamp + timedelta(hours=1),
                [candle(timestamp)],
                {"batch": index},
                dataset_version=dataset,
            )
            self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)

        with self.assertRaisesMessage(DatasetQualityError, "does not completely cover"):
            assert_dataset_window_usable(
                dataset,
                self.instrument,
                (RequiredCandleRange("H1", start, start + timedelta(hours=3)),),
                start + timedelta(hours=3),
            )

    def test_required_ranges_are_instrument_timeframe_and_as_of_specific(self):
        dataset = DatasetVersion.objects.create(
            name="bounded-window",
            version="1",
            source=self.source,
            manifest_sha256="w" * 64,
        )
        start = datetime(2026, 1, 5, tzinfo=UTC)
        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            start,
            start + timedelta(hours=2),
            [candle(start), candle(start + timedelta(hours=1))],
            {"bounded": True},
            dataset_version=dataset,
        )
        complete_range = (RequiredCandleRange("H1", start, start + timedelta(hours=2)),)

        assert_dataset_window_usable(
            dataset, self.instrument, complete_range, start + timedelta(hours=2)
        )
        with self.assertRaisesMessage(DatasetQualityError, "incomplete at as_of"):
            assert_dataset_window_usable(
                dataset, self.instrument, complete_range, start + timedelta(hours=1)
            )
        with self.assertRaisesMessage(DatasetQualityError, "does not completely cover"):
            daily_start = datetime(2026, 1, 4, 22, tzinfo=UTC)
            assert_dataset_window_usable(
                dataset,
                self.instrument,
                (RequiredCandleRange("D", daily_start, daily_start + timedelta(days=1)),),
                daily_start + timedelta(days=1),
            )

    def test_real_ingestion_replaces_development_fixtures(self):
        self.source.name = "Development fixtures"
        self.source.save(update_fields=("name",))
        oanda = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="test only",
        )
        start = datetime(2026, 1, 5, tzinfo=UTC)
        end = start + timedelta(hours=24)
        candles = [candle(start + timedelta(hours=4 * index)) for index in range(6)]
        store_ingestion(
            self.source,
            self.instrument,
            "H4",
            start,
            end,
            candles,
            {"source": "fixture", "requests": []},
        )

        run = store_ingestion(
            oanda,
            self.instrument,
            "H4",
            start,
            end,
            candles,
            {"source": "oanda", "requests": []},
        )

        self.assertEqual(run.stored_count, 6)
        self.assertEqual(
            set(Candle.objects.values_list("ingestion_run__source__name", flat=True)),
            {"OANDA v20"},
        )
        self.assertEqual(TechnicalSnapshot.objects.get().candle_count, 6)
        self.assertEqual(
            AuditEvent.objects.get(subject_id=str(run.pk)).payload["replaced_fixture_candles"],
            6,
        )

    def test_fixture_ingestion_is_discarded_after_real_data_exists(self):
        self.source.name = "Development fixtures"
        self.source.save(update_fields=("name",))
        oanda = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="test only",
        )
        start = datetime(2026, 1, 5, tzinfo=UTC)
        candles = [candle(start)]
        store_ingestion(
            oanda,
            self.instrument,
            "H4",
            start,
            start + timedelta(hours=4),
            candles,
            {"source": "oanda", "requests": []},
        )

        run = store_ingestion(
            self.source,
            self.instrument,
            "H4",
            start + timedelta(hours=4),
            start + timedelta(hours=8),
            [candle(start + timedelta(hours=4))],
            {"source": "fixture", "requests": []},
        )

        self.assertEqual(run.fetched_count, 1)
        self.assertEqual(run.stored_count, 0)
        self.assertEqual(Candle.objects.count(), 1)
        self.assertTrue(
            AuditEvent.objects.get(subject_id=str(run.pk)).payload["discarded_fixture_batch"]
        )

    def test_audit_events_reject_mutation_and_deletion(self):
        event = AuditEvent.objects.create(
            event_type="test", actor="test", subject_type="test", subject_id="1"
        )
        event.payload = {"changed": True}
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_governed_conflict_quarantines_batch_but_child_can_correct(self):
        start = datetime(2026, 1, 5, tzinfo=UTC)
        parent = DatasetVersion.objects.create(
            name="oanda", version="v1", source=self.source, manifest_sha256="1" * 64
        )
        child = DatasetVersion.objects.create(
            name="oanda",
            version="v2",
            parent=parent,
            source=self.source,
            manifest_sha256="2" * 64,
        )
        original = candle(start)
        corrected = candle(start, bid_close=original.bid_close + Decimal("0.0001"))

        first = store_ingestion(
            self.source,
            self.instrument,
            "H4",
            start,
            start + timedelta(hours=4),
            [original],
            {"batch": 1},
            dataset_version=parent,
        )
        duplicate = store_ingestion(
            self.source,
            self.instrument,
            "H4",
            start,
            start + timedelta(hours=4),
            [original],
            {"batch": 2},
            dataset_version=parent,
        )
        conflict = store_ingestion(
            self.source,
            self.instrument,
            "H4",
            start,
            start + timedelta(hours=4),
            [corrected],
            {"batch": 3},
            dataset_version=parent,
        )
        correction = store_ingestion(
            self.source,
            self.instrument,
            "H4",
            start,
            start + timedelta(hours=4),
            [corrected],
            {"batch": 4},
            dataset_version=child,
        )

        self.assertEqual(first.stored_count, 1)
        self.assertEqual(duplicate.stored_count, 0)
        self.assertEqual(conflict.status, IngestionRun.Status.QUARANTINED)
        self.assertEqual(CandleConflict.objects.count(), 1)
        self.assertEqual(CandleConflict.objects.get().differing_fields, ["bid_close"])
        self.assertEqual(correction.stored_count, 1)
        self.assertEqual(Candle.objects.count(), 2)

    def test_component_midpoints_are_derived_from_bid_and_ask(self):
        item = candle()
        stored = Candle(
            instrument=self.instrument,
            ingestion_run_id=1,
            granularity="H4",
            **item.__dict__,
        )

        self.assertEqual(stored.midpoint_open, (item.bid_open + item.ask_open) / 2)
        self.assertEqual(stored.midpoint_high, (item.bid_high + item.ask_high) / 2)
        self.assertEqual(stored.midpoint_low, (item.bid_low + item.ask_low) / 2)
        self.assertEqual(stored.midpoint_close, (item.bid_close + item.ask_close) / 2)


class AuditDatabaseInvariantTests(TransactionTestCase):
    def test_queryset_cannot_bypass_append_only_trigger(self):
        event = AuditEvent.objects.create(
            event_type="test", actor="test", subject_type="test", subject_id="1"
        )

        with self.assertRaises(DatabaseError), transaction.atomic():
            AuditEvent.objects.filter(pk=event.pk).update(payload={"changed": True})

        event.refresh_from_db()
        self.assertEqual(event.payload, {})

    def test_legacy_candle_cannot_be_mutated_while_promoted_to_governed_dataset(self):
        source = SourceRegistry.objects.create(
            name="legacy-source",
            tier=SourceRegistry.Tier.QUARANTINE,
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test",
        )
        instrument = Instrument.objects.create(
            code="EUR_USD", base_currency="EUR", quote_currency="USD", display_order=1
        )
        at = datetime(2026, 1, 5, tzinfo=UTC)
        run = IngestionRun.objects.create(
            source=source,
            instrument=instrument,
            granularity="H1",
            requested_from=at,
            requested_to=at + timedelta(hours=1),
            parameters={},
            request_manifest_hash="legacy",
            status=IngestionRun.Status.SUCCEEDED,
        )
        item = candle(at)
        stored = Candle.objects.create(
            instrument=instrument,
            ingestion_run=run,
            granularity="H1",
            **item.__dict__,
        )
        dataset = DatasetVersion.objects.create(
            name="governed", version="1", manifest_sha256="7" * 64
        )

        with self.assertRaises(DatabaseError), transaction.atomic():
            Candle.objects.filter(pk=stored.pk).update(
                dataset_version=dataset,
                bid_close=stored.bid_close + Decimal("0.0001"),
            )

        stored.refresh_from_db()
        self.assertIsNone(stored.dataset_version_id)
