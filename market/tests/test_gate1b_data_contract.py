import json
from datetime import UTC, datetime

from django.db import DatabaseError, connection, transaction

from market.historical_acquisition import (
    PHASE1_MANIFEST_SHA256,
    PHASE1_SPEC_SHA256,
)
from market.historical_discovery import (
    DISCOVERY_V2_MANIFEST_SHA256,
    REPLACEMENT_DATA_IDENTITY,
    SUPERSEDED_DATA_IDENTITY,
    _registration_hashes,
    canonical_hash,
    future_data_contract_semantic_hash,
    run_discovery_chunk,
)
from market.models import (
    DatasetVersion,
    HistoricalDataContract,
    HistoricalDatasetPlan,
    HistoricalIngestionAttempt,
    HistoricalIngestionChunk,
    HistoricalTimestampInventory,
    HistoricalTimestampObservation,
    IngestionRun,
)
from market.provider_observed_acquisition import (
    REPLACEMENT_ACQUISITION_CONTRACT,
    REPLACEMENT_ACQUISITION_VERSION,
    _build_replacement_payloads,
    _replacement_chunk_rows,
    build_data_contract_payload,
    build_replacement_acquisition_payloads,
    create_historical_data_contract,
    materialize_replacement_chunks,
    replacement_chunk_logical_key,
    replacement_supersession_lineage_report,
    sealed_inventory_timestamps,
)
from market.services import DatasetQualityError
from market.tests.test_gate4_full_discovery import Gate4FixtureTestCase, WaveSuccessClient
from research.models import StrategyDefinition, StrategyParameterManifest, StrategyVersion

SEAL_TABLES = (
    "market_historicaldiscoveryapproval",
    "market_historicaldiscoveryregistration",
    "market_historicaldiscoveryplan",
)


def governed_strategy_version(suffix=""):
    definition = StrategyDefinition.objects.create(key=f"failed-break{suffix}", name="Failed Break")
    strategy = StrategyVersion.objects.create(
        definition=definition,
        version="v1",
        detector_version="failed-break-detector-v1",
        data_identity=SUPERSEDED_DATA_IDENTITY,
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
        strategy_version=strategy,
        payload={},
        sha256=PHASE1_MANIFEST_SHA256,
        phase1_spec_hash=PHASE1_SPEC_SHA256,
        phase1_manifest_hash=PHASE1_MANIFEST_SHA256,
    )
    return strategy


