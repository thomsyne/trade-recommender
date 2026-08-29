from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.historical_acquisition import INSTRUMENTS
from market.historical_discovery import build_initial_discovery_plan, create_discovery_plan
from market.models import IngestionRun, Instrument, SourceRegistry


class ProviderObservedInventoryMigrationTests(TransactionTestCase):
    discovery = [("market", "0013_provider_observed_inventory")]
    previous = [("market", "0012_operation_aware_historical_dataset")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.discovery)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.discovery)
        super().tearDown()

    def test_migration_depends_directly_on_0012(self):
        migration = __import__(
            "market.migrations.0013_provider_observed_inventory", fromlist=["Migration"]
        ).Migration
        self.assertIn(("market", "0012_operation_aware_historical_dataset"), migration.dependencies)
        self.assertTrue(migration.atomic)

    def test_empty_reverse_and_reapply_succeed(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('market_historicaldiscoveryplan')")
            self.assertIsNone(cursor.fetchone()[0])

        MigrationExecutor(connection).migrate(self.discovery)
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('market_historicaldiscoveryplan')")
            self.assertEqual(cursor.fetchone()[0], "market_historicaldiscoveryplan")

    def test_any_plan_evidence_blocks_reverse(self):
        SourceRegistry.objects.create(
            name="OANDA v20",
            tier=SourceRegistry.Tier.ESTABLISHED,
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="migration test",
            enabled=True,
        )
        for order, code in enumerate(INSTRUMENTS, 1):
            base, quote = code.split("_")
            Instrument.objects.create(
                code=code,
                base_currency=base,
                quote_currency=quote,
                display_order=order,
                active=True,
            )
        create_discovery_plan(build_initial_discovery_plan())

        with self.assertRaisesMessage(
            RuntimeError, "provider-observed discovery evidence prohibits migration reversal"
        ):
            MigrationExecutor(connection).migrate(self.previous)

    def test_forward_preflight_rejects_unexpected_discovery_run(self):
        MigrationExecutor(connection).migrate(self.previous)
        source = SourceRegistry.objects.create(
            name="unexpected source",
            tier=SourceRegistry.Tier.ESTABLISHED,
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test",
            enabled=True,
        )
        instrument = Instrument.objects.create(
            code="EUR_USD",
            base_currency="EUR",
            quote_currency="USD",
            display_order=1,
            active=True,
        )
        run = IngestionRun.objects.create(
            source=source,
            instrument=instrument,
            granularity="D",
            requested_from="2020-01-01T22:00:00Z",
            requested_to="2020-01-02T22:00:00Z",
            parameters={"purpose": "provider_timestamp_inventory_discovery"},
            request_manifest_hash="f" * 64,
        )

        with self.assertRaisesMessage(
            RuntimeError, "unexpected provider-observed discovery evidence exists"
        ):
            MigrationExecutor(connection).migrate(self.discovery)

        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM market_ingestionrun WHERE id=%s", [run.pk])
        MigrationExecutor(connection).migrate(self.discovery)
