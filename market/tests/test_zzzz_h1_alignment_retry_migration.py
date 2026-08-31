from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.tests.test_replacement_canary_activation import (
    attempt_one_hash,
    build_retry_ready_state,
    record_attempt_two_success,
    seed_governed_market,
    state_hashes,
)

DIAGNOSTICS_FUNCTION = "market_discovery_structural_diagnostics_valid"
REPLACED_FUNCTIONS = (
    "market_validate_replacement_canary_attempt",
    "market_validate_discovery_audit_insert",
    "market_validate_discovery_observation",
)


class H1AlignmentRetryMigrationTests(TransactionTestCase):
    current = [("market", "0016_provider_observed_h1_alignment_retry")]
    previous = [("market", "0015_provider_observed_canary_activation")]
    latest = [("market", "0019_provider_observed_data_contract")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.current)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.latest)
        super().tearDown()

    def migration_module(self):
        return import_module("market.migrations.0016_provider_observed_h1_alignment_retry")

    def governance_module(self):
        return import_module("market.migrations.0014_historical_discovery_supersession")

    def replaced_fingerprints(self):
        with connection.cursor() as cursor:
            cursor.execute(
                self.governance_module().FUNCTION_FINGERPRINT_SQL, [list(REPLACED_FUNCTIONS)]
            )
            return {name: (arguments, digest) for name, arguments, digest in cursor.fetchall()}

    def diagnostics_function_count(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT count(*) FROM pg_proc p
                   JOIN pg_namespace n ON n.oid = p.pronamespace
                   WHERE n.nspname = current_schema() AND p.proname = %s""",
                [DIAGNOSTICS_FUNCTION],
            )
            return cursor.fetchone()[0]

    def test_dependency_and_empty_reverse_restores_exact_0015_behavior(self):
        migration = self.migration_module()
        self.assertEqual(
            migration.Migration.dependencies,
            [("market", "0015_provider_observed_canary_activation")],
        )
        self.assertTrue(migration.Migration.atomic)
        pins = {
            name: tuple(value)
            for name, value in migration.REQUIRED_0015_FUNCTIONS.items()
            if name in REPLACED_FUNCTIONS
        }

        MigrationExecutor(connection).migrate(self.previous)
        baseline = self.replaced_fingerprints()
        self.assertEqual(baseline, pins)
        self.assertEqual(self.diagnostics_function_count(), 0)

        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(self.diagnostics_function_count(), 1)
        applied = self.replaced_fingerprints()
        for name in REPLACED_FUNCTIONS:
            self.assertNotEqual(applied[name], baseline[name], name)

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(self.replaced_fingerprints(), baseline)
        self.assertEqual(self.diagnostics_function_count(), 0)
        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(self.diagnostics_function_count(), 1)

    def test_preflight_rejects_altered_0015_governance(self):
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
                "required 0015 function market_validate_replacement_canary_attempt"
                " does not match its 0015 definition",
            ):
                MigrationExecutor(connection).migrate(self.current)
            self.assertEqual(self.diagnostics_function_count(), 0)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)
        MigrationExecutor(connection).migrate(self.current)

    def test_preflight_rejects_partial_prior_installation(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute(
                """CREATE FUNCTION market_discovery_structural_diagnostics_valid(
                     diagnostics jsonb, fetched integer)
                   RETURNS boolean AS $$BEGIN RETURN true; END$$ LANGUAGE plpgsql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "unexpected pre-existing function market_discovery_structural_diagnostics_valid",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DROP FUNCTION market_discovery_structural_diagnostics_valid(jsonb, integer)"
                )
        MigrationExecutor(connection).migrate(self.current)

    def test_state_is_byte_identical_across_empty_reverse_and_reapply(self):
        MigrationExecutor(connection).migrate(self.previous)
        source = seed_governed_market("h1 retry migration byte identity")
        superseded, replacement, _, _ = build_retry_ready_state(source)
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

    def test_reversal_prohibited_after_retry_attempt(self):
        MigrationExecutor(connection).migrate(self.previous)
        source = seed_governed_market("h1 retry migration reversal guard")
        _, replacement, _, _ = build_retry_ready_state(source)
        MigrationExecutor(connection).migrate(self.current)
        attempt = record_attempt_two_success(source, replacement)
        self.assertEqual(attempt.attempt_number, 2)

        with self.assertRaisesMessage(
            RuntimeError,
            "canary retry evidence prohibits h1 alignment migration reversal",
        ):
            MigrationExecutor(connection).migrate(self.previous)
