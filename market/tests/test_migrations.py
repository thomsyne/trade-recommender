from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class Phase2BMigrationSafetyTests(TransactionTestCase):
    latest = [("market", "0010_dataset_registration_enforcement")]
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

    def test_reverse_migration_rejects_historical_dataset_evidence(self):
        executor = MigrationExecutor(connection)
        apps = executor.loader.project_state(self.latest).apps
        Source = apps.get_model("market", "SourceRegistry")
        Dataset = apps.get_model("market", "DatasetVersion")
        source = Source.objects.create(
            name="rollback-evidence",
            tier="quarantine",
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test",
        )
        Dataset.objects.create(
            name="rollback-evidence",
            version="1",
            source=source,
            manifest={"historical_plan_sha256": "0" * 64},
            manifest_sha256="0" * 64,
        )

        with self.assertRaisesMessage(RuntimeError, "rollback is forbidden"):
            MigrationExecutor(connection).migrate(self.before_enforcement)

    def test_forward_preflight_rejects_partial_0009_plan(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before_enforcement)
        apps = executor.loader.project_state(self.before_enforcement).apps
        Source = apps.get_model("market", "SourceRegistry")
        Definition = apps.get_model("research", "StrategyDefinition")
        Version = apps.get_model("research", "StrategyVersion")
        Parameter = apps.get_model("research", "StrategyParameterManifest")
        Plan = apps.get_model("market", "HistoricalDatasetPlan")
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

        with self.assertRaisesMessage(RuntimeError, "invalid historical plan"):
            MigrationExecutor(connection).migrate(self.latest)

        Plan.objects.filter(pk=plan.pk).delete()
