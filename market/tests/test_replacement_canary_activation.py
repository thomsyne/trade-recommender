import json
import threading
import time
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings

from market.historical_acquisition import INSTRUMENTS
from market.historical_discovery import (
    CANARY_ATTEMPT1_FETCHED_COUNT,
    CANARY_ATTEMPT1_MISALIGNED_COUNT,
    CANARY_RETRY_IDEMPOTENCY_KEY,
    CANARY_V2_IDEMPOTENCY_KEY,
    CANARY_V2_LOGICAL_KEY,
    CANARY_V2_REQUEST_SHA256,
    DISCOVERY_PURPOSE,
    GOVERNING_CANARY_LOGICAL_KEY,
    DiscoveryFailureCode,
    DiscoveryResponseError,
    StructuralObservation,
    _classify_failure,
    _record_failure,
    _record_success,
    _validate_response,
    approve_and_register_discovery,
    begin_discovery_attempt,
    build_initial_discovery_plan,
    build_replacement_discovery_plan,
    canonical_hash,
    create_discovery_plan,
    run_discovery_chunk,
    supersede_discovery_plan,
)
from market.models import (
    HistoricalDiscoveryAttempt,
    HistoricalDiscoveryPlan,
    HistoricalDiscoverySupersession,
    HistoricalTimestampInventory,
    IngestionRun,
    Instrument,
    SourceRegistry,
)
from market.oanda import OandaError
from market.services import DatasetQualityError

CANARY_START = datetime(2009, 12, 31, 15, tzinfo=UTC)
MIGRATION_0015 = [("market", "0015_provider_observed_canary_activation")]
MIGRATION_0016 = [("market", "0016_provider_observed_h1_alignment_retry")]
V1_LINEAGE_HASH_SQL = """
    SELECT market_sha256(jsonb_build_object(
             'plan',to_jsonb(p),'chunks',(SELECT jsonb_agg(to_jsonb(c) ORDER BY c.ordinal)
               FROM market_historicaldiscoverychunk c WHERE c.plan_id=p.id),
             'attempts',(SELECT jsonb_agg(to_jsonb(a) ORDER BY a.id)
               FROM market_historicaldiscoveryattempt a
               JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
               WHERE c.plan_id=p.id),
             'runs',(SELECT jsonb_agg(to_jsonb(r) ORDER BY r.id)
               FROM market_ingestionrun r JOIN market_historicaldiscoveryattempt a
                 ON a.ingestion_run_id=r.id JOIN market_historicaldiscoverychunk c
                 ON c.id=a.chunk_id WHERE c.plan_id=p.id),
             'evidence',(SELECT jsonb_agg(to_jsonb(e) ORDER BY e.id)
               FROM market_historicaldiscoveryproviderevidence e
               JOIN market_historicaldiscoveryattempt a ON a.id=e.attempt_id
               JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
               WHERE c.plan_id=p.id),
             'audits',(SELECT jsonb_agg(to_jsonb(ev) ORDER BY ev.id)
               FROM market_auditevent ev JOIN market_historicaldiscoveryattempt a
                 ON ev.subject_id=a.id::text JOIN market_historicaldiscoverychunk c
                 ON c.id=a.chunk_id WHERE c.plan_id=p.id
                   AND ev.subject_type='HistoricalDiscoveryAttempt')))
      FROM market_historicaldiscoveryplan p WHERE p.sha256=%s
"""
PLAN_AND_CHUNKS_HASH_SQL = """
    SELECT market_sha256(jsonb_build_object(
             'plan',to_jsonb(p),'chunks',(SELECT jsonb_agg(to_jsonb(c) ORDER BY c.ordinal)
               FROM market_historicaldiscoverychunk c WHERE c.plan_id=p.id)))
      FROM market_historicaldiscoveryplan p WHERE p.sha256=%s
"""
SUPERSESSION_ROW_HASH_SQL = (
    "SELECT market_sha256(to_jsonb(s)) FROM market_historicaldiscoverysupersession s"
)
ATTEMPT_ONE_HASH_SQL = """
    SELECT market_sha256(jsonb_build_object(
             'attempt',to_jsonb(a),'run',to_jsonb(r),
             'evidence',(SELECT jsonb_agg(to_jsonb(e) ORDER BY e.id)
               FROM market_historicaldiscoveryproviderevidence e WHERE e.attempt_id=a.id),
             'audits',(SELECT jsonb_agg(to_jsonb(ev) ORDER BY ev.id)
               FROM market_auditevent ev
               WHERE ev.subject_type='HistoricalDiscoveryAttempt'
                 AND ev.subject_id=a.id::text)))
      FROM market_historicaldiscoveryattempt a
      JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
     WHERE a.idempotency_key=%s
"""


