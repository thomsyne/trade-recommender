from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib import import_module
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import DatabaseError, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase

from market.historical_acquisition import (
    INSTRUMENTS,
    begin_historical_attempt,
    create_historical_dataset_plan,
    register_historical_dataset,
    run_historical_chunk,
)
from market.models import (
    Candle,
    DatasetRegistration,
    HistoricalDatasetPlan,
    HistoricalIngestionAttempt,
    IngestionRun,
    Instrument,
    SourceRegistry,
)
from market.services import DatasetQualityError, assert_dataset_usable
from market.tests.factories import candle
from research.models import (
    StrategyDefinition,
    StrategyParameterManifest,
    StrategyVersion,
)


class FakeClient:
    def fetch_candles(self, instrument, granularity, start, end):
        return [candle(start)], {
            "instrument": instrument,
            "granularity": granularity,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "price": "BA",
            "smooth": False,
            "alignmentTimezone": "America/New_York",
            "dailyAlignment": 17,
            "weeklyAlignment": "Friday",
            "requests": [{"status": 200}],
        }


class FailingClient:
    def fetch_candles(self, instrument, granularity, start, end):
        raise RuntimeError("synthetic provider failure")


class WrongRangeClient(FakeClient):
    def fetch_candles(self, instrument, granularity, start, end):
        candles, manifest = super().fetch_candles(instrument, granularity, start, end)
        manifest["price"] = "M"
        return candles, manifest


class HistoricalFixtureMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.new_york = ZoneInfo("America/New_York")

    def setUp(self):
        super().setUp()
        self.source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier=SourceRegistry.Tier.ESTABLISHED,
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="governed test",
            enabled=True,
        )
        for display_order, code in enumerate(INSTRUMENTS, 1):
            base, quote = code.split("_")
            Instrument.objects.create(
                code=code,
                base_currency=base,
                quote_currency=quote,
                display_order=display_order,
            )
        definition = StrategyDefinition.objects.create(
            key="failed-break-test", name="Failed break test"
        )
        self.strategy = StrategyVersion.objects.create(
            definition=definition,
            version="v1",
            detector_version="failed-break-detector-v1",
            data_identity="oanda-ba-ny17-friday-v1",
            event_identity="event-policy-none-v1",
            execution_identity="execution-h1-stop-first-v1",
            cost_identity="cost-observed-spread-only-v1",
            portfolio_identity="portfolio-common-fraction-025-100-050-v1",
            content_hash="1" * 64,
        )
        StrategyParameterManifest.objects.create(
            strategy_version=self.strategy,
            payload={},
            sha256="2" * 64,
            phase1_spec_hash="3" * 64,
            phase1_manifest_hash="4" * 64,
        )

    def payload(self, *, ranges=None):
        ranges = ranges or {
            "H1": {
                "from": datetime(2010, 1, 4, 0, tzinfo=self.new_york).isoformat(),
                "to": datetime(2010, 1, 4, 1, tzinfo=self.new_york).isoformat(),
            },
            "D": {
                "from": datetime(2010, 1, 3, 17, tzinfo=self.new_york).isoformat(),
                "to": datetime(2010, 1, 4, 17, tzinfo=self.new_york).isoformat(),
            },
            "W": {
                "from": datetime(2010, 1, 1, 17, tzinfo=self.new_york).isoformat(),
                "to": datetime(2010, 1, 8, 17, tzinfo=self.new_york).isoformat(),
            },
        }
        return {
            "identity": "oanda-ba-ny17-friday-v1",
            "source_id": self.source.pk,
            "strategy_version_id": self.strategy.pk,
            "dataset": {
                "name": "failed-break-history",
                "version": "test-v1",
                "description": "synthetic bounded fixture",
            },
            "instruments": list(INSTRUMENTS),
            "granularities": ["W", "D", "H1"],
            "ranges": ranges,
            "chunk_size": 4999,
        }

    def plan(self):
        return create_historical_dataset_plan(self.payload())


