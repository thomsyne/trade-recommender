from datetime import UTC, datetime
from importlib import import_module

from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class Phase2ADataMigrationTests(TransactionTestCase):
    migrate_from = [("research", "0010_phase_2a_append_only_triggers")]
    prepared = [("research", "0011_phase_2a_review_corrections")]
    migrate_to = [("research", "0014_enforce_entry_boundary")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        self.apps = executor.loader.project_state(self.migrate_from).apps
        self.addCleanup(self._restore_latest_schema)

        Source = self.apps.get_model("market", "SourceRegistry")
        Instrument = self.apps.get_model("market", "Instrument")
        Dataset = self.apps.get_model("market", "DatasetVersion")
        Definition = self.apps.get_model("research", "StrategyDefinition")
        Version = self.apps.get_model("research", "StrategyVersion")
        self.Setup = self.apps.get_model("research", "SetupEvent")
        self.Transition = self.apps.get_model("research", "SetupTransition")
        self.Evaluation = self.apps.get_model("research", "EntryEligibilityEvaluation")
        self.Analysis = self.apps.get_model("research", "AnalysisRun")
        self.JobRun = self.apps.get_model("research", "JobRun")
        self.Level = self.apps.get_model("research", "Level")

        source = Source.objects.create(
            name="migration-fixture",
            tier="quarantine",
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test",
        )
        self.instrument = Instrument.objects.create(
            code="EUR_USD", base_currency="EUR", quote_currency="USD", display_order=1
        )
        self.dataset = Dataset.objects.create(
            name="migration", version="1", source=source, manifest_sha256="1" * 64
        )
        definition = Definition.objects.create(key="migration", name="Migration")
        self.strategy = self._strategy(Version, definition, "1", "2" * 64)
        self.other_strategy = self._strategy(Version, definition, "2", "3" * 64)
        self.at = datetime(2026, 1, 1, tzinfo=UTC)

    def _restore_latest_schema(self):
        MigrationExecutor(connection).migrate(self.migrate_to)

    @staticmethod
    def _strategy(Version, definition, version, content_hash):
        return Version.objects.create(
            definition=definition,
            version=version,
            detector_version=f"detector-{version}",
            data_identity="data",
            event_identity="event",
            execution_identity="execution",
            cost_identity="cost",
            portfolio_identity="portfolio",
            content_hash=content_hash,
        )

    def _setup(self):
        return self.Setup.objects.create(
            instrument=self.instrument,
            direction="long",
            sweep_h1_timestamp=self.at,
            detector_version=self.strategy.detector_version,
            dataset_version=self.dataset,
            strategy_version=self.strategy,
            sweep_evidence={},
            bias_evidence={},
            provisional_swing_evidence={},
            threshold_evidence={},
            evidence_hash="4" * 64,
        )

    def _blocked_multi_book_fixture(self):
        setup = self._setup()
        self.Transition.objects.create(
            setup=setup,
            from_state="TRIGGER_PENDING",
            to_state="CONFIRMED",
            effective_at=self.at,
            evidence={},
            evidence_hash="4" * 64,
        )
        self.Transition.objects.create(
            setup=setup,
            from_state="CONFIRMED",
            to_state="NO_TARGET",
            effective_at=self.at,
            reason="NO_ACTIVE_OPPOSING_LEVEL",
            evidence={},
            evidence_hash="5" * 64,
        )
        for book in ("book-a", "book-b"):
            self.Evaluation.objects.create(
                setup=setup,
                book_identity=book,
                decision="NO_TARGET",
                terminal_reason="NO_ACTIVE_OPPOSING_LEVEL",
                evidence={},
                evidence_hash="5" * 64,
            )
        self.Analysis.objects.create(
            instrument=self.instrument,
            completed_h1_timestamp=self.at,
            strategy_version=self.strategy,
            dataset_version=self.dataset,
            result="NO_SETUP",
            evidence_hash="6" * 64,
        )
        return setup

    def test_multi_book_rewrite_is_reversible_and_preserves_protection(self):
        setup = self._blocked_multi_book_fixture()

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        Transition = apps.get_model("research", "SetupTransition")
        self.assertEqual(
            set(
                Transition.objects.filter(setup_id=setup.pk, from_state="CONFIRMED").values_list(
                    "book_identity", flat=True
                )
            ),
            {"book-a", "book-b"},
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_trigger WHERE tgname LIKE %s AND NOT tgisinternal",
                ["%_phase2a_migration_guard"],
            )
            self.assertEqual(cursor.fetchone()[0], 0)

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        Transition = old_apps.get_model("research", "SetupTransition")
        self.assertEqual(
            Transition.objects.filter(setup_id=setup.pk, from_state="CONFIRMED").count(), 1
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            Transition.objects.filter(setup_id=setup.pk).update(evidence={"tampered": True})

    def test_injected_rewrite_failure_rolls_back_data_and_trigger_removal(self):
        setup = self._blocked_multi_book_fixture()
        executor = MigrationExecutor(connection)
        executor.migrate(self.prepared)
        apps = executor.loader.project_state(self.prepared).apps
        rewrite = import_module(
            "research.migrations.0012_enforce_phase_2a_lineage"
        ).rewrite_with_protection

        with self.assertRaisesMessage(RuntimeError, "injected migration failure"):
            with connection.schema_editor(atomic=True) as schema_editor:
                rewrite(apps, schema_editor, inject_failure=True)

        Transition = apps.get_model("research", "SetupTransition")
        stored = Transition.objects.get(setup_id=setup.pk, from_state="CONFIRMED")
        self.assertEqual(stored.book_identity, "")
        self.assertIsNone(stored.strategy_version_id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tgname FROM pg_trigger WHERE tgname IN (%s, %s) AND NOT tgisinternal",
                [
                    "research_setuptransition_append_only",
                    "research_setuptransition_phase2a_migration_guard",
                ],
            )
            self.assertEqual(
                {row[0] for row in cursor.fetchall()},
                {
                    "research_setuptransition_append_only",
                    "research_setuptransition_phase2a_migration_guard",
                },
            )
        with self.assertRaises(DatabaseError), transaction.atomic():
            Transition.objects.filter(pk=stored.pk).update(evidence={"tampered": True})

    def test_preflight_rejects_entry_pending_and_mismatched_job_lineage(self):
        preflight = import_module(
            "research.migrations.0011_phase_2a_review_corrections"
        ).preflight_registered_identities

        with transaction.atomic():
            setup = self._setup()
            target = self.Level.objects.create(
                family="PREVIOUS_WEEKLY_EXTREME",
                role="resistance",
                instrument=self.instrument,
                strategy_version=self.strategy,
                dataset_version=self.dataset,
                source_timeframe="W",
                source_candle_timestamp=self.at,
                central_price="1.2",
                zone_lower="1.19",
                zone_upper="1.21",
                atr_at_activation="0.1",
                activated_at=self.at,
                stable_key="7" * 64,
            )
            self.Evaluation.objects.create(
                setup=setup,
                book_identity="book",
                decision="ENTRY_PENDING",
                entry_timestamp=self.at,
                entry_price="1.1",
                stop_price="1.0",
                target_price="1.19",
                reward_risk="1.9",
                target_level=target,
                evidence_hash="8" * 64,
            )
            with self.assertRaisesMessage(RuntimeError, "lack registered CAD conversion"):
                preflight(self.apps, None)
            transaction.set_rollback(True)

        with transaction.atomic():
            setup = self._setup()
            job = self.JobRun.objects.create(
                job_name="wrong-lineage",
                strategy_version=self.other_strategy,
                dataset_version=self.dataset,
                config_hash="9" * 64,
                idempotency_key="wrong-lineage",
                as_of=self.at,
                status="succeeded",
            )
            self.Transition.objects.create(
                setup=setup,
                from_state="TRIGGER_PENDING",
                to_state="CONFIRMED",
                effective_at=self.at,
                evidence_hash="a" * 64,
                job_run=job,
            )
            with self.assertRaisesMessage(RuntimeError, "job lineage conflicts"):
                preflight(self.apps, None)
            transaction.set_rollback(True)
