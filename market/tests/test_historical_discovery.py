import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from market.historical_acquisition import INSTRUMENTS
from market.historical_discovery import (
    DISCOVERY_PROVIDER_MAX_CANDLES,
    DiscoveryFailureCode,
    DiscoveryResponseError,
    StructuralObservation,
    _registration_hashes,
    _validate_response,
    approve_and_register_discovery,
    begin_discovery_attempt,
    build_initial_discovery_plan,
    canonical_hash,
    create_discovery_plan,
    future_data_contract_semantic_hash,
    logical_discovery_key,
    resolve_stale_discovery_attempt,
    run_discovery_chunk,
    semantic_inventory_hashes,
)
from market.models import (
    AuditEvent,
    HistoricalDiscoveryApproval,
    HistoricalDiscoveryAttempt,
    HistoricalDiscoveryPlan,
    HistoricalDiscoveryProviderEvidence,
    HistoricalDiscoveryRegistration,
    HistoricalTimestampInventory,
    HistoricalTimestampObservation,
    IngestionRun,
    Instrument,
    SourceRegistry,
)
from market.oanda import OandaError
from market.services import DatasetQualityError


class OfflineDiscoveryPlanTests(SimpleTestCase):
    def test_initial_plan_is_exactly_84_portable_canonical_requests(self):
        payload = build_initial_discovery_plan()

        self.assertEqual(payload["declared_chunk_count"], 84)
        self.assertEqual(len(payload["requests"]), 84)
        self.assertEqual(
            payload["canonical_request_manifest_sha256"], canonical_hash(payload["requests"])
        )
        plan_body = {key: value for key, value in payload.items() if key != "plan_sha256"}
        self.assertEqual(payload["plan_sha256"], canonical_hash(plan_body))
        self.assertEqual([item["ordinal"] for item in payload["requests"]], list(range(1, 85)))
        serialized = json.dumps(payload, sort_keys=True)
        for forbidden in ("source_id", "instrument_id", "run_id", "attempt_number"):
            self.assertNotIn(forbidden, serialized)

    def test_future_contract_fixture_depends_only_on_semantic_inventory(self):
        semantic = "a" * 64
        expected = future_data_contract_semantic_hash(global_semantic_inventory_sha256=semantic)

        for operational_history in (
            {"attempt": 1, "request_id": "first"},
            {"attempt": 7, "request_id": "different", "approval": "changed"},
        ):
            self.assertEqual(
                future_data_contract_semantic_hash(global_semantic_inventory_sha256=semantic),
                expected,
                operational_history,
            )


class FailingInventoryClient:
    def __init__(self, request_sha256):
        self.request_sha256 = request_sha256

    def fetch_historical_inventory(self, instrument, granularity, start, end):
        raise OandaError(
            "safe connection failure",
            failure_kind="http",
            provider_evidence={
                "endpoint_identity": (
                    f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"
                ),
                "http_method": "GET",
                "oanda_environment": "practice",
                "canonical_request_sha256": self.request_sha256,
                "unavailable_fields": ["http_status", "provider_request_id"],
            },
        )


class HistoricalDiscoveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier=SourceRegistry.Tier.ESTABLISHED,
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="governed test evidence",
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

    def single_request_payload(self, version="phase-2b1r-discovery-v2"):
        payload = build_initial_discovery_plan()
        request = dict(payload["requests"][0])
        request_body = request["canonical_request"]
        start = datetime.fromisoformat(request_body["from"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(request_body["to"].replace("Z", "+00:00"))
        request["logical_discovery_key"] = logical_discovery_key(
            request_sha256=request["canonical_request_sha256"],
            instrument=request_body["instrument"],
            granularity=request_body["granularity"],
            requested_from=start,
            requested_to=end,
            discovery_version=version,
        )
        body = {
            key: value for key, value in payload.items() if key not in {"requests", "plan_sha256"}
        }
        body.update(
            identity=f"test-{version}",
            discovery_version=version,
            declared_chunk_count=1,
            requests=[request],
            canonical_request_manifest_sha256=canonical_hash([request]),
        )
        return {**body, "plan_sha256": canonical_hash(body)}

    def create_plan(self):
        return create_discovery_plan(self.single_request_payload())

    def evidence_for(self, chunk, request_id="provider-request-1"):
        return {
            "endpoint_identity": (
                f"oanda-v20-practice:GET:/v3/instruments/{chunk.instrument.code}/candles"
            ),
            "http_method": "GET",
            "oanda_environment": "practice",
            "http_status": 200,
            "provider_request_id": request_id,
            "canonical_request_sha256": chunk.canonical_request_sha256,
        }

    def run_success(self, plan):
        chunk = plan.chunks.select_related("instrument").get()
        client = type(
            "SuccessfulInventoryClient",
            (),
            {
                "fetch_historical_inventory": lambda _, instrument, granularity, start, end: (
                    [StructuralObservation(start, True, 10, True, True)],
                    self.evidence_for(chunk),
                )
            },
        )()
        return run_discovery_chunk(chunk.logical_key, client)

    def test_separately_versioned_plan_uses_declared_count_not_global_84(self):
        plan = self.create_plan()

        self.assertEqual(plan.declared_chunk_count, 1)
        self.assertEqual(plan.chunks.count(), 1)
        self.assertEqual(plan.canonical_request_manifest, self.single_request_payload()["requests"])

    def test_discovery_attempt_reuses_canonical_ingestion_run(self):
        plan = self.create_plan()
        chunk = plan.chunks.get()
        attempt = begin_discovery_attempt(chunk.logical_key)

        self.assertEqual(HistoricalDiscoveryAttempt.objects.count(), 1)
        self.assertEqual(IngestionRun.objects.count(), 1)
        self.assertEqual(
            attempt.ingestion_run.parameters["purpose"], "provider_timestamp_inventory_discovery"
        )
        self.assertEqual(attempt.ingestion_run.dataset_version_id, None)
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(
            attempt.idempotency_key, f"historical-discovery-attempt:{chunk.logical_key}:1"
        )
        with self.assertRaisesMessage(DatasetQualityError, "already has a running attempt"):
            begin_discovery_attempt(chunk.logical_key)

    def test_success_stores_only_structural_inventory_and_one_terminal_event(self):
        plan = self.create_plan()
        attempt = self.run_success(plan)
        attempt.refresh_from_db()
        run = attempt.ingestion_run

        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual((run.fetched_count, run.stored_count, run.rejected_count), (1, 1, 0))
        inventory = HistoricalTimestampInventory.objects.get()
        observation = HistoricalTimestampObservation.objects.get()
        self.assertEqual(observation.volume, 10)
        self.assertTrue(
            observation.complete and observation.bid_present and observation.ask_present
        )
        self.assertEqual(inventory.observation_count, 1)
        self.assertEqual(
            AuditEvent.objects.filter(
                event_type="market.historical_discovery_succeeded",
                subject_id=str(attempt.pk),
            ).count(),
            1,
        )
        prohibited = {
            "bid_open",
            "bid_high",
            "bid_low",
            "bid_close",
            "ask_open",
            "ask_high",
            "ask_low",
            "ask_close",
            "authorization",
            "raw_url",
            "body",
            "account_id",
        }
        model_fields = {field.name for field in HistoricalTimestampObservation._meta.fields}
        self.assertTrue(prohibited.isdisjoint(model_fields))
        serialized = json.dumps(AuditEvent.objects.get().payload, sort_keys=True).lower()
        self.assertTrue(all(value not in serialized for value in prohibited))
        with self.assertRaisesMessage(DatasetQualityError, "cannot be retried"):
            begin_discovery_attempt(plan.chunks.get().logical_key)

    def test_network_failure_records_explicit_unavailable_fields_without_secret_data(self):
        plan = self.create_plan()
        chunk = plan.chunks.get()

        with self.assertRaises(OandaError):
            run_discovery_chunk(
                chunk.logical_key, FailingInventoryClient(chunk.canonical_request_sha256)
            )

        attempt = HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").get()
        evidence = HistoricalDiscoveryProviderEvidence.objects.get()
        event = AuditEvent.objects.get(event_type="market.historical_discovery_failed")
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertEqual(
            attempt.ingestion_run.failure_reason, DiscoveryFailureCode.PROVIDER_HTTP_ERROR
        )
        self.assertIsNone(evidence.http_status)
        self.assertIsNone(evidence.provider_request_id)
        self.assertEqual(evidence.unavailable_fields, ["http_status", "provider_request_id"])
        serialized = json.dumps(event.payload, sort_keys=True).lower()
        for forbidden in ("bearer", "token", "authorization", "raw_url", "account_id"):
            self.assertNotIn(forbidden, serialized)

        retry = begin_discovery_attempt(chunk.logical_key)
        self.assertEqual(retry.attempt_number, 2)
        self.assertEqual(
            retry.idempotency_key, f"historical-discovery-attempt:{chunk.logical_key}:2"
        )

    def test_stale_resolution_requires_explicit_stale_attempt_threshold_and_reason(self):
        plan = self.create_plan()
        with patch("django.utils.timezone.now", return_value=timezone.now() - timedelta(hours=2)):
            attempt = begin_discovery_attempt(plan.chunks.get().logical_key)

        with self.assertRaisesMessage(DatasetQualityError, "is not stale"):
            resolve_stale_discovery_attempt(attempt.pk, timedelta(hours=3), "WORKER_LOST")
        resolved = resolve_stale_discovery_attempt(attempt.pk, timedelta(hours=1), "WORKER_LOST")
        self.assertEqual(resolved.ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertEqual(resolved.ingestion_run.failure_reason, DiscoveryFailureCode.STALE_ATTEMPT)
        self.assertEqual(
            resolved.provider_evidence.unavailable_fields,
            ["http_status", "provider_request_id"],
        )

    def test_terminal_audit_failure_rolls_back_success_transition(self):
        plan = self.create_plan()
        chunk = plan.chunks.select_related("instrument").get()
        client = type(
            "SuccessfulInventoryClient",
            (),
            {
                "fetch_historical_inventory": lambda _, instrument, granularity, start, end: (
                    [StructuralObservation(start, True, 10, True, True)],
                    self.evidence_for(chunk),
                )
            },
        )()

        with (
            patch.object(
                AuditEvent.objects, "create", side_effect=DatabaseError("synthetic audit failure")
            ),
            self.assertRaises(DatabaseError),
        ):
            run_discovery_chunk(chunk.logical_key, client)

        attempt = HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").get()
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.RUNNING)
        self.assertFalse(HistoricalTimestampInventory.objects.exists())
        self.assertFalse(HistoricalDiscoveryProviderEvidence.objects.exists())

    def test_structural_validation_fails_closed_for_every_governed_field(self):
        plan = self.create_plan()
        chunk = plan.chunks.select_related("instrument").get()
        valid = StructuralObservation(chunk.requested_from, True, 1, True, True)
        cases = {
            "duplicate_timestamps": [valid, valid],
            "unordered_timestamps": [
                StructuralObservation(
                    chunk.requested_from + timedelta(weeks=1), True, 1, True, True
                ),
                valid,
            ],
            "timestamp_out_of_range": [
                StructuralObservation(chunk.requested_to, True, 1, True, True)
            ],
            "timestamp_misaligned": [
                StructuralObservation(
                    chunk.requested_from + timedelta(minutes=1), True, 1, True, True
                )
            ],
            "completeness_missing": [
                StructuralObservation(chunk.requested_from, None, 1, True, True)
            ],
            "incomplete": [StructuralObservation(chunk.requested_from, False, 1, True, True)],
            "invalid_volume": [StructuralObservation(chunk.requested_from, True, -1, True, True)],
            "bid_missing": [StructuralObservation(chunk.requested_from, True, 1, False, True)],
            "ask_missing": [StructuralObservation(chunk.requested_from, True, 1, True, False)],
        }
        for code, observations in cases.items():
            with self.subTest(code=code), self.assertRaises(DiscoveryResponseError) as raised:
                _validate_response(chunk, observations, self.evidence_for(chunk))
            self.assertIn(code, raised.exception.diagnostics["issue_counts"])

    def test_provider_limit_equality_fails_before_first_last_can_be_used(self):
        plan = self.create_plan()
        chunk = plan.chunks.select_related("instrument").get()
        observations = [
            StructuralObservation(chunk.requested_from, True, 1, True, True)
        ] * DISCOVERY_PROVIDER_MAX_CANDLES

        with self.assertRaises(DiscoveryResponseError) as raised:
            _validate_response(chunk, observations, self.evidence_for(chunk))

        self.assertEqual(raised.exception.error_code, DiscoveryFailureCode.PROVIDER_LIMIT_SUSPECTED)

    def test_semantic_hash_excludes_operational_history_but_covers_all_structure(self):
        plan = self.create_plan()
        chunk = plan.chunks.get()
        base = [StructuralObservation(chunk.requested_from, True, 10, True, True)]
        hashes = semantic_inventory_hashes(chunk, base)

        self.assertEqual(hashes, semantic_inventory_hashes(chunk, list(base)))
        changes = (
            [
                StructuralObservation(
                    chunk.requested_from + timedelta(weeks=1), True, 10, True, True
                )
            ],
            [StructuralObservation(chunk.requested_from, False, 10, True, True)],
            [StructuralObservation(chunk.requested_from, True, 11, True, True)],
            [StructuralObservation(chunk.requested_from, True, 10, False, True)],
            [StructuralObservation(chunk.requested_from, True, 10, True, False)],
        )
        for changed in changes:
            self.assertNotEqual(hashes[2], semantic_inventory_hashes(chunk, changed)[2])
        operational_one = canonical_hash({"attempt": 1, "provider_request_id": "a", "pk": 1})
        operational_two = canonical_hash({"attempt": 2, "provider_request_id": "b", "pk": 9})
        self.assertNotEqual(operational_one, operational_two)

    def test_database_rejects_queryset_and_raw_sql_mutation_and_truncate(self):
        plan = self.create_plan()

        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalDiscoveryPlan.objects.filter(pk=plan.pk).update(identity="changed")
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE market_historicaldiscoverychunk SET logical_key=%s WHERE plan_id=%s",
                ["0" * 64, plan.pk],
            )
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE market_historicaldiscoverychunk")

    def test_incomplete_or_unauthorized_plan_cannot_be_sealed(self):
        plan = self.create_plan()
        user = get_user_model().objects.create_user("reviewer")

        with self.assertRaises(PermissionDenied):
            approve_and_register_discovery(plan.sha256, user.pk, "a" * 64)
        permission = Permission.objects.get(codename="approve_historical_discovery")
        user.user_permissions.add(permission)
        with self.assertRaisesMessage(DatasetQualityError, "accepted inventory"):
            approve_and_register_discovery(plan.sha256, user.pk, "a" * 64)
        self.assertFalse(HistoricalDiscoveryApproval.objects.exists())
        self.assertFalse(HistoricalDiscoveryRegistration.objects.exists())

        user.user_permissions.add(Permission.objects.get(codename="approve_historical_discovery"))
        user.is_active = False
        user.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            approve_and_register_discovery(plan.sha256, user.pk, "a" * 64)

    def test_approval_registration_and_seal_commit_atomically(self):
        plan = self.create_plan()
        self.run_success(plan)
        user = get_user_model().objects.create_user("approver")
        user.user_permissions.add(Permission.objects.get(codename="approve_historical_discovery"))

        with (
            patch(
                "market.historical_discovery.HistoricalDiscoveryRegistration.objects.create",
                side_effect=DatabaseError("synthetic registration failure"),
            ),
            self.assertRaises(DatabaseError),
        ):
            approve_and_register_discovery(plan.sha256, user.pk, "b" * 64)
        self.assertFalse(HistoricalDiscoveryApproval.objects.exists())
        plan.refresh_from_db()
        self.assertIsNone(plan.sealed_at)

        registration = approve_and_register_discovery(plan.sha256, user.pk, "b" * 64)
        plan.refresh_from_db()
        self.assertIsNotNone(plan.sealed_at)
        self.assertEqual(registration.registered_at, plan.sealed_at)
        self.assertEqual(
            _registration_hashes(plan)[1], registration.global_semantic_inventory_sha256
        )
        with self.assertRaisesMessage(DatasetQualityError, "sealed"):
            begin_discovery_attempt(plan.chunks.get().logical_key)
        inventory = HistoricalTimestampInventory.objects.get()
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalTimestampObservation.objects.create(
                inventory=inventory,
                timestamp=inventory.observations.get().timestamp + timedelta(weeks=1),
                complete=True,
                volume=1,
                bid_present=True,
                ask_present=True,
            )

    @patch("market.management.commands.discover_historical_inventory.OandaClient")
    def test_command_requires_explicit_execute_before_client_creation(self, client):
        with self.assertRaisesMessage(CommandError, "explicit --execute"):
            call_command("discover_historical_inventory", logical_discovery_key="0" * 64)
        client.assert_not_called()

    def test_model_layer_rejects_terminal_evidence_mutation(self):
        plan = self.create_plan()
        self.run_success(plan)
        inventory = HistoricalTimestampInventory.objects.get()
        inventory.observation_count = 2
        with self.assertRaises(ValidationError):
            inventory.save()


class HistoricalDiscoveryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier=SourceRegistry.Tier.ESTABLISHED,
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="concurrency test",
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
        self.plan = create_discovery_plan(build_initial_discovery_plan())

    def test_concurrent_starts_allocate_only_one_next_attempt(self):
        logical_key = (
            self.plan.chunks.order_by("ordinal").values_list("logical_key", flat=True).first()
        )

        def start():
            close_old_connections()
            try:
                return ("created", begin_discovery_attempt(logical_key).attempt_number)
            except DatasetQualityError as error:
                return ("rejected", str(error))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: start(), range(2)))

        self.assertEqual(sum(result[0] == "created" for result in results), 1)
        self.assertEqual(sum(result[0] == "rejected" for result in results), 1)
        self.assertEqual(HistoricalDiscoveryAttempt.objects.count(), 1)
        self.assertEqual(IngestionRun.objects.count(), 1)
