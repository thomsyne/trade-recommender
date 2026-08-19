from datetime import UTC, datetime

from django.db import DatabaseError, transaction
from django.test import TransactionTestCase

from research.models import RawRetrieval
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
