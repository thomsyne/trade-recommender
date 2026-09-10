from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.state.canonical import identity_digest
from market.strategy.persistence import register
from market.tests.historical_database import HistoricalDatabaseMixin, head_fingerprint
from market.tests.test_strategy_library_persistence import snapshot


class MigrationTests(HistoricalDatabaseMixin, TransactionTestCase):
    historical_market_migration = "0037_"

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

    def test_populated_prior_tables_preserved_empty_roundtrip_populated_refusal(self):
        snapshot()
        before = self.fingerprint()
        head = [("market", "0040_strategy_contract_corrections")]
        MigrationExecutor(connection).migrate(head)
        self.assertEqual(before, self.fingerprint(before))
        MigrationExecutor(connection).migrate([("market", "0038_strategy_library_records")])
        MigrationExecutor(connection).migrate(head)
        self.assertEqual(before, self.fingerprint(before))
        register("ewmac-d-v1")
        with connection.cursor() as cursor:
            populated = head_fingerprint(cursor)
        with self.assertRaisesMessage(RuntimeError, "phase5_populated_reverse_refused"):
            MigrationExecutor(connection).migrate([("market", "0037_market_state_lifecycle")])
        with connection.cursor() as cursor:
            self.assertEqual(populated, head_fingerprint(cursor))
        self.assertEqual(before, self.fingerprint(before))

    def test_legacy_phase5_definition_is_preserved_not_relabelled(self):
        from market.models import StrategyDefinition
        from market.strategy.definitions import definition

        MigrationExecutor(connection).migrate([("market", "0039_strategy_library_guards")])
        body = definition("fixed-risk-v1")
        body.pop("revision")
        body["implementation_sha256"] = (
            "554b925a6c67adc8f1cccdd7fdc086d49a0392678d63b8adaa304815a47d4591"
        )
        body["specification_sha256"] = (
            "d4e1f0e635f8faf800feddf5a61ec6ce88932fcdae6642930766ce31c61d3c64"
        )
        StrategyDefinition.objects.create(
            strategy="fixed-risk-v1", body=body, body_sha256=identity_digest(body)
        )
        before = self.fingerprint()
        MigrationExecutor(connection).migrate([("market", "0040_strategy_contract_corrections")])
        self.assertEqual(before, self.fingerprint(before))
        with self.assertRaisesMessage(ValueError, "strategy_version_conflict"):
            register("fixed-risk-v1")
        with self.assertRaisesMessage(RuntimeError, "phase5_populated_reverse_refused"):
            MigrationExecutor(connection).migrate([("market", "0039_strategy_library_guards")])
        self.assertEqual(before, self.fingerprint(before))
