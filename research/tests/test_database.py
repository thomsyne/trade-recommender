from datetime import UTC, datetime

from django.db import DatabaseError, transaction
from django.test import TransactionTestCase

from market.models import Instrument
from research.models import PairEvidenceSnapshot, RawRetrieval
from research.tests.factories import source_policy


class EvidenceDatabaseTests(TransactionTestCase):
    reset_sequences = True

    def test_database_trigger_rejects_raw_snapshot_updates_and_deletes(self):
        policy = source_policy()
        retrieval = RawRetrieval.objects.create(
            source_policy=policy,
            url="https://official.example/feed",
            request_fingerprint="a" * 64,
            fetched_at=datetime(2026, 8, 19, tzinfo=UTC),
            http_status=200,
            content_type="application/rss+xml",
            byte_count=4,
            body_sha256="b" * 64,
            body=b"test",
            retention_decision="test",
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            RawRetrieval.objects.filter(pk=retrieval.pk).update(quality_reason="rewritten")
        with self.assertRaises(DatabaseError), transaction.atomic():
            RawRetrieval.objects.filter(pk=retrieval.pk).delete()

    def test_database_trigger_rejects_pair_evidence_updates_and_deletes(self):
        instrument = Instrument.objects.create(
            code="USD_CAD",
            base_currency="USD",
            quote_currency="CAD",
            display_order=1,
        )
        captured_at = datetime(2026, 8, 19, tzinfo=UTC)
        snapshot = PairEvidenceSnapshot.objects.create(
            instrument=instrument,
            information_cutoff=captured_at,
            payload={"schema": "test"},
            sha256="c" * 64,
            captured_at=captured_at,
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            PairEvidenceSnapshot.objects.filter(pk=snapshot.pk).update(payload={})
        with self.assertRaises(DatabaseError), transaction.atomic():
            PairEvidenceSnapshot.objects.filter(pk=snapshot.pk).delete()
