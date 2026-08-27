import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase

from market.historical_acquisition import (
    INSTRUMENTS,
    PHASE1_MANIFEST_SHA256,
    PHASE1_SPEC_SHA256,
    begin_historical_attempt,
    create_historical_dataset_plan,
    register_historical_dataset,
    resolve_stale_historical_attempt,
    run_historical_chunk,
    stable_hash,
)
from market.models import (
    AuditEvent,
    Candle,
    DatasetRegistration,
    HistoricalDatasetPlan,
    HistoricalIngestionAttempt,
    HistoricalIngestionChunk,
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
from research.signal_count import _validate_dataset_contract


class FakeClient:
    def fetch_historical_chunk(self, instrument, granularity, start, end):
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
            "includeFirst": True,
            "requests": [{"status": 200}],
        }


class FailingClient:
    def fetch_historical_chunk(self, instrument, granularity, start, end):
        raise RuntimeError("synthetic provider failure")


class WrongRangeClient(FakeClient):
    def fetch_historical_chunk(self, instrument, granularity, start, end):
        candles, manifest = super().fetch_historical_chunk(instrument, granularity, start, end)
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
            pair_metadata={
                "instruments": [
                    "EUR_USD",
                    "GBP_USD",
                    "EUR_GBP",
                    "USD_CAD",
                    "USD_JPY",
                    "AUD_USD",
                ]
            },
            content_hash=PHASE1_MANIFEST_SHA256,
        )
        StrategyParameterManifest.objects.create(
            strategy_version=self.strategy,
            payload={},
            sha256=PHASE1_MANIFEST_SHA256,
            phase1_spec_hash=PHASE1_SPEC_SHA256,
            phase1_manifest_hash=PHASE1_MANIFEST_SHA256,
        )

    def payload(self, *, ranges=None):
        ranges = ranges or {
            "H1": {
                "from": datetime(2018, 12, 31, 22, tzinfo=self.new_york).isoformat(),
                "to": datetime(2018, 12, 31, 23, tzinfo=self.new_york).isoformat(),
            },
            "D": {
                "from": datetime(2018, 12, 30, 17, tzinfo=self.new_york).isoformat(),
                "to": datetime(2018, 12, 31, 17, tzinfo=self.new_york).isoformat(),
            },
            "W": {
                "from": datetime(2018, 12, 21, 17, tzinfo=self.new_york).isoformat(),
                "to": datetime(2018, 12, 28, 17, tzinfo=self.new_york).isoformat(),
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

    def test_generated_manifest_is_accepted_by_existing_return_blind_validator(self):
        ranges = {
            "H1": {
                "from": datetime(2009, 12, 30, 10, tzinfo=self.new_york).isoformat(),
                "to": datetime(2018, 12, 31, 23, tzinfo=self.new_york).isoformat(),
            },
            "D": {
                "from": datetime(2009, 2, 22, 17, tzinfo=self.new_york).isoformat(),
                "to": datetime(2018, 12, 31, 17, tzinfo=self.new_york).isoformat(),
            },
            "W": {
                "from": datetime(2009, 12, 18, 17, tzinfo=self.new_york).isoformat(),
                "to": datetime(2018, 12, 28, 17, tzinfo=self.new_york).isoformat(),
            },
        }
        _, dataset = create_historical_dataset_plan(self.payload(ranges=ranges))

        grouped = _validate_dataset_contract(
            dataset, self.strategy, datetime(2019, 1, 1, tzinfo=self.new_york)
        )

        self.assertEqual(set(grouped), set(INSTRUMENTS))
        self.assertEqual(len(dataset.manifest["required_ranges"]), 18)

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
                self.assertRaisesRegex(ValueError, "final development completion|completing"),
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

    def test_stale_attempt_requires_explicit_threshold_and_allows_separate_retry(self):
        plan, _ = self.plan()
        chunk = plan.chunks.first()
        attempt, _ = begin_historical_attempt(chunk.logical_key)

        with patch(
            "market.historical_acquisition.timezone.now",
            return_value=attempt.ingestion_run.started_at + timedelta(hours=3),
        ):
            resolved = resolve_stale_historical_attempt(
                attempt.pk, timedelta(hours=2), "worker lease was manually verified absent"
            )
        retry, created = begin_historical_attempt(chunk.logical_key)

        self.assertEqual(resolved.ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertTrue(created)
        self.assertEqual(retry.attempt_number, 2)
        event = AuditEvent.objects.get(event_type="market.historical_attempt_stale_failed")
        self.assertEqual(event.payload["attempt_id"], attempt.pk)
        with self.assertRaisesMessage(DatasetQualityError, "RUNNING"):
            resolve_stale_historical_attempt(
                attempt.pk, timedelta(hours=2), "must not transition twice"
            )

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

    def test_pgcrypto_canonical_hash_support_matches_application_hash(self):
        payload = {"z": [True, 2, {"text": "spaces stay"}], "a": "value"}
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regprocedure('digest(bytea,text)'), market_sha256(%s::jsonb)",
                [json.dumps(payload)],
            )
            digest_function, database_hash = cursor.fetchone()
        self.assertIsNotNone(digest_function)
        self.assertEqual(database_hash, stable_hash(payload))

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
        with self.assertRaises(DatabaseError), transaction.atomic():
            IngestionRun.objects.create(
                source=plan.source,
                dataset_version=dataset,
                instrument=wrong_instrument,
                granularity=chunk.granularity,
                requested_from=chunk.requested_from,
                requested_to=chunk.requested_to,
                parameters=chunk.canonical_request,
                request_manifest_hash="e" * 64,
            )

    def test_database_rejects_bulk_plan_chunk_hash_and_logical_key_tampering(self):
        plan, dataset = self.plan()
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE market_historicaldatasetplan SET identity=%s WHERE id=%s",
                ["raw-sql-tamper", plan.pk],
            )
        tampered_plan = HistoricalDatasetPlan(
            identity=plan.identity,
            source=plan.source,
            strategy_version=plan.strategy_version,
            instruments=plan.instruments[:-1],
            granularities=plan.granularities,
            ranges=plan.ranges,
            alignment=plan.alignment,
            chunk_size=plan.chunk_size,
            phase1_spec_hash=plan.phase1_spec_hash,
            phase1_manifest_hash=plan.phase1_manifest_hash,
            payload=plan.payload,
            sha256="0" * 64,
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalDatasetPlan.objects.bulk_create([tampered_plan])

        chunk = plan.chunks.first()
        tampered_chunk = HistoricalIngestionChunk(
            plan=plan,
            dataset_version=dataset,
            instrument=chunk.instrument,
            granularity=chunk.granularity,
            requested_from=chunk.requested_from,
            requested_to=chunk.requested_to,
            canonical_request=chunk.canonical_request,
            canonical_request_sha256="0" * 64,
            logical_key="1" * 64,
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalIngestionChunk.objects.bulk_create([tampered_chunk])

    def test_database_rejects_success_without_manifest_and_false_registration(self):
        plan, dataset = self.plan()
        attempt, _ = begin_historical_attempt(plan.chunks.first().logical_key)
        with self.assertRaises(DatabaseError), transaction.atomic():
            IngestionRun.objects.filter(pk=attempt.ingestion_run_id).update(
                status=IngestionRun.Status.SUCCEEDED,
                finished_at=datetime.now(UTC),
            )
        with self.assertRaises(DatabaseError), transaction.atomic():
            DatasetRegistration.objects.bulk_create(
                [
                    DatasetRegistration(
                        dataset_version=dataset,
                        plan=plan,
                        series_manifest=[],
                        row_counts={},
                        first_last_timestamps={},
                        missingness={},
                        conflict_count=0,
                        incident_count=0,
                        logical_chunk_set_hash="0" * 64,
                        successful_attempt_set_hash="0" * 64,
                        ingestion_manifest_set_hash="0" * 64,
                        candle_key_hash="0" * 64,
                        candle_payload_hash="0" * 64,
                        configuration_sha256="0" * 64,
                        report_sha256="0" * 64,
                    )
                ]
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