def migrate_to(targets):
    MigrationExecutor(connection).migrate(targets)


class FailingCanaryClient:
    def __init__(self, request_sha256):
        self.request_sha256 = request_sha256

    def fetch_historical_inventory(self, instrument, granularity, start, end):
        raise OandaError(
            "safe mocked HTTP failure",
            failure_kind="http",
            provider_evidence={
                "endpoint_identity": (
                    f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"
                ),
                "http_method": "GET",
                "oanda_environment": "practice",
                "http_status": 400,
                "provider_request_id": "canary-activation-failure",
                "canonical_request_sha256": self.request_sha256,
            },
        )


class SucceedingCanaryClient:
    def __init__(self, request_sha256):
        self.request_sha256 = request_sha256
        self.calls = []

    def fetch_historical_inventory(self, instrument, granularity, start, end):
        self.calls.append((instrument, granularity, start, end))
        return (
            [
                StructuralObservation(start, True, 10, True, True),
                # A Saturday-New-York whole hour: rejected by the synthetic
                # market-open calendar, accepted by the corrected H1 policy.
                StructuralObservation(start + timedelta(hours=33), True, 4, True, True),
            ],
            {
                "endpoint_identity": (
                    f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"
                ),
                "http_method": "GET",
                "oanda_environment": "practice",
                "http_status": 200,
                "provider_request_id": "canary-activation-success",
                "canonical_request_sha256": self.request_sha256,
            },
        )


class MisalignedCanaryClient:
    """Mirrors the governed attempt-1 response: 2,932 observations of which
    exactly 106 carry non-zero minutes and fail the corrected H1 policy."""

    def __init__(self, request_sha256):
        self.request_sha256 = request_sha256

    def fetch_historical_inventory(self, instrument, granularity, start, end):
        observations = [
            StructuralObservation(CANARY_START + timedelta(hours=hour), True, 1, True, True)
            for hour in range(CANARY_ATTEMPT1_FETCHED_COUNT - CANARY_ATTEMPT1_MISALIGNED_COUNT)
        ]
        observations.extend(
            StructuralObservation(
                CANARY_START + timedelta(hours=2830 + index * 10, minutes=30),
                True,
                1,
                True,
                True,
            )
            for index in range(CANARY_ATTEMPT1_MISALIGNED_COUNT)
        )
        observations.sort(key=lambda item: item.timestamp)
        return (
            observations,
            {
                "endpoint_identity": (
                    f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"
                ),
                "http_method": "GET",
                "oanda_environment": "practice",
                "http_status": 200,
                "provider_request_id": "canary-attempt-one-ledger",
                "canonical_request_sha256": self.request_sha256,
            },
        )


def seed_governed_market(retention_policy):
    source = SourceRegistry.objects.create(
        name="OANDA v20",
        tier=SourceRegistry.Tier.ESTABLISHED,
        base_url="https://developer.oanda.com",
        acquisition_method="v20 REST API",
        retention_policy=retention_policy,
        enabled=True,
    )
    for order, code in enumerate(INSTRUMENTS, 1):
        base, quote = code.split("_")
        Instrument.objects.create(
            code=code,
            base_currency=base,
            quote_currency=quote,
            display_order=order,
            active=True,
        )
    return source


