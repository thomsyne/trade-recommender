from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.historical_acquisition import INSTRUMENTS
from market.historical_discovery import (
    GOVERNING_CANARY_LOGICAL_KEY,
    build_initial_discovery_plan,
    build_replacement_discovery_plan,
    create_discovery_plan,
    run_discovery_chunk,
    supersede_discovery_plan,
)
from market.models import HistoricalDiscoveryAttempt, Instrument, SourceRegistry
from market.oanda import OandaError


class FailedClient:
    def __init__(self, chunk):
        self.chunk = chunk

    def fetch_historical_inventory(self, *args):
        raise OandaError(
            "safe mocked HTTP failure",
            failure_kind="http",
            provider_evidence={
                "endpoint_identity": (
                    f"oanda-v20-practice:GET:/v3/instruments/{self.chunk.instrument.code}/candles"
                ),
                "http_method": "GET",
                "oanda_environment": "practice",
                "http_status": 400,
                "provider_request_id": "migration-provider-request",
                "canonical_request_sha256": self.chunk.canonical_request_sha256,
            },
        )


class HistoricalDiscoverySupersessionMigrationTests(TransactionTestCase):
    current = [("market", "0014_historical_discovery_supersession")]
    previous = [("market", "0013_provider_observed_inventory")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.current)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.current)
        super().tearDown()

    def seed_governed_source(self):
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

    def create_failed_v1(self):
        plan = create_discovery_plan(build_initial_discovery_plan())
        chunk = plan.chunks.select_related("instrument").get(
            logical_key=GOVERNING_CANARY_LOGICAL_KEY
        )
        with self.assertRaises(OandaError):
            run_discovery_chunk(chunk.logical_key, FailedClient(chunk))
        return plan, HistoricalDiscoveryAttempt.objects.get(chunk=chunk)

    def evidence_hash(self, plan):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT market_sha256(jsonb_build_object(
                     'plan',to_jsonb(p),'chunks',(SELECT jsonb_agg(to_jsonb(c) ORDER BY c.ordinal)
                       FROM market_historicaldiscoverychunk c WHERE c.plan_id=p.id),
                     'attempts',(SELECT jsonb_agg(to_jsonb(a) ORDER BY a.id)
                       FROM market_historicaldiscoveryattempt a
                       JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
                       WHERE c.plan_id=p.id),
                     'runs',(SELECT jsonb_agg(to_jsonb(r) ORDER BY r.id)
                       FROM market_ingestionrun r JOIN market_historicaldiscoveryattempt a
                         ON a.ingestion_run_id=r.id JOIN market_historicaldiscoverychunk c
                         ON c.id=a.chunk_id WHERE c.plan_id=p.id),
                     'evidence',(SELECT jsonb_agg(to_jsonb(e) ORDER BY e.id)
                       FROM market_historicaldiscoveryproviderevidence e
                       JOIN market_historicaldiscoveryattempt a ON a.id=e.attempt_id
                       JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
                       WHERE c.plan_id=p.id),
                     'audits',(SELECT jsonb_agg(to_jsonb(ev) ORDER BY ev.id)
                       FROM market_auditevent ev JOIN market_historicaldiscoveryattempt a
                         ON ev.subject_id=a.id::text JOIN market_historicaldiscoverychunk c
                         ON c.id=a.chunk_id WHERE c.plan_id=p.id
                           AND ev.subject_type='HistoricalDiscoveryAttempt')))
                   FROM market_historicaldiscoveryplan p WHERE p.id=%s""",
                [plan.pk],
            )
            return cursor.fetchone()[0]

    def test_dependency_and_empty_reverse_restore_0013_behavior(self):
        migration = __import__(
            "market.migrations.0014_historical_discovery_supersession",
            fromlist=["Migration"],
        ).Migration
        self.assertEqual(migration.dependencies, [("market", "0013_provider_observed_inventory")])
        self.assertTrue(migration.atomic)

        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('market_historicaldiscoverysupersession')")
            self.assertIsNone(cursor.fetchone()[0])
            cursor.execute(
                """SELECT count(*) FROM pg_trigger
                   WHERE tgrelid='market_historicaldiscoveryattempt'::regclass
                     AND tgname='market_discovery_attempt_validate'"""
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                "SELECT count(*) FROM pg_proc WHERE proname='market_validate_discovery_supersession'"
            )
            self.assertEqual(cursor.fetchone()[0], 0)

        MigrationExecutor(connection).migrate(self.current)
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('market_historicaldiscoverysupersession')")
            self.assertEqual(cursor.fetchone()[0], "market_historicaldiscoverysupersession")

    def test_v1_evidence_is_byte_identical_across_empty_reverse_and_reapply(self):
        self.seed_governed_source()
        plan, _ = self.create_failed_v1()
        expected = self.evidence_hash(plan)

        MigrationExecutor(connection).migrate(self.previous)
        self.assertEqual(self.evidence_hash(plan), expected)
        MigrationExecutor(connection).migrate(self.current)
        self.assertEqual(self.evidence_hash(plan), expected)

    def test_supersession_evidence_blocks_reverse(self):
        self.seed_governed_source()
        plan, attempt = self.create_failed_v1()
        replacement = create_discovery_plan(build_replacement_discovery_plan())
        supersede_discovery_plan(plan.sha256, replacement.sha256, attempt.pk)

        with self.assertRaisesMessage(
            RuntimeError,
            "historical discovery supersession evidence prohibits migration reversal",
        ):
            MigrationExecutor(connection).migrate(self.previous)

    def governance_catalog(self):
        with connection.cursor() as cursor:
            cursor.execute(
                r"""SELECT p.proname, md5(p.prosrc) FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = current_schema() AND p.proname LIKE 'market\_%'
                    ORDER BY p.proname"""
            )
            functions = cursor.fetchall()
            cursor.execute(
                """SELECT t.tgname, c.relname FROM pg_trigger t
                   JOIN pg_class c ON c.oid = t.tgrelid
                   WHERE NOT t.tgisinternal ORDER BY t.tgname, c.relname"""
            )
            return {"functions": functions, "triggers": cursor.fetchall()}

    def assert_no_supersession_objects(self):
        migration = self.migration_module()
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s)", [migration.SUPERSESSION_TABLE])
            self.assertIsNone(cursor.fetchone()[0])
            cursor.execute(
                """SELECT count(*) FROM pg_proc p
                   JOIN pg_namespace n ON n.oid = p.pronamespace
                   WHERE n.nspname = current_schema() AND p.proname = ANY(%s)""",
                [list(migration.SUPERSESSION_FUNCTIONS)],
            )
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute(
                """SELECT count(*) FROM pg_trigger t WHERE NOT t.tgisinternal
                   AND t.tgname = ANY(%s)""",
                [list(migration.SUPERSESSION_TRIGGERS)],
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def migration_module(self):
        return __import__(
            "market.migrations.0014_historical_discovery_supersession",
            fromlist=["Migration"],
        )

    def test_preflight_rejects_partial_prior_installation(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute(
                """CREATE FUNCTION market_validate_discovery_supersession()
                   RETURNS trigger AS $$BEGIN RETURN NEW; END$$ LANGUAGE plpgsql"""
            )
        snapshot = self.governance_catalog()
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "unexpected pre-existing supersession function"
                " market_validate_discovery_supersession",
            ):
                MigrationExecutor(connection).migrate(self.current)
            self.assertEqual(self.governance_catalog(), snapshot)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT to_regclass(%s)", [self.migration_module().SUPERSESSION_TABLE]
                )
                self.assertIsNone(cursor.fetchone()[0])
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP FUNCTION market_validate_discovery_supersession()")
        MigrationExecutor(connection).migrate(self.current)

    def test_preflight_rejects_altered_0013_governance(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_functiondef('market_discovery_reject_mutation()'::regprocedure)"
            )
            original = cursor.fetchone()[0]
            cursor.execute(
                """CREATE OR REPLACE FUNCTION market_discovery_reject_mutation()
                   RETURNS trigger AS $$BEGIN RETURN NEW; END$$ LANGUAGE plpgsql"""
            )
        snapshot = self.governance_catalog()
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "required function market_discovery_reject_mutation"
                " does not match its 0013 definition",
            ):
                MigrationExecutor(connection).migrate(self.current)
            self.assertEqual(self.governance_catalog(), snapshot)
            self.assert_no_supersession_objects()
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)
        MigrationExecutor(connection).migrate(self.current)

    def test_preflight_rejects_missing_0013_governance(self):
        MigrationExecutor(connection).migrate(self.previous)
        with connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER market_discovery_audit_no_truncate ON market_auditevent")
        snapshot = self.governance_catalog()
        try:
            with self.assertRaisesMessage(
                RuntimeError,
                "required trigger market_discovery_audit_no_truncate"
                " on market_auditevent is missing",
            ):
                MigrationExecutor(connection).migrate(self.current)
            self.assertEqual(self.governance_catalog(), snapshot)
            self.assert_no_supersession_objects()
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    """CREATE TRIGGER market_discovery_audit_no_truncate
                       BEFORE TRUNCATE ON market_auditevent FOR EACH STATEMENT
                       EXECUTE FUNCTION market_discovery_audit_reject_truncate()"""
                )
        MigrationExecutor(connection).migrate(self.current)

    def test_preflight_constants_match_live_0013_catalog(self):
        migration = self.migration_module()
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT p.proname, md5(p.prosrc) FROM pg_proc p
                   JOIN pg_namespace n ON n.oid = p.pronamespace
                   WHERE n.nspname = current_schema() AND p.proname = ANY(%s)""",
                [list(migration.PREFLIGHT_FUNCTIONS)],
            )
            self.assertEqual(dict(cursor.fetchall()), migration.PREFLIGHT_FUNCTIONS)
            cursor.execute(
                """SELECT t.tgname, c.relname FROM pg_trigger t
                   JOIN pg_class c ON c.oid = t.tgrelid WHERE NOT t.tgisinternal"""
            )
            live_triggers = set(cursor.fetchall())
        self.assertEqual(
            set(migration.PREFLIGHT_TRIGGERS) - live_triggers,
            set(),
        )
