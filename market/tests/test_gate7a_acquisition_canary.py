import json
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.test import override_settings

from market.historical_acquisition import (
    PHASE1_MANIFEST_SHA256,
    PHASE1_SPEC_SHA256,
    HistoricalFailureCode,
    HistoricalResponseError,
    _classify_historical_failure,
    _invalid_price_categories,
    _validate_chunk_response,
    begin_historical_attempt,
    run_historical_chunk,
    stable_hash,
)
from market.historical_discovery import (
    ACCEPTED_OPERATIONAL_EVIDENCE_SET_SHA256,
    DISCOVERY_V2_MANIFEST_SHA256,
    GLOBAL_SEMANTIC_INVENTORY_SHA256,
    run_discovery_chunk,
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
)
from market.oanda import OandaError, _parse_candle
from market.provider_observed_acquisition import (
    build_replacement_acquisition_payloads,
    create_historical_data_contract,
    materialize_replacement_chunks,
)
from market.provider_observed_canary import (
    ACQUISITION_CANARY_DISCOVERY_ORDINAL,
    ACQUISITION_CANARY_IDEMPOTENCY_KEY,
    ACQUISITION_CANARY_LOGICAL_KEY,
    REPLACEMENT_DATASET_MANIFEST_SHA256,
    REPLACEMENT_PLAN_SHA256,
    SEALED_APPROVAL_SHA256,
    SEALED_REGISTRATION_REPORT_SHA256,
    build_canary_authorization,
    replacement_contract_sha256,
)
from market.services import DatasetQualityError
from market.tests.factories import candle
from market.tests.test_gate1b_data_contract import governed_strategy_version
from market.tests.test_gate4_full_discovery import (
    FORBIDDEN_OUTPUT_MARKERS,
    Gate4FixtureTestCase,
    WaveSuccessClient,
)

DOCS = Path("docs/strategy/failed-break/v1")
SEAL_TABLES = (
    "market_historicaldiscoveryapproval",
    "market_historicaldiscoveryregistration",
    "market_historicaldiscoveryplan",
)
INVENTORY_TABLES = (
    "market_historicaltimestampinventory",
    "market_historicaltimestampobservation",
)
CANARY_START = datetime(2009, 12, 31, 15, tzinfo=UTC)


def forge_production_seal(replacement):
    """Test-only: with triggers disabled, record a seal carrying the exact
    production Gate 5 identity strings so the production-pinned Gate 7A
    activation is exercisable against synthetic fixtures."""
    sealed_at = datetime(2026, 8, 30, 21, 13, 34, tzinfo=UTC)
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
                       VALUES ('gate7a-seal','',false,false,true,'','','',now())
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
                    GLOBAL_SEMANTIC_INVENTORY_SHA256,
                    ACCEPTED_OPERATIONAL_EVIDENCE_SET_SHA256,
                    json.dumps({"identity": "test-forged-approval"}),
                    SEALED_APPROVAL_SHA256,
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
                    DISCOVERY_V2_MANIFEST_SHA256,
                    GLOBAL_SEMANTIC_INVENTORY_SHA256,
                    ACCEPTED_OPERATIONAL_EVIDENCE_SET_SHA256,
                    "d" * 64,
                    json.dumps({"identity": "test-forged-registration"}),
                    SEALED_REGISTRATION_REPORT_SHA256,
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


def forge_production_inventory_identities(replacement):
    """Test-only: with triggers disabled, stamp the committed per-chunk
    semantic identities and counts onto the fixture inventories and give
    the canary inventory exactly its 2,932 sealed observation rows."""
    rows = json.loads((DOCS / "phase-2b1r-gate1b-replacement-chunk-manifest.json").read_text())[
        "chunks"
    ]
    with connection.cursor() as cursor:
        for table in INVENTORY_TABLES:
            cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        try:
            for row in rows:
                cursor.execute(
                    """UPDATE market_historicaltimestampinventory i
                       SET semantic_inventory_sha256=%s, observation_count=%s
                       FROM market_historicaldiscoverychunk c
                       WHERE i.chunk_id=c.id AND c.plan_id=%s AND c.ordinal=%s""",
                    [
                        row["semantic_inventory_sha256"],
                        row["expected_observation_count"],
                        replacement.pk,
                        row["ordinal"],
                    ],
                )
                assert cursor.rowcount == 1, row["ordinal"]
            cursor.execute(
                """SELECT i.id FROM market_historicaltimestampinventory i
                   JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
                   WHERE c.plan_id=%s AND c.ordinal=%s""",
                [replacement.pk, ACQUISITION_CANARY_DISCOVERY_ORDINAL],
            )
            inventory_id = cursor.fetchone()[0]
            cursor.execute(
                "DELETE FROM market_historicaltimestampobservation WHERE inventory_id=%s",
                [inventory_id],
            )
            cursor.execute(
                """INSERT INTO market_historicaltimestampobservation
                   (inventory_id, timestamp, complete, volume, bid_present, ask_present)
                   SELECT %s, ts, true,
                          100 + (extract(epoch FROM ts)::bigint / 3600) %% 251, true, true
                   FROM generate_series(timestamptz '2009-12-31 15:00:00+00',
                        timestamptz '2009-12-31 15:00:00+00' + interval '2931 hours',
                        interval '1 hour') AS ts""",
                [inventory_id],
            )
            assert cursor.rowcount == 2932
        finally:
            for table in INVENTORY_TABLES:
                cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")