def build_superseded_state():
    superseded = create_discovery_plan(build_initial_discovery_plan())
    v1_canary = superseded.chunks.select_related("instrument").get(
        logical_key=GOVERNING_CANARY_LOGICAL_KEY
    )
    try:
        run_discovery_chunk(
            v1_canary.logical_key, FailingCanaryClient(v1_canary.canonical_request_sha256)
        )
    except OandaError:
        pass
    governing = HistoricalDiscoveryAttempt.objects.get(chunk=v1_canary)
    replacement = create_discovery_plan(build_replacement_discovery_plan())
    supersession = supersede_discovery_plan(superseded.sha256, replacement.sha256, governing.pk)
    return superseded, replacement, supersession


def legacy_structural_diagnostics(issue_counts, sample_code):
    """The 0013-era diagnostics shape the production attempt-1 ledger carries:
    3 keys, at most 32 two-field samples, deterministic truncation flag."""
    total = sum(issue_counts.values())
    return {
        "issue_counts": dict(sorted(issue_counts.items())),
        "issue_samples": [{"code": sample_code, "index": index} for index in range(min(total, 32))],
        "diagnostic_truncated": total > 32,
    }


def canary_raw_evidence(request_sha256, request_id="canary-attempt-one-ledger"):
    return {
        "endpoint_identity": "oanda-v20-practice:GET:/v3/instruments/AUD_USD/candles",
        "http_method": "GET",
        "oanda_environment": "practice",
        "http_status": 200,
        "provider_request_id": request_id,
        "canonical_request_sha256": request_sha256,
    }


def record_attempt_one_ledger(
    source,
    replacement,
    *,
    issue_counts=None,
    fetched=CANARY_ATTEMPT1_FETCHED_COUNT,
    http_failure=False,
    succeed=False,
):
    """Constructs the attempt-1 ledger under the 0015 migration state, where
    the one-shot rule authorized exactly attempt 1. The schema must be at
    0015 when this is called; production authorization is not broadened."""
    canary = replacement.chunks.select_related("plan", "instrument").get(
        logical_key=CANARY_V2_LOGICAL_KEY
    )
    with transaction.atomic(), connection.cursor() as cursor:
        insert_raw_canary_attempt(cursor, source.pk, canary, 1)
    attempt = HistoricalDiscoveryAttempt.objects.get(chunk=canary, attempt_number=1)
    if succeed:
        observations = [
            StructuralObservation(canary.requested_from, True, 1, True, True),
            StructuralObservation(canary.requested_from + timedelta(hours=1), True, 1, True, True),
        ]
        validated, sanitized = _validate_response(
            canary, observations, canary_raw_evidence(canary.canonical_request_sha256)
        )
        _record_success(attempt.pk, validated, sanitized)
    elif http_failure:
        error = OandaError(
            "safe mocked HTTP failure",
            failure_kind="http",
            provider_evidence={
                "endpoint_identity": ("oanda-v20-practice:GET:/v3/instruments/AUD_USD/candles"),
                "http_method": "GET",
                "oanda_environment": "practice",
                "http_status": 400,
                "provider_request_id": "canary-attempt-one-http",
                "canonical_request_sha256": canary.canonical_request_sha256,
            },
        )
        _record_failure(attempt.pk, _classify_failure(error, canary))
    else:
        counts = issue_counts or {"timestamp_misaligned": CANARY_ATTEMPT1_MISALIGNED_COUNT}
        failure = DiscoveryResponseError(
            "discovery response contains invalid structural observations",
            DiscoveryFailureCode.STRUCTURE_INVALID,
            "response_validation",
            legacy_structural_diagnostics(counts, next(iter(sorted(counts)))),
            canary_raw_evidence(canary.canonical_request_sha256),
            fetched,
        )
        _record_failure(attempt.pk, failure)
    return HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").get(pk=attempt.pk)


def build_retry_ready_state(source):
    """Full production-mirroring fixture; requires the 0015 schema."""
    superseded, replacement, supersession = build_superseded_state()
    attempt_one = record_attempt_one_ledger(source, replacement)
    return superseded, replacement, supersession, attempt_one


