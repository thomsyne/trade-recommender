from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from market.state.canonical import identity_digest
from market.tests.historical_database import HistoricalDatabaseMixin, head_fingerprint
from research.evidence_store import review_rights
from research.tests.factories import source_policy
from research.tests.test_phase7_evidence import rights


class Phase7MigrationTests(HistoricalDatabaseMixin, TransactionTestCase):
    historical_market_migration = "0041_"

    def fingerprint(self, tables=None):
        with connection.cursor() as cursor:
            if tables is None:
                cursor.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>'django_migrations' ORDER BY tablename"
                )
                tables = [r[0] for r in cursor.fetchall()]
            rows = {}
            for table in tables:
                cursor.execute(
                    f"SELECT to_jsonb(t)::text FROM {connection.ops.quote_name(table)} t ORDER BY to_jsonb(t)::text"
                )
                rows[table] = identity_digest([r[0] for r in cursor.fetchall()])
            return rows

    def test_forward_preservation_empty_reverse_and_populated_refusal(self):
        source = source_policy().source
        before = self.fingerprint()
        target = [("research", "0022_phase7_provenance_corrections")]
        MigrationExecutor(connection).migrate(target)
        self.assertEqual(before, self.fingerprint(before))
        MigrationExecutor(connection).migrate(
            [("research", "0015_pre_s1_inventory_entry_boundary")]
        )
        self.assertEqual(before, self.fingerprint(before))
        MigrationExecutor(connection).migrate(target)
        review_rights(source, rights(source.pk, "local", now=timezone.now()))
        with connection.cursor() as cursor:
            installed = head_fingerprint(cursor)
        with self.assertRaisesMessage(RuntimeError, "Phase7 populated evidence reversal refused"):
            MigrationExecutor(connection).migrate(
                [("research", "0015_pre_s1_inventory_entry_boundary")]
            )
        with connection.cursor() as cursor:
            self.assertEqual(installed, head_fingerprint(cursor))
        self.assertEqual(before, self.fingerprint(before))
