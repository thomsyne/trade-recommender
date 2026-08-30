import hashlib
from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.tests.test_replacement_canary_activation import (
    MIGRATION_0015,
    attempt_one_hash,
    build_retry_ready_state,
    migrate_to,
    record_attempt_two_success,
    seed_governed_market,
    state_hashes,
)

REPLACED_FUNCTIONS = (
    "market_validate_historical_plan",
    "market_validate_historical_chunk",
    "market_validate_historical_dataset",
    "market_validate_dataset_registration",
)
NEW_FUNCTIONS = (
    "market_validate_data_contract",
    "market_data_contract_reject_mutation",
    "market_data_contract_reject_truncate",
    "market_validate_replacement_plan",
    "market_validate_replacement_chunk",
    "market_validate_replacement_dataset",
    "market_validate_replacement_registration",
)


class Gate1BMigrationTests(TransactionTestCase):
    current = [("market", "0019_provider_observed_data_contract")]
    previous = [("market", "0018_provider_observed_discovery_registration_activation")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.current)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.current)
        super().tearDown()

    def migration_module(self):
        return import_module("market.migrations.0019_provider_observed_data_contract")

    def prosrc_md5s(self, names):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT proname, md5(prosrc) FROM pg_proc p
                   JOIN pg_namespace n ON n.oid=p.pronamespace
                   WHERE n.nspname=current_schema() AND proname = ANY(%s)""",
                [list(names)],
            )
            return dict(cursor.fetchall())

    def build_gate1b_state(self):
        migrate_to(MIGRATION_0015)
        source = seed_governed_market("gate1b migration fixture")
        superseded, replacement, _, _ = build_retry_ready_state(source)
        MigrationExecutor(connection).migrate(
            [("market", "0016_provider_observed_h1_alignment_retry")]
        )
        record_attempt_two_success(source, replacement)
        MigrationExecutor(connection).migrate(self.current)
        return source, superseded, replacement

    def test_dependency_atomicity_and_no_data_migration(self):
        migration = self.migration_module()
        self.assertIn(
            ("market", "0018_provider_observed_discovery_registration_activation"),
            migration.Migration.dependencies,
        )
        self.assertTrue(migration.Migration.atomic)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM market_historicaldatacontract")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_empty_reverse_restores_exact_0018_definitions(self):
        migration = self.migration_module()
        expected_0018 = {
            "market_validate_historical_plan": hashlib.md5(
                migration.HISTORICAL_PLAN_0018_PROSRC.encode()
            ).hexdigest(),
            "market_validate_historical_chunk": hashlib.md5(
                migration.HISTORICAL_CHUNK_0018_PROSRC.encode()
            ).hexdigest(),
            "market_validate_historical_dataset": hashlib.md5(
                migration.HISTORICAL_DATASET_0018_PROSRC.encode()
            ).hexdigest(),
            "market_validate_dataset_registration": hashlib.md5(
                migration.DATASET_REGISTRATION_0018_PROSRC.encode()
            ).hexdigest(),
        }
        expected_gate1b = {
            "market_validate_historical_plan": hashlib.md5(
                migration.HISTORICAL_PLAN_GATE1B_PROSRC.encode()
            ).hexdigest(),
            "market_validate_historical_chunk": hashlib.md5(
                migration.HISTORICAL_CHUNK_GATE1B_PROSRC.encode()
            ).hexdigest(),
            "market_validate_historical_dataset": hashlib.md5(
                migration.HISTORICAL_DATASET_GATE1B_PROSRC.encode()
            ).hexdigest(),
            "market_validate_dataset_registration": hashlib.md5(
                migration.DATASET_REGISTRATION_GATE1B_PROSRC.encode()
            ).hexdigest(),
        }
        self.assertEqual(self.prosrc_md5s(REPLACED_FUNCTIONS), expected_gate1b)
        self.assertEqual(set(self.prosrc_md5s(NEW_FUNCTIONS)), set(NEW_FUNCTIONS))

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(self.prosrc_md5s(REPLACED_FUNCTIONS), expected_0018)
        self.assertEqual(self.prosrc_md5s(NEW_FUNCTIONS), {})

        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(self.prosrc_md5s(REPLACED_FUNCTIONS), expected_gate1b)

    def test_preflight_rejects_altered_0018_governance(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_functiondef('market_validate_historical_plan()'::regprocedure)"
            )
            original = cursor.fetchone()[0]
            cursor.execute(
                """CREATE OR REPLACE FUNCTION market_validate_historical_plan()
                   RETURNS trigger AS $$BEGIN RETURN NEW; END$$ LANGUAGE plpgsql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "required 0018 function market_validate_historical_plan"
                " does not match its 0018 definition",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)
        MigrationExecutor(connection).migrate(self.current)

    def test_state_is_byte_identical_across_empty_reverse_and_reapply(self):
        source, superseded, replacement = self.build_gate1b_state()
        expected = state_hashes(superseded, replacement)
        expected_ledger = attempt_one_hash()

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)
        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)

    def test_reversal_prohibited_once_contract_evidence_exists(self):
        self.build_gate1b_state()
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_datasetversion DISABLE TRIGGER USER")
            try:
                cursor.execute(
                    """INSERT INTO market_datasetversion
                       (name,version,description,manifest,manifest_sha256,
                        data_contract_sha256,created_at)
                       VALUES ('gate1b-guard','v1','','{}'::jsonb,%s,%s,now())""",
                    ["9" * 64, "8" * 64],
                )
            finally:
                cursor.execute("ALTER TABLE market_datasetversion ENABLE TRIGGER USER")
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "provider-observed contract evidence prohibits gate1b reversal",
            ):
                MigrationExecutor(connection).migrate(self.previous)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE market_datasetversion DISABLE TRIGGER USER")
                try:
                    cursor.execute("DELETE FROM market_datasetversion WHERE name='gate1b-guard'")
                finally:
                    cursor.execute("ALTER TABLE market_datasetversion ENABLE TRIGGER USER")
        MigrationExecutor(connection).migrate(self.current)