class CanaryClient:
    """Mocked transport returning exactly the sealed canary series."""

    def __init__(self, chunk, mutate=None, fail_kind=None, request_id="canary-req-1"):
        self.chunk = chunk
        self.mutate = mutate
        self.fail_kind = fail_kind
        self.request_id = request_id
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def sealed_candles(self):
        return [
            candle(
                timestamp=row["timestamp"].astimezone(UTC),
                volume=row["volume"],
                complete=row["complete"],
            )
            for row in self.chunk.discovery_inventory.observations.order_by("timestamp").values(
                "timestamp", "volume", "complete"
            )
        ]

    def response(self, instrument, granularity, start, end, canonical_request_sha256):
        evidence = {
            "endpoint_identity": (f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"),
            "http_method": "GET",
            "oanda_environment": "practice",
            "canonical_request_sha256": canonical_request_sha256,
        }
        candles = self.sealed_candles()
        if self.mutate:
            candles = self.mutate(candles)
        manifest = {
            "instrument": instrument,
            "granularity": granularity,
            "from": start.astimezone(UTC).isoformat(),
            "to": end.astimezone(UTC).isoformat(),
            "price": "BA",
            "smooth": False,
            "alignmentTimezone": "America/New_York",
            "dailyAlignment": 17,
            "weeklyAlignment": "Friday",
            "includeFirst": True,
            "requests": [{**evidence, "http_status": 200, "provider_request_id": self.request_id}],
        }
        return candles, manifest

    def fetch_historical_chunk(
        self, instrument, granularity, start, end, canonical_request_sha256=None
    ):
        self.calls += 1
        if self.fail_kind:
            raise OandaError(
                "safe mocked provider failure",
                failure_kind=self.fail_kind,
                provider_evidence={
                    "endpoint_identity": (
                        f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"
                    ),
                    "http_method": "GET",
                    "oanda_environment": "practice",
                    "http_status": 401 if self.fail_kind == "auth" else 500,
                    "provider_request_id": self.request_id,
                    "canonical_request_sha256": canonical_request_sha256,
                },
            )
        return self.response(instrument, granularity, start, end, canonical_request_sha256)


class Gate7AFixtureTestCase(Gate4FixtureTestCase):
    """The production-pinned replacement lineage: real v2 discovery plan,
    forged production seal and inventory identities from the committed
    Gate 1B artifacts, then contract, plan, dataset and 132 chunks created
    through the reviewed services under real triggers."""

    retention_policy = "gate7a fixture"

    def setUp(self):
        super().setUp()
        # The Gate 7A suite is the regression suite for the exact 0020
        # activation it was reviewed against; migration 0021 reverses
        # emptily here and Gate 4 teardown restores the latest catalog.
        from market.tests.test_replacement_canary_activation import (
            MIGRATION_0020,
            migrate_to,
        )

        migrate_to(MIGRATION_0020)
        client = WaveSuccessClient(self.replacement)
        for chunk in self.remaining:
            run_discovery_chunk(chunk.logical_key, client)
        forge_production_seal(self.replacement)
        forge_production_inventory_identities(self.replacement)
        self.strategy = governed_strategy_version(
            key="top-down-failed-break-continuation",
            version="failed-break-phase-1-freeze-v1",
        )
        self.contract = create_historical_data_contract(self.strategy)
        assert self.contract.sha256 == replacement_contract_sha256()
        self.payloads = build_replacement_acquisition_payloads(self.contract)
        assert self.payloads["plan_sha256"] == REPLACEMENT_PLAN_SHA256
        assert self.payloads["dataset_manifest_sha256"] == REPLACEMENT_DATASET_MANIFEST_SHA256
        plan_payload = self.payloads["plan"]
        self.plan = HistoricalDatasetPlan.objects.create(
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
        self.dataset = DatasetVersion.objects.create(
            name=plan_payload["dataset"]["name"],
            version=plan_payload["dataset"]["version"],
            description=plan_payload["dataset"]["description"],
            source=self.source,
            manifest=self.payloads["dataset_manifest"],
            manifest_sha256="",
            data_contract_sha256=self.contract.sha256,
        )
        materialize_replacement_chunks(self.plan, self.dataset, self.payloads)
        self.canary_chunk = HistoricalIngestionChunk.objects.select_related(
            "discovery_inventory", "instrument", "plan", "dataset_version"
        ).get(logical_key=ACQUISITION_CANARY_LOGICAL_KEY)

    def canary_client(self, **kwargs):
        return CanaryClient(self.canary_chunk, **kwargs)

    def run_command(self, *, execute=False, client=None, logical_key=None):
        stdout = StringIO()
        client = client or self.canary_client()
        args = ["--logical-key", logical_key or ACQUISITION_CANARY_LOGICAL_KEY]
        if execute:
            args.append("--execute")
        with (
            patch(
                "market.management.commands.acquire_replacement_canary.OandaClient",
                return_value=client,
            ),
            override_settings(
                OANDA_ENVIRONMENT="practice", OANDA_DISCOVERY_TOKEN="safe-test-token"
            ),
        ):
            call_command("acquire_replacement_canary", *args, stdout=stdout)
        return client, stdout.getvalue()


class Gate7AActivationTests(Gate7AFixtureTestCase):
    def test_committed_authorization_artifact_matches_the_governed_pins(self):
        authorization = build_canary_authorization()
        committed = (DOCS / "phase-2b1r-gate7a-acquisition-canary-authorization.json").read_bytes()
        self.assertEqual(
            committed,
            json.dumps(authorization, sort_keys=True, separators=(",", ":")).encode(),
        )
        body = {key: value for key, value in authorization.items() if key != "authorization_sha256"}
        self.assertEqual(authorization["authorization_sha256"], stable_hash(body))
        self.assertEqual(authorization["logical_key"], self.canary_chunk.logical_key)
        self.assertEqual(authorization["canonical_request"], self.canary_chunk.canonical_request)
        self.assertEqual(authorization["data_contract_sha256"], self.contract.sha256)
        self.assertEqual(authorization["max_provider_requests"], 1)

    def test_only_canary_attempt_one_is_permitted(self):
        rejected = 0
        for chunk in HistoricalIngestionChunk.objects.filter(plan=self.plan).exclude(
            logical_key=ACQUISITION_CANARY_LOGICAL_KEY
        ):
            with (
                self.assertRaisesMessage(
                    DatabaseError, "acquisition canary activation rejects this ingestion run"
                ),
                transaction.atomic(),
            ):
                begin_historical_attempt(chunk.logical_key)
            rejected += 1
        self.assertEqual(rejected, 131)
        self.assertFalse(HistoricalIngestionAttempt.objects.exists())

        attempt, created = begin_historical_attempt(ACQUISITION_CANARY_LOGICAL_KEY)
        self.assertTrue(created)
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.idempotency_key, ACQUISITION_CANARY_IDEMPOTENCY_KEY)
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO market_historicalingestionattempt
                   (chunk_id,ingestion_run_id,attempt_number,idempotency_key,created_at)
                   VALUES (%s,%s,2,%s,now())""",
                [
                    self.canary_chunk.pk,
                    attempt.ingestion_run_id,
                    f"failed-break-ingestion-attempt:{ACQUISITION_CANARY_LOGICAL_KEY}:2",
                ],
            )
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)

    def test_dry_run_is_read_only_and_reports_the_exact_lineage(self):
        before_attempts = HistoricalIngestionAttempt.objects.count()
        before_runs = IngestionRun.objects.count()
        client, output = self.run_command(execute=False)
        report = json.loads(output)
        self.assertEqual(client.calls, 0)
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), before_attempts)
        self.assertEqual(IngestionRun.objects.count(), before_runs)
        self.assertTrue(report["read_only"])
        self.assertEqual(report["provider_requests_performed"], 0)
        self.assertEqual(report["data_contract_sha256"], self.contract.sha256)
        self.assertEqual(report["replacement_plan_sha256"], REPLACEMENT_PLAN_SHA256)
        self.assertEqual(
            report["replacement_dataset_manifest_sha256"],
            REPLACEMENT_DATASET_MANIFEST_SHA256,
        )
        self.assertEqual(report["logical_key"], ACQUISITION_CANARY_LOGICAL_KEY)
        self.assertEqual(report["expected_candle_count"], 2932)
        self.assertEqual(report["instrument"], "AUD_USD")
        self.assertEqual(report["granularity"], "H1")
        for marker in FORBIDDEN_OUTPUT_MARKERS:
            self.assertNotIn(marker, output)
        with self.assertRaisesMessage(
            CommandError, "acquisition canary requires the exact governed logical key"
        ):
            self.run_command(execute=False, logical_key="f" * 64)

    def test_command_success_stores_exactly_the_sealed_series_once(self):
        blocker = IngestionRun.objects.create(
            source=self.source,
            instrument=self.canary_chunk.instrument,
            granularity="H1",
            requested_from=self.canary_chunk.requested_from,
            requested_to=self.canary_chunk.requested_to,
            parameters={},
            request_manifest_hash="0" * 64,
        )
        with self.assertRaisesMessage(CommandError, "an acquisition is already running"):
            self.run_command(execute=True)
        IngestionRun.objects.filter(pk=blocker.pk).delete()

        client, output = self.run_command(execute=True)
        self.assertEqual(client.calls, 1)
        result = json.loads(output)
        self.assertEqual(result["status"], IngestionRun.Status.SUCCEEDED)
        self.assertEqual(result["attempt_number"], 1)
        attempt = HistoricalIngestionAttempt.objects.get()
        run = attempt.ingestion_run
        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(run.fetched_count, 2932)
        self.assertEqual(run.stored_count, 2932)
        stored = Candle.objects.filter(dataset_version=self.dataset)
        self.assertEqual(stored.count(), 2932)
        self.assertEqual(
            tuple(stored.order_by("timestamp").values_list("timestamp", flat=True)),
            tuple(
                self.canary_chunk.discovery_inventory.observations.order_by(
                    "timestamp"
                ).values_list("timestamp", flat=True)
            ),
        )
        manifest = IngestionManifest.objects.get(ingestion_run=run)
        self.assertEqual(manifest.sha256, stable_hash(manifest.payload))
        self.assertEqual(manifest.payload["historical_logical_key"], ACQUISITION_CANARY_LOGICAL_KEY)
        self.assertEqual(
            manifest.payload["requests"][0]["canonical_request_sha256"],
            self.canary_chunk.canonical_request_sha256,
        )
        success = AuditEvent.objects.get(event_type="market.replacement_canary_succeeded")
        payload = success.payload
        self.assertEqual(payload["stored_candle_count"], 2932)
        self.assertEqual(payload["expected_candle_count"], 2932)
        self.assertEqual(payload["data_contract_sha256"], self.contract.sha256)
        self.assertEqual(payload["plan_sha256"], REPLACEMENT_PLAN_SHA256)
        self.assertEqual(payload["dataset_manifest_sha256"], REPLACEMENT_DATASET_MANIFEST_SHA256)
        self.assertEqual(payload["ingestion_manifest_sha256"], manifest.sha256)
        for field in (
            "candle_key_hash",
            "candle_payload_hash",
            "terminal_event_sha256",
            "operational_evidence_sha256",
        ):
            self.assertRegex(payload[field], r"^[0-9a-f]{64}$")
        self.assertEqual(
            payload["terminal_event_sha256"],
            stable_hash(
                {
                    key: value
                    for key, value in payload.items()
                    if key
                    not in (
                        "schema_version",
                        "provider_evidence",
                        "terminal_event_sha256",
                        "operational_evidence_sha256",
                    )
                }
            ),
        )
        self.assertFalse(DatasetRegistration.objects.exists())
        rendered = json.dumps(payload, sort_keys=True)
        for marker in FORBIDDEN_OUTPUT_MARKERS:
            self.assertNotIn(marker, rendered)

        # retry after success is rejected everywhere: the command refuses,
        # the service returns the existing attempt without touching the
        # provider, and a forced second attempt is rejected in PostgreSQL
        with self.assertRaisesMessage(
            CommandError, "acquisition canary attempt already exists; retry is prohibited"
        ):
            self.run_command(execute=True)
        existing, created = begin_historical_attempt(ACQUISITION_CANARY_LOGICAL_KEY)
        self.assertFalse(created)
        self.assertEqual(existing.pk, attempt.pk)
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO market_historicalingestionattempt
                   (chunk_id,ingestion_run_id,attempt_number,idempotency_key,created_at)
                   VALUES (%s,%s,2,%s,now())""",
                [
                    self.canary_chunk.pk,
                    run.pk,
                    f"failed-break-ingestion-attempt:{ACQUISITION_CANARY_LOGICAL_KEY}:2",
                ],
            )

        # old candles and manifests cannot be reassigned into the lineage
        with (
            self.assertRaisesMessage(DatabaseError, "governed dataset candles"),
            transaction.atomic(),
        ):
            Candle.objects.filter(dataset_version=self.dataset).update(volume=1)
        with self.assertRaises(DatabaseError), transaction.atomic():
            IngestionManifest.objects.filter(pk=manifest.pk).update(sha256="1" * 64)
        with (
            self.assertRaisesMessage(DatabaseError, "governed dataset candles are append-only"),
            transaction.atomic(),
        ):
            Candle.objects.filter(dataset_version=self.dataset).delete()
        for statement in (
            "TRUNCATE market_candle CASCADE",
            "TRUNCATE market_ingestionmanifest, market_historicalingestionattempt CASCADE",
        ):
            with (
                self.assertRaisesMessage(
                    DatabaseError, "governed acquisition evidence cannot be truncated"
                ),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(statement)
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)
        self.assertEqual(Candle.objects.filter(dataset_version=self.dataset).count(), 2932)

    def test_provider_failure_is_terminal_sanitized_and_unrepeatable(self):
        inventory = self.canary_chunk.discovery_inventory
        before_semantic = inventory.semantic_inventory_sha256
        client = self.canary_client(
            mutate=lambda candles: candles[:-1]  # one sealed timestamp missing
        )
        with self.assertRaisesMessage(
            HistoricalResponseError,
            "provider response drifted from the sealed timestamp inventory",
        ):
            run_historical_chunk(ACQUISITION_CANARY_LOGICAL_KEY, client)
        self.assertEqual(client.calls, 1)
        attempt = HistoricalIngestionAttempt.objects.get()
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertEqual(
            attempt.ingestion_run.failure_reason,
            HistoricalFailureCode.TIMESTAMP_SET_MISMATCH,
        )
        self.assertEqual(Candle.objects.filter(dataset_version=self.dataset).count(), 0)
        self.assertFalse(IngestionManifest.objects.exists())
        inventory.refresh_from_db()
        self.assertEqual(inventory.semantic_inventory_sha256, before_semantic)
        self.assertEqual(inventory.observations.count(), 2932)
        failure = AuditEvent.objects.get(event_type="market.historical_ingestion_failed")
        rendered = json.dumps(failure.payload, sort_keys=True)
        for marker in FORBIDDEN_OUTPUT_MARKERS:
            self.assertNotIn(marker, rendered)

        # retry after failure is rejected everywhere
        with (
            self.assertRaisesMessage(
                DatabaseError, "acquisition canary activation rejects this ingestion run"
            ),
            transaction.atomic(),
        ):
            begin_historical_attempt(ACQUISITION_CANARY_LOGICAL_KEY)
        with self.assertRaisesMessage(
            CommandError, "acquisition canary attempt already exists; retry is prohibited"
        ):
            self.run_command(execute=True)
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)

    def test_invalid_price_failure_is_terminal_and_sanitized(self):
        inventory = self.canary_chunk.discovery_inventory
        before_observations = inventory.observations.count()

        def poison(candles):
            poisoned = list(candles)
            poisoned[3] = candle(
                timestamp=poisoned[3].timestamp,
                volume=poisoned[3].volume,
                bid_open=Decimal("0"),
            )
            return poisoned

        client = self.canary_client(mutate=poison)
        stdout = StringIO()
        with (
            patch(
                "market.management.commands.acquire_replacement_canary.OandaClient",
                return_value=client,
            ),
            override_settings(
                OANDA_ENVIRONMENT="practice", OANDA_DISCOVERY_TOKEN="safe-test-token"
            ),
            self.assertRaisesMessage(
                CommandError, "acquisition canary failed: INVALID_PRICE_STRUCTURE"
            ),
        ):
            call_command(
                "acquire_replacement_canary",
                "--logical-key",
                ACQUISITION_CANARY_LOGICAL_KEY,
                "--execute",
                stdout=stdout,
            )
        self.assertEqual(client.calls, 1)
        attempt = HistoricalIngestionAttempt.objects.get()
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertEqual(
            attempt.ingestion_run.failure_reason,
            HistoricalFailureCode.INVALID_PRICE_STRUCTURE,
        )
        self.assertEqual(Candle.objects.filter(dataset_version=self.dataset).count(), 0)
        self.assertFalse(IngestionManifest.objects.exists())
        inventory.refresh_from_db()
        self.assertEqual(inventory.observations.count(), before_observations)
        failure = AuditEvent.objects.get(event_type="market.historical_ingestion_failed")
        self.assertEqual(failure.payload["error_code"], "INVALID_PRICE_STRUCTURE")
        self.assertEqual(failure.payload["diagnostics"]["categories"], ["non_positive"])
        rendered = json.dumps(failure.payload)
        for marker in (*FORBIDDEN_OUTPUT_MARKERS, "0.89", "1.10"):
            self.assertNotIn(marker, rendered)
        with self.assertRaisesMessage(
            CommandError, "acquisition canary attempt already exists; retry is prohibited"
        ):
            self.run_command(execute=True)
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)

    def test_response_validation_rejects_every_drift_shape(self):
        chunk = self.canary_chunk
        client = self.canary_client()
        base_candles, base_manifest = client.fetch_historical_chunk(
            "AUD_USD",
            "H1",
            chunk.requested_from,
            chunk.requested_to,
            canonical_request_sha256=chunk.canonical_request_sha256,
        )

        def expect(code, candles):
            with self.assertRaises(HistoricalResponseError) as caught:
                _validate_chunk_response(chunk, candles, base_manifest)
            self.assertEqual(caught.exception.error_code, code)

        in_range_unsealed = candle(timestamp=CANARY_START + timedelta(hours=2950))
        expect(  # extra timestamp
            HistoricalFailureCode.TIMESTAMP_SET_MISMATCH,
            base_candles + [in_range_unsealed],
        )
        expect(  # duplicate timestamp
            HistoricalFailureCode.TIMESTAMP_SET_MISMATCH,
            base_candles + [base_candles[-1]],
        )
        expect(  # unordered timestamps
            HistoricalFailureCode.TIMESTAMP_SET_MISMATCH,
            [base_candles[1], base_candles[0], *base_candles[2:]],
        )
        expect(  # correct first/last with an internal substitution
            HistoricalFailureCode.TIMESTAMP_SET_MISMATCH,
            [*base_candles[:100], in_range_unsealed, *base_candles[101:]],
        )
        volume_drift = list(base_candles)
        volume_drift[50] = candle(
            timestamp=volume_drift[50].timestamp, volume=volume_drift[50].volume + 1
        )
        expect(HistoricalFailureCode.STRUCTURAL_INVENTORY_DRIFT, volume_drift)
        incomplete = list(base_candles)
        incomplete[10] = candle(
            timestamp=incomplete[10].timestamp,
            volume=incomplete[10].volume,
            complete=False,
        )
        expect(HistoricalFailureCode.STRUCTURAL_INVENTORY_DRIFT, incomplete)
        malformed = list(base_candles)
        malformed[5] = candle(
            timestamp=malformed[5].timestamp,
            volume=malformed[5].volume,
            bid_low=malformed[5].bid_high + 1,
        )
        # since the strict price contract, inconsistent OHLC is caught by
        # the provider-observed price validation ahead of validate_candles
        expect(HistoricalFailureCode.INVALID_PRICE_STRUCTURE, malformed)
        with self.assertRaises(KeyError):  # missing ask component is malformed
            _parse_candle(
                {
                    "time": "2010-01-04T00:00:00Z",
                    "complete": True,
                    "volume": 5,
                    "bid": {"o": "1", "h": "1", "l": "1", "c": "1"},
                }
            )
        for label, changes in (
            ("nan", {"bid_low": Decimal("NaN")}),
            ("signaling_nan", {"ask_close": Decimal("sNaN")}),
            ("infinity", {"ask_high": Decimal("Infinity")}),
            ("negative_infinity", {"bid_open": Decimal("-Infinity")}),
            ("zero", {"bid_open": Decimal("0")}),
            (
                "negative_consistent",
                {
                    field: -value
                    for field, value in (
                        ("bid_open", Decimal("1.1000")),
                        ("bid_high", Decimal("1.0990")),
                        ("bid_low", Decimal("1.1020")),
                        ("bid_close", Decimal("1.1010")),
                        ("ask_open", Decimal("1.1002")),
                        ("ask_high", Decimal("1.0992")),
                        ("ask_low", Decimal("1.1022")),
                        ("ask_close", Decimal("1.1012")),
                    )
                },
            ),
            ("excessive_precision", {"bid_close": Decimal("1.1234567")}),
            ("out_of_range", {"ask_open": Decimal("1000000")}),
        ):
            invalid = list(base_candles)
            invalid[7] = candle(timestamp=invalid[7].timestamp, volume=invalid[7].volume, **changes)
            with self.assertRaises(HistoricalResponseError) as caught:
                _validate_chunk_response(chunk, invalid, base_manifest)
            self.assertEqual(
                caught.exception.error_code,
                HistoricalFailureCode.INVALID_PRICE_STRUCTURE,
                label,
            )
            diagnostics = json.dumps(caught.exception.diagnostics)
            for leaked in ("NaN", "Infinity", "1.1234567", "1000000", "1.1000"):
                self.assertNotIn(leaked, diagnostics, label)
        self.assertEqual(
            _invalid_price_categories(candle(bid_open=Decimal("1.1000E+0"))),
            [],
            "exact scientific notation must convert exactly and be accepted",
        )
        self.assertEqual(
            _invalid_price_categories(candle(bid_low=Decimal("2"), bid_high=Decimal("0.5"))),
            ["crossed_bid_ask", "inconsistent_ohlc"],
        )
        for kind, expected_code in (
            ("auth", HistoricalFailureCode.PROVIDER_AUTH_ERROR),
            ("http", HistoricalFailureCode.PROVIDER_HTTP_ERROR),
            ("malformed", HistoricalFailureCode.PROVIDER_RESPONSE_MALFORMED),
        ):
            failure = _classify_historical_failure(
                OandaError("safe", failure_kind=kind, provider_evidence={}),
                chunk,
                None,
                "provider_request",
            )
            self.assertEqual(failure.error_code, expected_code)
        self.assertFalse(HistoricalIngestionAttempt.objects.exists())

    def test_forged_lineage_fails_closed(self):
        forgeries = (
            (
                "market_historicaldatacontract",
                "UPDATE market_historicaldatacontract SET sha256=%s",
                ["f" * 64],
                "UPDATE market_historicaldatacontract SET sha256=%s",
                [self.contract.sha256],
            ),
            (
                "market_historicaldatasetplan",
                "UPDATE market_historicaldatasetplan SET sha256=%s WHERE id=%s",
                ["e" * 64, self.plan.pk],
                "UPDATE market_historicaldatasetplan SET sha256=%s WHERE id=%s",
                [REPLACEMENT_PLAN_SHA256, self.plan.pk],
            ),
            (
                "market_datasetversion",
                "UPDATE market_datasetversion SET manifest_sha256=%s WHERE id=%s",
                ["c" * 64, self.dataset.pk],
                "UPDATE market_datasetversion SET manifest_sha256=%s WHERE id=%s",
                [REPLACEMENT_DATASET_MANIFEST_SHA256, self.dataset.pk],
            ),
            (
                "market_historicaltimestampinventory",
                "UPDATE market_historicaltimestampinventory SET observation_count=%s WHERE id=%s",
                [2931, self.canary_chunk.discovery_inventory_id],
                "UPDATE market_historicaltimestampinventory SET observation_count=%s WHERE id=%s",
                [2932, self.canary_chunk.discovery_inventory_id],
            ),
            (
                "market_historicalingestionchunk",
                "UPDATE market_historicalingestionchunk"
                " SET canonical_request_sha256=%s WHERE id=%s",
                ["a" * 64, self.canary_chunk.pk],
                "UPDATE market_historicalingestionchunk"
                " SET canonical_request_sha256=%s WHERE id=%s",
                [self.canary_chunk.canonical_request_sha256, self.canary_chunk.pk],
            ),
        )
        for table, forge_sql, forge_args, restore_sql, restore_args in forgeries:
            with connection.cursor() as cursor:
                cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
                try:
                    cursor.execute(forge_sql, forge_args)
                finally:
                    cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
            try:
                with self.assertRaises((DatabaseError, DatasetQualityError)), transaction.atomic():
                    begin_historical_attempt(ACQUISITION_CANARY_LOGICAL_KEY)
            finally:
                with connection.cursor() as cursor:
                    cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
                    try:
                        cursor.execute(restore_sql, restore_args)
                    finally:
                        cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        self.assertFalse(HistoricalIngestionAttempt.objects.exists())
        attempt, created = begin_historical_attempt(ACQUISITION_CANARY_LOGICAL_KEY)
        self.assertTrue(created)

    def test_raw_sql_and_queryset_bypasses_fail_closed(self):
        chunk = self.canary_chunk
        other = (
            HistoricalIngestionChunk.objects.filter(plan=self.plan)
            .exclude(pk=chunk.pk)
            .select_related("instrument")[0]
        )
        with (
            self.assertRaisesMessage(
                DatabaseError, "acquisition canary activation rejects this ingestion run"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_ingestionrun
                   (granularity,requested_from,requested_to,parameters,
                    request_manifest_hash,status,fetched_count,stored_count,
                    rejected_count,failure_reason,started_at,instrument_id,
                    source_id,dataset_version_id)
                   VALUES (%s,%s,%s,%s::jsonb,%s,'running',0,0,0,'',now(),%s,%s,%s)""",
                [
                    other.granularity,
                    other.requested_from,
                    other.requested_to,
                    json.dumps(other.canonical_request),
                    stable_hash(
                        {"attempt": (f"failed-break-ingestion-attempt:{other.logical_key}:1")}
                    ),
                    other.instrument_id,
                    self.source.pk,
                    self.dataset.pk,
                ],
            )
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalIngestionChunk.objects.filter(pk=chunk.pk).update(
                expected_observation_count=1
            )
        run = IngestionRun.objects.create(
            source=self.source,
            dataset_version=self.dataset,
            instrument=chunk.instrument,
            granularity=chunk.granularity,
            requested_from=chunk.requested_from,
            requested_to=chunk.requested_to,
            parameters=chunk.canonical_request,
            request_manifest_hash=stable_hash({"attempt": "gate7a-bypass-probe"}),
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            Candle.objects.bulk_create(
                [
                    Candle(
                        instrument=chunk.instrument,
                        ingestion_run=run,
                        dataset_version=self.dataset,
                        granularity="H1",
                        **candle(timestamp=CANARY_START + timedelta(hours=2950)).__dict__,
                    )
                ]
            )
        self.assertEqual(Candle.objects.filter(dataset_version=self.dataset).count(), 0)
        self.assertFalse(HistoricalIngestionAttempt.objects.exists())

        # with a legitimate attempt open, raw-SQL candles carrying invalid
        # prices are rejected inside PostgreSQL even at sealed timestamps
        attempt, created = begin_historical_attempt(ACQUISITION_CANARY_LOGICAL_KEY)
        self.assertTrue(created)
        observation = chunk.discovery_inventory.observations.order_by("timestamp").first()
        columns = (
            "(instrument_id,ingestion_run_id,dataset_version_id,granularity,"
            '"timestamp",complete,volume,bid_open,bid_high,bid_low,bid_close,'
            "ask_open,ask_high,ask_low,ask_close)"
        )
        for label, prices in (
            (
                "negative_consistent",
                [
                    "-1.1000",
                    "-1.0990",
                    "-1.1020",
                    "-1.1010",
                    "-1.1002",
                    "-1.0992",
                    "-1.1022",
                    "-1.1012",
                ],
            ),
            ("zero", ["0", "0", "0", "0", "0", "0", "0", "0"]),
            (
                "inconsistent_ohlc",
                ["1.1000", "1.0000", "1.0990", "1.1010", "1.1002", "1.1022", "1.0992", "1.1012"],
            ),
            ("nan_special", ["NaN"] * 8),
            ("infinity_special", ["Infinity"] * 8),
        ):
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"INSERT INTO market_candle {columns} VALUES "
                    "(%s,%s,%s,'H1',%s,true,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        chunk.instrument_id,
                        attempt.ingestion_run_id,
                        self.dataset.pk,
                        observation.timestamp,
                        observation.volume,
                        *prices,
                    ],
                )
        self.assertEqual(Candle.objects.filter(dataset_version=self.dataset).count(), 0)
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)


class Gate7AConcurrencyTests(Gate7AFixtureTestCase):
    def worker_results(self, target):
        results = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                target(barrier)
                results.append("committed")
            except Exception as error:  # noqa: BLE001 - the label is the assertion
                results.append(f"rejected: {type(error).__name__}: {error}"[:200])
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        return results

    def test_concurrent_service_starts_commit_exactly_one_attempt(self):
        def target(barrier):
            barrier.wait(timeout=30)
            attempt, created = begin_historical_attempt(ACQUISITION_CANARY_LOGICAL_KEY)
            if not created:
                raise DatasetQualityError("existing attempt returned")

        results = self.worker_results(target)
        self.assertEqual(len(results), 2, results)
        self.assertEqual(
            sorted(item.split(":")[0] for item in results), ["committed", "rejected"], results
        )
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)
        self.assertEqual(IngestionRun.objects.filter(dataset_version=self.dataset).count(), 1)

    def test_concurrent_raw_sql_starts_commit_exactly_one_attempt(self):
        chunk = self.canary_chunk

        def target(barrier):
            # The barrier releases before either transaction begins; the
            # database alone (unique run identity plus the attempt trigger)
            # must then serialize the race to exactly one committed attempt.
            barrier.wait(timeout=30)
            with transaction.atomic():
                run = IngestionRun.objects.create(
                    source=self.source,
                    dataset_version=self.dataset,
                    instrument=chunk.instrument,
                    granularity=chunk.granularity,
                    requested_from=chunk.requested_from,
                    requested_to=chunk.requested_to,
                    parameters=chunk.canonical_request,
                    request_manifest_hash=stable_hash(
                        {"attempt": ACQUISITION_CANARY_IDEMPOTENCY_KEY}
                    ),
                )
                with connection.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO market_historicalingestionattempt
                           (chunk_id,ingestion_run_id,attempt_number,
                            idempotency_key,created_at)
                           VALUES (%s,%s,1,%s,now())""",
                        [chunk.pk, run.pk, ACQUISITION_CANARY_IDEMPOTENCY_KEY],
                    )

        results = self.worker_results(target)
        self.assertEqual(len(results), 2, results)
        self.assertEqual(
            sorted(item.split(":")[0] for item in results), ["committed", "rejected"], results
        )
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)
        self.assertEqual(IngestionRun.objects.filter(dataset_version=self.dataset).count(), 1)
