import json
import math
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from market.historical_acquisition import FROZEN_RANGES, INSTRUMENTS
from market.historical_discovery import (
    DISCOVERY_PROVIDER_MAX_CANDLES,
    DiscoveryFailureCode,
    DiscoveryPersistenceError,
    DiscoveryResponseError,
    StructuralObservation,
    _operational_hash,
    _registration_hashes,
    _terminal_event_body,
    _validate_response,
    approve_and_register_discovery,
    begin_discovery_attempt,
    build_initial_discovery_plan,
    build_replacement_discovery_plan,
    canonical_hash,
    create_discovery_plan,
    future_data_contract_semantic_hash,
    logical_discovery_key,
    resolve_stale_discovery_attempt,
    run_discovery_chunk,
    semantic_inventory_hashes,
    supersede_discovery_plan,
)
from market.models import (
    AuditEvent,
    HistoricalDiscoveryApproval,
    HistoricalDiscoveryAttempt,
    HistoricalDiscoveryChunk,
    HistoricalDiscoveryPlan,
    HistoricalDiscoveryProviderEvidence,
    HistoricalDiscoveryRegistration,
    HistoricalDiscoverySupersession,
    HistoricalTimestampInventory,
    HistoricalTimestampObservation,
    IngestionRun,
    Instrument,
    SourceRegistry,
)
from market.oanda import OandaError
from market.quality import expected_candle_timestamps
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

        self.assertEqual(
            payload["plan_sha256"],
            "292556a591024876c7051212d1c6886cd026a097e141295e9b60257fc5402b33",
        )
        self.assertEqual(
            payload["canonical_request_manifest_sha256"],
            "a3cf7ef1f484d2379bfd1ef94769216b2ed9b41635cad7cadbd71a8de251bb2e",
        )

    def test_replacement_plan_uses_wall_clock_bounded_contiguous_h1_ranges(self):
        payload = build_replacement_discovery_plan()
        requests = payload["requests"]
        distribution = Counter(item["canonical_request"]["granularity"] for item in requests)
        h1_start = datetime.fromisoformat(FROZEN_RANGES["H1"]["from"])
        h1_end = datetime.fromisoformat(FROZEN_RANGES["H1"]["to"])
        derived_h1_per_instrument = math.ceil((h1_end - h1_start) / timedelta(hours=4000))

        self.assertEqual(derived_h1_per_instrument, 20)
        self.assertEqual(distribution, {"D": 6, "H1": 120, "W": 6})
        self.assertEqual(len(requests), len(INSTRUMENTS) * (derived_h1_per_instrument + 2))
        self.assertEqual(payload["declared_chunk_count"], len(requests))
        self.assertEqual(
            payload["plan_sha256"],
            "2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a",
        )
        self.assertEqual(
            payload["canonical_request_manifest_sha256"],
            "04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427",
        )
        durations = []
        for instrument in INSTRUMENTS:
            series = [
                item["canonical_request"]
                for item in requests
                if item["canonical_request"]["instrument"] == instrument
                and item["canonical_request"]["granularity"] == "H1"
            ]
            boundaries = [
                (
                    datetime.fromisoformat(item["from"].replace("Z", "+00:00")),
                    datetime.fromisoformat(item["to"].replace("Z", "+00:00")),
                )
                for item in series
            ]
            self.assertEqual(boundaries[0][0], h1_start)
            self.assertEqual(boundaries[-1][1], h1_end)
            self.assertTrue(
                all(left[1] == right[0] for left, right in zip(boundaries, boundaries[1:]))
            )
            for start, end in boundaries:
                duration = (end - start) / timedelta(hours=1)
                durations.append(duration)
                self.assertGreater(duration, 0)
                self.assertLessEqual(duration, 4000)
                provider_specific_unique_hourly_timestamps = {
                    start + timedelta(hours=offset) for offset in range(math.ceil(duration))
                }
                self.assertLessEqual(len(provider_specific_unique_hourly_timestamps), 4000)
        self.assertEqual((min(durations), max(durations)), (2901, 4000))

        for granularity in ("D", "W"):
            expected_range = FROZEN_RANGES[granularity]
            series = [
                item["canonical_request"]
                for item in requests
                if item["canonical_request"]["granularity"] == granularity
            ]
            self.assertEqual(len(series), len(INSTRUMENTS))
            self.assertTrue(
                all(
                    item["from"]
                    == datetime.fromisoformat(expected_range["from"])
                    .isoformat()
                    .replace("+00:00", "Z")
                    and item["to"]
                    == datetime.fromisoformat(expected_range["to"])
                    .isoformat()
                    .replace("+00:00", "Z")
                    for item in series
                )
            )

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

    def single_request_payload(self, version="phase-2b1r-discovery-v2", request_index=0):
        payload = build_initial_discovery_plan()
        request = dict(payload["requests"][request_index])
        request["ordinal"] = 1
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

    def create_supersession(self):
        superseded = create_discovery_plan(self.single_request_payload("phase-2b1r-discovery-v1"))
        chunk = superseded.chunks.select_related("instrument").get()
        with self.assertRaises(OandaError):
            run_discovery_chunk(
                chunk.logical_key,
                FailingInventoryClient(chunk.canonical_request_sha256),
            )
        attempt = HistoricalDiscoveryAttempt.objects.get(chunk=chunk)
        replacement = create_discovery_plan(build_replacement_discovery_plan())
        supersession = supersede_discovery_plan(
            superseded.sha256,
            replacement.sha256,
            attempt.pk,
        )
        return superseded, replacement, attempt, supersession

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

    def test_allowlisted_http_limit_is_recorded_as_stable_limit_failure(self):
        plan = self.create_plan()
        chunk = plan.chunks.select_related("instrument").get()

        class LimitClient:
            def fetch_historical_inventory(inner_self, *args):
                raise OandaError(
                    "bounded provider limit response",
                    failure_kind="limit",
                    provider_evidence={
                        "endpoint_identity": (
                            "oanda-v20-practice:GET:/v3/instruments/"
                            f"{chunk.instrument.code}/candles"
                        ),
                        "http_method": "GET",
                        "oanda_environment": "practice",
                        "http_status": 400,
                        "provider_request_id": "provider-limit-request",
                        "canonical_request_sha256": chunk.canonical_request_sha256,
                    },
                )

        with self.assertRaises(OandaError):
            run_discovery_chunk(chunk.logical_key, LimitClient())

        attempt = HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").get()
        self.assertEqual(
            attempt.ingestion_run.failure_reason,
            DiscoveryFailureCode.PROVIDER_LIMIT_SUSPECTED,
        )
        event = AuditEvent.objects.get(event_type="market.historical_discovery_failed")
        self.assertEqual(event.payload["stage"], "response_validation")
        self.assertEqual(event.payload["diagnostics"], {"observation_count": 0})
        serialized = json.dumps(event.payload, sort_keys=True).lower()
        self.assertNotIn("body", serialized)
        self.assertNotIn("authorization", serialized)
        self.assertFalse(HistoricalTimestampInventory.objects.exists())

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

    def assert_persistence_failure(self, component, target, method):
        plan = create_discovery_plan(
            self.single_request_payload(f"phase-2b1r-discovery-v{10 + len(component)}")
        )
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
        original = getattr(target, method)
        calls = 0

        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise DatabaseError("synthetic persistence failure")
            return original(*args, **kwargs)

        with (
            patch.object(target, method, side_effect=fail_once),
            self.assertRaises(DiscoveryPersistenceError),
        ):
            run_discovery_chunk(chunk.logical_key, client)

        attempt = HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").get()
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertEqual(
            attempt.ingestion_run.failure_reason, DiscoveryFailureCode.PERSISTENCE_FAILED
        )
        self.assertFalse(HistoricalTimestampInventory.objects.exists())
        event = AuditEvent.objects.get(event_type="market.historical_discovery_failed")
        self.assertEqual(event.payload["diagnostics"], {"component": component})

    def test_inventory_persistence_failure_records_terminal_failure(self):
        self.assert_persistence_failure("inventory", HistoricalTimestampInventory.objects, "create")

    def test_observation_persistence_failure_records_terminal_failure(self):
        self.assert_persistence_failure(
            "observations", HistoricalTimestampObservation.objects, "bulk_create"
        )

    def test_provider_evidence_persistence_failure_records_terminal_failure(self):
        self.assert_persistence_failure(
            "provider_evidence", HistoricalDiscoveryProviderEvidence.objects, "create"
        )

    def test_audit_persistence_failure_records_terminal_failure(self):
        self.assert_persistence_failure("audit_event", AuditEvent.objects, "create")

    def test_deferred_reconstruction_failure_records_terminal_failure(self):
        plan = create_discovery_plan(self.single_request_payload("phase-2b1r-discovery-v32"))
        chunk = plan.chunks.select_related("instrument").get()
        client = type(
            "SuccessfulInventoryClient",
            (),
            {
                "fetch_historical_inventory": lambda *_: (
                    [StructuralObservation(chunk.requested_from, True, 10, True, True)],
                    self.evidence_for(chunk),
                )
            },
        )()

        with (
            patch(
                "market.historical_discovery.semantic_inventory_hashes",
                return_value=("0" * 64, "1" * 64, "2" * 64),
            ),
            self.assertRaises(DiscoveryPersistenceError) as raised,
        ):
            run_discovery_chunk(chunk.logical_key, client)

        self.assertEqual(raised.exception.component, "database_constraints")
        attempt = HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").get()
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertEqual(
            attempt.ingestion_run.failure_reason, DiscoveryFailureCode.PERSISTENCE_FAILED
        )
        self.assertFalse(HistoricalTimestampInventory.objects.exists())
        event = AuditEvent.objects.get(event_type="market.historical_discovery_failed")
        self.assertEqual(event.payload["diagnostics"], {"component": "database_constraints"})

    def test_failure_evidence_error_leaves_attempt_for_stale_resolution(self):
        plan = create_discovery_plan(self.single_request_payload("phase-2b1r-discovery-v30"))
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
                HistoricalTimestampInventory.objects,
                "create",
                side_effect=DatabaseError("inventory unavailable"),
            ),
            patch.object(
                HistoricalDiscoveryProviderEvidence.objects,
                "create",
                side_effect=DatabaseError("failure evidence unavailable"),
            ),
            self.assertRaises(DiscoveryPersistenceError),
        ):
            run_discovery_chunk(chunk.logical_key, client)

        attempt = HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").get()
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.RUNNING)
        self.assertFalse(AuditEvent.objects.exists())

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

    def test_structural_failure_terminal_audit_reconstructs(self):
        plan = self.create_plan()
        chunk = plan.chunks.select_related("instrument").get()
        observation = StructuralObservation(chunk.requested_from, True, 1, True, True)
        client = type(
            "DuplicateInventoryClient",
            (),
            {
                "fetch_historical_inventory": lambda *_: (
                    [observation, observation],
                    self.evidence_for(chunk),
                )
            },
        )()

        with self.assertRaises(DiscoveryResponseError):
            run_discovery_chunk(chunk.logical_key, client)

        event = AuditEvent.objects.get(event_type="market.historical_discovery_failed")
        self.assertEqual(event.payload["error_code"], DiscoveryFailureCode.STRUCTURE_INVALID)

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

    def test_database_permanently_rejects_duplicate_and_forged_terminal_audit(self):
        plan = self.create_plan()
        attempt = self.run_success(plan)
        event = AuditEvent.objects.get(subject_id=str(attempt.pk))

        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO market_auditevent
                   (occurred_at,event_type,actor,subject_type,subject_id,payload)
                   VALUES (now(),%s,%s,%s,%s,%s::jsonb)""",
                [
                    event.event_type,
                    event.actor,
                    event.subject_type,
                    event.subject_id,
                    json.dumps(event.payload),
                ],
            )
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE market_auditevent SET payload=%s::jsonb WHERE id=%s",
                [json.dumps({"raw_url": "https://forbidden.invalid"}), event.pk],
            )
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE market_auditevent")

    def test_database_rejects_noncanonical_terminal_audit_json(self):
        plan = self.create_plan()
        attempt = begin_discovery_attempt(plan.chunks.get().logical_key)
        run = attempt.ingestion_run
        occurred_at = timezone.now()
        evidence = {
            "canonical_request_sha256": attempt.chunk.canonical_request_sha256,
            "endpoint_identity": (
                f"oanda-v20-practice:GET:/v3/instruments/{attempt.chunk.instrument.code}/candles"
            ),
            "environment": "practice",
            "http_method": "GET",
            "http_status": 500,
            "provider_request_id": "request-id",
            "unavailable_fields": [],
        }
        event_body = _terminal_event_body(
            attempt,
            code=DiscoveryFailureCode.PROVIDER_HTTP_ERROR,
            stage="provider_request",
            evidence=evidence,
            diagnostics={},
            occurred_at=occurred_at,
        )
        malformed_bodies = []
        for key in ("schema_version", "attempt_number"):
            malformed = dict(event_body)
            malformed[key] = str(malformed[key])
            malformed_bodies.append(malformed)
        missing = dict(event_body)
        missing["unexpected"] = missing.pop("instrument")
        malformed_bodies.append(missing)
        substituted = dict(event_body)
        substituted["granularity"] = "H1"
        malformed_bodies.append(substituted)

        for malformed_body in malformed_bodies:
            with self.subTest(payload=malformed_body):
                event_hash = canonical_hash(malformed_body)
                run.status = IngestionRun.Status.FAILED
                run.failure_reason = DiscoveryFailureCode.PROVIDER_HTTP_ERROR
                run.finished_at = occurred_at
                with self.assertRaises(DatabaseError), transaction.atomic():
                    run.save()
                    operational_hash = _operational_hash(attempt, run, evidence, event_hash)
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """INSERT INTO market_historicaldiscoveryproviderevidence
                               (attempt_id,endpoint_identity,http_method,environment,http_status,
                                provider_request_id,canonical_request_sha256,unavailable_fields,
                                terminal_event_sha256,operational_evidence_sha256,created_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,now())""",
                            [
                                attempt.pk,
                                evidence["endpoint_identity"],
                                evidence["http_method"],
                                evidence["environment"],
                                evidence["http_status"],
                                evidence["provider_request_id"],
                                evidence["canonical_request_sha256"],
                                json.dumps(evidence["unavailable_fields"]),
                                event_hash,
                                operational_hash,
                            ],
                        )
                        cursor.execute(
                            """INSERT INTO market_auditevent
                               (occurred_at,event_type,actor,subject_type,subject_id,payload)
                               VALUES (now(),%s,%s,%s,%s,%s::jsonb)""",
                            [
                                "market.historical_discovery_failed",
                                "market.historical_discovery.run_discovery_chunk",
                                "HistoricalDiscoveryAttempt",
                                str(attempt.pk),
                                json.dumps({**malformed_body, "event_sha256": event_hash}),
                            ],
                        )

    def test_database_rejects_unsafe_raw_sql_provider_evidence(self):
        plan = self.create_plan()
        attempt = begin_discovery_attempt(plan.chunks.get().logical_key)
        run = attempt.ingestion_run
        occurred_at = timezone.now()
        evidence = {
            "canonical_request_sha256": attempt.chunk.canonical_request_sha256,
            "endpoint_identity": (
                f"oanda-v20-practice:GET:/v3/instruments/{attempt.chunk.instrument.code}/candles"
            ),
            "environment": "practice",
            "http_method": "GET",
            "http_status": 500,
            "provider_request_id": "https://unsafe.invalid/secret",
            "unavailable_fields": [],
        }
        event_body = _terminal_event_body(
            attempt,
            code=DiscoveryFailureCode.PROVIDER_HTTP_ERROR,
            stage="provider_request",
            evidence=evidence,
            diagnostics={},
            occurred_at=occurred_at,
        )
        event_hash = canonical_hash(event_body)
        run.status = IngestionRun.Status.FAILED
        run.failure_reason = DiscoveryFailureCode.PROVIDER_HTTP_ERROR
        run.finished_at = occurred_at

        with self.assertRaises(DatabaseError), transaction.atomic():
            run.save()
            operational_hash = _operational_hash(attempt, run, evidence, event_hash)
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO market_historicaldiscoveryproviderevidence
                       (attempt_id,endpoint_identity,http_method,environment,http_status,
                        provider_request_id,canonical_request_sha256,unavailable_fields,
                        terminal_event_sha256,operational_evidence_sha256,created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,now())""",
                    [
                        attempt.pk,
                        evidence["endpoint_identity"],
                        evidence["http_method"],
                        evidence["environment"],
                        evidence["http_status"],
                        evidence["provider_request_id"],
                        evidence["canonical_request_sha256"],
                        json.dumps(evidence["unavailable_fields"]),
                        event_hash,
                        operational_hash,
                    ],
                )
                cursor.execute(
                    """INSERT INTO market_auditevent
                       (occurred_at,event_type,actor,subject_type,subject_id,payload)
                       VALUES (now(),%s,%s,%s,%s,%s::jsonb)""",
                    [
                        "market.historical_discovery_failed",
                        "market.historical_discovery.run_discovery_chunk",
                        "HistoricalDiscoveryAttempt",
                        str(attempt.pk),
                        json.dumps({**event_body, "event_sha256": event_hash}),
                    ],
                )
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_4999_observations_reconstruct_once_with_bounded_runtime(self):
        payload = build_initial_discovery_plan()
        h1_index = next(
            index
            for index, request in enumerate(payload["requests"])
            if request["canonical_request"]["granularity"] == "H1"
        )
        plan = create_discovery_plan(
            self.single_request_payload("phase-2b1r-discovery-v31", h1_index)
        )
        chunk = plan.chunks.select_related("instrument").get()
        timestamps = expected_candle_timestamps(
            chunk.requested_from, chunk.requested_to, chunk.granularity
        )
        self.assertEqual(len(timestamps), 4999)
        observations = [StructuralObservation(item, True, 1, True, True) for item in timestamps]
        client = type(
            "LargeInventoryClient",
            (),
            {
                "fetch_historical_inventory": lambda *_: (
                    observations,
                    self.evidence_for(chunk),
                )
            },
        )()

        started = time.monotonic()
        run_discovery_chunk(chunk.logical_key, client)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS market_discovery_inventory_reconstruct IMMEDIATE")
            cursor.execute(
                """SELECT count(*) FROM pg_trigger
                   WHERE tgrelid='market_historicaltimestampobservation'::regclass
                     AND tgname='market_discovery_observation_reconstruct'"""
            )
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(HistoricalTimestampObservation.objects.count(), 4999)

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
        self.assertEqual(registration.approval.payload["cross_series_report_sha256"], "b" * 64)
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

    def test_database_rejects_forged_approval_payload_and_hash(self):
        plan = self.create_plan()
        self.run_success(plan)
        user = get_user_model().objects.create_user("approval-forger")
        user.user_permissions.add(Permission.objects.get(codename="approve_historical_discovery"))
        original = HistoricalDiscoveryApproval.objects.create

        def forged_create(**kwargs):
            kwargs["payload"] = {**kwargs["payload"], "raw_url": "https://forbidden.invalid"}
            kwargs["sha256"] = "f" * 64
            return original(**kwargs)

        with (
            patch.object(HistoricalDiscoveryApproval.objects, "create", side_effect=forged_create),
            self.assertRaises(DatabaseError),
        ):
            approve_and_register_discovery(plan.sha256, user.pk, "c" * 64)
        self.assertFalse(HistoricalDiscoveryApproval.objects.exists())
        self.assertFalse(HistoricalDiscoveryRegistration.objects.exists())

    def test_database_rejects_forged_registration_payload_and_hash(self):
        plan = self.create_plan()
        self.run_success(plan)
        user = get_user_model().objects.create_user("registration-forger")
        user.user_permissions.add(Permission.objects.get(codename="approve_historical_discovery"))
        original = HistoricalDiscoveryRegistration.objects.create

        def forged_create(**kwargs):
            kwargs["payload"] = {**kwargs["payload"], "body": "forbidden"}
            kwargs["report_sha256"] = "f" * 64
            return original(**kwargs)

        with (
            patch.object(
                HistoricalDiscoveryRegistration.objects, "create", side_effect=forged_create
            ),
            self.assertRaises(DatabaseError),
        ):
            approve_and_register_discovery(plan.sha256, user.pk, "d" * 64)
        self.assertFalse(HistoricalDiscoveryApproval.objects.exists())
        self.assertFalse(HistoricalDiscoveryRegistration.objects.exists())

    def test_supersession_preserves_v1_evidence_and_blocks_all_old_plan_writes(self):
        superseded = create_discovery_plan(self.single_request_payload("phase-2b1r-discovery-v1"))
        chunk = superseded.chunks.select_related("instrument").get()
        with self.assertRaises(OandaError):
            run_discovery_chunk(
                chunk.logical_key,
                FailingInventoryClient(chunk.canonical_request_sha256),
            )
        attempt = HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").get(
            chunk=chunk
        )
        evidence = HistoricalDiscoveryProviderEvidence.objects.get(attempt=attempt)
        event = AuditEvent.objects.get(subject_id=str(attempt.pk))
        immutable_snapshot = {
            "plan": HistoricalDiscoveryPlan.objects.filter(pk=superseded.pk).values().get(),
            "chunks": list(superseded.chunks.order_by("ordinal").values()),
            "attempt": HistoricalDiscoveryAttempt.objects.filter(pk=attempt.pk).values().get(),
            "run": IngestionRun.objects.filter(pk=attempt.ingestion_run_id).values().get(),
            "evidence": HistoricalDiscoveryProviderEvidence.objects.filter(pk=evidence.pk)
            .values()
            .get(),
            "event": AuditEvent.objects.filter(pk=event.pk).values().get(),
        }
        replacement = create_discovery_plan(build_replacement_discovery_plan())
        supersession = supersede_discovery_plan(
            superseded.sha256,
            replacement.sha256,
            attempt.pk,
        )

        self.assertEqual(supersession.governing_attempt_id, attempt.pk)
        self.assertEqual(
            supersession.payload["governing_failure_code"],
            run_failure := "DISCOVERY_PROVIDER_HTTP_ERROR",
        )
        self.assertEqual(attempt.ingestion_run.failure_reason, run_failure)
        self.assertEqual(
            immutable_snapshot,
            {
                "plan": HistoricalDiscoveryPlan.objects.filter(pk=superseded.pk).values().get(),
                "chunks": list(superseded.chunks.order_by("ordinal").values()),
                "attempt": HistoricalDiscoveryAttempt.objects.filter(pk=attempt.pk).values().get(),
                "run": IngestionRun.objects.filter(pk=attempt.ingestion_run_id).values().get(),
                "evidence": HistoricalDiscoveryProviderEvidence.objects.filter(pk=evidence.pk)
                .values()
                .get(),
                "event": AuditEvent.objects.filter(pk=event.pk).values().get(),
            },
        )
        with self.assertRaisesMessage(DatasetQualityError, "superseded"):
            begin_discovery_attempt(chunk.logical_key)
        user = get_user_model().objects.create_user("superseded-approver")
        user.user_permissions.add(Permission.objects.get(codename="approve_historical_discovery"))
        with self.assertRaisesMessage(DatasetQualityError, "superseded"):
            approve_and_register_discovery(superseded.sha256, user.pk, "a" * 64)
        with (
            self.assertRaisesMessage(DatabaseError, "superseded discovery plans"),
            transaction.atomic(),
        ):
            HistoricalDiscoveryPlan.objects.filter(pk=superseded.pk).update(
                sealed_at=timezone.now()
            )
        with (
            self.assertRaisesMessage(DatabaseError, "superseded discovery plans"),
            transaction.atomic(),
        ):
            HistoricalDiscoveryChunk.objects.bulk_create(
                [
                    HistoricalDiscoveryChunk(
                        plan=superseded,
                        ordinal=1,
                        instrument=chunk.instrument,
                        granularity=chunk.granularity,
                        requested_from=chunk.requested_from,
                        requested_to=chunk.requested_to,
                        canonical_request=chunk.canonical_request,
                        canonical_request_sha256=chunk.canonical_request_sha256,
                        logical_key="f" * 64,
                    )
                ]
            )
        with (
            self.assertRaisesMessage(DatabaseError, "superseded discovery plans"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryattempt
                   (chunk_id,ingestion_run_id,attempt_number,idempotency_key,created_at)
                   VALUES (%s,999999,2,%s,now())""",
                [chunk.pk, "historical-discovery-attempt:forbidden:2"],
            )
        with (
            self.assertRaisesMessage(DatabaseError, "superseded discovery plans"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [superseded.pk, user.pk, "a" * 64, "b" * 64, "c" * 64],
            )
        with (
            self.assertRaisesMessage(DatabaseError, "superseded discovery plans"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryregistration
                   (plan_id,approval_id,ordered_chunk_manifest_sha256,
                    global_semantic_inventory_sha256,accepted_operational_evidence_set_sha256,
                    cross_series_report_sha256,payload,report_sha256,registered_at)
                   VALUES (%s,999999,%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [superseded.pk, "a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64],
            )

    def test_supersession_is_immutable_and_rejects_self_cycles_and_version_regression(self):
        superseded, replacement, attempt, supersession = self.create_supersession()

        supersession.reason_code = "CHANGED"
        with self.assertRaises(ValidationError):
            supersession.save()
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalDiscoverySupersession.objects.filter(pk=supersession.pk).update(
                reason_code="CHANGED"
            )
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM market_historicaldiscoverysupersession WHERE id=%s",
                [supersession.pk],
            )
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE market_historicaldiscoverysupersession")
        with self.assertRaises(DatasetQualityError):
            supersede_discovery_plan(superseded.sha256, superseded.sha256, attempt.pk)

        for old_id, new_id in (
            (superseded.pk, superseded.pk),
            (replacement.pk, superseded.pk),
        ):
            with (
                self.subTest(old_id=old_id, new_id=new_id),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    """INSERT INTO market_historicaldiscoverysupersession
                       (superseded_plan_id,replacement_plan_id,governing_attempt_id,reason_code,
                        superseded_plan_sha256,replacement_plan_sha256,
                        governing_terminal_event_sha256,
                        governing_operational_evidence_sha256,payload,sha256,created_at)
                       VALUES (%s,%s,%s,'PROVIDER_REQUEST_BOUND_UNSAFE',%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                    [
                        old_id,
                        new_id,
                        attempt.pk,
                        "a" * 64,
                        "b" * 64,
                        "c" * 64,
                        "d" * 64,
                        "e" * 64,
                    ],
                )

    def test_database_rejects_supersession_to_noncanonical_v2_layout(self):
        superseded = create_discovery_plan(self.single_request_payload("phase-2b1r-discovery-v1"))
        chunk = superseded.chunks.select_related("instrument").get()
        with self.assertRaises(OandaError):
            run_discovery_chunk(
                chunk.logical_key,
                FailingInventoryClient(chunk.canonical_request_sha256),
            )
        attempt = HistoricalDiscoveryAttempt.objects.get(chunk=chunk)
        incomplete_v2 = create_discovery_plan(
            self.single_request_payload("phase-2b1r-discovery-v2")
        )

        with self.assertRaisesMessage(DatabaseError, "supersession lineage is invalid"):
            supersede_discovery_plan(
                superseded.sha256,
                incomplete_v2.sha256,
                attempt.pk,
            )
        self.assertFalse(HistoricalDiscoverySupersession.objects.exists())

    @patch("market.management.commands.discover_historical_inventory.OandaClient")
    def test_command_requires_explicit_execute_before_client_creation(self, client):
        with self.assertRaisesMessage(CommandError, "explicit --execute"):
            call_command("discover_historical_inventory", logical_discovery_key="0" * 64)
        client.assert_not_called()

    @override_settings(
        OANDA_ENVIRONMENT="live",
        OANDA_DISCOVERY_TOKEN="dedicated-test-value",
        OANDA_TOKEN="generic-value",
    )
    @patch("market.management.commands.discover_historical_inventory.OandaClient")
    def test_command_rejects_live_environment_before_client_creation(self, client):
        with self.assertRaisesMessage(CommandError, "practice environment"):
            call_command(
                "discover_historical_inventory",
                logical_discovery_key="0" * 64,
                execute=True,
            )
        client.assert_not_called()

    @override_settings(
        OANDA_ENVIRONMENT="practice",
        OANDA_DISCOVERY_TOKEN="",
        OANDA_TOKEN="generic-production-value",
    )
    @patch("market.management.commands.discover_historical_inventory.OandaClient")
    def test_command_rejects_generic_token_without_dedicated_test_credential(self, client):
        with self.assertRaisesMessage(CommandError, "OANDA_API_KEY_TEST"):
            call_command(
                "discover_historical_inventory",
                logical_discovery_key="0" * 64,
                execute=True,
            )
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


class ReplacementDiscoveryPortabilityTests(TransactionTestCase):
    def test_displaced_primary_keys_do_not_change_v2_identities(self):
        SourceRegistry.objects.create(
            name="unrelated source",
            tier=SourceRegistry.Tier.CONTEXTUAL,
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test",
            enabled=False,
        )
        Instrument.objects.create(
            code="NZD_USD",
            base_currency="NZD",
            quote_currency="USD",
            display_order=1,
            active=False,
        )
        source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier=SourceRegistry.Tier.ESTABLISHED,
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="portability test",
            enabled=True,
        )
        for order, code in enumerate(INSTRUMENTS, 2):
            base, quote = code.split("_")
            Instrument.objects.create(
                code=code,
                base_currency=base,
                quote_currency=quote,
                display_order=order,
                active=True,
            )

        payload = build_replacement_discovery_plan()
        plan = create_discovery_plan(payload)

        self.assertGreater(source.pk, 1)
        self.assertGreater(plan.chunks.order_by("instrument_id").first().instrument_id, 1)
        self.assertEqual(
            plan.sha256,
            "2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a",
        )
        self.assertEqual(
            plan.canonical_request_manifest_sha256,
            "04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427",
        )
        serialized = json.dumps(plan.payload, sort_keys=True)
        self.assertNotIn("source_id", serialized)
        self.assertNotIn("instrument_id", serialized)
