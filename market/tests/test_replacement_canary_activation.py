import json
import threading
import time
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings

from market.historical_acquisition import INSTRUMENTS
from market.historical_discovery import (
    CANARY_V2_IDEMPOTENCY_KEY,
    CANARY_V2_LOGICAL_KEY,
    CANARY_V2_REQUEST_SHA256,
    DISCOVERY_PURPOSE,
    GOVERNING_CANARY_LOGICAL_KEY,
    StructuralObservation,
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
            [StructuralObservation(start, True, 10, True, True)],
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


def state_hashes(superseded, replacement):
    with connection.cursor() as cursor:
        cursor.execute(V1_LINEAGE_HASH_SQL, [superseded.sha256])
        v1_lineage = cursor.fetchone()[0]
        cursor.execute(PLAN_AND_CHUNKS_HASH_SQL, [replacement.sha256])
        v2_plan = cursor.fetchone()[0]
        cursor.execute(SUPERSESSION_ROW_HASH_SQL)
        supersession_row = cursor.fetchone()[0]
    return {"v1": v1_lineage, "v2": v2_plan, "supersession": supersession_row}


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


class ReplacementCanaryActivationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = seed_governed_market("canary activation test")
        cls.superseded, cls.replacement, cls.supersession = build_superseded_state()
        cls.canary = cls.replacement.chunks.select_related("instrument").get(
            logical_key=CANARY_V2_LOGICAL_KEY
        )
        cls.v1_canary = cls.superseded.chunks.select_related("instrument").get(
            logical_key=GOVERNING_CANARY_LOGICAL_KEY
        )

    def test_canary_chunk_matches_the_approved_identity(self):
        self.assertEqual(self.canary.canonical_request_sha256, CANARY_V2_REQUEST_SHA256)
        self.assertEqual(self.canary.ordinal, 2)
        self.assertEqual(self.canary.instrument.code, "AUD_USD")
        self.assertEqual(self.canary.granularity, "H1")
        self.assertEqual(
            (self.canary.requested_to - self.canary.requested_from).total_seconds(), 4000 * 3600
        )

    def test_exact_canary_first_attempt_succeeds_through_service(self):
        before = state_hashes(self.superseded, self.replacement)
        client = SucceedingCanaryClient(self.canary.canonical_request_sha256)

        attempt = run_discovery_chunk(CANARY_V2_LOGICAL_KEY, client)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][0], "AUD_USD")
        self.assertEqual(client.calls[0][1], "H1")
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.idempotency_key, CANARY_V2_IDEMPOTENCY_KEY)
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.SUCCEEDED)
        self.assertTrue(HistoricalTimestampInventory.objects.filter(chunk=self.canary).exists())
        self.assertEqual(state_hashes(self.superseded, self.replacement), before)

    def test_every_other_v2_chunk_is_rejected(self):
        other_chunks = list(
            self.replacement.chunks.select_related("instrument").exclude(
                logical_key=CANARY_V2_LOGICAL_KEY
            )
        )
        self.assertEqual(len(other_chunks), 131)
        covered = {
            "granularity": {chunk.granularity for chunk in other_chunks},
            "instrument": {chunk.instrument.code for chunk in other_chunks},
        }
        self.assertEqual(covered["granularity"], {"D", "H1", "W"})
        self.assertEqual(covered["instrument"], set(INSTRUMENTS))
        for chunk in other_chunks:
            with (
                self.subTest(ordinal=chunk.ordinal),
                self.assertRaisesMessage(
                    DatasetQualityError, "replacement canary activation rejects this attempt"
                ),
            ):
                begin_discovery_attempt(chunk.logical_key)
        self.assertFalse(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).exists()
        )

    def test_raw_sql_permits_only_the_exact_canary_identities(self):
        wrong = (
            ("wrong-number", self.canary, 2, None),
            ("wrong-key", self.canary, 1, "historical-discovery-attempt:forged:1"),
            ("wrong-chunk", self.replacement.chunks.get(ordinal=1), 1, None),
            ("wrong-chunk-h1", self.replacement.chunks.get(ordinal=3), 1, None),
        )
        for label, chunk, number, key in wrong:
            with (
                self.subTest(case=label),
                self.assertRaisesMessage(
                    DatabaseError, "replacement canary activation rejects this attempt"
                ),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                insert_raw_canary_attempt(cursor, self.source.pk, chunk, number, key)
        self.assertFalse(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).exists()
        )

        with connection.cursor() as cursor:
            insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 1)
        attempt = HistoricalDiscoveryAttempt.objects.get(chunk=self.canary)
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.idempotency_key, CANARY_V2_IDEMPOTENCY_KEY)

    def test_second_attempt_and_retry_are_rejected_after_success(self):
        run_discovery_chunk(
            CANARY_V2_LOGICAL_KEY,
            SucceedingCanaryClient(self.canary.canonical_request_sha256),
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
            insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 2)
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(),
            1,
        )

    def test_retry_is_rejected_after_failure(self):
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
            insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 2)
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(),
            1,
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
        approver = get_user_model().objects.create_user("canary-approver")
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
        self.assertEqual(
            calls, [("AUD_USD", "H1", self.canary.requested_from, self.canary.requested_to)]
        )
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["attempt_number"], 1)
        self.assertEqual(result["status"], IngestionRun.Status.SUCCEEDED)


class ReplacementCanaryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.source = seed_governed_market("canary activation concurrency")
        self.superseded, self.replacement, self.supersession = build_superseded_state()
        self.canary = self.replacement.chunks.select_related("instrument").get(
            logical_key=CANARY_V2_LOGICAL_KEY
        )

    def test_two_concurrent_service_starts_produce_exactly_one_attempt(self):
        barrier = threading.Barrier(2)
        outcomes = []

        def start_canary():
            close_old_connections()
            try:
                barrier.wait(5)
                begin_discovery_attempt(CANARY_V2_LOGICAL_KEY)
                outcomes.append("committed")
            except (DatasetQualityError, DatabaseError):
                outcomes.append("rejected")
            finally:
                close_old_connections()

        threads = [threading.Thread(target=start_canary) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        self.assertEqual(sorted(outcomes), ["committed", "rejected"])
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(),
            1,
        )

    def test_two_concurrent_raw_starts_produce_exactly_one_attempt(self):
        result = {}
        ready = threading.Event()

        def contender():
            close_old_connections()
            try:
                ready.set()
                with transaction.atomic(), connection.cursor() as cursor:
                    insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 1)
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
                    insert_raw_canary_attempt(cursor, self.source.pk, self.canary, 1)
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
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(),
            1,
        )
