import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from market.models import (
    Candle,
    DatasetRegistration,
    DatasetVersion,
    HistoricalDataContract,
    HistoricalDatasetPlan,
    HistoricalDiscoveryApproval,
    HistoricalDiscoveryAttempt,
    HistoricalDiscoveryChunk,
    HistoricalDiscoveryPlan,
    HistoricalDiscoveryRegistration,
    HistoricalIngestionAttempt,
    HistoricalIngestionChunk,
    HistoricalTimestampInventory,
    HistoricalTimestampObservation,
    IngestionManifest,
    IngestionRun,
    Instrument,
    SourceRegistry,
)
from research.failed_break_detector_v2 import (
    SUCCESSOR_CONTRACT_SHA256,
    SUCCESSOR_DATA_IDENTITY,
    SUCCESSOR_DATASET_VERSION,
    SUCCESSOR_INVENTORY_SHA256,
    SUCCESSOR_MANIFEST_SHA256,
    SUCCESSOR_REGISTRATION_CONFIGURATION_SHA256,
    SUCCESSOR_REGISTRATION_REPORT_SHA256,
    load_instrument_snapshot,
    validate_registered_successor,
)
from research.models import StrategyDefinition, StrategyVersion

START = datetime(2015, 1, 1, tzinfo=UTC)


def fixture_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


