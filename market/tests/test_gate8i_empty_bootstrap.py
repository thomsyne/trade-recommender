"""Exercise the replacement on a new disposable 0026 database per scenario."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from django.db import OperationalError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase

from market.tests.historical_database import HistoricalDatabaseMixin

bootstrap = import_module("market.migrations.0027_gate8i_empty_bootstrap")
original = bootstrap.original
BEFORE = [("market", "0026_gate8g_successor_acquisition_activation")]
AFTER = [("market", "0027_gate8i_empty_bootstrap")]


class Gate8IEmptyBootstrapTests(HistoricalDatabaseMixin, TransactionTestCase):
    historical_market_migration = "0026_"

    def snapshot(self):
        with connection.cursor() as cursor:
            catalog = original.gate8g._catalog(cursor)
            cursor.execute("SELECT id,app,name,applied FROM django_migrations ORDER BY id")
            recorder = cursor.fetchall()
            cursor.execute(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() AND c.relkind IN ('r','p','m') "
                "AND c.relname<>'django_migrations' ORDER BY c.relname"
            )
            tables = [row[0] for row in cursor.fetchall()]
            rows = {}
            for table in tables:
                cursor.execute(
                    f"SELECT to_jsonb(t)::text FROM {connection.ops.quote_name(table)} t "
                    "ORDER BY to_jsonb(t)::text"
                )
                rows[table] = cursor.fetchall()
            cursor.execute(
                "SELECT sequencename,last_value FROM pg_sequences "
                "WHERE schemaname=current_schema() AND sequencename<>'django_migrations_id_seq' "
                "ORDER BY sequencename"
            )
            sequences = cursor.fetchall()
            cursor.execute(
                "SELECT c.relname,c.relkind,c.relrowsecurity,c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() ORDER BY c.relname"
            )
            relations = cursor.fetchall()
            cursor.execute("SELECT * FROM pg_policies WHERE schemaname=current_schema()")
            policies = cursor.fetchall()
        return catalog, recorder, rows, sequences, relations, policies

    def test_empty_installs_exact_delta_and_second_run_is_noop(self):
        before = self.snapshot()
        MigrationExecutor(connection).migrate(AFTER)
        after = self.snapshot()
        self.assertEqual(before[2:], after[2:])
        self.assertTrue(all(not rows for rows in after[2].values()))
        self.assertEqual(
            original._without_registration_validator(before[0]),
            original._without_registration_validator(after[0]),
        )
        with connection.cursor() as cursor:
            self.assertEqual(
                original.gate8g._installed_body(cursor, "market_validate_replacement_registration"),
                original.GATE8I_REGISTRATION_PROSRC,
            )
        self.assertEqual(after[1][: len(before[1])], before[1])
        self.assertEqual(
            {(row[1], row[2]) for row in after[1][len(before[1]) :]},
            {AFTER[0], ("market", "0027_gate8i_final_dataset_acceptance")},
        )
        MigrationExecutor(connection).migrate(AFTER)
        self.assertEqual(after, self.snapshot())
        MigrationExecutor(connection).migrate(BEFORE)
        with connection.cursor() as cursor:
            original._require_0026_catalog(cursor)
        self.assertEqual(before[2:], self.snapshot()[2:])
        MigrationExecutor(connection).migrate(AFTER)
        reapplied = self.snapshot()
        self.assertEqual(after[0], reapplied[0])
        self.assertEqual(after[2:], reapplied[2:])

    def test_representative_original_recorder_adds_only_replacement_record(self):
        # Loader/recorder fixture ONLY, explicitly not a deployed backup or an
        # accepted acquisition. Never use this to bootstrap a usable test head.
        # The deliberately unchanged 0026 catalog proves no operation executes.
        MigrationRecorder(connection).record_applied(
            "market", "0027_gate8i_final_dataset_acceptance"
        )
        apps = MigrationExecutor(connection).loader.project_state(BEFORE).apps
        apps.get_model("auth", "User").objects.create(username="representative")
        before = self.snapshot()
        with patch.object(
            bootstrap.Migration.operations[0],
            "code",
            side_effect=AssertionError("must not execute"),
        ):
            executor = MigrationExecutor(connection)
            self.assertEqual(executor.migration_plan(AFTER), [])
            executor.migrate(AFTER)
        after = self.snapshot()
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[2:], after[2:])
        self.assertEqual(before[1], after[1][:-1])
        self.assertEqual(after[1][-1][1:3], AFTER[0])
        MigrationExecutor(connection).migrate(AFTER)
        self.assertEqual(after, self.snapshot())

    def assert_original_refusal(self):
        before = self.snapshot()
        # Explicitly rebuild without replacements only to test original 0027.
        executor = MigrationExecutor(connection)
        executor.loader.replace_migrations = False
        executor.loader.build_graph()
        with self.assertRaises(RuntimeError) as published:
            executor.migrate([("market", "0027_gate8i_final_dataset_acceptance")])
        self.assertEqual(
            str(published.exception), "Gate 8I requires the accepted complete successor acquisition"
        )
        self.assertEqual(before, self.snapshot())
        with patch.object(original, "forward", wraps=original.forward) as forward:
            with self.assertRaisesMessage(RuntimeError, str(published.exception)):
                MigrationExecutor(connection).migrate(AFTER)
            forward.assert_called_once()
        self.assertEqual(before, self.snapshot())

    def test_metadata_only_preserves_original_failure_atomically(self):
        apps = MigrationExecutor(connection).loader.project_state(BEFORE).apps
        apps.get_model("market", "SourceRegistry").objects.create(
            name="unaccepted metadata", tier="quarantine", base_url="https://example.invalid"
        )
        self.assert_original_refusal()

    def test_audit_only_preserves_original_failure_atomically(self):
        apps = MigrationExecutor(connection).loader.project_state(BEFORE).apps
        apps.get_model("market", "AuditEvent").objects.create(
            event_type="test.unaccepted", actor="test", subject_type="test", subject_id="1"
        )
        self.assert_original_refusal()

    def test_empty_catalog_drift_refused_atomically(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE FUNCTION market_unreviewed() RETURNS integer LANGUAGE sql AS 'SELECT 1'"
            )
        before = self.snapshot()
        with self.assertRaisesMessage(RuntimeError, "complete migration 0026 function catalog"):
            MigrationExecutor(connection).migrate(AFTER)
        self.assertEqual(before, self.snapshot())

    def test_disabled_trigger_refused_atomically(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT c.relname,t.tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid=t.tgrelid "
                "WHERE NOT t.tgisinternal AND c.relname LIKE 'market_%' "
                "ORDER BY c.relname,t.tgname LIMIT 1"
            )
            table, trigger = cursor.fetchone()
            quote = connection.ops.quote_name
            cursor.execute(f"ALTER TABLE {quote(table)} DISABLE TRIGGER {quote(trigger)}")
        before = self.snapshot()
        with self.assertRaisesMessage(RuntimeError, "does not match its catalog pin"):
            MigrationExecutor(connection).migrate(AFTER)
        self.assertEqual(before, self.snapshot())

    def test_user_only_is_not_framework_bookkeeping(self):
        apps = MigrationExecutor(connection).loader.project_state(BEFORE).apps
        apps.get_model("auth", "User").objects.create(username="unaccepted")
        self.assert_original_refusal()

    def test_unknown_populated_table_is_not_ignored(self):
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE unrecognized_evidence (id integer PRIMARY KEY)")
            cursor.execute("INSERT INTO unrecognized_evidence VALUES (42)")
        self.assert_original_refusal()

    def test_empty_materialized_view_delegates_atomically(self):
        with connection.cursor() as cursor:
            cursor.execute("CREATE MATERIALIZED VIEW unsupported AS SELECT 42 AS n WHERE false")
        self.assert_original_refusal()

    def test_populated_materialized_view_delegates_atomically(self):
        with connection.cursor() as cursor:
            cursor.execute("CREATE MATERIALIZED VIEW unsupported AS SELECT 42 AS n")
        self.assert_original_refusal()

    def test_forced_rls_hidden_row_as_non_superuser_database_owner(self):
        apps = MigrationExecutor(connection).loader.project_state(BEFORE).apps
        apps.get_model("market", "SourceRegistry").objects.create(
            name="hidden metadata", tier="quarantine", base_url="https://example.invalid"
        )
        role = "bootstrap_owner_" + uuid4().hex
        quote = connection.ops.quote_name
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user,current_database()")
            admin, database = cursor.fetchone()
            cursor.execute(f"CREATE ROLE {quote(role)} NOSUPERUSER NOBYPASSRLS")
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"ALTER DATABASE {quote(database)} OWNER TO {quote(role)}")
                cursor.execute(f"ALTER SCHEMA public OWNER TO {quote(role)}")
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                for (table,) in cursor.fetchall():
                    cursor.execute(f"ALTER TABLE {quote(table)} OWNER TO {quote(role)}")
                cursor.execute(
                    "SELECT p.oid::regprocedure::text FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public' AND p.proname LIKE 'market_%'"
                )
                for (signature,) in cursor.fetchall():
                    cursor.execute(f"ALTER FUNCTION {signature} OWNER TO {quote(role)}")
                cursor.execute("ALTER TABLE market_sourceregistry ENABLE ROW LEVEL SECURITY")
                cursor.execute("ALTER TABLE market_sourceregistry FORCE ROW LEVEL SECURITY")
            admin_before = self.snapshot()
            with connection.cursor() as cursor:
                cursor.execute(f"SET ROLE {quote(role)}")
                cursor.execute(
                    "SELECT r.rolsuper,r.rolbypassrls,d.datdba=r.oid FROM pg_roles r "
                    "JOIN pg_database d ON d.datname=current_database() WHERE r.rolname=current_user"
                )
                self.assertEqual(cursor.fetchone(), (False, False, True))
                cursor.execute("SELECT count(*) FROM market_sourceregistry")
                self.assertEqual(cursor.fetchone()[0], 0)
            self.assert_original_refusal()
            with connection.cursor() as cursor:
                cursor.execute("RESET ROLE")
                cursor.execute("SELECT count(*) FROM market_sourceregistry")
                self.assertEqual(cursor.fetchone()[0], 1)
            self.assertEqual(admin_before, self.snapshot())
        finally:
            with connection.cursor() as cursor:
                cursor.execute("RESET ROLE")
                # This unique role owns only the disposable scenario database.
                cursor.execute(f"REASSIGN OWNED BY {quote(role)} TO {quote(admin)}")
                cursor.execute(f"DROP ROLE {quote(role)}")

    def test_concurrent_writer_cannot_race_empty_inspection(self):
        # Pause only after the real table locks and empty inspection. A writer
        # must time out, then succeed once the real migration commits.
        inspected = Event()
        release = Event()
        require_catalog = original._require_0026_catalog

        def pause_after_inspection(cursor):
            result = require_catalog(cursor)
            inspected.set()
            if not release.wait(10):
                raise AssertionError("Concurrent writer did not release migration")
            return result

        def migrate():
            try:
                MigrationExecutor(connection).migrate(AFTER)
            finally:
                connection.close()

        with (
            patch.object(original, "_require_0026_catalog", side_effect=pause_after_inspection),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            future = pool.submit(migrate)
            try:
                self.assertTrue(inspected.wait(10))
                with self.assertRaisesMessage(OperationalError, "lock timeout"):
                    with transaction.atomic(), connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout='100ms'")
                        cursor.execute(
                            "INSERT INTO auth_user (password,last_login,is_superuser,username,"
                            "first_name,last_name,email,is_staff,is_active,date_joined) "
                            "VALUES ('',NULL,false,'racing','','','',false,true,now())"
                        )
            finally:
                release.set()
            future.result(timeout=10)
        apps = MigrationExecutor(connection).loader.project_state(AFTER).apps
        apps.get_model("auth", "User").objects.create(username="after_commit")
        self.assertEqual(apps.get_model("auth", "User").objects.count(), 1)
