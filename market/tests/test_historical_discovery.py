import json
import math
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from market.historical_acquisition import FROZEN_RANGES, INSTRUMENTS
from market.historical_discovery import (
    DISCOVERY_PROVIDER_MAX_CANDLES,
    DISCOVERY_PURPOSE,
    GOVERNING_CANARY_LOGICAL_KEY,
    GOVERNING_CANARY_REQUEST_SHA256,
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

    def test_report_command_renders_both_plan_versions_without_database_access(self):
        for arguments, expected_identity, expected_sha in (
            ((), "failed-break-phase-2b1r-discovery-plan-v1", None),
            (
                ("--plan-version", "v1"),
                "failed-break-phase-2b1r-discovery-plan-v1",
                "292556a591024876c7051212d1c6886cd026a097e141295e9b60257fc5402b33",
            ),
            (
                ("--plan-version", "v2"),
                "failed-break-phase-2b1r-discovery-plan-v2",
                "2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a",
            ),
        ):
            with self.subTest(arguments=arguments):
                stdout = StringIO()
                call_command("report_provider_observed_discovery_plan", *arguments, stdout=stdout)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["identity"], expected_identity)
                if expected_sha is not None:
                    self.assertEqual(payload["plan_sha256"], expected_sha)

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

    def create_failed_canary_plan(self):
        superseded = create_discovery_plan(build_initial_discovery_plan())
        chunk = superseded.chunks.select_related("instrument").get(
            logical_key=GOVERNING_CANARY_LOGICAL_KEY
        )
        with self.assertRaises(OandaError):
            run_discovery_chunk(
                chunk.logical_key,
                FailingInventoryClient(chunk.canonical_request_sha256),
            )
        return superseded, chunk, HistoricalDiscoveryAttempt.objects.get(chunk=chunk)

    def create_supersession(self):
        superseded, _, attempt = self.create_failed_canary_plan()
        replacement = create_discovery_plan(build_replacement_discovery_plan())
        supersession = supersede_discovery_plan(
            superseded.sha256,
            replacement.sha256,
            attempt.pk,
        )
        return superseded, replacement, attempt, supersession

    def test_replacement_plan_attempts_await_activation_after_supersession(self):
        _, replacement, _, _ = self.create_supersession()
        chunk = replacement.chunks.order_by("ordinal").first()

        with self.assertRaisesMessage(
            DatasetQualityError,
            "replacement canary activation rejects this attempt",
        ):
            begin_discovery_attempt(chunk.logical_key)
        self.assertFalse(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=replacement).exists()
        )

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

    def test_generic_plans_can_never_be_sealed_under_gate5(self):
        plan = self.create_plan()
        user = get_user_model().objects.create_user("reviewer")

        with self.assertRaisesMessage(
            DatasetQualityError, "only the approved replacement discovery plan may be approved"
        ):
            approve_and_register_discovery(plan.sha256, user.pk, "a" * 64)
        permission = Permission.objects.get(codename="approve_historical_discovery")
        user.user_permissions.add(permission)
        self.run_success(plan)
        with self.assertRaisesMessage(
            DatasetQualityError, "only the approved replacement discovery plan may be approved"
        ):
            approve_and_register_discovery(plan.sha256, user.pk, "a" * 64)
        self.assertFalse(HistoricalDiscoveryApproval.objects.exists())
        self.assertFalse(HistoricalDiscoveryRegistration.objects.exists())
        plan.refresh_from_db()
        self.assertIsNone(plan.sealed_at)

    def test_database_rejects_raw_full_seal_bypass_of_generic_plan(self):
        plan = self.create_plan()
        self.run_success(plan)
        user = get_user_model().objects.create_user("seal-forger")
        user.user_permissions.add(Permission.objects.get(codename="approve_historical_discovery"))
        chunk_hash, semantic_hash, operational_hash = _registration_hashes(plan)
        with (
            self.assertRaisesMessage(
                DatabaseError,
                "only the approved replacement discovery plan may be approved",
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now()) RETURNING id""",
                [plan.pk, user.pk, semantic_hash, operational_hash, "c" * 64],
            )
            approval_id = cursor.fetchone()[0]
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryregistration
                   (plan_id,approval_id,ordered_chunk_manifest_sha256,
                    global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,cross_series_report_sha256,
                    payload,report_sha256,registered_at)
                   VALUES (%s,%s,%s,%s,%s,%s,'{}'::jsonb,%s,now()) RETURNING registered_at""",
                [
                    plan.pk,
                    approval_id,
                    chunk_hash,
                    semantic_hash,
                    operational_hash,
                    "d" * 64,
                    "e" * 64,
                ],
            )
            registered_at = cursor.fetchone()[0]
            cursor.execute(
                "UPDATE market_historicaldiscoveryplan SET sealed_at=%s WHERE id=%s",
                [registered_at, plan.pk],
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        self.assertFalse(HistoricalDiscoveryApproval.objects.exists())
        self.assertFalse(HistoricalDiscoveryRegistration.objects.exists())
        plan.refresh_from_db()
        self.assertIsNone(plan.sealed_at)

    def test_database_rejects_raw_partial_approval_of_generic_plan(self):
        plan = self.create_plan()
        self.run_success(plan)
        user = get_user_model().objects.create_user("approval-forger")
        with (
            self.assertRaisesMessage(
                DatabaseError,
                "only the approved replacement discovery plan may be approved",
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [plan.pk, user.pk, "a" * 64, "b" * 64, "c" * 64],
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        self.assertFalse(HistoricalDiscoveryApproval.objects.exists())
        self.assertFalse(HistoricalDiscoveryRegistration.objects.exists())

    def test_supersession_preserves_v1_evidence_and_blocks_all_old_plan_writes(self):
        superseded, chunk, attempt = self.create_failed_canary_plan()
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

    def self_consistent_variant_payload(self, *, version, identity, mutate_requests=None):
        base = build_replacement_discovery_plan()
        requests = [
            dict(item, canonical_request=dict(item["canonical_request"]))
            for item in base["requests"]
        ]
        if mutate_requests:
            requests = mutate_requests(requests)
        rebuilt = []
        for ordinal, item in enumerate(requests, 1):
            request = item["canonical_request"]
            start = datetime.fromisoformat(request["from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(request["to"].replace("Z", "+00:00"))
            request_sha = canonical_hash(request)
            rebuilt.append(
                {
                    "ordinal": ordinal,
                    "logical_discovery_key": logical_discovery_key(
                        request_sha256=request_sha,
                        instrument=request["instrument"],
                        granularity=request["granularity"],
                        requested_from=start,
                        requested_to=end,
                        discovery_version=version,
                    ),
                    "canonical_request": request,
                    "canonical_request_sha256": request_sha,
                }
            )
        body = {
            key: value
            for key, value in base.items()
            if key not in {"requests", "plan_sha256", "canonical_request_manifest_sha256"}
        }
        body.update(
            discovery_version=version,
            identity=identity,
            declared_chunk_count=len(rebuilt),
            requests=rebuilt,
            canonical_request_manifest_sha256=canonical_hash(rebuilt),
        )
        return {**body, "plan_sha256": canonical_hash(body)}

    def raw_insert_plan(self, payload):
        body = {key: value for key, value in payload.items() if key != "plan_sha256"}
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryplan
                   (identity,version,source_id,purpose,environment,phase1_spec_hash,
                    phase1_manifest_hash,superseded_data_identity,declared_chunk_count,
                    canonical_request_manifest,canonical_request_manifest_sha256,payload,
                    sha256,sealed_at,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,NULL,now())
                   RETURNING id""",
                [
                    body["identity"],
                    body["discovery_version"],
                    self.source.pk,
                    body["purpose"],
                    body["environment"],
                    body["phase1_spec_hash"],
                    body["phase1_manifest_hash"],
                    body["superseded_data_identity"],
                    body["declared_chunk_count"],
                    json.dumps(body["requests"]),
                    body["canonical_request_manifest_sha256"],
                    json.dumps(body),
                    payload["plan_sha256"],
                ],
            )
            return cursor.fetchone()[0]

    def raw_supersession_row(self, superseded, replacement, attempt, overrides=None):
        evidence = HistoricalDiscoveryProviderEvidence.objects.get(attempt=attempt)
        run = attempt.ingestion_run
        event = AuditEvent.objects.get(
            subject_type="HistoricalDiscoveryAttempt",
            subject_id=str(attempt.pk),
            event_type="market.historical_discovery_failed",
        )
        payload = {
            "identity": "historical-discovery-supersession-v1",
            "reason_code": "PROVIDER_REQUEST_BOUND_UNSAFE",
            "superseded_plan_sha256": superseded["sha256"],
            "superseded_request_manifest_sha256": superseded["manifest_sha256"],
            "replacement_plan_sha256": replacement["sha256"],
            "replacement_request_manifest_sha256": replacement["manifest_sha256"],
            "governing_attempt_idempotency_key": attempt.idempotency_key,
            "governing_run_request_manifest_hash": run.request_manifest_hash,
            "governing_failure_code": run.failure_reason,
            "governing_terminal_event_sha256": evidence.terminal_event_sha256,
            "governing_operational_evidence_sha256": evidence.operational_evidence_sha256,
            "governing_audit_event_sha256": event.payload["event_sha256"],
        }
        row = {
            "superseded_plan_id": superseded["id"],
            "replacement_plan_id": replacement["id"],
            "governing_attempt_id": attempt.pk,
            "reason_code": "PROVIDER_REQUEST_BOUND_UNSAFE",
            "superseded_plan_sha256": superseded["sha256"],
            "replacement_plan_sha256": replacement["sha256"],
            "governing_terminal_event_sha256": evidence.terminal_event_sha256,
            "governing_operational_evidence_sha256": evidence.operational_evidence_sha256,
            "payload": payload,
        }
        row.update(overrides or {})
        row["sha256"] = canonical_hash(row["payload"])
        return row

    def raw_supersede(self, row):
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO market_historicaldiscoverysupersession
                   (superseded_plan_id,replacement_plan_id,governing_attempt_id,reason_code,
                    superseded_plan_sha256,replacement_plan_sha256,
                    governing_terminal_event_sha256,governing_operational_evidence_sha256,
                    payload,sha256,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,now())""",
                [
                    row["superseded_plan_id"],
                    row["replacement_plan_id"],
                    row["governing_attempt_id"],
                    row["reason_code"],
                    row["superseded_plan_sha256"],
                    row["replacement_plan_sha256"],
                    row["governing_terminal_event_sha256"],
                    row["governing_operational_evidence_sha256"],
                    json.dumps(row["payload"]),
                    row["sha256"],
                ],
            )

    def test_supersession_rejects_non_pinned_replacement_plans(self):
        superseded, _, attempt = self.create_failed_canary_plan()
        incomplete_v2 = create_discovery_plan(
            self.single_request_payload("phase-2b1r-discovery-v2")
        )

        with self.assertRaisesMessage(DatasetQualityError, "supersession lineage is invalid"):
            supersede_discovery_plan(superseded.sha256, incomplete_v2.sha256, attempt.pk)
        self.assertFalse(HistoricalDiscoverySupersession.objects.exists())

    def test_supersession_rejects_variant_plans_in_service_and_database(self):
        superseded, _, attempt = self.create_failed_canary_plan()
        superseded_ref = {
            "id": superseded.pk,
            "sha256": superseded.sha256,
            "manifest_sha256": superseded.canonical_request_manifest_sha256,
        }
        pinned_identity = "failed-break-phase-2b1r-discovery-plan-v2"

        def shift_first_h1(requests):
            for item in requests:
                request = item["canonical_request"]
                if request["granularity"] == "H1" and request["instrument"] == "AUD_USD":
                    end = datetime.fromisoformat(request["to"].replace("Z", "+00:00"))
                    request["to"] = (end + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
                    break
            return requests

        def drop_last_chunk(requests):
            return requests[:-1]

        def duplicate_last_chunk(requests):
            return [*requests, dict(requests[-1])]

        def swap_instrument(requests):
            for item in requests:
                if item["canonical_request"]["instrument"] == "AUD_USD":
                    item["canonical_request"]["instrument"] = "NZD_USD"
            return requests

        variants = (
            (
                "v3-plan",
                "phase-2b1r-discovery-v3",
                "failed-break-phase-2b1r-discovery-plan-v3",
                None,
            ),
            ("shifted-h1", "phase-2b1r-discovery-v2", pinned_identity, shift_first_h1),
            ("missing-chunk", "phase-2b1r-discovery-v2", pinned_identity, drop_last_chunk),
            ("added-chunk", "phase-2b1r-discovery-v2", pinned_identity, duplicate_last_chunk),
            ("instrument-swap", "phase-2b1r-discovery-v2", pinned_identity, swap_instrument),
        )
        for label, version, identity, mutation in variants:
            with self.subTest(variant=label):
                marker = transaction.savepoint()
                try:
                    payload = self.self_consistent_variant_payload(
                        version=version, identity=identity, mutate_requests=mutation
                    )
                    self.assertNotEqual(
                        payload["plan_sha256"],
                        "2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a",
                    )
                    variant_id = self.raw_insert_plan(payload)
                    with self.assertRaisesMessage(
                        DatasetQualityError, "supersession lineage is invalid"
                    ):
                        supersede_discovery_plan(
                            superseded.sha256, payload["plan_sha256"], attempt.pk
                        )
                    row = self.raw_supersession_row(
                        superseded_ref,
                        {
                            "id": variant_id,
                            "sha256": payload["plan_sha256"],
                            "manifest_sha256": payload["canonical_request_manifest_sha256"],
                        },
                        attempt,
                    )
                    with (
                        self.assertRaisesMessage(
                            DatabaseError, "discovery supersession lineage is invalid"
                        ),
                        transaction.atomic(),
                    ):
                        self.raw_supersede(row)
                finally:
                    transaction.savepoint_rollback(marker)
        self.assertFalse(HistoricalDiscoverySupersession.objects.exists())

    def test_supersession_rejects_non_canary_governing_evidence(self):
        superseded = create_discovery_plan(build_initial_discovery_plan())
        other_chunk = superseded.chunks.select_related("instrument").get(ordinal=1)
        self.assertNotEqual(other_chunk.logical_key, GOVERNING_CANARY_LOGICAL_KEY)
        with self.assertRaises(OandaError):
            run_discovery_chunk(
                other_chunk.logical_key,
                FailingInventoryClient(other_chunk.canonical_request_sha256),
            )
        other_attempt = HistoricalDiscoveryAttempt.objects.get(chunk=other_chunk)
        canary_chunk = superseded.chunks.select_related("instrument").get(
            logical_key=GOVERNING_CANARY_LOGICAL_KEY
        )
        self.assertEqual(canary_chunk.canonical_request_sha256, GOVERNING_CANARY_REQUEST_SHA256)
        for _ in range(2):
            with self.assertRaises(OandaError):
                run_discovery_chunk(
                    canary_chunk.logical_key,
                    FailingInventoryClient(canary_chunk.canonical_request_sha256),
                )
        retry_attempt = HistoricalDiscoveryAttempt.objects.get(chunk=canary_chunk, attempt_number=2)
        replacement = create_discovery_plan(build_replacement_discovery_plan())

        for label, governing in (
            ("different-chunk", other_attempt),
            ("retry-attempt", retry_attempt),
        ):
            with (
                self.subTest(governing=label),
                self.assertRaisesMessage(DatasetQualityError, "supersession lineage is invalid"),
            ):
                supersede_discovery_plan(superseded.sha256, replacement.sha256, governing.pk)

        canary_attempt = HistoricalDiscoveryAttempt.objects.get(
            chunk=canary_chunk, attempt_number=1
        )
        superseded_ref = {
            "id": superseded.pk,
            "sha256": superseded.sha256,
            "manifest_sha256": superseded.canonical_request_manifest_sha256,
        }
        replacement_ref = {
            "id": replacement.pk,
            "sha256": replacement.sha256,
            "manifest_sha256": replacement.canonical_request_manifest_sha256,
        }
        mutations = (
            ("terminal-event-hash", {"governing_terminal_event_sha256": "f" * 64}, None),
            (
                "operational-evidence-hash",
                {"governing_operational_evidence_sha256": "f" * 64},
                None,
            ),
            ("audit-event-hash", None, {"governing_audit_event_sha256": "f" * 64}),
            (
                "idempotency-key",
                None,
                {"governing_attempt_idempotency_key": "historical-discovery-attempt:forged:1"},
            ),
            (
                "request-manifest-hash",
                None,
                {"superseded_request_manifest_sha256": "f" * 64},
            ),
        )
        for label, column_overrides, payload_overrides in mutations:
            with self.subTest(mutation=label):
                row = self.raw_supersession_row(
                    superseded_ref, replacement_ref, canary_attempt, column_overrides
                )
                if payload_overrides:
                    row["payload"] = {**row["payload"], **payload_overrides}
                    row["sha256"] = canonical_hash(row["payload"])
                with (
                    self.assertRaisesMessage(
                        DatabaseError, "discovery supersession lineage is invalid"
                    ),
                    transaction.atomic(),
                ):
                    self.raw_supersede(row)
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


class DiscoverySupersessionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier=SourceRegistry.Tier.ESTABLISHED,
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="supersession concurrency test",
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
        self.superseded = create_discovery_plan(build_initial_discovery_plan())
        self.canary = self.superseded.chunks.select_related("instrument").get(
            logical_key=GOVERNING_CANARY_LOGICAL_KEY
        )
        with self.assertRaises(OandaError):
            run_discovery_chunk(
                self.canary.logical_key,
                FailingInventoryClient(self.canary.canonical_request_sha256),
            )
        self.attempt = HistoricalDiscoveryAttempt.objects.select_related("ingestion_run").get(
            chunk=self.canary
        )
        self.replacement = create_discovery_plan(build_replacement_discovery_plan())
        self.replacement_chunk = (
            self.replacement.chunks.select_related("instrument").order_by("ordinal").first()
        )

    def insert_supersession(self, cursor):
        evidence = HistoricalDiscoveryProviderEvidence.objects.get(attempt=self.attempt)
        run = self.attempt.ingestion_run
        event = AuditEvent.objects.get(
            subject_type="HistoricalDiscoveryAttempt",
            subject_id=str(self.attempt.pk),
            event_type="market.historical_discovery_failed",
        )
        payload = {
            "identity": "historical-discovery-supersession-v1",
            "reason_code": "PROVIDER_REQUEST_BOUND_UNSAFE",
            "superseded_plan_sha256": self.superseded.sha256,
            "superseded_request_manifest_sha256": (
                self.superseded.canonical_request_manifest_sha256
            ),
            "replacement_plan_sha256": self.replacement.sha256,
            "replacement_request_manifest_sha256": (
                self.replacement.canonical_request_manifest_sha256
            ),
            "governing_attempt_idempotency_key": self.attempt.idempotency_key,
            "governing_run_request_manifest_hash": run.request_manifest_hash,
            "governing_failure_code": run.failure_reason,
            "governing_terminal_event_sha256": evidence.terminal_event_sha256,
            "governing_operational_evidence_sha256": evidence.operational_evidence_sha256,
            "governing_audit_event_sha256": event.payload["event_sha256"],
        }
        cursor.execute(
            """INSERT INTO market_historicaldiscoverysupersession
               (superseded_plan_id,replacement_plan_id,governing_attempt_id,reason_code,
                superseded_plan_sha256,replacement_plan_sha256,
                governing_terminal_event_sha256,governing_operational_evidence_sha256,
                payload,sha256,created_at)
               VALUES (%s,%s,%s,'PROVIDER_REQUEST_BOUND_UNSAFE',%s,%s,%s,%s,%s::jsonb,%s,now())""",
            [
                self.superseded.pk,
                self.replacement.pk,
                self.attempt.pk,
                self.superseded.sha256,
                self.replacement.sha256,
                evidence.terminal_event_sha256,
                evidence.operational_evidence_sha256,
                json.dumps(payload),
                canonical_hash(payload),
            ],
        )

    def insert_attempt(self, cursor, chunk, number):
        key = f"historical-discovery-attempt:{chunk.logical_key}:{number}"
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
                self.source.pk,
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

    def assert_single_winner(self, holder, contender, expected_error):
        result = {}
        ready = threading.Event()

        def worker():
            close_old_connections()
            try:
                ready.set()
                with transaction.atomic(), connection.cursor() as cursor:
                    contender(cursor)
                result["outcome"] = "committed"
            except DatabaseError as error:
                result["outcome"] = "rejected"
                result["error"] = str(error)
            finally:
                result["finished_at"] = time.monotonic()
                close_old_connections()

        thread = threading.Thread(target=worker)
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    holder(cursor)
                thread.start()
                self.assertTrue(ready.wait(5))
                time.sleep(0.5)
                self.assertTrue(
                    thread.is_alive(), "contender was not blocked by the governance lock"
                )
                commit_at = time.monotonic()
        finally:
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["outcome"], "rejected")
        self.assertIn(expected_error, result["error"])
        self.assertGreater(result["finished_at"], commit_at)

    def test_old_plan_attempt_blocks_then_fails_when_supersession_locks_first(self):
        self.assert_single_winner(
            self.insert_supersession,
            lambda cursor: self.insert_attempt(cursor, self.canary, 2),
            "superseded discovery plans reject new writes",
        )
        self.assertEqual(HistoricalDiscoverySupersession.objects.count(), 1)
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.superseded).count(), 1
        )

    def test_supersession_blocks_then_fails_when_old_plan_attempt_locks_first(self):
        self.assert_single_winner(
            lambda cursor: self.insert_attempt(cursor, self.canary, 2),
            self.insert_supersession,
            "discovery supersession lineage is invalid",
        )
        self.assertFalse(HistoricalDiscoverySupersession.objects.exists())
        self.assertEqual(HistoricalDiscoveryAttempt.objects.filter(chunk=self.canary).count(), 2)

    def test_replacement_attempt_blocks_then_fails_when_supersession_locks_first(self):
        self.assert_single_winner(
            self.insert_supersession,
            lambda cursor: self.insert_attempt(cursor, self.replacement_chunk, 1),
            "replacement canary activation rejects this attempt",
        )
        self.assertEqual(HistoricalDiscoverySupersession.objects.count(), 1)
        self.assertFalse(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).exists()
        )

    def test_supersession_blocks_then_fails_when_replacement_attempt_locks_first(self):
        self.assert_single_winner(
            lambda cursor: self.insert_attempt(cursor, self.replacement_chunk, 1),
            self.insert_supersession,
            "discovery supersession lineage is invalid",
        )
        self.assertFalse(HistoricalDiscoverySupersession.objects.exists())
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(), 1
        )
