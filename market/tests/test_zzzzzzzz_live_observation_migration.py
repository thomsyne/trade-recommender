"""Migration 0028 over representative legacy rows: honest markers, no fabrication; reversible only while no live evidence exists.

Migration 0029 (the same Phase 1.4 remediation) must apply over a realistic
non-empty 0028 ledger: it renumbers dense per-candle chains while the
self-referential ``supersedes`` foreign key queues deferred trigger events,
and it must not trip over its own constraint installation.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.models import Candle, CandleObservation, IngestionRun
from market.services import _candle_payload, _json_hash, live_candle_completion
from market.tests.historical_database import HistoricalDatabaseMixin
from market.tests.timeline import POLL_DELAY

BEFORE = [("market", "0027_gate8i_final_dataset_acceptance")]
AFTER = [("market", "0028_live_candle_observation_identity")]
AFTER_0029 = [("market", "0029_candle_observation_lineage")]
START_TS = datetime(2026, 1, 5, 8, tzinfo=UTC)
# A provider reports a candle after it closes, never before: these fixtures are
# built to the same contract market.tests.timeline states and 0029 enforces.
CANDLE_A_OBSERVED = live_candle_completion(START_TS, "H1") + POLL_DELAY
OBSERVED_CEILING = datetime(2026, 1, 5, 11, tzinfo=UTC)
PROTECTIONS = (
    "market_live_candle_protect",
    "market_technicalsnapshot_protect",
    "market_candleobservation_append_only",
    "market_candleobservation_reject_truncate",
    "market_technicalsnapshot_reject_truncate",
)


def instrument_at_0028(**values):
    """Seed the schema under test, then bind its identity to the service model.

    Runtime Instrument acquired ingestion_enabled in 0030; its INSERT cannot
    target a deliberately old 0028 table. Do not fake forward migrations here.
    """
    from market.models import Instrument

    historical = (
        MigrationExecutor(connection)
        .loader.project_state(AFTER)
        .apps.get_model("market", "Instrument")
    )
    row = historical.objects.create(**values)
    return Instrument.objects.defer("ingestion_enabled").get(pk=row.pk)


def restore_head():
    # Only this class's isolated historical graph. The mixin restores the
    # untouched normal database, including its installed M15 functions.
    MigrationExecutor(connection).migrate(AFTER)


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


class LiveObservationMigrationTests(HistoricalDatabaseMixin, TransactionTestCase):
    historical_market_migration = "0028_"

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(AFTER)

    def tearDown(self):
        # Reset this isolated historical schema only. The mixin reconnects the
        # untouched head database after the class and removes its temporary DB.
        restore_head()
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

    def record_live_observation(self):
        """One provider observation through the real ingestion path at the 0028 schema."""
        from market.models import SourceRegistry
        from market.services import store_ingestion
        from market.tests.factories import candle

        instrument = instrument_at_0028(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="migration test",
        )
        start = datetime(2026, 1, 5, 8, tzinfo=UTC)
        run = store_ingestion(
            source,
            instrument,
            "H1",
            start,
            start + timedelta(hours=1),
            [candle(start)],
            {"batch": "ledger", "requests": []},
        )
        self.assertEqual(run.status, "succeeded")

    def assert_schema_untouched_at_0028(self):
        self.assertEqual(trigger_names(), set(PROTECTIONS))
        self.assertIn("market_candleobservation", self.tables())
        self.assertIn("provenance", column_names("market_candle"))
        self.assertIn("source_candle_set_sha256", column_names("market_technicalsnapshot"))
        self.assertIn(AFTER[0], MigrationExecutor(connection).loader.applied_migrations)

    def test_reverse_is_refused_while_the_observation_ledger_has_rows(self):
        from market.models import CandleObservation

        self.record_live_observation()
        self.assertEqual(CandleObservation.objects.count(), 1)

        with self.assertRaisesMessage(RuntimeError, "forward-only once live observations exist"):
            MigrationExecutor(connection).migrate(BEFORE)

        # Refused before anything was dropped: no silent deletion, nothing unapplied.
        self.assert_schema_untouched_at_0028()
        self.assertEqual(CandleObservation.objects.count(), 1)

    def test_reverse_is_refused_while_appended_snapshots_share_an_as_of(self):
        from market.models import CandleObservation, TechnicalSnapshot

        instrument = instrument_at_0028(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        as_of = datetime(2026, 1, 5, 9, tzinfo=UTC)
        for digest in ("a" * 64, "b" * 64):
            TechnicalSnapshot.objects.create(
                instrument=instrument,
                granularity="H1",
                as_of=as_of,
                candle_count=1,
                algorithm_version=TechnicalSnapshot.ALGORITHM_VERSION,
                provenance=TechnicalSnapshot.Provenance.OBSERVED,
                source_candle_set_sha256=digest,
            )
        self.assertEqual(CandleObservation.objects.count(), 0)

        with self.assertRaisesMessage(RuntimeError, "unique_technical_snapshot"):
            MigrationExecutor(connection).migrate(BEFORE)

        self.assert_schema_untouched_at_0028()
        self.assertEqual(TechnicalSnapshot.objects.count(), 2)

    def tables(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
            )
            return {row[0] for row in cursor.fetchall()}


class LineageRenumberMigrationTests(HistoricalDatabaseMixin, TransactionTestCase):
    """0029 must apply over a realistic 0028 ledger without pending-trigger events.

    The pre-fix migration failed with ``cannot ALTER TABLE ... because it has
    pending trigger events`` the moment the renumber rewrote real rows. This
    seeds the exact shapes 0029 exists to repair -- a cross-source revision
    with no predecessor and a legacy adoption row written as revision 2 --
    and asserts the migration renumbers them dense per candle.
    """

    historical_market_migration = "0028_"

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(AFTER)

    def tearDown(self):
        # 0029 is forward-only while observations exist: empty the ledger (and
        # its protected parents) created in this isolated historical database
        # before resetting it to 0028. The normal database is never migrated back.
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_candleobservation DISABLE TRIGGER USER")
            cursor.execute("ALTER TABLE market_candle DISABLE TRIGGER USER")
            cursor.execute("ALTER TABLE market_ingestionrun DISABLE TRIGGER USER")
            cursor.execute("DELETE FROM market_candleobservation")
            cursor.execute("DELETE FROM market_candle")
            cursor.execute("DELETE FROM market_ingestionrun")
            cursor.execute("ALTER TABLE market_candleobservation ENABLE TRIGGER USER")
            cursor.execute("ALTER TABLE market_candle ENABLE TRIGGER USER")
            cursor.execute("ALTER TABLE market_ingestionrun ENABLE TRIGGER USER")
        restore_head()
        super().tearDown()

    def seed_0028_ledger(self):
        """Two candles: one with an initial + source revisions (including a
        cross-source revision-2 written with no predecessor) and one legacy
        candle whose first recorded view was written as revision 2 with no
        supersedes. Prices are sub-unit so the canonical SQL/Python hash
        parity is exercised by the migration preflight too."""
        from market.models import SourceRegistry

        instrument = instrument_at_0028(
            code="AUD_USD", base_currency="AUD", quote_currency="USD", display_order=1
        )
        source_a = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="migration test",
        )
        source_b = SourceRegistry.objects.create(
            name="Secondary provider",
            tier="established",
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="migration test",
        )
        start = datetime(2026, 1, 5, 8, tzinfo=UTC)
        # Legacy candle rows are not observed yet at 0028; the runs that froze
        # them are historical. started_at is auto_now_add, so it is pinned via
        # update afterwards to sit before the fixture's observed_at values and
        # satisfy the 0029 chronology preflight.
        started_at = start - timedelta(minutes=5)

        def pin(run):
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE market_ingestionrun DISABLE TRIGGER market_ingestion_run_enforce"
                )
                cursor.execute(
                    "UPDATE market_ingestionrun SET started_at = %s WHERE id = %s",
                    [started_at, run.pk],
                )
                cursor.execute(
                    "ALTER TABLE market_ingestionrun ENABLE TRIGGER market_ingestion_run_enforce"
                )
            return run

        run_a1 = pin(
            IngestionRun.objects.create(
                source=source_a,
                instrument=instrument,
                granularity="H1",
                requested_from=start,
                requested_to=start + timedelta(hours=1),
                parameters={},
                request_manifest_hash="0029-legacy-a1",
                status="succeeded",
                finished_at=start + timedelta(hours=1),
            )
        )
        run_a2 = pin(
            IngestionRun.objects.create(
                source=source_a,
                instrument=instrument,
                granularity="H1",
                requested_from=start,
                requested_to=start + timedelta(hours=1),
                parameters={},
                request_manifest_hash="0029-legacy-a2",
                status="succeeded",
                finished_at=start + timedelta(hours=1),
            )
        )
        run_b2 = pin(
            IngestionRun.objects.create(
                source=source_b,
                instrument=instrument,
                granularity="H1",
                requested_from=start,
                requested_to=start + timedelta(hours=1),
                parameters={},
                request_manifest_hash="0029-legacy-b2",
                status="succeeded",
                finished_at=start + timedelta(hours=1),
            )
        )
        legacy_run = pin(
            IngestionRun.objects.create(
                source=source_a,
                instrument=instrument,
                granularity="H1",
                requested_from=start,
                requested_to=start + timedelta(hours=2),
                parameters={},
                request_manifest_hash="0029-legacy-adoption",
                status="succeeded",
                finished_at=start + timedelta(hours=2),
            )
        )

        def content(**changes):
            values = {
                "bid_open": Decimal("0.650000"),
                "bid_high": Decimal("0.652000"),
                "bid_low": Decimal("0.648000"),
                "bid_close": Decimal("0.651000"),
                "ask_open": Decimal("0.650020"),
                "ask_high": Decimal("0.652020"),
                "ask_low": Decimal("0.648020"),
                "ask_close": Decimal("0.651020"),
            }
            values.update(changes)
            return values

        candle_a = Candle(
            instrument=instrument,
            ingestion_run=run_a1,
            granularity="H1",
            timestamp=start,
            complete=True,
            volume=100,
            provenance=Candle.Provenance.OBSERVED,
            content_sha256=None,
            observed_at=CANDLE_A_OBSERVED,
            **content(),
        )
        candle_a.content_sha256 = self._content_hash(candle_a)
        candle_a.save()

        legacy = Candle.objects.create(
            instrument=instrument,
            ingestion_run=legacy_run,
            granularity="H1",
            timestamp=start + timedelta(hours=1),
            complete=True,
            volume=100,
            provenance=Candle.Provenance.LEGACY_UNKNOWN,
            **content(),
        )

        columns = (
            "instrument_id",
            "granularity",
            "timestamp",
            "interval_end",
            "complete",
            "volume",
            "bid_open",
            "bid_high",
            "bid_low",
            "bid_close",
            "ask_open",
            "ask_high",
            "ask_low",
            "ask_close",
            "source_id",
            "ingestion_run_id",
            "candle_id",
            "kind",
            "revision",
            "supersedes_id",
            "content_sha256",
            "differing_fields",
            "observed_at",
            "created_at",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE market_candleobservation DISABLE TRIGGER "
                "market_candleobservation_append_only"
            )
            insert = (
                "INSERT INTO market_candleobservation ({cols}) VALUES ({ph}) RETURNING id"
            ).format(cols=", ".join(columns), ph=", ".join(["%s"] * len(columns)))

            def put(
                candle_row,
                source,
                run,
                kind,
                revision,
                supersedes_id,
                differing_fields,
                observed_at=None,
                **changes,
            ):
                row = Candle(
                    instrument=instrument,
                    ingestion_run=run,
                    granularity="H1",
                    timestamp=candle_row.timestamp,
                    complete=True,
                    volume=100,
                    **content(**changes),
                )
                values = [
                    instrument.pk,
                    "H1",
                    candle_row.timestamp,
                    candle_row.timestamp + timedelta(hours=1),
                    True,
                    100,
                    row.bid_open,
                    row.bid_high,
                    row.bid_low,
                    row.bid_close,
                    row.ask_open,
                    row.ask_high,
                    row.ask_low,
                    row.ask_close,
                    source.pk,
                    run.pk,
                    candle_row.pk,
                    kind,
                    revision,
                    supersedes_id,
                    self._content_hash(row),
                    json.dumps(differing_fields),
                    observed_at
                    or (live_candle_completion(candle_row.timestamp, "H1") + POLL_DELAY),
                    OBSERVED_CEILING,
                ]
                cursor.execute(insert, values)
                return cursor.fetchone()[0]

            # candle_a: rev 1 froze it (source A); source A then revises it,
            # and source B writes its own revision 2 with NO predecessor.
            first_id = put(
                candle_a,
                source_a,
                run_a1,
                "initial",
                1,
                None,
                [],
                observed_at=candle_a.observed_at,
            )
            put(
                candle_a,
                source_a,
                run_a2,
                "revision",
                2,
                first_id,
                ["bid_close"],
                bid_close=Decimal("0.651100"),
            )
            put(
                candle_a,
                source_b,
                run_b2,
                "revision",
                2,
                None,
                ["bid_close"],
                bid_close=Decimal("0.651200"),
            )
            # legacy candle: first recorded view written as revision 2 with no
            # supersedes; 0029 must make it revision 1.
            put(
                legacy,
                source_a,
                legacy_run,
                "revision",
                2,
                None,
                ["bid_close"],
                bid_close=Decimal("0.651300"),
            )

    def _content_hash(self, candle_row):
        return _json_hash(
            {
                "instrument": candle_row.instrument.code,
                "granularity": candle_row.granularity,
                **_candle_payload(candle_row),
            }
        )

    def test_0029_applies_over_legacy_and_cross_source_chains_and_renumbers_dense(self):
        self.seed_0028_ledger()
        self.assertEqual(CandleObservation.objects.count(), 4)

        MigrationExecutor(connection).migrate(AFTER_0029)

        chains = {}
        for observation in CandleObservation.objects.order_by("id"):
            chains.setdefault(observation.candle_id, []).append(observation)
        candle_chain = chains.get(Candle.objects.get(timestamp=START_TS).pk)
        self.assertEqual(
            [(row.revision, row.supersedes_id is not None, row.kind) for row in candle_chain],
            [(1, False, "initial"), (2, True, "revision"), (3, True, "revision")],
        )
        legacy_chain = chains[Candle.objects.get(timestamp=START_TS + timedelta(hours=1)).pk]
        self.assertEqual(
            [(row.revision, row.supersedes_id is not None, row.kind) for row in legacy_chain],
            [(1, False, "revision")],
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT conname FROM pg_constraint WHERE conname = ANY(%s)",
                [["unique_candle_observation_chain", "candle_observation_revision_shape"]],
            )
            constraints = {row[0] for row in cursor.fetchall()}
        self.assertEqual(
            constraints,
            {"unique_candle_observation_chain", "candle_observation_revision_shape"},
        )

    def test_0029_migration_depends_on_0028(self):
        from importlib import import_module

        module = import_module("market.migrations.0029_candle_observation_lineage")
        self.assertEqual(module.Migration.dependencies, AFTER)
