from datetime import UTC, datetime

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class Phase2ADataMigrationTests(TransactionTestCase):
    migrate_from = [("research", "0010_phase_2a_append_only_triggers")]
    migrate_to = [("research", "0012_enforce_phase_2a_lineage")]

    def test_multi_book_entry_transitions_and_detector_runs_migrate_deterministically(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        Source = old_apps.get_model("market", "SourceRegistry")
        Instrument = old_apps.get_model("market", "Instrument")
        Dataset = old_apps.get_model("market", "DatasetVersion")
        Definition = old_apps.get_model("research", "StrategyDefinition")
        Version = old_apps.get_model("research", "StrategyVersion")
        Setup = old_apps.get_model("research", "SetupEvent")
        Transition = old_apps.get_model("research", "SetupTransition")
        Evaluation = old_apps.get_model("research", "EntryEligibilityEvaluation")
        Analysis = old_apps.get_model("research", "AnalysisRun")

        source = Source.objects.create(
            name="migration-fixture",
            tier="quarantine",
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test",
        )
        instrument = Instrument.objects.create(
            code="EUR_USD", base_currency="EUR", quote_currency="USD", display_order=1
        )
        dataset = Dataset.objects.create(
            name="migration", version="1", source=source, manifest_sha256="1" * 64
        )
        definition = Definition.objects.create(key="migration", name="Migration")

        def strategy(version, content_hash):
            return Version.objects.create(
                definition=definition,
                version=version,
                detector_version="shared-detector",
                data_identity="data",
                event_identity="event",
                execution_identity="execution",
                cost_identity="cost",
                portfolio_identity="portfolio",
                content_hash=content_hash,
            )

        first_strategy = strategy("1", "2" * 64)
        second_strategy = strategy("2", "3" * 64)
        at = datetime(2026, 1, 1, tzinfo=UTC)
        setup = Setup.objects.create(
            instrument=instrument,
            direction="long",
            sweep_h1_timestamp=at,
            detector_version="shared-detector",
            dataset_version=dataset,
            strategy_version=first_strategy,
            sweep_evidence={},
            bias_evidence={},
            provisional_swing_evidence={},
            threshold_evidence={},
            evidence_hash="4" * 64,
        )
        Transition.objects.create(
            setup=setup,
            from_state="CONFIRMED",
            to_state="NO_TARGET",
            effective_at=at,
            reason="NO_ACTIVE_OPPOSING_LEVEL",
            evidence={},
            evidence_hash="5" * 64,
        )
        for book in ("book-a", "book-b"):
            Evaluation.objects.create(
                setup=setup,
                book_identity=book,
                decision="NO_TARGET",
                terminal_reason="NO_ACTIVE_OPPOSING_LEVEL",
                evidence={},
                evidence_hash="5" * 64,
            )
        for strategy_version in (first_strategy, second_strategy):
            Analysis.objects.create(
                instrument=instrument,
                completed_h1_timestamp=at,
                strategy_version=strategy_version,
                dataset_version=dataset,
                result="NO_SETUP",
                evidence_hash="6" * 64,
            )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        Transition = apps.get_model("research", "SetupTransition")
        Analysis = apps.get_model("research", "AnalysisRun")

        self.assertEqual(
            set(
                Transition.objects.filter(setup_id=setup.pk, from_state="CONFIRMED").values_list(
                    "book_identity", flat=True
                )
            ),
            {"book-a", "book-b"},
        )
        self.assertEqual(Analysis.objects.count(), 1)
