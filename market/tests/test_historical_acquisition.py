import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase

from market.historical_acquisition import (
    ACQUISITION_CONTRACT,
    ACQUISITION_VERSION,
    FROZEN_RANGES,
    INSTRUMENTS,
    PHASE1_MANIFEST_SHA256,
    PHASE1_SPEC_SHA256,
    SOURCE_IDENTITY,
    begin_historical_attempt,
    create_historical_dataset_plan,
    offline_acquisition_report,
    parse_timestamp,
    register_historical_dataset,
    resolve_stale_historical_attempt,
    run_historical_chunk,
    stable_hash,
)
from market.models import (
    AuditEvent,
    Candle,
    DatasetRegistration,
    DatasetVersion,
    HistoricalDatasetPlan,
    HistoricalIngestionAttempt,
    HistoricalIngestionChunk,
    IngestionManifest,
    IngestionRun,
    Instrument,
    SourceRegistry,
)
from market.quality import expected_candle_timestamps
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
        return [candle(item) for item in expected_candle_timestamps(start, end, granularity)], {
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
            "requests": [
                {
                    "endpoint_identity": (
                        f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"
                    ),
                    "http_method": "GET",
                    "oanda_environment": "practice",
                    "canonical_request_sha256": stable_hash(
                        {
                            "instrument": instrument,
                            "granularity": granularity,
                            "from": start.isoformat(),
                            "to": end.isoformat(),
                            "price": "BA",
                            "price_component": "COMBINED_BID_ASK",
                            "smooth": False,
                            "dailyAlignment": 17,
                            "alignmentTimezone": "America/New_York",
                            "weeklyAlignment": "Friday",
                            "includeFirst": True,
                            "complete_only": True,
                        }
                    ),
                    "provider_request_id": "test-request-id",
                    "http_status": 200,
                }
            ],
        }


class FailingClient:
    def fetch_historical_chunk(self, instrument, granularity, start, end):
        raise RuntimeError("synthetic provider failure")


class WrongRangeClient(FakeClient):
    def fetch_historical_chunk(self, instrument, granularity, start, end):
        candles, manifest = super().fetch_historical_chunk(instrument, granularity, start, end)
        manifest["price"] = "M"
        return candles, manifest