class DetectorV2QueryBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        source = SourceRegistry.objects.create(
            name="detector-v2-fixture",
            tier="primary",
            base_url="https://invalid.example",
            terms_url="",
            acquisition_method="fixture",
            retention_policy="fixture",
            deletion_policy="",
            export_policy="",
        )
        cls.instrument = Instrument.objects.create(
            code="AUD_USD",
            base_currency="AUD",
            quote_currency="USD",
            display_order=1,
        )
        definition = StrategyDefinition.objects.create(key="fixture-v2", name="fixture")
        strategy = StrategyVersion.objects.create(
            definition=definition,
            version="fixture-v2",
            detector_version="fixture-v2",
            data_identity="fixture-v2",
            event_identity="fixture",
            execution_identity="fixture",
            cost_identity="fixture",
            portfolio_identity="fixture",
            content_hash="1" * 64,
        )
        discovery_plan = HistoricalDiscoveryPlan.objects.create(
            identity="fixture-discovery",
            version="v1",
            source=source,
            purpose="fixture",
            environment="practice",
            phase1_spec_hash="2" * 64,
            phase1_manifest_hash="3" * 64,
            superseded_data_identity="fixture-v1",
            declared_chunk_count=3,
            canonical_request_manifest={},
            canonical_request_manifest_sha256="",
            payload={},
            sha256="",
            sealed_at=START,
        )
        inventories = {}
        for ordinal, granularity in enumerate(("H1", "D", "W"), start=1):
            chunk = HistoricalDiscoveryChunk.objects.create(
                plan=discovery_plan,
                ordinal=ordinal,
                instrument=cls.instrument,
                granularity=granularity,
                requested_from=START,
                requested_to=START + timedelta(days=30),
                canonical_request={},
                canonical_request_sha256=fixture_hash(f"discovery-request-{ordinal}"),
                logical_key=f"discovery-{granularity}",
            )
            run = IngestionRun.objects.create(
                source=source,
                instrument=cls.instrument,
                granularity=granularity,
                requested_from=START,
                requested_to=START + timedelta(days=30),
                parameters={},
                request_manifest_hash=fixture_hash(f"discovery-run-{ordinal}"),
                status=IngestionRun.Status.SUCCEEDED,
                finished_at=START,
            )
            attempt = HistoricalDiscoveryAttempt.objects.create(
                chunk=chunk,
                ingestion_run=run,
                attempt_number=1,
                idempotency_key="",
            )
            inventory = HistoricalTimestampInventory.objects.create(
                chunk=chunk,
                accepted_attempt=attempt,
                observation_count=5,
                timestamp_set_sha256=fixture_hash(f"timestamps-{ordinal}"),
                structural_observation_sha256=fixture_hash(f"structure-{ordinal}"),
                semantic_inventory_sha256=fixture_hash(f"semantic-{ordinal}"),
            )
            members = tuple(START + timedelta(days=index, hours=ordinal) for index in range(5))
            HistoricalTimestampObservation.objects.bulk_create(
                [
                    HistoricalTimestampObservation(
                        inventory=inventory,
                        timestamp=timestamp,
                        complete=True,
                        volume=1,
                        bid_present=True,
                        ask_present=True,
                    )
                    for timestamp in members
                ]
            )
            inventories[granularity] = (inventory, members)
        user = get_user_model().objects.create_user(username="detector-v2-reviewer")
        approval = HistoricalDiscoveryApproval.objects.create(
            plan=discovery_plan,
            approved_by=user,
            global_semantic_inventory_sha256="a" * 64,
            accepted_operational_evidence_set_sha256="b" * 64,
            payload={},
            sha256="c" * 64,
            approved_at=START,
        )
        registration = HistoricalDiscoveryRegistration.objects.create(
            plan=discovery_plan,
            approval=approval,
            ordered_chunk_manifest_sha256="d" * 64,
            global_semantic_inventory_sha256="a" * 64,
            accepted_operational_evidence_set_sha256="b" * 64,
            cross_series_report_sha256="e" * 64,
            payload={},
            report_sha256="f" * 64,
            registered_at=START,
        )
        cls.contract = HistoricalDataContract.objects.bulk_create(
            [
                HistoricalDataContract(
                    identity=SUCCESSOR_DATA_IDENTITY,
                    strategy_version=strategy,
                    discovery_registration=registration,
                    superseded_data_identity="fixture-v1",
                    phase1_spec_hash="2" * 64,
                    phase1_manifest_hash="3" * 64,
                    global_semantic_inventory_sha256=SUCCESSOR_INVENTORY_SHA256,
                    approval_sha256=approval.sha256,
                    registration_report_sha256=registration.report_sha256,
                    payload={"fixture": "v2"},
                    sha256=SUCCESSOR_CONTRACT_SHA256,
                )
            ]
        )[0]
        cls.dataset = DatasetVersion.objects.bulk_create(
            [
                DatasetVersion(
                    name=SUCCESSOR_DATA_IDENTITY,
                    version=SUCCESSOR_DATASET_VERSION,
                    source=source,
                    description="fixture",
                    manifest={"fixture": "v2"},
                    manifest_sha256=SUCCESSOR_MANIFEST_SHA256,
                    data_contract_sha256=SUCCESSOR_CONTRACT_SHA256,
                )
            ]
        )[0]
        plan = HistoricalDatasetPlan.objects.create(
            identity="fixture-v2",
            source=source,
            strategy_version=strategy,
            instruments=[cls.instrument.code],
            granularities=["H1", "D", "W"],
            ranges={},
            alignment={},
            phase1_spec_hash="2" * 64,
            phase1_manifest_hash="3" * 64,
            payload={"fixture": "v2-acquisition"},
            sha256="",
            data_contract=cls.contract,
            data_contract_sha256=cls.contract.sha256,
        )
        DatasetRegistration.objects.bulk_create(
            [
                DatasetRegistration(
                    dataset_version=cls.dataset,
                    plan=plan,
                    series_manifest={},
                    row_counts={},
                    first_last_timestamps={},
                    missingness={},
                    conflict_count=0,
                    incident_count=0,
                    logical_chunk_set_hash="4" * 64,
                    successful_attempt_set_hash="5" * 64,
                    ingestion_manifest_set_hash="6" * 64,
                    candle_key_hash="7" * 64,
                    candle_payload_hash="8" * 64,
                    configuration_sha256=SUCCESSOR_REGISTRATION_CONFIGURATION_SHA256,
                    report_sha256=SUCCESSOR_REGISTRATION_REPORT_SHA256,
                    data_contract=cls.contract,
                    global_semantic_inventory_sha256=SUCCESSOR_INVENTORY_SHA256,
                )
            ]
        )
        for ordinal, granularity in enumerate(("H1", "D", "W"), start=1):
            inventory, members = inventories[granularity]
            chunk = HistoricalIngestionChunk.objects.create(
                plan=plan,
                dataset_version=cls.dataset,
                instrument=cls.instrument,
                granularity=granularity,
                requested_from=START,
                requested_to=START + timedelta(days=30),
                canonical_request={},
                canonical_request_sha256=fixture_hash(f"acquisition-request-{ordinal}"),
                logical_key=f"acquisition-{granularity}",
                discovery_inventory=inventory,
                semantic_inventory_sha256=inventory.semantic_inventory_sha256,
                expected_observation_count=len(members),
                data_contract_sha256=cls.contract.sha256,
            )
            run = IngestionRun.objects.create(
                source=source,
                dataset_version=cls.dataset,
                instrument=cls.instrument,
                granularity=granularity,
                requested_from=START,
                requested_to=START + timedelta(days=30),
                parameters={},
                request_manifest_hash=fixture_hash(f"acquisition-run-{ordinal}"),
                status=IngestionRun.Status.SUCCEEDED,
                fetched_count=len(members),
                stored_count=len(members),
                finished_at=START,
            )
            HistoricalIngestionAttempt.objects.create(
                chunk=chunk,
                ingestion_run=run,
                attempt_number=1,
                idempotency_key="",
            )
            IngestionManifest.objects.bulk_create(
                [
                    IngestionManifest(
                        ingestion_run=run,
                        dataset_version=cls.dataset,
                        payload={},
                        sha256=fixture_hash(f"acquisition-manifest-{ordinal}"),
                    )
                ]
            )
            Candle.objects.bulk_create(
                [
                    Candle(
                        instrument=cls.instrument,
                        ingestion_run=run,
                        dataset_version=cls.dataset,
                        granularity=granularity,
                        timestamp=timestamp,
                        complete=True,
                        volume=1,
                        bid_open=Decimal("1.0"),
                        bid_high=Decimal("1.1"),
                        bid_low=Decimal("0.9"),
                        bid_close=Decimal("1.0"),
                        ask_open=Decimal("1.01"),
                        ask_high=Decimal("1.11"),
                        ask_low=Decimal("0.91"),
                        ask_close=Decimal("1.01"),
                    )
                    for timestamp in members
                ]
            )
        cls.ranges = {
            granularity: (members[0], members[-1])
            for granularity, (_, members) in inventories.items()
        }

    def test_registration_validation_uses_one_query(self):
        with CaptureQueriesContext(connection) as captured:
            identity = validate_registered_successor(self.dataset, self.contract)
        self.assertEqual(len(captured), 1)
        self.assertEqual(identity["contract_sha256"], SUCCESSOR_CONTRACT_SHA256)

    def test_preload_query_budget_is_three_independent_of_row_count(self):
        narrow = {key: (value[0], value[0]) for key, value in self.ranges.items()}
        for ranges, expected_per_granularity in ((narrow, 1), (self.ranges, 5)):
            with self.subTest(expected_per_granularity=expected_per_granularity):
                with CaptureQueriesContext(connection) as captured:
                    snapshot = load_instrument_snapshot(
                        dataset=self.dataset,
                        contract=self.contract,
                        instrument=self.instrument,
                        ranges=ranges,
                    )
                self.assertEqual(len(captured), 3)
                self.assertEqual(
                    {key: len(value) for key, value in snapshot.inventory.items()},
                    {
                        "H1": expected_per_granularity,
                        "D": expected_per_granularity,
                        "W": expected_per_granularity,
                    },
                )
                self.assertEqual(len(snapshot.candles), expected_per_granularity * 3)
