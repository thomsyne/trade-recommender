"""Normally migrated isolated databases for irreversible historical-state tests.

The installed application graph stays intact. Only the temporary database visits
historical states; no evidence rollback capability is added to production.
"""

from uuid import uuid4

from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class HistoricalDatabaseMixin:
    historical_market_migration = "0030_"

    @classmethod
    def setUpClass(cls):
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
            cursor.execute("SELECT app,name FROM django_migrations ORDER BY app,name")
            cls._original_migrations = tuple(cursor.fetchall())
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
            if market_target[1] >= "0027":
                before = next(
                    node
                    for node in executor.loader.graph.nodes
                    if node[0] == "market" and node[1].startswith("0026_")
                )
                accommodated = next(
                    node
                    for node in executor.loader.graph.nodes
                    if node[0] == "market" and node[1].startswith("0027_")
                )
                executor.migrate([before])
                # The sole documented repository bootstrap accommodation.
                MigrationExecutor(connection).migrate([accommodated], fake=True)
            MigrationExecutor(connection).migrate([market_target, *targets])
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM django_migrations WHERE app='forecasts' AND name>='0018'"
                )
                if cursor.fetchone()[0]:
                    raise RuntimeError("Historical target unexpectedly installed prospective graph")
            super().setUpClass()
        except BaseException:
            cls._close_historical_database()
            raise

    @classmethod
    def _close_historical_database(cls):
        connection.close()
        connection.settings_dict["NAME"] = cls._original_database_name
        with connection.cursor() as cursor:
            cursor.execute('DROP DATABASE "' + cls._historical_database_name + '" WITH (FORCE)')
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != cls._original_database_name:
                raise RuntimeError("Original test database was not restored")
            cursor.execute("SELECT app,name FROM django_migrations ORDER BY app,name")
            if tuple(cursor.fetchall()) != cls._original_migrations:
                raise RuntimeError("Historical harness changed the installed migration graph")

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            cls._close_historical_database()