class CondensedFakeClient(FakeClient):
    def fetch_historical_chunk(self, instrument, granularity, start, end):
        _, manifest = super().fetch_historical_chunk(instrument, granularity, start, end)
        return [candle(start)], manifest


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
                "from": datetime(2009, 12, 31, 10, tzinfo=self.new_york).isoformat(),
                "to": datetime(2018, 12, 31, 23, tzinfo=self.new_york).isoformat(),
            },
            "D": {
                "from": datetime(2009, 2, 26, 17, tzinfo=self.new_york).isoformat(),
                "to": datetime(2018, 12, 31, 17, tzinfo=self.new_york).isoformat(),
            },
            "W": {
                "from": datetime(2009, 12, 18, 17, tzinfo=self.new_york).isoformat(),
                "to": datetime(2018, 12, 28, 17, tzinfo=self.new_york).isoformat(),
            },
        }
        return {
            "acquisition_contract": ACQUISITION_CONTRACT,
            "acquisition_version": ACQUISITION_VERSION,
            "source": {"name": "OANDA v20", "governed_identity": SOURCE_IDENTITY},
            "strategy": {
                "definition_key": self.strategy.definition.key,
                "version": self.strategy.version,
                "content_hash": self.strategy.content_hash,
            },
            "data_identity": "oanda-ba-ny17-friday-v1",
            "phase1_spec_hash": PHASE1_SPEC_SHA256,
            "phase1_manifest_hash": PHASE1_MANIFEST_SHA256,
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

    def condensed_expected_timestamps(self, plan):
        series_starts = {
            granularity: tuple(
                plan.chunks.filter(instrument__code=INSTRUMENTS[0], granularity=granularity)
                .order_by("requested_from")
                .values_list("requested_from", flat=True)
            )
            for granularity in ("D", "H1", "W")
        }

        def condensed(start, end, granularity):
            plan_range = plan.ranges[granularity]
            if start == parse_timestamp(plan_range["from"]) and end == parse_timestamp(
                plan_range["to"]
            ):
                return series_starts[granularity]
            return (start,)

        return patch("market.historical_acquisition.expected_candle_timestamps", condensed)

    @contextmanager
    def without_registration_validation_trigger(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """ALTER TABLE market_datasetregistration
                   DISABLE TRIGGER market_dataset_registration_validate"""
            )
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute(
                    """ALTER TABLE market_datasetregistration
                       ENABLE TRIGGER market_dataset_registration_validate"""
                )

    def manifest_payload(self, attempt):
        chunk = attempt.chunk
        return {
            "instrument": chunk.instrument.code,
            "granularity": chunk.granularity,
            "from": chunk.requested_from.isoformat(),
            "to": chunk.requested_to.isoformat(),
            "price": "BA",
            "price_component": "COMBINED_BID_ASK",
            "smooth": False,
            "dailyAlignment": 17,
            "alignmentTimezone": "America/New_York",
            "weeklyAlignment": "Friday",
            "includeFirst": True,
            "complete_only": True,
            "historical_logical_key": chunk.logical_key,
            "historical_attempt": attempt.attempt_number,
            "requests": [
                {
                    "endpoint_identity": (
                        f"oanda-v20-practice:GET:/v3/instruments/{chunk.instrument.code}/candles"
                    ),
                    "http_method": "GET",
                    "oanda_environment": "practice",
                    "canonical_request_sha256": chunk.canonical_request_sha256,
                    "provider_request_id": "test-request-id",
                    "http_status": 200,
                }
            ],
        }


class HistoricalAcquisitionTests(HistoricalFixtureMixin, TestCase):
    def test_plan_is_idempotent_and_materializes_frozen_bid_ask_chunks(self):
        first_plan, first_dataset = self.plan()
        second_plan, second_dataset = self.plan()

        self.assertEqual(first_plan.pk, second_plan.pk)
        self.assertEqual(first_dataset.pk, second_dataset.pk)
        self.assertEqual(first_plan.chunks.count(), 84)
        self.assertEqual(first_plan.price_component, "COMBINED_BID_ASK")
        self.assertEqual(
            set(first_plan.chunks.values_list("granularity", flat=True)), {"W", "D", "H1"}
        )
        for chunk in first_plan.chunks.all():
            self.assertEqual(chunk.canonical_request["price"], "BA")
            self.assertEqual(chunk.canonical_request["price_component"], "COMBINED_BID_ASK")
            self.assertIs(chunk.canonical_request["includeFirst"], True)
            self.assertLess(chunk.requested_to, datetime(2019, 1, 1, 5, tzinfo=UTC))

    def test_plan_and_chunk_hashes_contain_only_portable_identities(self):
        plan, dataset = self.plan()
        chunk = plan.chunks.first()
        serialized = json.dumps(
            {"plan": plan.payload, "dataset": dataset.manifest, "request": chunk.canonical_request}
        )

        self.assertNotIn('"source_id"', serialized)
        self.assertNotIn('"strategy_version_id"', serialized)
        without_include_first = {**chunk.canonical_request}
        without_include_first.pop("includeFirst")
        false_include_first = {**chunk.canonical_request, "includeFirst": False}
        self.assertNotEqual(stable_hash(without_include_first), chunk.canonical_request_sha256)
        self.assertNotEqual(stable_hash(false_include_first), chunk.canonical_request_sha256)
        for changed_hash in map(stable_hash, (without_include_first, false_include_first)):
            self.assertNotEqual(
                stable_hash(
                    {
                        "plan_sha256": plan.sha256,
                        "dataset_manifest_sha256": dataset.manifest_sha256,
                        "canonical_request_sha256": changed_hash,
                    }
                ),
                chunk.logical_key,
            )

    def test_generated_manifest_is_compatible_but_requires_registration_for_admission(self):
        plan, dataset = self.plan()

        with (
            self.assertRaisesMessage(ValueError, "exactly one immutable dataset registration"),
            patch("research.signal_count.Candle.objects") as candles,
        ):
            _validate_dataset_contract(
                dataset, self.strategy, datetime(2019, 1, 1, tzinfo=self.new_york)
            )
        candles.assert_not_called()
        self.assertEqual(len(dataset.manifest["required_ranges"]), 18)
        self.assertEqual(dataset.manifest["granularities"], ["D", "H1", "W"])
        self.assertEqual(dataset.manifest["price_component"], "COMBINED_BID_ASK")
        self.assertEqual(plan.ranges, FROZEN_RANGES)
        self.assertEqual(
            {item: plan.ranges[item]["expected_count_per_instrument"] for item in FROZEN_RANGES},
            {"D": 2567, "H1": 56341, "W": 471},
        )
        self.assertEqual(
            sum(item["expected_count_per_instrument"] for item in plan.ranges.values()) * 6,
            356274,
        )

        registration = SimpleNamespace(
            dataset_version_id=dataset.pk,
            plan=plan,
            series_manifest=[],
            row_counts={},
            first_last_timestamps={},
            missingness={},
            conflict_count=0,
            incident_count=0,
            logical_chunk_set_hash="1" * 64,
            successful_attempt_set_hash="2" * 64,
            ingestion_manifest_set_hash="3" * 64,
            candle_key_hash="4" * 64,
            candle_payload_hash="5" * 64,
        )
        configuration = {
            "identity": "failed-break-historical-dataset-registration-v1",
            "plan_sha256": plan.sha256,
            "dataset_manifest_sha256": dataset.manifest_sha256,
            "price_component": "COMBINED_BID_ASK",
            "logical_chunk_set_hash": registration.logical_chunk_set_hash,
        }
        registration.configuration_sha256 = stable_hash(configuration)
        report = {
            "configuration_sha256": registration.configuration_sha256,
            "series_manifest": registration.series_manifest,
            "row_counts": registration.row_counts,
            "first_last_timestamps": registration.first_last_timestamps,
            "missingness": registration.missingness,
            "conflict_count": registration.conflict_count,
            "incident_count": registration.incident_count,
            "logical_chunk_set_hash": registration.logical_chunk_set_hash,
            "successful_attempt_set_hash": registration.successful_attempt_set_hash,
            "ingestion_manifest_set_hash": registration.ingestion_manifest_set_hash,
            "candle_key_hash": registration.candle_key_hash,
            "candle_payload_hash": registration.candle_payload_hash,
        }
        registration.report_sha256 = stable_hash(report)
        with (
            patch("research.signal_count.DatasetRegistration.objects") as registrations,
            patch("research.signal_count.Candle.objects") as candles,
        ):
            queryset = registrations.filter.return_value.select_related.return_value
            queryset.count.return_value = 1
            queryset.get.return_value = registration
            grouped = _validate_dataset_contract(
                dataset, self.strategy, datetime(2019, 1, 1, tzinfo=self.new_york)
            )
        self.assertEqual(set(grouped), set(INSTRUMENTS))
        candles.assert_not_called()

        sibling_strategy = SimpleNamespace(
            pk=self.strategy.pk + 1000,
            content_hash=self.strategy.content_hash,
            pair_metadata=self.strategy.pair_metadata,
            data_identity=self.strategy.data_identity,
        )
        original_identity = plan.identity
        original_dataset_id = registration.dataset_version_id
        original_report_hash = registration.report_sha256
        cases = (
            ("strategy", sibling_strategy),
            ("plan", self.strategy),
            ("dataset", self.strategy),
            ("hash", self.strategy),
        )
        for case, supplied_strategy in cases:
            plan.identity = "wrong" if case == "plan" else original_identity
            registration.dataset_version_id = (
                dataset.pk + 1000 if case == "dataset" else original_dataset_id
            )
            registration.report_sha256 = "0" * 64 if case == "hash" else original_report_hash
            with (
                self.subTest(case=case),
                patch("research.signal_count.DatasetRegistration.objects") as registrations,
                patch("research.signal_count.Candle.objects") as candles,
            ):
                queryset = registrations.filter.return_value.select_related.return_value
                queryset.count.return_value = 1
                queryset.get.return_value = registration
                with self.assertRaisesMessage(ValueError, "hashes or identities"):
                    _validate_dataset_contract(
                        dataset,
                        supplied_strategy,
                        datetime(2019, 1, 1, tzinfo=self.new_york),
                    )
                candles.assert_not_called()
        plan.identity = original_identity
        registration.dataset_version_id = original_dataset_id
        registration.report_sha256 = original_report_hash

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

    def test_frozen_starts_and_counts_reject_contraction_or_expansion(self):
        expected = {"D": 2567, "H1": 56341, "W": 471}
        plan, _ = self.plan()
        self.assertEqual(
            {key: value["expected_count_per_instrument"] for key, value in plan.ranges.items()},
            expected,
        )
        for granularity in ("D", "H1", "W"):
            for direction in (-1, 1):
                ranges = self.payload()["ranges"]
                start = datetime.fromisoformat(ranges[granularity]["from"])
                ranges[granularity]["from"] = (start + direction * timedelta(days=7)).isoformat()
                with (
                    self.subTest(granularity=granularity, direction=direction),
                    self.assertRaisesMessage(ValueError, "frozen acquisition range"),
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
        self.assertGreater(Candle.objects.count(), 0)

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
        with (
            self.condensed_expected_timestamps(plan),
            self.without_registration_validation_trigger(),
        ):
            for chunk in plan.chunks.order_by("logical_key"):
                run_historical_chunk(chunk.logical_key, CondensedFakeClient())
            registration = register_historical_dataset(dataset.pk, plan.sha256)
        replay = register_historical_dataset(dataset.pk, plan.sha256)

        self.assertEqual(registration.pk, replay.pk)
        self.assertEqual(sum(registration.row_counts.values()), 84)
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
        self.assertGreater(Candle.objects.count(), 0)
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


class HistoricalIdentityPortabilityTests(TransactionTestCase):
    reset_sequences = True

    def materialize_semantic_plan(self, *, displace_ids):
        if displace_ids:
            SourceRegistry.objects.create(
                name="identity-displacement-source",
                tier=SourceRegistry.Tier.QUARANTINE,
                base_url="https://example.invalid",
                acquisition_method="none",
                retention_policy="test only",
            )
            decoy_definition = StrategyDefinition.objects.create(
                key="identity-displacement-strategy", name="Identity displacement strategy"
            )
            StrategyVersion.objects.create(
                definition=decoy_definition,
                version="decoy",
                detector_version="decoy",
                data_identity="decoy",
                event_identity="decoy",
                execution_identity="decoy",
                cost_identity="decoy",
                portfolio_identity="decoy",
                content_hash="0" * 64,
            )

        source = SourceRegistry.objects.create(
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
            key="portable-failed-break", name="Portable failed break"
        )
        strategy = StrategyVersion.objects.create(
            definition=definition,
            version="v1",
            detector_version="failed-break-detector-v1",
            data_identity="oanda-ba-ny17-friday-v1",
            event_identity="event-policy-none-v1",
            execution_identity="execution-h1-stop-first-v1",
            cost_identity="cost-observed-spread-only-v1",
            portfolio_identity="portfolio-common-fraction-025-100-050-v1",
            pair_metadata={
                "instruments": list(
                    ("EUR_USD", "GBP_USD", "EUR_GBP", "USD_CAD", "USD_JPY", "AUD_USD")
                )
            },
            content_hash=PHASE1_MANIFEST_SHA256,
        )
        StrategyParameterManifest.objects.create(
            strategy_version=strategy,
            payload={},
            sha256=PHASE1_MANIFEST_SHA256,
            phase1_spec_hash=PHASE1_SPEC_SHA256,
            phase1_manifest_hash=PHASE1_MANIFEST_SHA256,
        )
        ranges = {
            key: {"from": value["from"], "to": value["to"]} for key, value in FROZEN_RANGES.items()
        }
        payload = {
            "acquisition_contract": ACQUISITION_CONTRACT,
            "acquisition_version": ACQUISITION_VERSION,
            "source": {"name": source.name, "governed_identity": SOURCE_IDENTITY},
            "strategy": {
                "definition_key": definition.key,
                "version": strategy.version,
                "content_hash": strategy.content_hash,
            },
            "data_identity": strategy.data_identity,
            "phase1_spec_hash": PHASE1_SPEC_SHA256,
            "phase1_manifest_hash": PHASE1_MANIFEST_SHA256,
            "dataset": {
                "name": "portable-history",
                "version": "v1",
                "description": "displaced primary-key portability regression",
            },
            "instruments": list(INSTRUMENTS),
            "granularities": ["D", "H1", "W"],
            "ranges": ranges,
            "chunk_size": 4999,
        }
        plan, dataset = create_historical_dataset_plan(payload)
        report = offline_acquisition_report(plan, dataset)
        return (source.pk, strategy.pk), {
            "plan_sha256": plan.sha256,
            "dataset_manifest_sha256": dataset.manifest_sha256,
            "canonical_request_sha256": [
                item["canonical_request_sha256"] for item in report["chunks"]
            ],
            "logical_keys": [item["logical_key"] for item in report["chunks"]],
            "ordered_manifest_sha256": report["ordered_manifest_sha256"],
        }

    def test_full_canonical_identity_is_portable_across_displaced_primary_keys(self):
        with transaction.atomic():
            first_ids, first = self.materialize_semantic_plan(displace_ids=False)
            transaction.set_rollback(True)

        second_ids, second = self.materialize_semantic_plan(displace_ids=True)

        self.assertNotEqual(first_ids, second_ids)
        self.assertEqual(len(first["canonical_request_sha256"]), 84)
        self.assertEqual(len(first["logical_keys"]), 84)
        self.assertEqual(first, second)


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

    def test_historical_dataset_manifest_is_exact_across_database_write_paths(self):
        plan, dataset = self.plan()

        missing_range = {**dataset.manifest}
        missing_range["required_ranges"] = missing_range["required_ranges"][:-1]
        with self.assertRaises(DatabaseError), transaction.atomic():
            DatasetVersion.objects.create(
                name=dataset.name,
                version=dataset.version,
                description=dataset.description,
                source=dataset.source,
                manifest=missing_range,
            )

        altered_range = {**dataset.manifest}
        altered_range["required_ranges"] = [*altered_range["required_ranges"]]
        altered_range["required_ranges"][0] = {
            **altered_range["required_ranges"][0],
            "start": "2009-02-25T22:00:00+00:00",
        }
        with self.assertRaises(DatabaseError), transaction.atomic():
            DatasetVersion.objects.filter(pk=dataset.pk).update(
                manifest=altered_range,
                manifest_sha256=stable_hash(altered_range),
            )

        duplicated_range = {**dataset.manifest}
        duplicated_range["required_ranges"] = [*duplicated_range["required_ranges"]]
        duplicated_range["required_ranges"][-1] = duplicated_range["required_ranges"][0]
        additional_field = {**dataset.manifest, "unapproved": True}
        for case, manifest in (("duplicate", duplicated_range), ("extra", additional_field)):
            with (
                self.subTest(case=case),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
            ):
                DatasetVersion.objects.bulk_create(
                    [
                        DatasetVersion(
                            name=dataset.name,
                            version=dataset.version,
                            description=dataset.description,
                            source=dataset.source,
                            manifest=manifest,
                            manifest_sha256=stable_hash(manifest),
                        )
                    ]
                )

        for case, manifest, manifest_hash in (
            ("missing", missing_range, stable_hash(missing_range)),
            ("wrong_hash", dataset.manifest, "0" * 64),
        ):
            with (
                self.subTest(case=case),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    """INSERT INTO market_datasetversion
                       (name,version,description,source_id,manifest,manifest_sha256,created_at)
                       VALUES (%s,%s,%s,%s,%s::jsonb,%s,now())""",
                    [
                        dataset.name,
                        dataset.version,
                        dataset.description,
                        plan.source_id,
                        json.dumps(manifest),
                        manifest_hash,
                    ],
                )

    def test_historical_manifest_semantics_are_enforced_across_write_paths(self):
        plan, dataset = self.plan()
        chunks = list(plan.chunks.order_by("logical_key"))
        canonical_attempt, _ = begin_historical_attempt(chunks.pop().logical_key)
        canonical = self.manifest_payload(canonical_attempt)
        manifest = IngestionManifest.objects.create(
            ingestion_run=canonical_attempt.ingestion_run,
            dataset_version=dataset,
            payload=canonical,
            sha256=stable_hash(canonical),
        )
        self.assertEqual(manifest.sha256, stable_hash(canonical))

        changed = {**canonical, "price": "M"}
        with self.assertRaises(DatabaseError), transaction.atomic():
            IngestionManifest.objects.filter(pk=manifest.pk).update(
                payload=changed, sha256=stable_hash(changed)
            )

        normal_attempt, _ = begin_historical_attempt(chunks.pop().logical_key)
        changed = {**self.manifest_payload(normal_attempt), "includeFirst": False}
        with self.assertRaises(ValidationError):
            IngestionManifest.objects.create(
                ingestion_run=normal_attempt.ingestion_run,
                dataset_version=dataset,
                payload=changed,
                sha256=stable_hash(changed),
            )

        raw_attempt, _ = begin_historical_attempt(chunks.pop().logical_key)
        changed = {**self.manifest_payload(raw_attempt), "complete_only": False}
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO market_ingestionmanifest
                   (ingestion_run_id,dataset_version_id,payload,sha256,created_at)
                   VALUES (%s,%s,%s::jsonb,%s,now())""",
                [
                    raw_attempt.ingestion_run_id,
                    dataset.pk,
                    json.dumps(changed),
                    stable_hash(changed),
                ],
            )

        mutations = (
            ("instrument", "NOT_A_PAIR"),
            ("granularity", "H4"),
            ("from", "2018-01-01T00:00:00+00:00"),
            ("to", "2018-01-01T01:00:00+00:00"),
            ("price", "M"),
            ("price_component", "MID"),
            ("smooth", True),
            ("dailyAlignment", 0),
            ("alignmentTimezone", "UTC"),
            ("weeklyAlignment", "Monday"),
            ("historical_logical_key", "0" * 64),
            ("historical_attempt", 99),
            ("requests", [{"http_status": 200}, {"http_status": 200}]),
            ("requests", [{"http_status": 500}]),
        )
        for (field, value), chunk in zip(mutations, chunks):
            attempt, _ = begin_historical_attempt(chunk.logical_key)
            changed = {**self.manifest_payload(attempt), field: value}
            false_manifest = IngestionManifest(
                ingestion_run=attempt.ingestion_run,
                dataset_version=dataset,
                payload=changed,
                sha256=stable_hash(changed),
            )
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
            ):
                IngestionManifest.objects.bulk_create([false_manifest])

    def test_database_rejects_each_request_evidence_mismatch_and_include_first_absence(self):
        plan, dataset = self.plan()
        chunks = iter(plan.chunks.order_by("logical_key"))
        cases = (
            ("endpoint_identity", "oanda-v20-live:GET:/wrong"),
            ("http_method", "POST"),
            ("oanda_environment", "sandbox"),
            ("canonical_request_sha256", "0" * 64),
            ("provider_request_id", ""),
            ("http_status", 201),
        )
        for field, value in cases:
            attempt, _ = begin_historical_attempt(next(chunks).logical_key)
            payload = self.manifest_payload(attempt)
            payload["requests"][0][field] = value
            with self.subTest(field=field), self.assertRaises(DatabaseError), transaction.atomic():
                IngestionManifest.objects.bulk_create(
                    [
                        IngestionManifest(
                            ingestion_run=attempt.ingestion_run,
                            dataset_version=dataset,
                            payload=payload,
                            sha256=stable_hash(payload),
                        )
                    ]
                )

        for include_first in (None, False):
            attempt, _ = begin_historical_attempt(next(chunks).logical_key)
            payload = self.manifest_payload(attempt)
            if include_first is None:
                payload.pop("includeFirst")
            else:
                payload["includeFirst"] = include_first
            with (
                self.subTest(include_first=include_first),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
            ):
                IngestionManifest.objects.bulk_create(
                    [
                        IngestionManifest(
                            ingestion_run=attempt.ingestion_run,
                            dataset_version=dataset,
                            payload=payload,
                            sha256=stable_hash(payload),
                        )
                    ]
                )

    def test_registration_revalidates_successful_manifest_semantics_in_database(self):
        plan, dataset = self.plan()
        with self.condensed_expected_timestamps(plan):
            for chunk in plan.chunks.order_by("logical_key"):
                run_historical_chunk(chunk.logical_key, CondensedFakeClient())
        manifest = dataset.manifests.first()
        changed = {**manifest.payload, "weeklyAlignment": "Monday"}
        try:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE market_ingestionmanifest DISABLE TRIGGER USER")
                cursor.execute(
                    "UPDATE market_ingestionmanifest SET payload=%s::jsonb,sha256=%s WHERE id=%s",
                    [json.dumps(changed), stable_hash(changed), manifest.pk],
                )
        finally:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE market_ingestionmanifest ENABLE TRIGGER USER")

        with (
            patch("market.historical_acquisition.validate_historical_ingestion_manifest"),
            self.condensed_expected_timestamps(plan),
            self.assertRaises(DatabaseError),
        ):
            register_historical_dataset(dataset.pk, plan.sha256)

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

        wrong_source = SourceRegistry.objects.create(
            name="shaped-but-wrong-source",
            tier=SourceRegistry.Tier.ESTABLISHED,
            base_url="https://example.invalid",
            acquisition_method="v20 REST API",
            retention_policy="test",
            enabled=True,
        )
        wrong_definition = StrategyDefinition.objects.create(
            key="shaped-but-wrong-strategy", name="Wrong strategy"
        )
        wrong_strategy = StrategyVersion.objects.create(
            definition=wrong_definition,
            version="v1",
            detector_version="failed-break-detector-v1",
            data_identity=plan.identity,
            event_identity="event-policy-none-v1",
            execution_identity="execution-h1-stop-first-v1",
            cost_identity="cost-observed-spread-only-v1",
            portfolio_identity="portfolio-common-fraction-025-100-050-v1",
            pair_metadata=self.strategy.pair_metadata,
            content_hash="9" * 64,
        )
        StrategyParameterManifest.objects.create(
            strategy_version=wrong_strategy,
            payload={},
            sha256="9" * 64,
            phase1_spec_hash=PHASE1_SPEC_SHA256,
            phase1_manifest_hash=PHASE1_MANIFEST_SHA256,
        )
        for field, relation in (("source", wrong_source), ("strategy_version", wrong_strategy)):
            shaped = HistoricalDatasetPlan(
                identity=plan.identity,
                source=plan.source,
                strategy_version=plan.strategy_version,
                instruments=plan.instruments,
                granularities=plan.granularities,
                ranges=plan.ranges,
                alignment=plan.alignment,
                chunk_size=plan.chunk_size,
                phase1_spec_hash=plan.phase1_spec_hash,
                phase1_manifest_hash=plan.phase1_manifest_hash,
                payload=plan.payload,
                sha256=plan.sha256,
            )
            setattr(shaped, field, relation)
            with self.subTest(field=field), self.assertRaises(DatabaseError), transaction.atomic():
                HistoricalDatasetPlan.objects.bulk_create([shaped])

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
        with (
            self.condensed_expected_timestamps(plan),
            self.without_registration_validation_trigger(),
        ):
            for chunk in plan.chunks.order_by("logical_key"):
                run_historical_chunk(chunk.logical_key, CondensedFakeClient())
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