def forge_discovery_seal(replacement):
    """Test-only: with triggers disabled, record an internally consistent
    seal for the completed synthetic discovery fixture. Real sealing runs
    only through the governed Gate 5 command."""
    chunk_hash, semantic_hash, operational_hash = _registration_hashes(replacement)
    assert chunk_hash == DISCOVERY_V2_MANIFEST_SHA256
    sealed_at = datetime(2026, 8, 30, 21, 13, 34, tzinfo=UTC)
    approval_payload = {"identity": "test-forged-approval", "plan_sha256": replacement.sha256}
    approval_sha = canonical_hash(approval_payload)
    registration_payload = {
        "identity": "test-forged-registration",
        "plan_sha256": replacement.sha256,
        "approval_sha256": approval_sha,
    }
    report_sha = canonical_hash(registration_payload)
    with connection.cursor() as cursor:
        for table in SEAL_TABLES:
            cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        try:
            cursor.execute("SELECT id FROM auth_user LIMIT 1")
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """INSERT INTO auth_user (username,password,is_superuser,is_staff,
                       is_active,first_name,last_name,email,date_joined)
                       VALUES ('gate1b-seal','',false,false,true,'','','',now())
                       RETURNING id"""
                )
                row = cursor.fetchone()
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s) RETURNING id""",
                [
                    replacement.pk,
                    row[0],
                    semantic_hash,
                    operational_hash,
                    json.dumps(approval_payload),
                    approval_sha,
                    sealed_at,
                ],
            )
            approval_id = cursor.fetchone()[0]
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryregistration
                   (plan_id,approval_id,ordered_chunk_manifest_sha256,
                    global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,cross_series_report_sha256,
                    payload,report_sha256,registered_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                [
                    replacement.pk,
                    approval_id,
                    chunk_hash,
                    semantic_hash,
                    operational_hash,
                    "d" * 64,
                    json.dumps(registration_payload),
                    report_sha,
                    sealed_at,
                ],
            )
            cursor.execute(
                "UPDATE market_historicaldiscoveryplan SET sealed_at=%s WHERE id=%s",
                [sealed_at, replacement.pk],
            )
        finally:
            for table in SEAL_TABLES:
                cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    return semantic_hash


class Gate1BFixtureTestCase(Gate4FixtureTestCase):
    """Real v2 discovery plan, 132 synthetic inventories, a forged (test-only)
    seal, the unchanged approved strategy version, and the data contract."""

    retention_policy = "gate1b fixture"
    discovery_client_factory = WaveSuccessClient

    def setUp(self):
        super().setUp()
        client = self.discovery_client_factory(self.replacement)
        for chunk in self.remaining:
            run_discovery_chunk(chunk.logical_key, client)
        self.global_semantic = forge_discovery_seal(self.replacement)
        self.strategy = governed_strategy_version()
        self.contract = create_historical_data_contract(self.strategy)

    def replacement_payloads(self):
        return _build_replacement_payloads(
            contract_sha256=self.contract.sha256,
            global_semantic_inventory_sha256=(self.contract.global_semantic_inventory_sha256),
            strategy={
                "definition_key": self.strategy.definition.key,
                "version": self.strategy.version,
                "content_hash": self.strategy.content_hash,
            },
            chunk_rows=_replacement_chunk_rows(self.replacement),
        )

    def create_replacement_plan_and_dataset(self):
        payloads = self.replacement_payloads()
        plan_payload = payloads["plan"]
        plan = HistoricalDatasetPlan.objects.create(
            identity=self.contract.identity,
            source=self.source,
            strategy_version=self.strategy,
            instruments=plan_payload["instruments"],
            granularities=plan_payload["granularities"],
            ranges=plan_payload["ranges"],
            alignment=plan_payload["alignment"],
            phase1_spec_hash=PHASE1_SPEC_SHA256,
            phase1_manifest_hash=PHASE1_MANIFEST_SHA256,
            payload=plan_payload,
            sha256="",
            data_contract=self.contract,
            data_contract_sha256=self.contract.sha256,
        )
        dataset = DatasetVersion.objects.create(
            name=plan_payload["dataset"]["name"],
            version=plan_payload["dataset"]["version"],
            description=plan_payload["dataset"]["description"],
            source=self.source,
            manifest=payloads["dataset_manifest"],
            manifest_sha256="",
            data_contract_sha256=self.contract.sha256,
        )
        return plan, dataset, payloads


class Gate1BContractTests(Gate1BFixtureTestCase):
    def test_contract_binds_the_frozen_portable_identity(self):
        self.assertEqual(self.contract.identity, REPLACEMENT_DATA_IDENTITY)
        self.assertEqual(self.contract.superseded_data_identity, SUPERSEDED_DATA_IDENTITY)
        self.assertEqual(self.contract.phase1_spec_hash, PHASE1_SPEC_SHA256)
        self.assertEqual(self.contract.phase1_manifest_hash, PHASE1_MANIFEST_SHA256)
        self.assertEqual(
            self.contract.sha256,
            future_data_contract_semantic_hash(
                global_semantic_inventory_sha256=self.global_semantic
            ),
        )
        self.assertEqual(
            self.contract.payload,
            build_data_contract_payload(self.global_semantic),
        )
        self.assertEqual(canonical_hash(self.contract.payload), self.contract.sha256)
        self.assertEqual(
            set(self.contract.payload),
            {
                "discovery_contract",
                "discovery_version",
                "source_identity",
                "phase1_spec_hash",
                "phase1_manifest_hash",
                "replacement_data_identity",
                "superseded_semantic_identity",
                "global_semantic_inventory_sha256",
            },
        )
        lineage = replacement_supersession_lineage_report(self.contract)
        self.assertEqual(lineage["superseded_data_identity"], SUPERSEDED_DATA_IDENTITY)
        self.assertEqual(
            lineage["report_sha256"],
            canonical_hash({k: v for k, v in lineage.items() if k != "report_sha256"}),
        )

    def test_no_duplicate_strategy_version_or_contract(self):
        strategy_count = StrategyVersion.objects.count()
        with self.assertRaises(DatabaseError), transaction.atomic():
            create_historical_data_contract(self.strategy)
        self.assertEqual(StrategyVersion.objects.count(), strategy_count)
        self.assertEqual(HistoricalDataContract.objects.count(), 1)

    def test_database_rejects_forged_contract_hash_and_identity(self):
        registration = self.contract.discovery_registration
        for column, value in (
            ("sha256", "f" * 64),
            ("identity", "oanda-ba-ny17-friday-provider-observed-v2"),
            ("global_semantic_inventory_sha256", "a" * 64),
        ):
            with (
                self.assertRaisesMessage(
                    DatabaseError, "historical data contract lineage does not reconstruct"
                ),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                values = {
                    "identity": REPLACEMENT_DATA_IDENTITY + "-forged",
                    "sha256": canonical_hash({"forged": column}),
                    "global_semantic_inventory_sha256": self.global_semantic,
                }
                values["identity"] = value if column == "identity" else values["identity"]
                values["sha256"] = value if column == "sha256" else values["sha256"]
                if column == "global_semantic_inventory_sha256":
                    values["global_semantic_inventory_sha256"] = value
                cursor.execute(
                    """INSERT INTO market_historicaldatacontract
                       (identity,strategy_version_id,discovery_registration_id,
                        superseded_data_identity,phase1_spec_hash,phase1_manifest_hash,
                        global_semantic_inventory_sha256,approval_sha256,
                        registration_report_sha256,payload,sha256,created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                    [
                        values["identity"],
                        self.strategy.pk,
                        registration.pk,
                        SUPERSEDED_DATA_IDENTITY,
                        PHASE1_SPEC_SHA256,
                        PHASE1_MANIFEST_SHA256,
                        values["global_semantic_inventory_sha256"],
                        registration.approval.sha256,
                        registration.report_sha256,
                        values["sha256"],
                    ],
                )
        self.assertEqual(HistoricalDataContract.objects.count(), 1)

    def test_contracts_are_append_only(self):
        with (
            self.assertRaisesMessage(DatabaseError, "historical data contracts are append-only"),
            transaction.atomic(),
        ):
            HistoricalDataContract.objects.filter(pk=self.contract.pk).update(identity="changed")


