"""Normally migrated isolated databases for irreversible historical-state tests.

The installed application graph stays intact. Only the temporary database visits
historical states; no evidence rollback capability is added to production.
"""

from uuid import uuid4

from django.apps import apps as runtime_apps
from django.contrib.auth.management import create_permissions
from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor


def head_fingerprint(cursor):
    """Exact shared-head recorder timestamps and durable SQL, not just leaf names."""
    result = []
    for sql in (
        "SELECT id,app,name,applied FROM django_migrations ORDER BY id",
        "SELECT p.oid,pg_get_functiondef(p.oid) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname=current_schema() AND p.prokind<>'a' ORDER BY p.oid",
        "SELECT t.oid,pg_get_triggerdef(t.oid),t.tgenabled FROM pg_trigger t "
        "JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=current_schema() ORDER BY t.oid",
        "SELECT c.oid,pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_namespace n ON n.oid=c.connamespace "
        "WHERE n.nspname=current_schema() ORDER BY c.oid",
    ):
        cursor.execute(sql)
        result.append(tuple(cursor.fetchall()))
    return tuple(result)


class PreservingMigrationExecutor(MigrationExecutor):
    """Reject impossible test rollback plans before partially undoing the head.

    Django checks reversibility one migration at a time. A historical test can
    therefore undo M15 SQL, then fail at an unrelated irreversible migration.
    Preflight preserves that failure (not a skip or SQL repair) without damaging
    the database used by subsequent tests. Runnable historical graphs should use
    HistoricalDatabaseMixin; this also protects older, blocked fixtures.
    """

    def migrate(self, targets, plan=None, *args, **kwargs):
        if plan is None:
            plan = self.migration_plan(targets)
        for migration, backwards in plan:
            if backwards:
                for operation in reversed(migration.operations):
                    if not operation.reversible:
                        raise IrreversibleError(
                            f"Operation {operation} in {migration} is not reversible"
                        )
        return super().migrate(targets, plan, *args, **kwargs)


class HistoricalDatabaseMixin:
    historical_market_migration = "0030_"

    @classmethod
    def _pre_setup(cls):
        cls._original_database_name = connection.settings_dict["NAME"]
        if connection.vendor != "postgresql" or not cls._original_database_name.startswith("test_"):
            raise RuntimeError(
                "Historical harness requires the runner's disposable PostgreSQL test database"
            )
        cls._historical_database_name = "test_history_" + uuid4().hex
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != cls._original_database_name:
                raise RuntimeError("Original test connection identity mismatch")
            cls._original_fingerprint = head_fingerprint(cursor)
            cursor.execute('CREATE DATABASE "' + cls._historical_database_name + '"')
        connection.close()
        connection.settings_dict["NAME"] = cls._historical_database_name
        try:
            executor = MigrationExecutor(connection)
            market_target = next(
                node
                for node in executor.loader.graph.nodes
                if node[0] == "market" and node[1].startswith(cls.historical_market_migration)
            )
            # These tests need auth/operations/research tables, not prospective forecasts.
            targets = [
                node
                for node in executor.loader.graph.leaf_nodes()
                if node[0] not in {"market", "forecasts", "research"}
            ]
            targets.append(("research", "0014_enforce_entry_boundary"))
            MigrationExecutor(connection).migrate([market_target, *targets])
            cls.historical_apps = (
                MigrationExecutor(connection).loader.project_state([market_target, *targets]).apps
            )
            cls._runtime_fields = []
            if cls.historical_market_migration < "0027_":
                # Old service tests import runtime models. Bind only their
                # forward-added columns to the historical model shape; never
                # add columns or disable enforcement in the scenario database.
                historical = cls.historical_apps
                for name in ("Instrument", "Candle", "TechnicalSnapshot"):
                    model = runtime_apps.get_model("market", name)
                    columns = {
                        field.column
                        for field in historical.get_model("market", name)._meta.local_fields
                    }
                    cls._runtime_fields.append((model, model._meta.local_fields))
                    model._meta.local_fields = [
                        field for field in model._meta.local_fields if field.column in columns
                    ]
                    model._meta._expire_cache()
                if cls.historical_market_migration < "0026_":
                    for config in runtime_apps.get_app_configs():
                        create_permissions(config, verbosity=0, apps=historical)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM django_migrations WHERE app='forecasts' AND name>='0018'"
                )
                if cursor.fetchone()[0]:
                    raise RuntimeError("Historical target unexpectedly installed prospective graph")
            super()._pre_setup()
        except BaseException:
            cls._close_historical_database()
            raise

    @classmethod
    def _close_historical_database(cls):
        for model, fields in getattr(cls, "_runtime_fields", []):
            model._meta.local_fields = fields
            model._meta._expire_cache()
        cls._runtime_fields = []
        connection.close()
        connection.settings_dict["NAME"] = cls._original_database_name
        with connection.cursor() as cursor:
            cursor.execute('DROP DATABASE "' + cls._historical_database_name + '" WITH (FORCE)')
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != cls._original_database_name:
                raise RuntimeError("Original test database was not restored")
            if head_fingerprint(cursor) != cls._original_fingerprint:
                raise RuntimeError("Historical harness changed the shared-head recorder or catalog")

    def _fixture_teardown(self):
        # The whole scenario database is discarded, including durable evidence.
        # Never flush an old schema using the current application's model graph.
        pass

    def _post_teardown(self):
        try:
            super()._post_teardown()
        finally:
            self._close_historical_database()