class HistoricalAcquisitionTests(HistoricalFixtureMixin, TestCase):
    def test_plan_is_idempotent_and_materializes_frozen_bid_ask_chunks(self):
        first_plan, first_dataset = self.plan()
        second_plan, second_dataset = self.plan()

        self.assertEqual(first_plan.pk, second_plan.pk)
        self.assertEqual(first_dataset.pk, second_dataset.pk)
        self.assertEqual(first_plan.chunks.count(), 18)
        self.assertEqual(first_plan.price_component, "COMBINED_BID_ASK")
        self.assertEqual(
            set(first_plan.chunks.values_list("granularity", flat=True)), {"W", "D", "H1"}
        )
        for chunk in first_plan.chunks.all():
            self.assertEqual(chunk.canonical_request["price"], "BA")
            self.assertEqual(chunk.canonical_request["price_component"], "COMBINED_BID_ASK")
            self.assertLess(chunk.requested_to, datetime(2019, 1, 1, 5, tzinfo=UTC))

    def test_boundary_completing_h1_and_post_boundary_daily_weekly_are_rejected(self):
        for granularity, start, end in (
            (
                "H1",
                datetime(2018, 12, 31, 23, tzinfo=self.new_york),
                datetime(2019, 1, 1, 0, tzinfo=self.new_york),
            ),
            (
                "D",
                datetime(2018, 12, 31, 17, tzinfo=self.new_york),
                datetime(2019, 1, 1, 17, tzinfo=self.new_york),
            ),
            (
                "W",
                datetime(2018, 12, 28, 17, tzinfo=self.new_york),
                datetime(2019, 1, 4, 17, tzinfo=self.new_york),
            ),
        ):
            ranges = self.payload()["ranges"]
            ranges[granularity] = {"from": start.isoformat(), "to": end.isoformat()}
            with (
                self.subTest(granularity=granularity),
                self.assertRaisesMessage(ValueError, "completing at/after development end"),
            ):
                create_historical_dataset_plan(self.payload(ranges=ranges))

    def test_running_attempt_blocks_concurrent_attempt_and_terminal_run_is_immutable(self):
        plan, _ = self.plan()
        chunk = plan.chunks.order_by("logical_key").first()
        attempt, created = begin_historical_attempt(chunk.logical_key)

        self.assertTrue(created)
        with self.assertRaisesMessage(DatasetQualityError, "already has a running attempt"):
            begin_historical_attempt(chunk.logical_key)
        attempt.ingestion_run.status = IngestionRun.Status.FAILED
        attempt.ingestion_run.finished_at = datetime.now(UTC)
        attempt.ingestion_run.save()
        attempt.ingestion_run.failure_reason = "changed"
        with self.assertRaisesMessage(ValidationError, "terminal ingestion runs are immutable"):
            attempt.ingestion_run.save()

    def test_failed_provider_attempt_is_append_only_and_retry_is_numbered(self):
        plan, _ = self.plan()
        chunk = plan.chunks.order_by("logical_key").first()

        with self.assertRaisesRegex(RuntimeError, "synthetic provider failure"):
            run_historical_chunk(chunk.logical_key, FailingClient())
        second = run_historical_chunk(chunk.logical_key, FakeClient())

        attempts = list(chunk.attempts.order_by("attempt_number"))
        self.assertEqual([item.attempt_number for item in attempts], [1, 2])
        self.assertEqual(attempts[0].ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertEqual(second.ingestion_run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(Candle.objects.count(), 1)

    def test_provider_response_must_match_logical_chunk_before_storage(self):
        plan, _ = self.plan()
        chunk = plan.chunks.first()

        with self.assertRaisesMessage(DatasetQualityError, "provider manifest conflicts"):
            run_historical_chunk(chunk.logical_key, WrongRangeClient())

        attempt = chunk.attempts.get()
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertEqual(Candle.objects.count(), 0)

    def test_complete_fixture_registers_immutably_with_deterministic_hashes(self):
        plan, dataset = self.plan()
        for chunk in plan.chunks.order_by("logical_key"):
            run_historical_chunk(chunk.logical_key, FakeClient())

        registration = register_historical_dataset(dataset.pk, plan.sha256)
        replay = register_historical_dataset(dataset.pk, plan.sha256)

        self.assertEqual(registration.pk, replay.pk)
        self.assertEqual(sum(registration.row_counts.values()), 18)
        self.assertEqual(set(registration.missingness.values()), {0})
        self.assertEqual(len(registration.report_sha256), 64)
        assert_dataset_usable(dataset)
        registration.row_counts = {}
        with self.assertRaises(ValidationError):
            registration.save()
        chunk = plan.chunks.first()
        with self.assertRaisesMessage(DatasetQualityError, "sealed"):
            begin_historical_attempt(chunk.logical_key)

    def test_registration_fails_closed_for_incomplete_dataset(self):
        plan, dataset = self.plan()
        chunk = plan.chunks.first()
        run_historical_chunk(chunk.logical_key, FakeClient())

        with self.assertRaisesMessage(DatasetQualityError, "exactly one successful attempt"):
            register_historical_dataset(dataset.pk, plan.sha256)

    @patch("market.management.commands.acquire_failed_break_dataset.OandaClient")
    def test_acquisition_command_requires_explicit_execute_before_client_creation(self, client):
        with self.assertRaisesMessage(CommandError, "explicit --execute"):
            call_command("acquire_failed_break_dataset", logical_chunk_key="0" * 64)
        client.assert_not_called()

    @patch("market.management.commands.acquire_failed_break_dataset.OandaClient")
    def test_acquisition_command_executes_only_the_selected_mocked_chunk(self, client_class):
        plan, _ = self.plan()
        chunk = plan.chunks.order_by("logical_key").first()
        client_class.return_value.__enter__.return_value = FakeClient()

        call_command(
            "acquire_failed_break_dataset", logical_chunk_key=chunk.logical_key, execute=True
        )

        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)
        self.assertEqual(Candle.objects.count(), 1)
        self.assertEqual(
            HistoricalIngestionAttempt.objects.get().chunk_id,
            chunk.pk,
        )

    def test_phase2b_market_migration_depends_on_approved_phase2a_graph(self):
        migration = import_module("market.migrations.0009_historical_dataset_governance").Migration
        self.assertEqual(
            set(migration.dependencies),
            {
                ("market", "0008_reject_governed_candle_promotion"),
                ("research", "0014_enforce_entry_boundary"),
            },
        )


class HistoricalAcquisitionDatabaseTests(HistoricalFixtureMixin, TransactionTestCase):
    reset_sequences = True

    def test_database_rejects_duplicate_attempt_number_and_terminal_run_mutation(self):
        plan, _ = self.plan()
        chunk = plan.chunks.first()
        attempt, _ = begin_historical_attempt(chunk.logical_key)

        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalIngestionAttempt.objects.create(
                chunk=chunk,
                ingestion_run=IngestionRun.objects.create(
                    source=chunk.plan.source,
                    dataset_version=chunk.dataset_version,
                    instrument=chunk.instrument,
                    granularity=chunk.granularity,
                    requested_from=chunk.requested_from,
                    requested_to=chunk.requested_to,
                    parameters=chunk.canonical_request,
                    request_manifest_hash="f" * 64,
                ),
                attempt_number=attempt.attempt_number,
                idempotency_key=attempt.idempotency_key,
            )
        attempt.ingestion_run.status = IngestionRun.Status.FAILED
        attempt.ingestion_run.finished_at = datetime.now(UTC)
        attempt.ingestion_run.save()
        with self.assertRaises(DatabaseError), transaction.atomic():
            IngestionRun.objects.filter(pk=attempt.ingestion_run_id).update(
                failure_reason="mutated terminal run"
            )

    def test_concurrent_attempt_start_creates_one_run(self):
        plan, _ = self.plan()
        logical_key = plan.chunks.first().logical_key

        def start():
            close_old_connections()
            try:
                attempt, created = begin_historical_attempt(logical_key)
                return attempt.pk, created
            except DatasetQualityError as error:
                return str(error)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: start(), range(2)))

        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)
        self.assertEqual(IngestionRun.objects.count(), 1)
        self.assertEqual(sum(isinstance(item, tuple) for item in results), 1)
        self.assertTrue(
            any(
                "already has a running attempt" in item for item in results if isinstance(item, str)
            )
        )

    def test_database_rejects_mutation_and_wrong_attempt_lineage(self):
        plan, dataset = self.plan()
        chunk = plan.chunks.first()
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalDatasetPlan.objects.filter(pk=plan.pk).update(identity="changed")

        wrong_instrument = Instrument.objects.exclude(pk=chunk.instrument_id).first()
        run = IngestionRun.objects.create(
            source=plan.source,
            dataset_version=dataset,
            instrument=wrong_instrument,
            granularity=chunk.granularity,
            requested_from=chunk.requested_from,
            requested_to=chunk.requested_to,
            parameters=chunk.canonical_request,
            request_manifest_hash="e" * 64,
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalIngestionAttempt.objects.create(
                chunk=chunk,
                ingestion_run=run,
                attempt_number=1,
                idempotency_key=f"failed-break-ingestion-attempt:{chunk.logical_key}:1",
            )

    def test_database_seals_registered_dataset(self):
        plan, dataset = self.plan()
        for chunk in plan.chunks.order_by("logical_key"):
            run_historical_chunk(chunk.logical_key, FakeClient())
        registration = register_historical_dataset(dataset.pk, plan.sha256)

        with self.assertRaises(DatabaseError), transaction.atomic():
            DatasetRegistration.objects.filter(pk=registration.pk).delete()
        with self.assertRaises(DatabaseError), transaction.atomic():
            Candle.objects.create(
                instrument=Instrument.objects.get(code="USD_CAD"),
                ingestion_run=plan.chunks.first().attempts.get().ingestion_run,
                dataset_version=dataset,
                granularity="H1",
                **candle(datetime(2010, 1, 4, 0, tzinfo=UTC)).__dict__,
            )
