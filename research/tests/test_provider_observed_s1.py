"""Gate 1B correction: provider-observed v2 S0/S1 execute against the sealed
inventory, including timestamps the theoretical calendar excludes.

These regressions build a registered v2 dataset whose candles exactly mirror
sparse, irregular sealed inventories (weekend hours included; most
theoretical hours absent) and execute run_s0 and run_s1_detector for real
on the disposable test database. No provider, credential or persistent
database is touched.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import connection

from market.historical_acquisition import stable_hash
from market.historical_discovery import StructuralObservation
from market.models import (
    Candle,
    DatasetVersion,
    HistoricalIngestionChunk,
    IngestionRun,
)
from market.provider_observed_acquisition import (
    materialize_replacement_chunks,
)
from market.quality import expected_candle_timestamps, registered_candle_completion
from market.services import (
    DatasetQualityError,
    provider_observed_contract,
    sealed_inventory_membership,
)
from market.tests.test_gate1b_data_contract import (
    Gate1BFixtureTestCase,
)
from research.failed_break_detector import run_s1_detector
from research.failed_break_services import _derive_history
from research.models import AnalysisRun, JobRun
from research.provider_observed import inventory_timestamps
from research.signal_count import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    RequiredCandleRange,
    ReturnBlindViolation,
    expected_analysis_keys,
    read_entry_projection,
    run_s0,
)

NEW_YORK = ZoneInfo("America/New_York")
AS_OF = datetime(2019, 6, 1, tzinfo=UTC)
FORGE_TABLES = (
    "market_ingestionrun",
    "market_ingestionmanifest",
    "market_candle",
    "market_historicalingestionattempt",
)


def designed_inventory_timestamps(granularity, start, end):
    """Sparse irregular provider membership: dense 16-hour head, then a
    47-hour stride that lands on New York weekend hours the theoretical
    calendar excludes, while most theoretical hours are absent."""
    if granularity in ("D", "W"):
        return list(expected_candle_timestamps(start, end, granularity))
    timestamps = [start + timedelta(hours=hour) for hour in range(16)]
    cursor = start + timedelta(hours=16 + 97)
    while cursor < end:
        timestamps.append(cursor)
        cursor += timedelta(hours=97)
    return sorted({timestamp for timestamp in timestamps if timestamp < end})


class InventoryDiscoveryClient:
    def __init__(self, plan):
        self.plan = plan

    def fetch_historical_inventory(self, instrument, granularity, start, end):
        chunk = self.plan.chunks.select_related("instrument").get(
            instrument__code=instrument, granularity=granularity, requested_from=start
        )
        observations = [
            StructuralObservation(timestamp, True, 3, True, True)
            for timestamp in designed_inventory_timestamps(granularity, start, end)
        ]
        return (
            observations,
            {
                "endpoint_identity": (
                    f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"
                ),
                "http_method": "GET",
                "oanda_environment": "practice",
                "http_status": 200,
                "provider_request_id": f"inventory-fixture-{chunk.ordinal}",
                "canonical_request_sha256": chunk.canonical_request_sha256,
            },
        )


def forge_inventory_backed_candles(source, plan, dataset):
    """Test-only: store candles exactly equal to each chunk's sealed
    inventory with succeeded-run and manifest lineage, so the runtime v2
    paths can execute. Real acquisition remains a later authorized gate."""
    with connection.cursor() as cursor:
        for table in FORGE_TABLES:
            cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        candles = []
        for chunk in HistoricalIngestionChunk.objects.filter(plan=plan).select_related(
            "instrument", "discovery_inventory"
        ):
            timestamps = list(
                chunk.discovery_inventory.observations.order_by("timestamp").values_list(
                    "timestamp", flat=True
                )
            )
            run = IngestionRun.objects.create(
                source=source,
                dataset_version=dataset,
                instrument=chunk.instrument,
                granularity=chunk.granularity,
                requested_from=chunk.requested_from,
                requested_to=chunk.requested_to,
                parameters=chunk.canonical_request,
                request_manifest_hash=stable_hash({"forged-run": chunk.logical_key}),
                status=IngestionRun.Status.SUCCEEDED,
                fetched_count=len(timestamps),
                stored_count=len(timestamps),
                rejected_count=0,
                finished_at=AS_OF,
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO market_ingestionmanifest
                       (ingestion_run_id,dataset_version_id,payload,sha256,created_at)
                       VALUES (%s,%s,%s::jsonb,%s,now())""",
                    [
                        run.pk,
                        dataset.pk,
                        json.dumps({"forged": chunk.logical_key}),
                        stable_hash({"forged-manifest": chunk.logical_key}),
                    ],
                )
                cursor.execute(
                    """INSERT INTO market_historicalingestionattempt
                       (chunk_id,ingestion_run_id,attempt_number,idempotency_key,created_at)
                       VALUES (%s,%s,1,%s,now())""",
                    [
                        chunk.pk,
                        run.pk,
                        f"failed-break-ingestion-attempt:{chunk.logical_key}:1",
                    ],
                )
            for index, timestamp in enumerate(timestamps):
                base = Decimal("1.1000") + Decimal(index % 7) / Decimal(10000)
                candles.append(
                    Candle(
                        instrument=chunk.instrument,
                        ingestion_run=run,
                        dataset_version=dataset,
                        granularity=chunk.granularity,
                        timestamp=timestamp,
                        complete=True,
                        volume=5,
                        bid_open=base,
                        bid_high=base + Decimal("0.0020"),
                        bid_low=base - Decimal("0.0010"),
                        bid_close=base + Decimal("0.0010"),
                        ask_open=base + Decimal("0.0002"),
                        ask_high=base + Decimal("0.0022"),
                        ask_low=base - Decimal("0.0008"),
                        ask_close=base + Decimal("0.0012"),
                    )
                )
        Candle.objects.bulk_create(candles, batch_size=5000)
    finally:
        with connection.cursor() as cursor:
            for table in FORGE_TABLES:
                cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")


