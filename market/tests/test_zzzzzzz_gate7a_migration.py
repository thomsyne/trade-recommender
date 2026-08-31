import hashlib
from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.tests.test_replacement_canary_activation import (
    MIGRATION_0015,
    MIGRATION_0016,
    attempt_one_hash,
    build_retry_ready_state,
    migrate_to,
    record_attempt_two_success,
    seed_governed_market,
    state_hashes,
)

REPLACED_FUNCTIONS = (
    "market_validate_historical_attempt",
    "market_ingestion_run_enforce",
    "market_governed_candle_reject_mutation",
)
ACTIVATION_FUNCTION = "market_validate_acquisition_canary"


class Gate7AMigrationTests(TransactionTestCase):
    current = [("market", "0020_provider_observed_acquisition_canary_activation")]
    previous = [("market", "0019_provider_observed_data_contract")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.current)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.current)
        super().tearDown()

    def migration_module(self):
        return import_module(
            "market.migrations.0020_provider_observed_acquisition_canary_activation"
        )

    def prosrc_md5s(self, names):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT proname, md5(prosrc) FROM pg_proc p
                   JOIN pg_namespace n ON n.oid=p.pronamespace
                   WHERE n.nspname=current_schema() AND proname = ANY(%s)""",
                [list(names)],
            )
            return dict(cursor.fetchall())

    def build_gate7a_state(self):
        migrate_to(MIGRATION_0015)
        source = seed_governed_market("gate7a migration fixture")
        superseded, replacement, _, _ = build_retry_ready_state(source)
        migrate_to(MIGRATION_0016)
        record_attempt_two_success(source, replacement)
        MigrationExecutor(connection).migrate(self.current)
        return source, superseded, replacement

    def test_dependency_atomicity_and_no_data_migration(self):
        migration = self.migration_module()
        self.assertIn(
            ("market", "0019_provider_observed_data_contract"),
            migration.Migration.dependencies,
        )
        self.assertTrue(migration.Migration.atomic)
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT count(*) FROM market_historicalingestionattempt a
                   JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
                   WHERE c.data_contract_sha256 IS NOT NULL"""
            )
            self.assertEqual(cursor.fetchone()[0], 0)
        self.assertEqual(len(migration.REQUIRED_0019_FUNCTIONS), 50)
        self.assertEqual(len(migration.REQUIRED_0019_TRIGGERS), 60)

    def test_empty_reverse_restores_exact_0019_definitions(self):
        migration = self.migration_module()
        expected_0019 = {
            "market_validate_historical_attempt": hashlib.md5(
                migration.HISTORICAL_ATTEMPT_0019_PROSRC.encode()
            ).hexdigest(),
            "market_ingestion_run_enforce": hashlib.md5(
                migration.INGESTION_RUN_0019_PROSRC.encode()
            ).hexdigest(),
            "market_governed_candle_reject_mutation": hashlib.md5(
                migration.GOVERNED_CANDLE_0019_PROSRC.encode()
            ).hexdigest(),
        }
        expected_gate7a = {
            "market_validate_historical_attempt": hashlib.md5(
                migration.HISTORICAL_ATTEMPT_GATE7A_PROSRC.encode()
            ).hexdigest(),
            "market_ingestion_run_enforce": hashlib.md5(
                migration.INGESTION_RUN_GATE7A_PROSRC.encode()
            ).hexdigest(),
            "market_governed_candle_reject_mutation": hashlib.md5(
                migration.GOVERNED_CANDLE_GATE7A_PROSRC.encode()
            ).hexdigest(),
        }
        self.assertEqual(self.prosrc_md5s(REPLACED_FUNCTIONS), expected_gate7a)
        self.assertEqual(set(self.prosrc_md5s([ACTIVATION_FUNCTION])), {ACTIVATION_FUNCTION})

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(self.prosrc_md5s(REPLACED_FUNCTIONS), expected_0019)
        self.assertEqual(self.prosrc_md5s([ACTIVATION_FUNCTION]), {})

        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(self.prosrc_md5s(REPLACED_FUNCTIONS), expected_gate7a)

    def test_preflight_rejects_altered_0019_governance_and_partial_installation(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_functiondef('market_validate_historical_attempt()'::regprocedure)"
            )
            original = cursor.fetchone()[0]
            cursor.execute(
                """CREATE OR REPLACE FUNCTION market_validate_historical_attempt()
                   RETURNS trigger AS $$BEGIN RETURN NEW; END$$ LANGUAGE plpgsql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "required 0019 function market_validate_historical_attempt"
                " does not match its 0019 definition",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)
        with connection.cursor() as cursor:
            cursor.execute(
                """CREATE FUNCTION market_gate7a_unexpected() RETURNS boolean
                   AS $$SELECT true$$ LANGUAGE sql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "unexpected function market_gate7a_unexpected outside the 0019 catalog",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP FUNCTION market_gate7a_unexpected()")
        MigrationExecutor(connection).migrate(self.current)

    def test_state_is_byte_identical_across_empty_reverse_and_reapply(self):
        source, superseded, replacement = self.build_gate7a_state()
        expected = state_hashes(superseded, replacement)
        expected_ledger = attempt_one_hash()

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)
        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)

    def test_reversal_prohibited_once_replacement_acquisition_evidence_exists(self):
        source, _, _ = self.build_gate7a_state()
        with connection.cursor() as cursor:
            for table in ("market_datasetversion", "market_ingestionrun"):
                cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
            try:
                cursor.execute(
                    """INSERT INTO market_datasetversion
                       (name,version,description,manifest,manifest_sha256,
                        data_contract_sha256,created_at)
                       VALUES ('gate7a-guard','v1','','{}'::jsonb,%s,%s,now())
                       RETURNING id""",
                    ["9" * 64, "8" * 64],
                )
                dataset_id = cursor.fetchone()[0]
                cursor.execute("SELECT id FROM market_instrument LIMIT 1")
                instrument_id = cursor.fetchone()[0]
                cursor.execute(
                    """INSERT INTO market_ingestionrun
                       (granularity,requested_from,requested_to,parameters,
                        request_manifest_hash,status,fetched_count,stored_count,
                        rejected_count,failure_reason,started_at,instrument_id,
                        source_id,dataset_version_id)
                       VALUES ('H1',now(),now(),'{}'::jsonb,%s,'failed',0,0,0,
                               'gate7a-guard',now(),%s,%s,%s)""",
                    ["7" * 64, instrument_id, source.pk, dataset_id],
                )
            finally:
                for table in ("market_datasetversion", "market_ingestionrun"):
                    cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "replacement acquisition evidence prohibits gate7a reversal",
            ):
                MigrationExecutor(connection).migrate(self.previous)
        finally:
            with connection.cursor() as cursor:
                for table in ("market_datasetversion", "market_ingestionrun"):
                    cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
                try:
                    cursor.execute(
                        "DELETE FROM market_ingestionrun WHERE failure_reason='gate7a-guard'"
                    )
                    cursor.execute("DELETE FROM market_datasetversion WHERE name='gate7a-guard'")
                finally:
                    for table in ("market_datasetversion", "market_ingestionrun"):
                        cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        MigrationExecutor(connection).migrate(self.current)
