from datetime import UTC, datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase, TransactionTestCase

from market.models import (
    AuditEvent,
    Candle,
    IngestionRun,
    Instrument,
    SourceRegistry,
    TechnicalSnapshot,
)
from market.services import store_ingestion
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

    def test_audit_events_reject_mutation_and_deletion(self):
        event = AuditEvent.objects.create(
            event_type="test", actor="test", subject_type="test", subject_id="1"
        )
        event.payload = {"changed": True}
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()


class AuditDatabaseInvariantTests(TransactionTestCase):
    def test_queryset_cannot_bypass_append_only_trigger(self):
        event = AuditEvent.objects.create(
            event_type="test", actor="test", subject_type="test", subject_id="1"
        )

        with self.assertRaises(DatabaseError), transaction.atomic():
            AuditEvent.objects.filter(pk=event.pk).update(payload={"changed": True})

        event.refresh_from_db()
        self.assertEqual(event.payload, {})
