from importlib import import_module

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.models import (
    HistoricalDiscoveryApproval,
    HistoricalDiscoveryPlan,
    HistoricalDiscoveryRegistration,
)
from market.tests.test_replacement_canary_activation import (
    MIGRATION_0015,
    attempt_one_hash,
    build_retry_ready_state,
    migrate_to,
    record_attempt_two_success,
    seed_governed_market,
    state_hashes,
)

GOVERNED_FUNCTIONS = (
    "market_validate_discovery_seal_deferred",
    "market_reject_superseded_discovery_write",
    "market_validate_gate5_registration",
)


class Gate5RegistrationMigrationTests(TransactionTestCase):
    current = [("market", "0018_provider_observed_discovery_registration_activation")]
    previous = [("market", "0017_provider_observed_full_discovery_activation")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.current)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.current)
        super().tearDown()

    def migration_module(self):
        return import_module(
            "market.migrations.0018_provider_observed_discovery_registration_activation"
        )

    def prosrc_md5s(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT proname, md5(prosrc) FROM pg_proc p
                   JOIN pg_namespace n ON n.oid=p.pronamespace
                   WHERE n.nspname=current_schema() AND proname = ANY(%s)""",
                [list(GOVERNED_FUNCTIONS)],
            )
            return dict(cursor.fetchall())

    def build_gate5_state(self):
        migrate_to(MIGRATION_0015)
        source = seed_governed_market("gate5 migration fixture")
        superseded, replacement, _, _ = build_retry_ready_state(source)
        MigrationExecutor(connection).migrate(
            [("market", "0016_provider_observed_h1_alignment_retry")]
        )
        record_attempt_two_success(source, replacement)
        MigrationExecutor(connection).migrate(self.current)
        return source, superseded, replacement

    def test_dependency_atomicity_and_no_data_migration(self):
        migration = self.migration_module()
        self.assertEqual(
            migration.Migration.dependencies,
            [("market", "0017_provider_observed_full_discovery_activation")],
        )
        self.assertTrue(migration.Migration.atomic)
        self.assertFalse(HistoricalDiscoveryApproval.objects.exists())
        self.assertFalse(HistoricalDiscoveryRegistration.objects.exists())
        self.assertFalse(HistoricalDiscoveryPlan.objects.filter(sealed_at__isnull=False).exists())

    def test_empty_reverse_restores_exact_prior_definitions(self):
        migration = self.migration_module()
        import hashlib

        expected_0017 = {
            "market_validate_discovery_seal_deferred": hashlib.md5(
                migration.SEAL_0013_PROSRC.encode()
            ).hexdigest(),
            "market_reject_superseded_discovery_write": hashlib.md5(
                migration.REJECT_SUPERSEDED_0016_PROSRC.encode()
            ).hexdigest(),
        }
        expected_gate5 = {
            "market_validate_discovery_seal_deferred": hashlib.md5(
                migration.SEAL_GATE5_PROSRC.encode()
            ).hexdigest(),
            "market_reject_superseded_discovery_write": hashlib.md5(
                migration.REJECT_SUPERSEDED_GATE5_PROSRC.encode()
            ).hexdigest(),
            "market_validate_gate5_registration": hashlib.md5(
                migration.GATE5_REGISTRATION_PROSRC.encode()
            ).hexdigest(),
        }
        self.assertEqual(self.prosrc_md5s(), expected_gate5)

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(self.prosrc_md5s(), expected_0017)

        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(self.prosrc_md5s(), expected_gate5)

    def test_preflight_rejects_altered_0017_governance(self):
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
                "required 0017 function market_reject_superseded_discovery_write"
                " does not match its 0017 definition",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)
        MigrationExecutor(connection).migrate(self.current)

    def test_preflight_rejects_altered_evidence_governance(self):
        """The battery must cover evidence governance beyond the functions
        0018 replaces: altering the observation validator blocks activation."""
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_functiondef('market_validate_discovery_observation()'::regprocedure)"
            )
            original = cursor.fetchone()[0]
            cursor.execute(
                """CREATE OR REPLACE FUNCTION market_validate_discovery_observation()
                   RETURNS trigger AS $$BEGIN RETURN NEW; END$$ LANGUAGE plpgsql"""
            )
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "required 0017 function market_validate_discovery_observation"
                " does not match its 0017 definition",
            ):
                MigrationExecutor(connection).migrate(self.current)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)
        MigrationExecutor(connection).migrate(self.current)

    def test_state_is_byte_identical_across_empty_reverse_and_reapply(self):
        source, superseded, replacement = self.build_gate5_state()
        expected = state_hashes(superseded, replacement)
        expected_ledger = attempt_one_hash()

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)
        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(state_hashes(superseded, replacement), expected)
        self.assertEqual(attempt_one_hash(), expected_ledger)

    def test_reversal_prohibited_once_approval_evidence_exists(self):
        source, superseded, replacement = self.build_gate5_state()
        user = get_user_model().objects.create_user("gate5-reversal-guard")
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_historicaldiscoveryapproval DISABLE TRIGGER USER")
            try:
                cursor.execute(
                    """INSERT INTO market_historicaldiscoveryapproval
                       (plan_id,approved_by_id,global_semantic_inventory_sha256,
                        accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                       VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                    [replacement.pk, user.pk, "a" * 64, "b" * 64, "c" * 64],
                )
            finally:
                cursor.execute("ALTER TABLE market_historicaldiscoveryapproval ENABLE TRIGGER USER")
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "approval, registration or sealing evidence prohibits gate5 reversal",
            ):
                MigrationExecutor(connection).migrate(self.previous)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE market_historicaldiscoveryapproval DISABLE TRIGGER USER"
                )
                try:
                    cursor.execute(
                        "DELETE FROM market_historicaldiscoveryapproval WHERE plan_id=%s",
                        [replacement.pk],
                    )
                finally:
                    cursor.execute(
                        "ALTER TABLE market_historicaldiscoveryapproval ENABLE TRIGGER USER"
                    )
        MigrationExecutor(connection).migrate(self.current)
