import hashlib
import json
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
    "market_validate_acquisition_canary",
    "market_ingestion_run_enforce",
    "market_governed_candle_reject_mutation",
)
NEW_FUNCTIONS = (
    "market_verify_replacement_canary_success",
    "market_validate_acquisition_audit",
    "market_enforce_acquisition_audit_completeness",
)


class Gate7BMigrationTests(TransactionTestCase):
    current = [("market", "0021_provider_observed_full_acquisition_activation")]
    previous = [("market", "0020_provider_observed_acquisition_canary_activation")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.current)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.current)
        super().tearDown()

    def migration_module(self):
        return import_module("market.migrations.0021_provider_observed_full_acquisition_activation")

    def gate7a_module(self):
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

    def audit_trigger_exists(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                   WHERE NOT t.tgisinternal AND c.relname='market_auditevent'
                     AND t.tgname='market_acquisition_audit_validate'"""
            )
            return cursor.fetchone()[0] == 1

    def completeness_trigger(self):
        """The deferred constraint trigger's installed shape, or None."""
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT t.tgdeferrable, t.tginitdeferred, t.tgconstraint <> 0, t.tgtype
                   FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                   WHERE NOT t.tgisinternal AND c.relname='market_ingestionrun'
                     AND t.tgname='market_acquisition_audit_complete'"""
            )
            rows = cursor.fetchall()
            return rows[0] if rows else None

    def build_gate7b_state(self):
        migrate_to(MIGRATION_0015)
        source = seed_governed_market("gate7b migration fixture")
        superseded, replacement, _, _ = build_retry_ready_state(source)
        migrate_to(MIGRATION_0016)
        record_attempt_two_success(source, replacement)
        MigrationExecutor(connection).migrate(self.current)
        return source, superseded, replacement

    def test_dependency_atomicity_and_no_data_migration(self):
        migration = self.migration_module()
        self.assertIn(
            ("market", "0020_provider_observed_acquisition_canary_activation"),
            migration.Migration.dependencies,
        )
        self.assertTrue(migration.Migration.atomic)
        self.assertEqual(len(migration.REQUIRED_0020_FUNCTIONS), 52)
        self.assertEqual(len(migration.REQUIRED_0020_TRIGGERS), 70)
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT count(*) FROM market_historicalingestionattempt a
                   JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
                   WHERE c.data_contract_sha256 IS NOT NULL"""
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_empty_reverse_restores_exact_0020_definitions(self):
        migration = self.migration_module()
        gate7a = self.gate7a_module()
        expected_0020 = {
            "market_validate_acquisition_canary": hashlib.md5(
                gate7a.ACQUISITION_CANARY_PROSRC.encode()
            ).hexdigest(),
            "market_ingestion_run_enforce": hashlib.md5(
                gate7a.INGESTION_RUN_GATE7A_PROSRC.encode()
            ).hexdigest(),
            "market_governed_candle_reject_mutation": hashlib.md5(
                gate7a.GOVERNED_CANDLE_GATE7A_PROSRC.encode()
            ).hexdigest(),
        }
        expected_gate7b = {
            "market_validate_acquisition_canary": hashlib.md5(
                migration.ACQUISITION_GATE7B_PROSRC.encode()
            ).hexdigest(),
            "market_ingestion_run_enforce": hashlib.md5(
                migration.INGESTION_RUN_GATE7B_PROSRC.encode()
            ).hexdigest(),
            "market_governed_candle_reject_mutation": hashlib.md5(
                migration.GOVERNED_CANDLE_GATE7B_PROSRC.encode()
            ).hexdigest(),
        }
        self.assertEqual(self.prosrc_md5s(REPLACED_FUNCTIONS), expected_gate7b)
        self.assertEqual(set(self.prosrc_md5s(NEW_FUNCTIONS)), set(NEW_FUNCTIONS))
        self.assertTrue(self.audit_trigger_exists())
        installed = self.completeness_trigger()
        self.assertIsNotNone(installed)
        deferrable, initially_deferred, is_constraint, tgtype = installed
        self.assertEqual((deferrable, initially_deferred, is_constraint), (True, True, True))
        self.assertEqual((tgtype & 1, tgtype & 2, tgtype & 16), (1, 0, 16))

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(self.prosrc_md5s(REPLACED_FUNCTIONS), expected_0020)
        self.assertEqual(self.prosrc_md5s(NEW_FUNCTIONS), {})
        self.assertFalse(self.audit_trigger_exists())
        self.assertIsNone(self.completeness_trigger())

        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(self.prosrc_md5s(REPLACED_FUNCTIONS), expected_gate7b)
        self.assertTrue(self.audit_trigger_exists())
        self.assertEqual(self.completeness_trigger(), installed)

    def test_preflight_rejects_altered_0020_governance_and_partial_installation(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_functiondef('market_acquisition_reject_truncate()'::regprocedure)"
            )
            original = cursor.fetchone()[0]
            cursor.execute(
                """CREATE OR REPLACE FUNCTION market_acquisition_reject_truncate()
                   RETURNS trigger AS $$BEGIN RETURN NULL; END$$ LANGUAGE plpgsql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "required 0020 function market_acquisition_reject_truncate"
                " does not match its 0020 definition",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)
        with connection.cursor() as cursor:
            cursor.execute(
                """CREATE FUNCTION market_gate7b_unexpected() RETURNS boolean
                   AS $$SELECT true$$ LANGUAGE sql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "unexpected function market_gate7b_unexpected outside the 0020 catalog",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP FUNCTION market_gate7b_unexpected()")
        MigrationExecutor(connection).migrate(self.current)

    def test_state_is_byte_identical_across_empty_reverse_and_reapply(self):
        source, superseded, replacement = self.build_gate7b_state()
        expected = state_hashes(superseded, replacement)
        expected_ledger = attempt_one_hash()

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)
        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)

    def test_reversal_prohibited_once_gate7b_evidence_exists(self):
        self.build_gate7b_state()
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_auditevent DISABLE TRIGGER USER")
            try:
                cursor.execute(
                    """INSERT INTO market_auditevent
                       (event_type,actor,subject_type,subject_id,payload,occurred_at)
                       VALUES ('market.replacement_acquisition_succeeded','gate7b-guard',
                               'HistoricalIngestionAttempt','999999',%s::jsonb,now())""",
                    [json.dumps({"guard": True})],
                )
            finally:
                cursor.execute("ALTER TABLE market_auditevent ENABLE TRIGGER USER")
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "replacement acquisition evidence prohibits gate7b reversal",
            ):
                MigrationExecutor(connection).migrate(self.previous)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE market_auditevent DISABLE TRIGGER USER")
                try:
                    cursor.execute("DELETE FROM market_auditevent WHERE actor='gate7b-guard'")
                finally:
                    cursor.execute("ALTER TABLE market_auditevent ENABLE TRIGGER USER")
        MigrationExecutor(connection).migrate(self.current)
