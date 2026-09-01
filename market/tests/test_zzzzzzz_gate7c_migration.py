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

VALIDATOR = "market_validate_replacement_registration"


class Gate7CMigrationTests(TransactionTestCase):
    current = [("market", "0022_provider_observed_registration_validator_correction")]
    previous = [("market", "0021_provider_observed_full_acquisition_activation")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.current)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.current)
        super().tearDown()

    def migration_module(self):
        return import_module(
            "market.migrations.0022_provider_observed_registration_validator_correction"
        )

    def contract_module(self):
        return import_module("market.migrations.0019_provider_observed_data_contract")

    def validator_md5(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT md5(prosrc) FROM pg_proc WHERE proname=%s", [VALIDATOR])
            rows = cursor.fetchall()
            return rows[0][0] if len(rows) == 1 else None

    def build_governed_state(self):
        migrate_to(MIGRATION_0015)
        source = seed_governed_market("gate7c migration fixture")
        superseded, replacement, _, _ = build_retry_ready_state(source)
        migrate_to(MIGRATION_0016)
        record_attempt_two_success(source, replacement)
        MigrationExecutor(connection).migrate(self.current)
        return superseded, replacement

    def test_dependency_atomicity_and_no_data_migration(self):
        # 1, 2
        migration = self.migration_module()
        self.assertEqual(
            migration.Migration.dependencies,
            [("market", "0021_provider_observed_full_acquisition_activation")],
        )
        self.assertTrue(migration.Migration.atomic)
        self.assertEqual(len(migration.REQUIRED_0021_FUNCTIONS), 55)
        self.assertEqual(len(migration.REQUIRED_0021_TRIGGERS), 72)
        # the migration only replaces one function: no schema or data operation
        self.assertEqual(
            [type(operation).__name__ for operation in migration.Migration.operations],
            ["RunPython", "RunPython"],
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM market_datasetregistration")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_only_the_registration_validator_changes_and_it_restores_exactly(self):
        # 3, 10, 11: the authentic catalog applies, reverse restores the exact
        # 0021 body, reapply reproduces the exact corrected body
        migration = self.migration_module()
        corrected = hashlib.md5(
            migration.CORRECTED_REPLACEMENT_REGISTRATION_PROSRC.encode()
        ).hexdigest()
        defective = hashlib.md5(
            self.contract_module().REPLACEMENT_REGISTRATION_PROSRC.encode()
        ).hexdigest()
        self.assertNotEqual(corrected, defective)

        def catalog():
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT proname, md5(prosrc) FROM pg_proc p
                       JOIN pg_namespace n ON n.oid=p.pronamespace
                       WHERE n.nspname=current_schema() AND proname LIKE 'market\\_%'"""
                )
                functions = dict(cursor.fetchall())
                cursor.execute(
                    """SELECT c.relname||'.'||t.tgname, t.tgtype, t.tgdeferrable, t.tginitdeferred
                       FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                       WHERE NOT t.tgisinternal AND c.relname LIKE 'market\\_%'"""
                )
                triggers = {row[0]: row[1:] for row in cursor.fetchall()}
            return functions, triggers

        applied_functions, applied_triggers = catalog()
        self.assertEqual(applied_functions[VALIDATOR], corrected)

        MigrationExecutor(connection).migrate(self.previous)
        reversed_functions, reversed_triggers = catalog()
        self.assertEqual(reversed_functions[VALIDATOR], defective)
        self.assertEqual(
            {name: digest for name, digest in reversed_functions.items() if name != VALIDATOR},
            {name: digest for name, digest in applied_functions.items() if name != VALIDATOR},
        )
        self.assertEqual(reversed_triggers, applied_triggers)

        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(catalog(), (applied_functions, applied_triggers))

    def test_preflight_rejects_altered_governance_and_partial_installation(self):
        # 4, 5, 6
        migration = self.migration_module()
        MigrationExecutor(connection).migrate(self.previous)

        # 4: the defective validator itself must be the reviewed 0019 body
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE OR REPLACE FUNCTION market_validate_replacement_registration("
                "reg market_datasetregistration) RETURNS void AS $$BEGIN RETURN; END$$"
                " LANGUAGE plpgsql"
            )
        with self.assertRaisesMessage(
            RuntimeError, "installed registration validator does not match its 0019 definition"
        ):
            MigrationExecutor(connection).migrate(self.current)

        # 6: a partial prior 0022 installation is refused too
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE OR REPLACE FUNCTION market_validate_replacement_registration("
                "reg market_datasetregistration) RETURNS void AS $governed$"
                + migration.CORRECTED_REPLACEMENT_REGISTRATION_PROSRC.replace("%", "%%")
                + "$governed$ LANGUAGE plpgsql"
            )
        with self.assertRaisesMessage(
            RuntimeError, "the corrected registration validator is already installed"
        ):
            MigrationExecutor(connection).migrate(self.current)

        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE OR REPLACE FUNCTION market_validate_replacement_registration("
                "reg market_datasetregistration) RETURNS void AS $governed$"
                + self.contract_module().REPLACEMENT_REGISTRATION_PROSRC.replace("%", "%%")
                + "$governed$ LANGUAGE plpgsql"
            )

        # 5: an unrelated altered governed function blocks the complete catalog
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
                "required 0021 function market_acquisition_reject_truncate"
                " does not match its 0021 definition",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)

        with connection.cursor() as cursor:
            cursor.execute(
                """CREATE FUNCTION market_gate7c_unexpected() RETURNS boolean
                   AS $$SELECT true$$ LANGUAGE sql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError, "unexpected function market_gate7c_unexpected"
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP FUNCTION market_gate7c_unexpected()")
        MigrationExecutor(connection).migrate(self.current)

    def test_state_is_byte_identical_across_empty_reverse_and_reapply(self):
        # 12
        superseded, replacement = self.build_governed_state()
        expected = state_hashes(superseded, replacement)
        expected_ledger = attempt_one_hash()

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)
        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)
