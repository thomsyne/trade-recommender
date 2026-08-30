from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.historical_discovery import run_discovery_chunk
from market.models import HistoricalTimestampInventory
from market.tests.test_gate4_full_discovery import WaveSuccessClient
from market.tests.test_replacement_canary_activation import (
    MIGRATION_0015,
    attempt_one_hash,
    build_retry_ready_state,
    migrate_to,
    record_attempt_two_success,
    seed_governed_market,
    state_hashes,
)

CANARY_FUNCTION = "market_validate_replacement_canary_attempt"


class FullDiscoveryActivationMigrationTests(TransactionTestCase):
    current = [("market", "0017_provider_observed_full_discovery_activation")]
    previous = [("market", "0016_provider_observed_h1_alignment_retry")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.current)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.current)
        super().tearDown()

    def migration_module(self):
        return import_module("market.migrations.0017_provider_observed_full_discovery_activation")

    def governance_module(self):
        return import_module("market.migrations.0014_historical_discovery_supersession")

    def canary_fingerprint(self):
        with connection.cursor() as cursor:
            cursor.execute(self.governance_module().FUNCTION_FINGERPRINT_SQL, [[CANARY_FUNCTION]])
            rows = cursor.fetchall()
        self.assertEqual(len(rows), 1)
        name, arguments, digest = rows[0]
        return (arguments, digest)

    def build_gate4_state(self):
        """Requires the schema at previous (0016)."""
        migrate_to(MIGRATION_0015)
        source = seed_governed_market("gate4 migration fixture")
        superseded, replacement, _, _ = build_retry_ready_state(source)
        MigrationExecutor(connection).migrate(self.previous)
        record_attempt_two_success(source, replacement)
        return source, superseded, replacement

    def test_dependency_and_empty_reverse_restores_exact_0016_behavior(self):
        migration = self.migration_module()
        self.assertEqual(
            migration.Migration.dependencies,
            [("market", "0016_provider_observed_h1_alignment_retry")],
        )
        self.assertTrue(migration.Migration.atomic)
        pin = tuple(migration.REQUIRED_0016_FUNCTIONS[CANARY_FUNCTION])

        MigrationExecutor(connection).migrate(self.previous)
        baseline = self.canary_fingerprint()
        self.assertEqual(baseline, pin)

        MigrationExecutor(connection).migrate(self.current)
        self.assertNotEqual(self.canary_fingerprint(), baseline)

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(self.canary_fingerprint(), baseline)
        MigrationExecutor(connection).migrate(self.current)
        self.assertNotEqual(self.canary_fingerprint(), baseline)

    def test_preflight_rejects_altered_0016_governance(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_functiondef('market_validate_replacement_canary_attempt("
                "bigint, bigint, integer, text, bigint)'::regprocedure)"
            )
            original = cursor.fetchone()[0]
            cursor.execute(
                """CREATE OR REPLACE FUNCTION market_validate_replacement_canary_attempt(
                     plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer,
                     new_idempotency_key text, new_ingestion_run_id bigint)
                   RETURNS void AS $$BEGIN END$$ LANGUAGE plpgsql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "required 0016 function market_validate_replacement_canary_attempt"
                " does not match its 0016 definition",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)
        MigrationExecutor(connection).migrate(self.current)

    def test_state_is_byte_identical_across_empty_reverse_and_reapply(self):
        source, superseded, replacement = self.build_gate4_state()
        expected = state_hashes(superseded, replacement)
        expected_ledger = attempt_one_hash()

        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)
        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)
        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)

    def test_reversal_prohibited_after_any_gate4_attempt(self):
        source, _, replacement = self.build_gate4_state()
        MigrationExecutor(connection).migrate(self.current)
        target = replacement.chunks.select_related("instrument").order_by("ordinal").first()
        attempt = run_discovery_chunk(target.logical_key, WaveSuccessClient(replacement))
        self.assertEqual(attempt.attempt_number, 1)
        self.assertTrue(HistoricalTimestampInventory.objects.filter(chunk=target).exists())

        with self.assertRaisesMessage(
            RuntimeError,
            "full discovery attempts prohibit gate4 activation reversal",
        ):
            MigrationExecutor(connection).migrate(self.previous)
