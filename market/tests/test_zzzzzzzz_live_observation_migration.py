"""Migration 0028 over representative legacy rows: honest markers, no fabrication, reversible."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("market", "0027_gate8i_final_dataset_acceptance")]
AFTER = [("market", "0028_live_candle_observation_identity")]
PROTECTIONS = (
    "market_live_candle_protect",
    "market_technicalsnapshot_protect",
    "market_candleobservation_append_only",
    "market_candleobservation_reject_truncate",
    "market_technicalsnapshot_reject_truncate",
)


def trigger_names():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(%s)",
            [list(PROTECTIONS)],
        )
        return {row[0] for row in cursor.fetchall()}


def column_names(table):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s", [table]
        )
        return {row[0] for row in cursor.fetchall()}


class LiveObservationMigrationTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(AFTER)

    def tearDown(self):
        MigrationExecutor(connection).migrate(AFTER)
        super().tearDown()

    def seed_legacy_rows(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)
        apps = executor.loader.project_state(BEFORE).apps
        Source = apps.get_model("market", "SourceRegistry")
        Instrument = apps.get_model("market", "Instrument")
        IngestionRun = apps.get_model("market", "IngestionRun")
        Candle = apps.get_model("market", "Candle")
        Snapshot = apps.get_model("market", "TechnicalSnapshot")
        Dataset = apps.get_model("market", "DatasetVersion")
        oanda = Source.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="migration test",
        )
        fixture = Source.objects.create(
            name="Development fixtures",
            tier="quarantine",
            base_url="https://example.invalid",
            acquisition_method="Deterministic local generator",
            retention_policy="Development only",
        )
        instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        start = datetime(2026, 1, 5, 8, tzinfo=UTC)
        prices = {
            "bid_open": Decimal("1.1000"),
            "bid_high": Decimal("1.1020"),
            "bid_low": Decimal("1.0990"),
            "bid_close": Decimal("1.1010"),
            "ask_open": Decimal("1.1002"),
            "ask_high": Decimal("1.1022"),
            "ask_low": Decimal("1.0992"),
            "ask_close": Decimal("1.1012"),
        }

        def run(source, manifest, dataset=None):
            return IngestionRun.objects.create(
                source=source,
                dataset_version=dataset,
                instrument=instrument,
                granularity="H1",
                requested_from=start,
                requested_to=start + timedelta(hours=1),
                parameters={},
                request_manifest_hash=manifest,
                status="succeeded",
                finished_at=start,
            )

        live = Candle.objects.create(
            instrument=instrument,
            ingestion_run=run(oanda, "legacy-live"),
            granularity="H1",
            timestamp=start,
            complete=True,
            volume=100,
            **prices,
        )
        fixture_row = Candle.objects.create(
            instrument=instrument,
            ingestion_run=run(fixture, "legacy-fixture"),
            granularity="H1",
            timestamp=start + timedelta(hours=1),
            complete=True,
            volume=100,
            **prices,
        )
        dataset = Dataset.objects.create(
            name="governed", version="1", manifest={"fixture": "governed"}, manifest_sha256="a" * 64
        )
        governed = Candle.objects.create(
            instrument=instrument,
            ingestion_run=run(oanda, "legacy-governed", dataset),
            dataset_version=dataset,
            granularity="H1",
            timestamp=start + timedelta(hours=2),
            complete=True,
            volume=100,
            **prices,
        )
        snapshot = Snapshot.objects.create(
            instrument=instrument,
            granularity="H1",
            as_of=start + timedelta(hours=1),
            candle_count=2,
            atr_14=Decimal("0.003"),
        )
        return live.pk, fixture_row.pk, governed.pk, snapshot.pk

    def test_legacy_rows_receive_honest_markers_and_nothing_is_fabricated(self):
        live_pk, fixture_pk, governed_pk, snapshot_pk = self.seed_legacy_rows()
        self.assertEqual(trigger_names(), set())

        MigrationExecutor(connection).migrate(AFTER)

        from market.models import Candle, TechnicalSnapshot

        live = Candle.objects.get(pk=live_pk)
        fixture = Candle.objects.get(pk=fixture_pk)
        governed = Candle.objects.get(pk=governed_pk)
        self.assertEqual(live.provenance, Candle.Provenance.LEGACY_UNKNOWN)
        self.assertIsNone(live.content_sha256)
        self.assertIsNone(live.observed_at)
        self.assertEqual(fixture.provenance, Candle.Provenance.FIXTURE)
        self.assertIsNone(fixture.content_sha256)
        self.assertIsNone(governed.provenance)
        self.assertIsNone(governed.content_sha256)
        self.assertEqual(live.volume, 100)
        snapshot = TechnicalSnapshot.objects.get(pk=snapshot_pk)
        self.assertEqual(snapshot.algorithm_version, "technicals-v1")
        self.assertEqual(snapshot.provenance, TechnicalSnapshot.Provenance.LEGACY_UNKNOWN)
        self.assertIsNone(snapshot.source_candle_set_sha256)
        self.assertEqual(trigger_names(), set(PROTECTIONS))
        self.assertFalse(Candle.objects.filter(pk=live_pk).exclude(volume=100).exists())

    def test_migration_is_reversible_and_dependency_pinned(self):
        from importlib import import_module

        module = import_module("market.migrations.0028_live_candle_observation_identity")
        self.assertEqual(module.Migration.dependencies, BEFORE)
        self.seed_legacy_rows()
        MigrationExecutor(connection).migrate(AFTER)
        self.assertIn("provenance", column_names("market_candle"))
        self.assertIn("market_candleobservation", self.tables())

        MigrationExecutor(connection).migrate(BEFORE)

        self.assertEqual(trigger_names(), set())
        self.assertNotIn("provenance", column_names("market_candle"))
        self.assertNotIn("source_candle_set_sha256", column_names("market_technicalsnapshot"))
        self.assertNotIn("market_candleobservation", self.tables())
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM market_candle")
            self.assertEqual(cursor.fetchone()[0], 3)

    def tables(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
            )
            return {row[0] for row in cursor.fetchall()}