def state_hashes(superseded, replacement):
    with connection.cursor() as cursor:
        cursor.execute(V1_LINEAGE_HASH_SQL, [superseded.sha256])
        v1_lineage = cursor.fetchone()[0]
        cursor.execute(PLAN_AND_CHUNKS_HASH_SQL, [replacement.sha256])
        v2_plan = cursor.fetchone()[0]
        cursor.execute(SUPERSESSION_ROW_HASH_SQL)
        supersession_row = cursor.fetchone()[0]
    return {"v1": v1_lineage, "v2": v2_plan, "supersession": supersession_row}


def attempt_one_hash():
    with connection.cursor() as cursor:
        cursor.execute(ATTEMPT_ONE_HASH_SQL, [CANARY_V2_IDEMPOTENCY_KEY])
        row = cursor.fetchone()
    return row[0] if row else None


def insert_raw_canary_attempt(cursor, source_pk, chunk, number, idempotency_key=None):
    key = idempotency_key or f"historical-discovery-attempt:{chunk.logical_key}:{number}"
    parameters = {
        "purpose": DISCOVERY_PURPOSE,
        "logical_discovery_key": chunk.logical_key,
        "canonical_request_sha256": chunk.canonical_request_sha256,
        **chunk.canonical_request,
    }
    cursor.execute(
        """INSERT INTO market_ingestionrun
           (source_id,instrument_id,granularity,requested_from,requested_to,parameters,
            request_manifest_hash,status,fetched_count,stored_count,rejected_count,
            failure_reason,started_at,finished_at)
           VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,'running',0,0,0,'',now(),NULL)
           RETURNING id""",
        [
            source_pk,
            chunk.instrument_id,
            chunk.granularity,
            chunk.requested_from,
            chunk.requested_to,
            json.dumps(parameters),
            canonical_hash({"purpose": DISCOVERY_PURPOSE, "attempt_idempotency_key": key}),
        ],
    )
    run_id = cursor.fetchone()[0]
    cursor.execute(
        """INSERT INTO market_historicaldiscoveryattempt
           (chunk_id,ingestion_run_id,attempt_number,idempotency_key,created_at)
           VALUES (%s,%s,%s,%s,now())""",
        [chunk.pk, run_id, number, key],
    )


class RetryFixtureTestCase(TransactionTestCase):
    """Builds the attempt-1 ledger under 0015, then applies 0016."""

    retention_policy = "canary retry fixture"

    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0015)
        self.source = seed_governed_market(self.retention_policy)
        (
            self.superseded,
            self.replacement,
            self.supersession,
            self.attempt_one,
        ) = build_retry_ready_state(self.source)
        migrate_to(MIGRATION_0016)
        self.canary = self.replacement.chunks.select_related("instrument").get(
            logical_key=CANARY_V2_LOGICAL_KEY
        )
        self.v1_canary = self.superseded.chunks.select_related("instrument").get(
            logical_key=GOVERNING_CANARY_LOGICAL_KEY
        )

    def tearDown(self):
        migrate_to(MIGRATION_0016)
        super().tearDown()