def forge_v2_registration(plan, dataset, contract):
    """Test-only registration through the model layer (hashes computed by
    save) with triggers disabled; real registration is a later gate."""
    from market.models import DatasetRegistration

    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE market_datasetregistration DISABLE TRIGGER USER")
    try:
        registration = DatasetRegistration(
            dataset_version=dataset,
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
            configuration_sha256="",
            report_sha256="",
            data_contract=contract,
            global_semantic_inventory_sha256=contract.global_semantic_inventory_sha256,
        )
        registration.save()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_datasetregistration ENABLE TRIGGER USER")
    return registration


class ProviderObservedRunTests(Gate1BFixtureTestCase):
    """One heavyweight fixture; every test runs against the same shape."""

    retention_policy = "provider observed s1"
    discovery_client_factory = InventoryDiscoveryClient

    def setUp(self):
        super().setUp()
        self.plan, self.dataset, self.payloads = self.create_replacement_plan_and_dataset()
        materialize_replacement_chunks(self.plan, self.dataset, self.payloads)
        forge_inventory_backed_candles(self.source, self.plan, self.dataset)
        self.registration = forge_v2_registration(self.plan, self.dataset, self.contract)
        self.dataset = DatasetVersion.objects.get(pk=self.dataset.pk)

    def declared_ranges(self):
        from django.utils.dateparse import parse_datetime

        ranges = {}
        for item in self.payloads["dataset_manifest"]["required_ranges"]:
            ranges.setdefault(item["instrument"], []).append(
                RequiredCandleRange(
                    item["granularity"],
                    parse_datetime(item["start"]),
                    parse_datetime(item["end"]),
                )
            )
        return ranges

    def weekend_dev_timestamps(self, code):
        development_start = DEVELOPMENT_START.astimezone(UTC)
        development_end = DEVELOPMENT_END.astimezone(UTC)
        return [
            timestamp
            for timestamp in inventory_timestamps(self.contract, code, "H1")
            if development_start <= registered_candle_completion(timestamp, "H1") < development_end
            and timestamp.astimezone(NEW_YORK).weekday() >= 5
        ]

    def test_v2_s0_and_detector_execute_against_the_sealed_inventory(self):
        weekend = self.weekend_dev_timestamps("EUR_USD")
        self.assertTrue(weekend, "fixture must include calendar-excluded weekend hours")
        theoretical = set(
            expected_candle_timestamps(
                DEVELOPMENT_START.astimezone(UTC),
                DEVELOPMENT_END.astimezone(UTC),
                "H1",
            )
        )
        self.assertTrue([timestamp for timestamp in weekend if timestamp not in theoretical])

        output, s0_job = run_s0(
            dataset_id=self.dataset.pk,
            strategy_version_id=self.strategy.pk,
            maximum_observations=500_000,
            as_of=AS_OF,
        )
        self.assertGreater(output.counts["observations"], 0)
        self.assertEqual(output.coverage["historical_data_contract_sha256"], self.contract.sha256)
        self.assertEqual(output.coverage["effective_data_identity"], self.contract.identity)
        for code, granularities in output.coverage["row_counts"].items():
            for granularity, observed in granularities.items():
                self.assertGreater(observed, 0, (code, granularity))
        self.assertEqual(
            sum(value for g in output.coverage["missingness"].values() for value in g.values()),
            0,
        )

        detector_job = run_s1_detector(
            dataset_id=self.dataset.pk,
            strategy_version_id=self.strategy.pk,
            s0_job_id=s0_job.pk,
            as_of=AS_OF,
        )
        self.assertEqual(detector_job.status, JobRun.Status.SUCCEEDED)
        report = detector_job.evidence["report"]
        expected = expected_analysis_keys(self.declared_ranges(), contract=self.contract)
        self.assertEqual(report["expected_analysis_count"], len(expected))
        self.assertEqual(report["expected_analysis_sha256"], stable_hash(expected))
        self.assertEqual(report["observed_analysis_count"], len(expected))
        self.assertEqual(report["observed_analysis_sha256"], stable_hash(expected))

        calendar_expected = expected_analysis_keys(self.declared_ranges())
        self.assertNotEqual(expected, calendar_expected)
        weekend_completion = registered_candle_completion(weekend[0], "H1")
        self.assertTrue(
            AnalysisRun.objects.filter(
                dataset_version=self.dataset,
                instrument__code="EUR_USD",
                completed_h1_timestamp=weekend_completion,
            ).exists(),
            "weekend sealed timestamp must be analysed by the detector",
        )
        self.assertFalse(
            AnalysisRun.objects.filter(
                dataset_version=self.dataset, result=AnalysisRun.Result.DATA_INCOMPLETE
            ).exists()
        )

    def test_last_n_history_is_selected_from_observed_inventory(self):
        code = "GBP_USD"
        instrument = self.plan.chunks.filter(instrument__code=code).first().instrument
        membership = inventory_timestamps(self.contract, code, "H1")
        boundary = registered_candle_completion(membership[40], "H1")
        derived = _derive_history(
            self.declared_ranges()[code],
            {"H1": 14},
            boundary,
            dataset_version=self.dataset,
            instrument=instrument,
        )
        h1 = next(required for required in derived if required.granularity == "H1")
        eligible = [
            timestamp
            for timestamp in membership
            if registered_candle_completion(timestamp, "H1") <= boundary
        ]
        self.assertEqual(h1.start, eligible[-14])
        self.assertEqual(h1.end, registered_candle_completion(eligible[-1], "H1"))
        self.assertIn(h1.start, membership)
        with self.assertRaisesMessage(
            DatasetQualityError, "history does not contain the required evidence candle"
        ):
            _derive_history(
                self.declared_ranges()[code],
                {"H1": 14},
                boundary,
                required_timestamps={"H1": membership[40] + timedelta(minutes=30)},
                dataset_version=self.dataset,
                instrument=instrument,
            )

    def test_missing_entry_fails_closed_and_sealed_weekend_entry_traverses(self):
        code = "EUR_USD"
        instrument = self.plan.chunks.filter(instrument__code=code).first().instrument
        weekend = self.weekend_dev_timestamps(code)
        self.assertTrue(weekend)
        sealed_weekend = weekend[0]

        missing = sealed_weekend + timedelta(minutes=30)
        with self.assertRaisesMessage(
            ReturnBlindViolation,
            "entry timestamp is not a sealed provider-observed candle",
        ):
            read_entry_projection(
                dataset_id=self.dataset.pk,
                instrument_id=instrument.pk,
                theoretical_entry_timestamp=missing,
                as_of=AS_OF,
            )

        projection = read_entry_projection(
            dataset_id=self.dataset.pk,
            instrument_id=instrument.pk,
            theoretical_entry_timestamp=sealed_weekend,
            as_of=AS_OF,
        )
        self.assertEqual(projection.timestamp, sealed_weekend)
        stored = Candle.objects.get(
            dataset_version=self.dataset,
            instrument=instrument,
            granularity="H1",
            timestamp=sealed_weekend,
        )
        self.assertEqual(projection.bid_open, stored.bid_open)
        self.assertEqual(projection.ask_open, stored.ask_open)

    def test_window_validation_uses_inventory_membership(self):
        from market.services import assert_dataset_window_usable

        code = "USD_JPY"
        instrument = self.plan.chunks.filter(instrument__code=code).first().instrument
        contract = provider_observed_contract(self.dataset)
        self.assertIsNotNone(contract)
        membership = inventory_timestamps(self.contract, code, "H1")
        window = RequiredCandleRange(
            "H1", membership[0], registered_candle_completion(membership[30], "H1")
        )
        assert_dataset_window_usable(self.dataset, instrument, (window,), AS_OF)
        sealed = sealed_inventory_membership(
            contract, instrument.pk, "H1", window.start, window.end
        )
        self.assertEqual(len(sealed), 31)
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_candle DISABLE TRIGGER USER")
            try:
                cursor.execute(
                    """DELETE FROM market_candle WHERE dataset_version_id=%s
                       AND instrument_id=%s AND granularity='H1' AND timestamp=%s""",
                    [self.dataset.pk, instrument.pk, membership[10]],
                )
            finally:
                cursor.execute("ALTER TABLE market_candle ENABLE TRIGGER USER")
        with self.assertRaisesMessage(
            DatasetQualityError, "dataset does not completely cover H1 range"
        ):
            assert_dataset_window_usable(self.dataset, instrument, (window,), AS_OF)

    def test_no_provider_or_persistent_database_involved(self):
        rendered = json.dumps(self.payloads["plan"], sort_keys=True)
        self.assertNotIn("api-fxpractice", rendered)
        self.assertNotIn("Authorization", rendered)
