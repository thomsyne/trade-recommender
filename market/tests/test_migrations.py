import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class Phase2BMigrationSafetyTests(TransactionTestCase):
    latest = [("market", "0012_operation_aware_historical_dataset")]
    portable_identities = [("market", "0011_portable_acquisition_identities")]
    before_enforcement = [("market", "0009_historical_dataset_governance")]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.latest)

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.latest)
        super().tearDown()

    def test_empty_phase2b_schema_is_reversible_before_acquisition(self):
        MigrationExecutor(connection).migrate(self.before_enforcement)
        MigrationExecutor(connection).migrate(self.latest)

    def test_portable_identity_correction_depends_exactly_on_0010(self):
        migration = __import__(
            "market.migrations.0011_portable_acquisition_identities", fromlist=["Migration"]
        ).Migration
        self.assertEqual(
            migration.dependencies,
            [("market", "0010_dataset_registration_enforcement")],
        )

    def test_operation_aware_dataset_trigger_depends_exactly_on_0011(self):
        migration = __import__(
            "market.migrations.0012_operation_aware_historical_dataset", fromlist=["Migration"]
        ).Migration
        self.assertEqual(
            migration.dependencies,
            [("market", "0011_portable_acquisition_identities")],
        )

    def dataset_trigger_catalog(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT trigger_name,event_manipulation,action_statement
                   FROM information_schema.triggers
                   WHERE event_object_schema=current_schema()
                     AND event_object_table='market_datasetversion'
                   ORDER BY trigger_name,event_manipulation"""
            )
            return cursor.fetchall()

    def function_definition(self, name):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT pg_get_functiondef(p.oid)
                   FROM pg_proc p
                   JOIN pg_namespace n ON n.oid=p.pronamespace
                   WHERE n.nspname=current_schema() AND p.proname=%s""",
                [name],
            )
            row = cursor.fetchone()
        return None if row is None else row[0]

    def test_applied_0011_is_upgraded_to_operation_aware_historical_enforcement(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.portable_identities)
        self.assertEqual(
            self.dataset_trigger_catalog(),
            [
                (
                    "market_datasetversion_append_only",
                    "DELETE",
                    "EXECUTE FUNCTION market_datasetversion_reject_mutation()",
                ),
                (
                    "market_datasetversion_append_only",
                    "UPDATE",
                    "EXECUTE FUNCTION market_datasetversion_reject_mutation()",
                ),
                (
                    "market_historical_dataset_validate",
                    "INSERT",
                    "EXECUTE FUNCTION market_validate_historical_dataset()",
                ),
            ],
        )
        old_definition = self.function_definition("market_validate_historical_dataset")
        self.assertNotIn("TG_OP", old_definition)
        self.assertIn("historical dataset conflicts with portable plan identity", old_definition)

        apps = executor.loader.project_state(self.portable_identities).apps
        Dataset = apps.get_model("market", "DatasetVersion")
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE market_datasetversion DISABLE TRIGGER "
                "market_historical_dataset_validate"
            )
        try:
            dataset = Dataset.objects.create(
                name="upgrade-fixture",
                version="1",
                manifest={"historical_plan_sha256": "upgrade-fixture"},
                manifest_sha256="8" * 64,
            )
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE market_datasetversion ENABLE TRIGGER "
                    "market_historical_dataset_validate"
                )

        MigrationExecutor(connection).migrate(self.latest)
        self.assertEqual(
            self.dataset_trigger_catalog(),
            [
                (
                    "market_historical_dataset_validate",
                    "DELETE",
                    "EXECUTE FUNCTION market_validate_historical_dataset()",
                ),
                (
                    "market_historical_dataset_validate",
                    "INSERT",
                    "EXECUTE FUNCTION market_validate_historical_dataset()",
                ),
                (
                    "market_historical_dataset_validate",
                    "UPDATE",
                    "EXECUTE FUNCTION market_validate_historical_dataset()",
                ),
            ],
        )
        definition = self.function_definition("market_validate_historical_dataset")
        self.assertIn("TG_OP='UPDATE'", definition)
        self.assertIn("TG_OP='DELETE'", definition)
        self.assertIsNone(self.function_definition("market_datasetversion_reject_mutation"))
        with self.assertRaises(DatabaseError) as raised, transaction.atomic():
            Dataset.objects.filter(pk=dataset.pk).update(description="mutation")
        self.assertEqual(raised.exception.__cause__.sqlstate, "P0001")
        self.assertEqual(
            raised.exception.__cause__.diag.message_primary,
            "historical dataset manifests are immutable",
        )
        self.assertIn(
            "PL/pgSQL function market_validate_historical_dataset()",
            raised.exception.__cause__.diag.context,
        )
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_datasetversion DISABLE TRIGGER USER")
            cursor.execute("DELETE FROM market_datasetversion WHERE id=%s", [dataset.pk])
            cursor.execute("ALTER TABLE market_datasetversion ENABLE TRIGGER USER")

    def test_safe_reverse_restores_exact_0011_dataset_trigger_set(self):
        MigrationExecutor(connection).migrate(self.portable_identities)
        self.assertEqual(
            self.dataset_trigger_catalog(),
            [
                (
                    "market_datasetversion_append_only",
                    "DELETE",
                    "EXECUTE FUNCTION market_datasetversion_reject_mutation()",
                ),
                (
                    "market_datasetversion_append_only",
                    "UPDATE",
                    "EXECUTE FUNCTION market_datasetversion_reject_mutation()",
                ),
                (
                    "market_historical_dataset_validate",
                    "INSERT",
                    "EXECUTE FUNCTION market_validate_historical_dataset()",
                ),
            ],
        )
        historical_definition = self.function_definition("market_validate_historical_dataset")
        self.assertNotIn("TG_OP", historical_definition)
        self.assertIn(
            "historical dataset conflicts with portable plan identity", historical_definition
        )
        generic_definition = self.function_definition("market_datasetversion_reject_mutation")
        self.assertIn("market_datasetversion is append-only", generic_definition)

        apps = MigrationExecutor(connection).loader.project_state(self.portable_identities).apps
        Dataset = apps.get_model("market", "DatasetVersion")
        dataset = Dataset.objects.create(
            name="reverse-fixture", version="1", manifest={}, manifest_sha256="7" * 64
        )
        with self.assertRaises(DatabaseError) as raised, transaction.atomic():
            Dataset.objects.filter(pk=dataset.pk).update(description="mutation")
        self.assertEqual(raised.exception.__cause__.sqlstate, "P0001")
        self.assertEqual(
            raised.exception.__cause__.diag.message_primary,
            "market_datasetversion is append-only",
        )
        self.assertIn(
            "PL/pgSQL function market_datasetversion_reject_mutation()",
            raised.exception.__cause__.diag.context,
        )
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_datasetversion DISABLE TRIGGER USER")
            cursor.execute("DELETE FROM market_datasetversion WHERE id=%s", [dataset.pk])
            cursor.execute("ALTER TABLE market_datasetversion ENABLE TRIGGER USER")

    def test_reverse_migration_rejects_historical_dataset_evidence(self):
        executor = MigrationExecutor(connection)
        apps = executor.loader.project_state(self.latest).apps
        AuditEvent = apps.get_model("market", "AuditEvent")
        AuditEvent.objects.create(
            event_type="market.historical_attempt_test_evidence",
            actor="migration-test",
            subject_type="HistoricalIngestionAttempt",
            subject_id="1",
            payload={},
        )

        with self.assertRaisesMessage(RuntimeError, "requires an empty historical evidence set"):
            MigrationExecutor(connection).migrate(self.before_enforcement)

    def test_forward_preflight_rejects_all_partial_0009_evidence_categories(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before_enforcement)
        apps = executor.loader.project_state(self.before_enforcement).apps
        Source = apps.get_model("market", "SourceRegistry")
        Definition = apps.get_model("research", "StrategyDefinition")
        Version = apps.get_model("research", "StrategyVersion")
        Parameter = apps.get_model("research", "StrategyParameterManifest")
        Plan = apps.get_model("market", "HistoricalDatasetPlan")
        Dataset = apps.get_model("market", "DatasetVersion")
        Instrument = apps.get_model("market", "Instrument")
        Chunk = apps.get_model("market", "HistoricalIngestionChunk")
        Run = apps.get_model("market", "IngestionRun")
        Attempt = apps.get_model("market", "HistoricalIngestionAttempt")
        Manifest = apps.get_model("market", "IngestionManifest")
        Candle = apps.get_model("market", "Candle")
        Conflict = apps.get_model("market", "CandleConflict")
        Incident = apps.get_model("market", "DataQualityIncident")
        AuditEvent = apps.get_model("market", "AuditEvent")
        source = Source.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test",
            enabled=True,
        )
        definition = Definition.objects.create(key="partial-0009", name="Partial 0009")
        strategy = Version.objects.create(
            definition=definition,
            version="partial",
            detector_version="failed-break-detector-v1",
            data_identity="oanda-ba-ny17-friday-v1",
            event_identity="event-policy-none-v1",
            execution_identity="execution-h1-stop-first-v1",
            cost_identity="cost-observed-spread-only-v1",
            portfolio_identity="portfolio-common-fraction-025-100-050-v1",
            content_hash="f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882",
        )
        Parameter.objects.create(
            strategy_version=strategy,
            payload={},
            sha256="f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882",
            phase1_spec_hash="47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd",
            phase1_manifest_hash="f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882",
        )
        plan = Plan.objects.create(
            identity="oanda-ba-ny17-friday-v1",
            source=source,
            strategy_version=strategy,
            instruments=[],
            granularities=[],
            ranges={},
            alignment={},
            chunk_size=1,
            phase1_spec_hash="0" * 64,
            phase1_manifest_hash="0" * 64,
            payload={},
            sha256="0" * 64,
        )
        dataset = Dataset.objects.create(
            name="partial-0009",
            version="1",
            source=source,
            manifest={"historical_plan_sha256": plan.sha256},
            manifest_sha256="0" * 64,
        )
        instrument = Instrument.objects.create(
            code="EUR_USD",
            base_currency="EUR",
            quote_currency="USD",
            display_order=1,
        )
        start = datetime(2018, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=1)
        chunk = Chunk.objects.create(
            plan=plan,
            dataset_version=dataset,
            instrument=instrument,
            granularity="H1",
            requested_from=start,
            requested_to=end,
            canonical_request={},
            canonical_request_sha256="1" * 64,
            logical_key="2" * 64,
        )
        run = Run.objects.create(
            source=source,
            dataset_version=dataset,
            instrument=instrument,
            granularity="H1",
            requested_from=start,
            requested_to=end,
            parameters={},
            request_manifest_hash="3" * 64,
            status="succeeded",
            fetched_count=1,
            stored_count=1,
            finished_at=end,
        )
        attempt = Attempt.objects.create(
            chunk=chunk,
            ingestion_run=run,
            attempt_number=2,
            idempotency_key="invalid-contiguous-attempt",
        )
        false_payload = {"self_consistent_but_semantically_false": True}
        manifest = Manifest.objects.create(
            ingestion_run=run,
            dataset_version=dataset,
            payload=false_payload,
            sha256=hashlib.sha256(
                json.dumps(false_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        candle = Candle.objects.create(
            instrument=instrument,
            ingestion_run=run,
            dataset_version=dataset,
            granularity="H1",
            timestamp=end + timedelta(hours=1),
            complete=True,
            volume=1,
            bid_open=Decimal("1.000000"),
            bid_high=Decimal("1.000000"),
            bid_low=Decimal("1.000000"),
            bid_close=Decimal("1.000000"),
            ask_open=Decimal("1.000100"),
            ask_high=Decimal("1.000100"),
            ask_low=Decimal("1.000100"),
            ask_close=Decimal("1.000100"),
        )
        conflict = Conflict.objects.create(
            dataset_version=dataset,
            ingestion_manifest=manifest,
            existing_candle=candle,
            existing_payload_sha256="4" * 64,
            incoming_payload_sha256="5" * 64,
            differing_fields=["bid_open"],
            incoming_payload={},
        )
        incident = Incident.objects.create(
            dataset_version=dataset,
            ingestion_run=run,
            code="partial_0009",
            details={},
            evidence_sha256="6" * 64,
        )
        audit = AuditEvent.objects.create(
            event_type="market.historical_attempt_stale_failed",
            actor="partial-0009",
            subject_type="HistoricalIngestionAttempt",
            subject_id="missing",
            payload={"attempt_id": 999999},
        )

        with self.assertRaisesMessage(RuntimeError, "written without complete enforcement"):
            MigrationExecutor(connection).migrate(self.latest)

        guarded_tables = (
            "market_candleconflict",
            "market_dataqualityincident",
            "market_candle",
            "market_ingestionmanifest",
            "market_ingestionrun",
            "market_historicalingestionattempt",
            "market_historicalingestionchunk",
            "market_historicaldatasetplan",
            "market_datasetversion",
            "market_auditevent",
        )
        try:
            with connection.cursor() as cursor:
                for table in guarded_tables:
                    cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
            Conflict.objects.filter(pk=conflict.pk).delete()
            Incident.objects.filter(pk=incident.pk).delete()
            Candle.objects.filter(pk=candle.pk).delete()
            Manifest.objects.filter(pk=manifest.pk).delete()
            Attempt.objects.filter(pk=attempt.pk).delete()
            Run.objects.filter(pk=run.pk).delete()
            Chunk.objects.filter(pk=chunk.pk).delete()
            Dataset.objects.filter(pk=dataset.pk).delete()
            Plan.objects.filter(pk=plan.pk).delete()
            Instrument.objects.filter(pk=instrument.pk).delete()
            AuditEvent.objects.filter(pk=audit.pk).delete()
        finally:
            with connection.cursor() as cursor:
                for table in guarded_tables:
                    cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