class ReplacementCanaryRetryTests(RetryFixtureTestCase):
    def test_attempt_one_ledger_matches_the_governing_finding(self):
        self.assertEqual(self.canary.canonical_request_sha256, CANARY_V2_REQUEST_SHA256)
        run = self.attempt_one.ingestion_run
        self.assertEqual(self.attempt_one.idempotency_key, CANARY_V2_IDEMPOTENCY_KEY)
        self.assertEqual(run.status, IngestionRun.Status.FAILED)
        self.assertEqual(run.failure_reason, "DISCOVERY_STRUCTURE_INVALID")
        self.assertEqual(run.fetched_count, CANARY_ATTEMPT1_FETCHED_COUNT)
        self.assertEqual(run.stored_count, 0)
        self.assertEqual(run.rejected_count, CANARY_ATTEMPT1_FETCHED_COUNT)

    def test_exact_retry_attempt_two_succeeds_through_service(self):
        before = state_hashes(self.superseded, self.replacement)
        ledger_before = attempt_one_hash()
        client = SucceedingCanaryClient(self.canary.canonical_request_sha256)

        attempt = run_discovery_chunk(CANARY_V2_LOGICAL_KEY, client)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(attempt.attempt_number, 2)
        self.assertEqual(attempt.idempotency_key, CANARY_RETRY_IDEMPOTENCY_KEY)
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.SUCCEEDED)
        self.assertTrue(HistoricalTimestampInventory.objects.filter(chunk=self.canary).exists())
        self.assertEqual(state_hashes(self.superseded, self.replacement), before)
        self.assertEqual(attempt_one_hash(), ledger_before)

    def test_every_other_v2_chunk_is_rejected(self):
        other_chunks = list(
            self.replacement.chunks.select_related("instrument").exclude(
                logical_key=CANARY_V2_LOGICAL_KEY
            )
        )
        self.assertEqual(len(other_chunks), 131)
        for chunk in other_chunks:
            with (
                self.subTest(ordinal=chunk.ordinal),
                self.assertRaisesMessage(
                    DatasetQualityError, "replacement canary activation rejects this attempt"
                ),
            ):
                begin_discovery_attempt(chunk.logical_key)
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(), 1
        )

    def test_raw_sql_permits_only_the_exact_retry_identities(self):
        wrong = (
            ("attempt-one-again", self.canary, 1, None),
            ("attempt-three", self.canary, 3, None),
            ("wrong-key", self.canary, 2, "historical-discovery-attempt:forged:2"),
            ("wrong-chunk", self.replacement.chunks.get(ordinal=1), 2, None),
        )
        for label, chunk, number, key in wrong:
            with (
                self.subTest(case=label),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                insert_raw_canary_attempt(cursor, self.source.pk, chunk, number, key)
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(), 1
        )

        with transaction.atomic(), connection.cursor() as cursor:
            insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 2)
        retry = HistoricalDiscoveryAttempt.objects.get(chunk=self.canary, attempt_number=2)
        self.assertEqual(retry.idempotency_key, CANARY_RETRY_IDEMPOTENCY_KEY)

    def test_attempt_three_and_retry_are_rejected_after_success(self):
        run_discovery_chunk(
            CANARY_V2_LOGICAL_KEY,
            SucceedingCanaryClient(self.canary.canonical_request_sha256),
        )
        with self.assertRaises(DatasetQualityError):
            begin_discovery_attempt(CANARY_V2_LOGICAL_KEY)
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement canary activation rejects this attempt"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 3)
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(), 2
        )

    def test_attempt_three_and_retry_are_rejected_after_failure(self):
        with self.assertRaises(OandaError):
            run_discovery_chunk(
                CANARY_V2_LOGICAL_KEY,
                FailingCanaryClient(self.canary.canonical_request_sha256),
            )
        with self.assertRaisesMessage(
            DatasetQualityError, "replacement canary activation rejects this attempt"
        ):
            begin_discovery_attempt(CANARY_V2_LOGICAL_KEY)
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement canary activation rejects this attempt"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 3)
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(), 2
        )

    def test_superseded_plan_writes_remain_rejected(self):
        with self.assertRaisesMessage(
            DatasetQualityError, "superseded discovery plans reject new attempts"
        ):
            begin_discovery_attempt(self.v1_canary.logical_key)
        with (
            self.assertRaisesMessage(DatabaseError, "superseded discovery plans reject new writes"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            insert_raw_canary_attempt(cursor, self.source.pk, self.v1_canary, 2)

    def test_replacement_approval_registration_sealing_and_bypasses_fail_closed(self):
        approver = get_user_model().objects.create_user("canary-retry-approver")
        approver.user_permissions.add(
            Permission.objects.get(codename="approve_historical_discovery")
        )
        with self.assertRaisesMessage(
            DatasetQualityError,
            "supersession replacement plans reject approval until governed activation",
        ):
            approve_and_register_discovery(self.replacement.sha256, approver.pk, "a" * 64)
        with (
            self.assertRaisesMessage(
                DatabaseError,
                "supersession replacement plans reject approval until governed activation",
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [self.replacement.pk, approver.pk, "a" * 64, "b" * 64, "c" * 64],
            )
        with (
            self.assertRaisesMessage(
                DatabaseError,
                "supersession replacement plans reject approval until governed activation",
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryregistration
                   (plan_id,approval_id,ordered_chunk_manifest_sha256,
                    global_semantic_inventory_sha256,accepted_operational_evidence_set_sha256,
                    cross_series_report_sha256,payload,report_sha256,registered_at)
                   VALUES (%s,999999,%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [self.replacement.pk, "a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64],
            )
        with (
            self.assertRaisesMessage(
                DatabaseError,
                "supersession replacement plans reject sealing until governed activation",
            ),
            transaction.atomic(),
        ):
            HistoricalDiscoveryPlan.objects.filter(pk=self.replacement.pk).update(
                sealed_at=datetime(2026, 1, 1, tzinfo=UTC)
            )
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalDiscoverySupersession.objects.filter(pk=self.supersession.pk).update(
                reason_code="CHANGED"
            )
        non_canary = self.replacement.chunks.get(ordinal=1)
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement canary activation rejects this attempt"
            ),
            transaction.atomic(),
        ):
            run = IngestionRun.objects.create(
                source=self.source,
                instrument=non_canary.instrument,
                granularity=non_canary.granularity,
                requested_from=non_canary.requested_from,
                requested_to=non_canary.requested_to,
                parameters={
                    "purpose": DISCOVERY_PURPOSE,
                    "logical_discovery_key": non_canary.logical_key,
                    "canonical_request_sha256": non_canary.canonical_request_sha256,
                    **non_canary.canonical_request,
                },
                request_manifest_hash=canonical_hash(
                    {
                        "purpose": DISCOVERY_PURPOSE,
                        "attempt_idempotency_key": (
                            f"historical-discovery-attempt:{non_canary.logical_key}:1"
                        ),
                    }
                ),
            )
            HistoricalDiscoveryAttempt.objects.bulk_create(
                [
                    HistoricalDiscoveryAttempt(
                        chunk=non_canary,
                        ingestion_run=run,
                        attempt_number=1,
                        idempotency_key=(
                            f"historical-discovery-attempt:{non_canary.logical_key}:1"
                        ),
                    )
                ]
            )

    @override_settings(OANDA_DISCOVERY_TOKEN="mocked-discovery-token", OANDA_ENVIRONMENT="practice")
    def test_discovery_command_uses_exactly_one_mocked_provider_request(self):
        calls = []
        request_sha = self.canary.canonical_request_sha256
        requested_from = self.canary.requested_from
        requested_to = self.canary.requested_to

        class MockedClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def fetch_historical_inventory(self, instrument, granularity, start, end):
                calls.append((instrument, granularity, start, end))
                return (
                    [StructuralObservation(start, True, 10, True, True)],
                    {
                        "endpoint_identity": (
                            f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"
                        ),
                        "http_method": "GET",
                        "oanda_environment": "practice",
                        "http_status": 200,
                        "provider_request_id": "canary-command-request",
                        "canonical_request_sha256": request_sha,
                    },
                )

        with patch(
            "market.management.commands.discover_historical_inventory.OandaClient",
            return_value=MockedClient(),
        ) as client_factory:
            stdout = StringIO()
            call_command(
                "discover_historical_inventory",
                "--logical-discovery-key",
                CANARY_V2_LOGICAL_KEY,
                "--execute",
                stdout=stdout,
            )
        client_factory.assert_called_once_with("mocked-discovery-token", "practice")
        self.assertEqual(calls, [("AUD_USD", "H1", requested_from, requested_to)])
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["attempt_number"], 2)
        self.assertEqual(result["status"], IngestionRun.Status.SUCCEEDED)


class ReplacementCanaryLedgerGateTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0015)
        self.source = seed_governed_market("canary ledger gate test")
        self.superseded, self.replacement, self.supersession = build_superseded_state()
        self.canary = self.replacement.chunks.select_related("instrument").get(
            logical_key=CANARY_V2_LOGICAL_KEY
        )

    def tearDown(self):
        migrate_to(MIGRATION_0016)
        super().tearDown()

    def assert_retry_rejected_everywhere(self):
        with self.assertRaisesMessage(
            DatasetQualityError, "replacement canary activation rejects this attempt"
        ):
            begin_discovery_attempt(CANARY_V2_LOGICAL_KEY)
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement canary activation rejects this attempt"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 2)

    def test_zero_attempts_fail_closed_under_0016(self):
        migrate_to(MIGRATION_0016)
        self.assert_retry_rejected_everywhere()
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement canary activation rejects this attempt"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 1)
        self.assertFalse(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).exists()
        )

    def test_retry_is_rejected_when_attempt_one_failure_code_differs(self):
        attempt = record_attempt_one_ledger(self.source, self.replacement, http_failure=True)
        self.assertEqual(attempt.ingestion_run.failure_reason, "DISCOVERY_PROVIDER_HTTP_ERROR")
        migrate_to(MIGRATION_0016)
        self.assert_retry_rejected_everywhere()

    def test_retry_is_rejected_when_attempt_one_counts_differ(self):
        attempt = record_attempt_one_ledger(
            self.source,
            self.replacement,
            issue_counts={"duplicate_timestamps": 1},
            fetched=2,
        )
        self.assertEqual(attempt.ingestion_run.failure_reason, "DISCOVERY_STRUCTURE_INVALID")
        self.assertEqual(attempt.ingestion_run.fetched_count, 2)
        migrate_to(MIGRATION_0016)
        self.assert_retry_rejected_everywhere()

    def test_retry_is_rejected_when_extra_issue_category_present(self):
        attempt = record_attempt_one_ledger(
            self.source,
            self.replacement,
            issue_counts={
                "timestamp_misaligned": CANARY_ATTEMPT1_MISALIGNED_COUNT,
                "incomplete": 1,
            },
        )
        run = attempt.ingestion_run
        self.assertEqual(run.failure_reason, "DISCOVERY_STRUCTURE_INVALID")
        self.assertEqual(run.fetched_count, CANARY_ATTEMPT1_FETCHED_COUNT)
        migrate_to(MIGRATION_0016)
        self.assert_retry_rejected_everywhere()

    def test_retry_is_rejected_when_attempt_one_succeeded_with_inventory(self):
        record_attempt_one_ledger(self.source, self.replacement, succeed=True)
        self.assertTrue(HistoricalTimestampInventory.objects.filter(chunk=self.canary).exists())
        migrate_to(MIGRATION_0016)
        with self.assertRaises(DatasetQualityError):
            begin_discovery_attempt(CANARY_V2_LOGICAL_KEY)
        with (
            self.assertRaises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 2)


class ReplacementCanaryRetryConcurrencyTests(RetryFixtureTestCase):
    retention_policy = "canary retry concurrency"

    def test_two_concurrent_service_retries_produce_exactly_one_attempt(self):
        barrier = threading.Barrier(2)
        outcomes = []

        def start_retry():
            close_old_connections()
            try:
                barrier.wait(5)
                begin_discovery_attempt(CANARY_V2_LOGICAL_KEY)
                outcomes.append("committed")
            except (DatasetQualityError, DatabaseError):
                outcomes.append("rejected")
            finally:
                close_old_connections()

        threads = [threading.Thread(target=start_retry) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        self.assertEqual(sorted(outcomes), ["committed", "rejected"])
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(), 2
        )

    def test_two_concurrent_raw_retries_produce_exactly_one_attempt(self):
        result = {}
        ready = threading.Event()

        def contender():
            close_old_connections()
            try:
                ready.set()
                with transaction.atomic(), connection.cursor() as cursor:
                    insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 2)
                result["outcome"] = "committed"
            except DatabaseError as error:
                result["outcome"] = "rejected"
                result["error"] = str(error)
            finally:
                close_old_connections()

        thread = threading.Thread(target=contender)
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 2)
                thread.start()
                self.assertTrue(ready.wait(5))
                time.sleep(0.5)
                self.assertTrue(thread.is_alive(), "contender was not blocked by the plan lock")
        finally:
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["outcome"], "rejected")
        self.assertTrue(
            "replacement canary activation rejects this attempt" in result["error"]
            or "unique_legacy_ingestion_manifest_hash" in result["error"],
            result["error"],
        )
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(), 2
        )
