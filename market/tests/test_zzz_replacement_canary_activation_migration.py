from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.historical_discovery import CANARY_V2_LOGICAL_KEY, run_discovery_chunk
from market.tests.test_replacement_canary_activation import (
    SucceedingCanaryClient,
    build_superseded_state,
    seed_governed_market,
    state_hashes,
)

ACTIVATION_SIGNATURE = "market_validate_replacement_canary_attempt"


class ReplacementCanaryActivationMigrationTests(TransactionTestCase):
    current = [("market", "0015_provider_observed_canary_activation")]
    previous = [("market", "0014_historical_discovery_supersession")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.current)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.current)
        super().tearDown()

    def migration_module(self):
        return import_module("market.migrations.0015_provider_observed_canary_activation")

    def governance_module(self):
        return import_module("market.migrations.0014_historical_discovery_supersession")

    def required_0014_fingerprints(self):
        migration = self.migration_module()
        with connection.cursor() as cursor:
            cursor.execute(
                self.governance_module().FUNCTION_FINGERPRINT_SQL,
                [list(migration.REQUIRED_0014_FUNCTIONS)],
            )
            return {name: (arguments, digest) for name, arguments, digest in cursor.fetchall()}

    def activation_function_count(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT count(*) FROM pg_proc p
                   JOIN pg_namespace n ON n.oid = p.pronamespace
                   WHERE n.nspname = current_schema() AND p.proname = %s""",
                [ACTIVATION_SIGNATURE],
            )
            return cursor.fetchone()[0]

    def test_dependency_and_empty_reverse_restores_exact_0014_behavior(self):
        migration = self.migration_module()
        self.assertEqual(
            migration.Migration.dependencies,
            [("market", "0014_historical_discovery_supersession")],
        )
        self.assertTrue(migration.Migration.atomic)

        MigrationExecutor(connection).migrate(self.previous)
        baseline = self.required_0014_fingerprints()
        self.assertEqual(
            baseline, {name: tuple(v) for name, v in migration.REQUIRED_0014_FUNCTIONS.items()}
        )
        self.assertEqual(self.activation_function_count(), 0)

        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(self.activation_function_count(), 1)
        applied = self.required_0014_fingerprints()
        self.assertNotEqual(
            applied["market_reject_superseded_discovery_write"],
            baseline["market_reject_superseded_discovery_write"],
        )

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(self.required_0014_fingerprints(), baseline)
        self.assertEqual(self.activation_function_count(), 0)
        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(self.activation_function_count(), 1)

    def test_preflight_rejects_altered_0014_governance(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_functiondef("
                "'market_reject_superseded_discovery_write()'::regprocedure)"
            )
            original = cursor.fetchone()[0]
            cursor.execute(
                """CREATE OR REPLACE FUNCTION market_reject_superseded_discovery_write()
                   RETURNS trigger AS $$BEGIN RETURN NEW; END$$ LANGUAGE plpgsql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "required 0014 function market_reject_superseded_discovery_write"
                " does not match its 0014 definition",
            ):
                MigrationExecutor(connection).migrate(self.current)
            self.assertEqual(self.activation_function_count(), 0)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)
        MigrationExecutor(connection).migrate(self.current)

    def test_preflight_rejects_partial_prior_installation(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute(
                """CREATE FUNCTION market_validate_replacement_canary_attempt(
                     plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer,
                     new_idempotency_key text, new_ingestion_run_id bigint)
                   RETURNS void AS $$BEGIN END$$ LANGUAGE plpgsql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "unexpected pre-existing function market_validate_replacement_canary_attempt",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DROP FUNCTION market_validate_replacement_canary_attempt("
                    "bigint, bigint, integer, text, bigint)"
                )
        MigrationExecutor(connection).migrate(self.current)

    def test_state_is_byte_identical_across_empty_reverse_and_reapply(self):
        seed_governed_market("canary activation migration test")
        superseded, replacement, _ = build_superseded_state()
        expected = state_hashes(superseded, replacement)

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(state_hashes(superseded, replacement), expected)

    def test_reversal_prohibited_after_replacement_attempt(self):
        seed_governed_market("canary activation reversal guard")
        _, replacement, _ = build_superseded_state()
        canary = replacement.chunks.select_related("instrument").get(
            logical_key=CANARY_V2_LOGICAL_KEY
        )
        attempt = run_discovery_chunk(
            CANARY_V2_LOGICAL_KEY, SucceedingCanaryClient(canary.canonical_request_sha256)
        )
        self.assertEqual(attempt.attempt_number, 1)

        with self.assertRaisesMessage(
            RuntimeError,
            "replacement discovery attempts prohibit canary activation reversal",
        ):
            MigrationExecutor(connection).migrate(self.previous)