class Gate1BGeneratorTests(Gate1BFixtureTestCase):
    def test_governed_generator_pins_the_exact_sealed_coverage(self):
        with self.assertRaisesMessage(
            DatasetQualityError, "replacement plan requires the exact sealed inventory coverage"
        ):
            build_replacement_acquisition_payloads(self.contract)

    def test_pure_generator_is_deterministic_and_portable(self):
        rows = _replacement_chunk_rows(self.replacement)
        self.assertEqual(len(rows), 132)
        grouped = {}
        for row in rows:
            grouped[row["granularity"]] = grouped.get(row["granularity"], 0) + 1
        self.assertEqual(grouped, {"D": 6, "H1": 120, "W": 6})
        first = self.replacement_payloads()
        second = self.replacement_payloads()
        self.assertEqual(first, second)
        self.assertEqual(first["plan"]["acquisition_contract"], REPLACEMENT_ACQUISITION_CONTRACT)
        self.assertEqual(first["plan"]["acquisition_version"], REPLACEMENT_ACQUISITION_VERSION)
        self.assertEqual(first["plan_sha256"], canonical_hash(first["plan"]))
        self.assertEqual(
            first["dataset_manifest_sha256"], canonical_hash(first["dataset_manifest"])
        )
        self.assertEqual(
            first["plan"]["expected_total_observations"],
            sum(row["expected_observation_count"] for row in rows),
        )
        for chunk in first["chunks"]:
            self.assertEqual(
                chunk["logical_key"],
                replacement_chunk_logical_key(
                    replacement_plan_sha256=first["plan_sha256"],
                    replacement_dataset_manifest_sha256=first["dataset_manifest_sha256"],
                    semantic_inventory_sha256=chunk["semantic_inventory_sha256"],
                    canonical_request_sha256=chunk["canonical_request_sha256"],
                ),
            )
        rendered = json.dumps(first, sort_keys=True)
        for marker in ('"id":', '"pk":', "attempt_id", "run_id"):
            self.assertNotIn(marker, rendered)

    def test_replacement_plan_dataset_and_chunks_reconstruct_in_postgresql(self):
        plan, dataset, payloads = self.create_replacement_plan_and_dataset()
        self.assertEqual(plan.sha256, payloads["plan_sha256"])
        self.assertEqual(dataset.manifest_sha256, payloads["dataset_manifest_sha256"])
        chunks = materialize_replacement_chunks(plan, dataset, payloads)
        self.assertEqual(len(chunks), 132)
        stored = HistoricalIngestionChunk.objects.filter(plan=plan)
        self.assertEqual(stored.count(), 132)
        for chunk in stored.select_related("discovery_inventory"):
            self.assertEqual(
                chunk.semantic_inventory_sha256,
                chunk.discovery_inventory.semantic_inventory_sha256,
            )
            self.assertEqual(
                chunk.expected_observation_count,
                chunk.discovery_inventory.observation_count,
            )
            self.assertEqual(chunk.data_contract_sha256, self.contract.sha256)
            self.assertTrue(sealed_inventory_timestamps(chunk))

    def test_tampered_replacement_lineage_fails_closed(self):
        plan, dataset, payloads = self.create_replacement_plan_and_dataset()
        template = payloads["chunks"][0]
        inventory = HistoricalTimestampInventory.objects.get(
            semantic_inventory_sha256=template["semantic_inventory_sha256"]
        )
        discovery_chunk = inventory.chunk
        base = dict(
            plan=plan,
            dataset_version=dataset,
            instrument=discovery_chunk.instrument,
            granularity=discovery_chunk.granularity,
            requested_from=discovery_chunk.requested_from,
            requested_to=discovery_chunk.requested_to,
            canonical_request=template["canonical_request"],
            canonical_request_sha256=template["canonical_request_sha256"],
            logical_key=template["logical_key"],
            discovery_inventory=inventory,
            semantic_inventory_sha256=template["semantic_inventory_sha256"],
            expected_observation_count=template["expected_observation_count"],
            data_contract_sha256=self.contract.sha256,
        )
        for tamper in (
            {"semantic_inventory_sha256": "a" * 64},
            {"expected_observation_count": template["expected_observation_count"] + 1},
            {"logical_key": canonical_hash({"forged": True})},
            {"data_contract_sha256": "b" * 64},
        ):
            with (
                self.assertRaisesMessage(
                    DatabaseError, "replacement chunk conflicts with sealed inventory lineage"
                ),
                transaction.atomic(),
            ):
                HistoricalIngestionChunk.objects.create(**{**base, **tamper})
        self.assertEqual(HistoricalIngestionChunk.objects.filter(plan=plan).count(), 0)

    def test_forged_plan_contract_hash_fails_closed(self):
        payloads = self.replacement_payloads()
        plan_payload = payloads["plan"]
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement plan conflicts with the data contract"
            ),
            transaction.atomic(),
        ):
            HistoricalDatasetPlan.objects.create(
                identity=self.contract.identity,
                source=self.source,
                strategy_version=self.strategy,
                instruments=plan_payload["instruments"],
                granularities=plan_payload["granularities"],
                ranges=plan_payload["ranges"],
                alignment=plan_payload["alignment"],
                phase1_spec_hash=PHASE1_SPEC_SHA256,
                phase1_manifest_hash=PHASE1_MANIFEST_SHA256,
                payload=plan_payload,
                sha256="",
                data_contract=self.contract,
                data_contract_sha256="c" * 64,
            )

    def test_legacy_rows_reject_v2_lineage_and_v2_identity_needs_contract(self):
        payloads = self.replacement_payloads()
        plan_payload = payloads["plan"]
        with (
            self.assertRaisesMessage(
                DatabaseError, "historical plan conflicts with the portable canonical contract"
            ),
            transaction.atomic(),
        ):
            HistoricalDatasetPlan.objects.create(
                identity=REPLACEMENT_DATA_IDENTITY,
                source=self.source,
                strategy_version=self.strategy,
                instruments=plan_payload["instruments"],
                granularities=plan_payload["granularities"],
                ranges=plan_payload["ranges"],
                alignment=plan_payload["alignment"],
                phase1_spec_hash=PHASE1_SPEC_SHA256,
                phase1_manifest_hash=PHASE1_MANIFEST_SHA256,
                payload=plan_payload,
                sha256="",
            )

    def test_provider_drift_fails_without_inventory_mutation(self):
        plan, dataset, payloads = self.create_replacement_plan_and_dataset()
        materialize_replacement_chunks(plan, dataset, payloads)
        chunk = HistoricalIngestionChunk.objects.filter(plan=plan, granularity="H1").select_related(
            "discovery_inventory", "instrument"
        )[0]
        inventory = chunk.discovery_inventory
        before_count = inventory.observations.count()
        before_semantic = inventory.semantic_inventory_sha256
        sealed = sealed_inventory_timestamps(chunk)

        class DriftingClient:
            def fetch_historical_chunk(self, instrument, granularity, start, end):
                from datetime import timedelta

                from market.historical_acquisition import stable_hash
                from market.tests.factories import candle

                drifted = [candle(timestamp=sealed[0].astimezone(UTC) + timedelta(hours=1))]
                manifest = {
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
                    "endpoint_identity": "oanda-v20-practice:GET:/v3/candles",
                    "http_method": "GET",
                    "oanda_environment": "practice",
                    "http_status": 200,
                    "provider_request_id": "drift-test",
                    "canonical_request_sha256": stable_hash({"attempt": "drift"}),
                }
                return drifted, manifest

        from market.historical_acquisition import run_historical_chunk

        with self.assertRaises(Exception):
            run_historical_chunk(chunk.logical_key, DriftingClient())
        attempt = HistoricalIngestionAttempt.objects.get(chunk=chunk)
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.FAILED)
        inventory.refresh_from_db()
        self.assertEqual(inventory.observations.count(), before_count)
        self.assertEqual(inventory.semantic_inventory_sha256, before_semantic)
        self.assertEqual(
            HistoricalTimestampObservation.objects.filter(inventory=inventory).count(),
            before_count,
        )

    def test_v2_registration_rejects_missing_or_foreign_candles(self):
        plan, dataset, payloads = self.create_replacement_plan_and_dataset()
        materialize_replacement_chunks(plan, dataset, payloads)
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO market_datasetregistration
                   (dataset_version_id,plan_id,series_manifest,row_counts,
                    first_last_timestamps,missingness,conflict_count,incident_count,
                    logical_chunk_set_hash,successful_attempt_set_hash,
                    ingestion_manifest_set_hash,candle_key_hash,candle_payload_hash,
                    configuration_sha256,report_sha256,data_contract_id,
                    global_semantic_inventory_sha256,registered_at)
                   VALUES (%s,%s,'[]'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,0,0,
                           %s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
                [
                    dataset.pk,
                    plan.pk,
                    "a" * 64,
                    "b" * 64,
                    "c" * 64,
                    "d" * 64,
                    "e" * 64,
                    "f" * 64,
                    "0" * 64,
                    self.contract.pk,
                    self.contract.global_semantic_inventory_sha256,
                ],
            )


class Gate1BUnsealedTests(Gate4FixtureTestCase):
    retention_policy = "gate1b unsealed"

    def test_contract_requires_the_sealed_registration(self):
        strategy = governed_strategy_version("-unsealed")
        with self.assertRaisesMessage(
            DatasetQualityError, "data contract requires the sealed approved discovery registration"
        ):
            create_historical_data_contract(strategy)
        self.assertFalse(HistoricalDataContract.objects.exists())
