import json
import os
import tempfile
import threading
import time
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from market.discovery_waves import build_wave_manifest
from market.historical_discovery import (
    CANARY_SUCCESS_OBSERVATION_COUNT,
    CANARY_V2_LOGICAL_KEY,
    GOVERNING_CANARY_LOGICAL_KEY,
    StructuralObservation,
    approve_and_register_discovery,
    begin_discovery_attempt,
    run_discovery_chunk,
)
from market.models import (
    HistoricalDiscoveryAttempt,
    HistoricalDiscoveryPlan,
    HistoricalDiscoverySupersession,
    HistoricalTimestampInventory,
    IngestionRun,
)
from market.oanda import OandaError
from market.services import DatasetQualityError
from market.tests.test_replacement_canary_activation import (
    MIGRATION_0015,
    MIGRATION_0016,
    MIGRATION_0017,
    MIGRATION_0019,
    build_retry_ready_state,
    build_superseded_state,
    insert_raw_canary_attempt,
    migrate_to,
    record_attempt_two_failure,
    record_attempt_two_success,
    seed_governed_market,
    state_hashes,
)
from market.tests.test_replacement_canary_activation import (
    canary_raw_evidence as raw_evidence_for,
)

FORBIDDEN_OUTPUT_MARKERS = (
    "Authorization",
    "Bearer",
    "https://",
    "api-fxpractice",
    "account",
    '"o":',
    '"h":',
    '"l":',
    '"c":',
)


class WaveSuccessClient:
    def __init__(self, plan, fail_on_ordinals=()):
        self.plan = plan
        self.fail_on_ordinals = set(fail_on_ordinals)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def fetch_historical_inventory(self, instrument, granularity, start, end):
        chunk = self.plan.chunks.select_related("instrument").get(
            instrument__code=instrument, granularity=granularity, requested_from=start
        )
        self.calls.append(chunk.ordinal)
        if chunk.ordinal in self.fail_on_ordinals:
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
                    "provider_request_id": f"wave-failure-{chunk.ordinal}",
                    "canonical_request_sha256": chunk.canonical_request_sha256,
                },
            )
        return (
            [StructuralObservation(start, True, 5, True, True)],
            {
                "endpoint_identity": (
                    f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"
                ),
                "http_method": "GET",
                "oanda_environment": "practice",
                "http_status": 200,
                "provider_request_id": f"wave-success-{chunk.ordinal}",
                "canonical_request_sha256": chunk.canonical_request_sha256,
            },
        )


class Gate4FixtureTestCase(TransactionTestCase):
    retention_policy = "gate4 fixture"

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
        self.attempt_two = record_attempt_two_success(self.source, self.replacement)
        migrate_to(MIGRATION_0019)
        self.canary = self.replacement.chunks.select_related("instrument").get(
            logical_key=CANARY_V2_LOGICAL_KEY
        )
        self.remaining = list(
            self.replacement.chunks.select_related("instrument")
            .exclude(logical_key=CANARY_V2_LOGICAL_KEY)
            .order_by("ordinal")
        )

    def tearDown(self):
        migrate_to(MIGRATION_0019)
        super().tearDown()

    def validator_outcomes(self):
        from market.historical_discovery import _validate_replacement_canary_activation

        accepted, rejected = [], 0
        for chunk in self.replacement.chunks.select_related("plan", "instrument"):
            try:
                _validate_replacement_canary_activation(chunk)
                accepted.append(chunk.logical_key)
            except DatasetQualityError:
                rejected += 1
        return accepted, rejected


class Gate4ActivationTests(Gate4FixtureTestCase):
    def test_canary_success_prerequisite_is_established(self):
        run = self.attempt_two.ingestion_run
        self.assertEqual(run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(run.fetched_count, CANARY_SUCCESS_OBSERVATION_COUNT)
        self.assertEqual(run.stored_count, CANARY_SUCCESS_OBSERVATION_COUNT)
        self.assertEqual(run.rejected_count, 0)
        inventory = HistoricalTimestampInventory.objects.get(chunk=self.canary)
        self.assertEqual(inventory.observation_count, CANARY_SUCCESS_OBSERVATION_COUNT)

    def test_all_remaining_chunks_eligible_and_canary_permanently_closed(self):
        accepted, rejected = self.validator_outcomes()
        self.assertEqual(len(accepted), 131)
        self.assertEqual(rejected, 1)
        self.assertNotIn(CANARY_V2_LOGICAL_KEY, accepted)

    def test_service_attempt_one_succeeds_then_no_retry(self):
        before = state_hashes(self.superseded, self.replacement)
        target = self.remaining[0]
        client = WaveSuccessClient(self.replacement)

        attempt = run_discovery_chunk(target.logical_key, client)

        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(
            attempt.idempotency_key,
            f"historical-discovery-attempt:{target.logical_key}:1",
        )
        self.assertEqual(attempt.ingestion_run.status, IngestionRun.Status.SUCCEEDED)
        self.assertEqual(state_hashes(self.superseded, self.replacement), before)
        with self.assertRaisesMessage(
            DatasetQualityError, "replacement canary activation rejects this attempt"
        ):
            begin_discovery_attempt(target.logical_key)
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement canary activation rejects this attempt"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            insert_raw_canary_attempt(cursor, self.source.pk, target, 2)

    def test_failed_chunk_cannot_be_retried(self):
        target = self.remaining[0]
        with self.assertRaises(OandaError):
            run_discovery_chunk(
                target.logical_key,
                WaveSuccessClient(self.replacement, fail_on_ordinals={target.ordinal}),
            )
        with self.assertRaisesMessage(
            DatasetQualityError, "replacement canary activation rejects this attempt"
        ):
            begin_discovery_attempt(target.logical_key)
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement canary activation rejects this attempt"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            insert_raw_canary_attempt(cursor, self.source.pk, target, 2)

    def test_attempt_two_or_wrong_key_rejected_for_fresh_chunks(self):
        target = self.remaining[3]
        cases = (
            ("attempt-two", target, 2, None),
            ("wrong-key", target, 1, "historical-discovery-attempt:forged:1"),
            ("canary-reopen", self.canary, 3, None),
        )
        for label, chunk, number, key in cases:
            with (
                self.subTest(case=label),
                self.assertRaisesMessage(
                    DatabaseError, "replacement canary activation rejects this attempt"
                ),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                insert_raw_canary_attempt(cursor, self.source.pk, chunk, number, key)

    def test_only_one_discovery_attempt_may_run_globally(self):
        first = begin_discovery_attempt(self.remaining[0].logical_key)
        self.assertEqual(first.ingestion_run.status, IngestionRun.Status.RUNNING)
        with self.assertRaisesMessage(
            DatasetQualityError, "replacement canary activation rejects this attempt"
        ):
            begin_discovery_attempt(self.remaining[1].logical_key)
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement canary activation rejects this attempt"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            insert_raw_canary_attempt(cursor, self.source.pk, self.remaining[2], 1)

    def test_superseded_approval_registration_sealing_remain_blocked(self):
        v1_canary = self.superseded.chunks.get(logical_key=GOVERNING_CANARY_LOGICAL_KEY)
        with self.assertRaisesMessage(
            DatasetQualityError, "superseded discovery plans reject new attempts"
        ):
            begin_discovery_attempt(v1_canary.logical_key)
        approver = get_user_model().objects.create_user("gate4-approver")
        approver.user_permissions.add(
            Permission.objects.get(codename="approve_historical_discovery")
        )
        with self.assertRaisesMessage(
            DatasetQualityError,
            "gate5 approval requires the committed cross-series completion-summary hash",
        ):
            approve_and_register_discovery(self.replacement.sha256, approver.pk, "a" * 64)
        with (
            self.assertRaisesMessage(
                DatabaseError, "gate5 registration state does not reconstruct"
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

    def test_orm_bulk_bypasses_fail_closed(self):
        target = self.remaining[5]
        run = None
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement canary activation rejects this attempt"
            ),
            transaction.atomic(),
        ):
            run = IngestionRun.objects.create(
                source=self.source,
                instrument=target.instrument,
                granularity=target.granularity,
                requested_from=target.requested_from,
                requested_to=target.requested_to,
                parameters={"purpose": "provider_timestamp_inventory_discovery"},
                request_manifest_hash="f" * 64,
            )
            HistoricalDiscoveryAttempt.objects.bulk_create(
                [
                    HistoricalDiscoveryAttempt(
                        chunk=target,
                        ingestion_run=run,
                        attempt_number=1,
                        idempotency_key="historical-discovery-attempt:forged:1",
                    )
                ]
            )
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalDiscoveryPlan.objects.filter(pk=self.replacement.pk).update(payload={})

    def test_concurrent_service_starts_permit_exactly_one_running_attempt(self):
        barrier = threading.Barrier(2)
        outcomes = []
        targets = [self.remaining[0].logical_key, self.remaining[1].logical_key]

        def start(logical_key):
            close_old_connections()
            try:
                barrier.wait(5)
                begin_discovery_attempt(logical_key)
                outcomes.append("committed")
            except (DatasetQualityError, DatabaseError):
                outcomes.append("rejected")
            finally:
                close_old_connections()

        threads = [threading.Thread(target=start, args=(key,)) for key in targets]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        self.assertEqual(sorted(outcomes), ["committed", "rejected"])
        self.assertEqual(
            IngestionRun.objects.filter(
                status=IngestionRun.Status.RUNNING,
                parameters__purpose="provider_timestamp_inventory_discovery",
            ).count(),
            1,
        )

    def test_concurrent_raw_starts_permit_exactly_one_running_attempt(self):
        result = {}
        ready = threading.Event()
        chunk_a, chunk_b = self.remaining[0], self.remaining[1]

        def contender():
            close_old_connections()
            try:
                ready.set()
                with transaction.atomic(), connection.cursor() as cursor:
                    insert_raw_canary_attempt(cursor, self.source.pk, chunk_b, 1)
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
                    insert_raw_canary_attempt(cursor, self.source.pk, chunk_a, 1)
                thread.start()
                self.assertTrue(ready.wait(5))
                time.sleep(0.5)
                self.assertTrue(thread.is_alive(), "contender was not blocked by the plan lock")
        finally:
            thread.join(10)
        self.assertEqual(result["outcome"], "rejected")
        self.assertIn("replacement canary activation rejects this attempt", result["error"])
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(chunk__plan=self.replacement).count(),
            3,
        )


class Gate4PrerequisiteTests(TransactionTestCase):
    def tearDown(self):
        migrate_to(MIGRATION_0019)
        super().tearDown()

    def assert_activation_blocked(self, source, replacement):
        target = (
            replacement.chunks.exclude(logical_key=CANARY_V2_LOGICAL_KEY)
            .order_by("ordinal")
            .first()
        )
        with self.assertRaisesMessage(
            DatasetQualityError, "replacement canary activation rejects this attempt"
        ):
            begin_discovery_attempt(target.logical_key)
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement canary activation rejects this attempt"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            insert_raw_canary_attempt(cursor, source.pk, target, 1)

    def test_missing_attempt_two_blocks_activation(self):
        migrate_to(MIGRATION_0015)
        source = seed_governed_market("gate4 missing attempt two")
        _, replacement, _, _ = build_retry_ready_state(source)
        migrate_to(MIGRATION_0017)
        self.assert_activation_blocked(source, replacement)

    def test_failed_attempt_two_blocks_activation(self):
        migrate_to(MIGRATION_0015)
        source = seed_governed_market("gate4 failed attempt two")
        _, replacement, _, _ = build_retry_ready_state(source)
        migrate_to(MIGRATION_0016)
        record_attempt_two_failure(source, replacement)
        migrate_to(MIGRATION_0017)
        self.assert_activation_blocked(source, replacement)

    def test_incomplete_canary_inventory_blocks_activation(self):
        migrate_to(MIGRATION_0015)
        source = seed_governed_market("gate4 short inventory")
        _, replacement, _, _ = build_retry_ready_state(source)
        migrate_to(MIGRATION_0016)
        from market.historical_discovery import _record_success, _validate_response

        canary = replacement.chunks.select_related("plan", "instrument").get(
            logical_key=CANARY_V2_LOGICAL_KEY
        )
        with transaction.atomic(), connection.cursor() as cursor:
            insert_raw_canary_attempt(cursor, source.pk, canary, 2)
        attempt = HistoricalDiscoveryAttempt.objects.get(chunk=canary, attempt_number=2)
        observations = [
            StructuralObservation(canary.requested_from, True, 1, True, True),
            StructuralObservation(canary.requested_from.replace(hour=16), True, 1, True, True),
        ]
        validated, sanitized = _validate_response(
            canary,
            observations,
            raw_evidence_for(canary.canonical_request_sha256, request_id="short-success"),
        )
        _record_success(attempt.pk, validated, sanitized)
        migrate_to(MIGRATION_0017)
        self.assert_activation_blocked(source, replacement)

    def test_zero_canary_attempts_blocks_activation(self):
        migrate_to(MIGRATION_0015)
        source = seed_governed_market("gate4 zero attempts")
        _, replacement, _ = build_superseded_state()
        migrate_to(MIGRATION_0017)
        self.assert_activation_blocked(source, replacement)


@override_settings(OANDA_DISCOVERY_TOKEN="mocked-discovery-token", OANDA_ENVIRONMENT="practice")
class Gate4WaveRunnerTests(Gate4FixtureTestCase):
    retention_policy = "gate4 wave runner"

    def setUp(self):
        super().setUp()
        semantic = HistoricalTimestampInventory.objects.get(
            chunk=self.canary
        ).semantic_inventory_sha256
        self.manifest = build_wave_manifest(semantic)
        manifest_dir = tempfile.TemporaryDirectory(
            prefix="gate4-wave-manifest-", ignore_cleanup_errors=True
        )
        self.addCleanup(manifest_dir.cleanup)
        self.manifest_file = os.path.join(manifest_dir.name, "wave-manifest.json")
        self.write_manifest(self.manifest)

    def write_manifest(self, manifest):
        with open(self.manifest_file, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True)

    def run_wave(self, client, wave=1, max_chunks=2, resume=False):
        stdout = StringIO()
        with patch(
            "market.management.commands.run_discovery_wave.OandaClient",
            return_value=client,
        ) as factory:
            call_command(
                "run_discovery_wave",
                "--manifest",
                self.manifest_file,
                "--plan-sha256",
                self.manifest["v2_plan_sha256"],
                "--manifest-sha256",
                self.manifest["v2_manifest_sha256"],
                "--wave",
                str(wave),
                "--max-chunks",
                str(max_chunks),
                "--execute",
                *(["--resume"] if resume else []),
                stdout=stdout,
            )
        return factory, [json.loads(line) for line in stdout.getvalue().splitlines()]

    def test_wave_executes_sequentially_and_respects_the_bound(self):
        client = WaveSuccessClient(self.replacement)
        _, checkpoints = self.run_wave(client, wave=1, max_chunks=2)
        self.assertEqual(client.calls, [1, 22])
        events = [entry["event"] for entry in checkpoints]
        self.assertEqual(events, ["chunk_succeeded", "chunk_succeeded", "wave_bounded"])
        self.assertEqual(checkpoints[2]["next_ordinal"], 23)
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.filter(
                chunk__plan=self.replacement,
                chunk__logical_key__in=[entry["logical_key"] for entry in checkpoints[:2]],
            ).count(),
            2,
        )

    def test_wave_stops_on_first_failure_and_leaves_later_chunks_untouched(self):
        client = WaveSuccessClient(self.replacement, fail_on_ordinals={22})
        with self.assertRaisesMessage(CommandError, "wave stopped with no retry"):
            self.run_wave(client, wave=1, max_chunks=5)
        self.assertEqual(client.calls, [1, 22])
        ordinal_1 = self.replacement.chunks.get(ordinal=1)
        ordinal_22 = self.replacement.chunks.get(ordinal=22)
        ordinal_23 = self.replacement.chunks.get(ordinal=23)
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.get(chunk=ordinal_1).ingestion_run.status,
            IngestionRun.Status.SUCCEEDED,
        )
        self.assertEqual(
            HistoricalDiscoveryAttempt.objects.get(chunk=ordinal_22).ingestion_run.status,
            IngestionRun.Status.FAILED,
        )
        self.assertFalse(HistoricalDiscoveryAttempt.objects.filter(chunk=ordinal_23).exists())

    def test_resume_skips_only_successes_and_never_failures(self):
        client = WaveSuccessClient(self.replacement)
        self.run_wave(client, wave=1, max_chunks=1)
        with self.assertRaisesMessage(CommandError, "requires --resume"):
            self.run_wave(WaveSuccessClient(self.replacement), wave=1, max_chunks=1)
        resumed = WaveSuccessClient(self.replacement)
        _, checkpoints = self.run_wave(resumed, wave=1, max_chunks=1, resume=True)
        self.assertEqual(resumed.calls, [22])
        self.assertEqual(
            [entry["event"] for entry in checkpoints],
            ["chunk_skipped_already_succeeded", "chunk_succeeded", "wave_bounded"],
        )
        failing = WaveSuccessClient(self.replacement, fail_on_ordinals={23})
        with self.assertRaisesMessage(CommandError, "wave stopped with no retry"):
            self.run_wave(failing, wave=1, max_chunks=5, resume=True)
        with self.assertRaisesMessage(CommandError, "never retried or skipped"):
            self.run_wave(WaveSuccessClient(self.replacement), wave=1, max_chunks=5, resume=True)

    def test_manifest_validation_rejects_tampering_before_any_client_use(self):
        variants = {}
        tampered = json.loads(json.dumps(self.manifest))
        tampered["chunks"][0]["logical_key"] = "f" * 64
        variants["altered-key"] = tampered
        duplicated = json.loads(json.dumps(self.manifest))
        duplicated["chunks"].append(duplicated["chunks"][0])
        variants["duplicate-chunk"] = duplicated
        reordered = json.loads(json.dumps(self.manifest))
        reordered["chunks"][0], reordered["chunks"][1] = (
            reordered["chunks"][1],
            reordered["chunks"][0],
        )
        variants["reordered"] = reordered
        with_canary = json.loads(json.dumps(self.manifest))
        with_canary["chunks"][0]["logical_key"] = CANARY_V2_LOGICAL_KEY
        variants["canary-included"] = with_canary
        bad_sha = json.loads(json.dumps(self.manifest))
        bad_sha["ordered_manifest_sha256"] = "f" * 64
        variants["bad-ordered-sha"] = bad_sha
        for label, manifest in variants.items():
            with self.subTest(variant=label):
                self.write_manifest(manifest)
                with (
                    patch("market.management.commands.run_discovery_wave.OandaClient") as factory,
                    self.assertRaisesMessage(CommandError, "wave manifest does not reconstruct"),
                ):
                    call_command(
                        "run_discovery_wave",
                        "--manifest",
                        self.manifest_file,
                        "--plan-sha256",
                        self.manifest["v2_plan_sha256"],
                        "--manifest-sha256",
                        self.manifest["v2_manifest_sha256"],
                        "--wave",
                        "1",
                        "--max-chunks",
                        "1",
                        "--execute",
                    )
                factory.assert_not_called()

    def test_runner_guardrails(self):
        self.write_manifest(self.manifest)
        with self.assertRaisesMessage(CommandError, "--max-chunks must be a positive"):
            self.run_wave(WaveSuccessClient(self.replacement), wave=1, max_chunks=0)
        with self.assertRaisesMessage(CommandError, "explicit --execute"):
            call_command(
                "run_discovery_wave",
                "--manifest",
                self.manifest_file,
                "--plan-sha256",
                self.manifest["v2_plan_sha256"],
                "--manifest-sha256",
                self.manifest["v2_manifest_sha256"],
                "--wave",
                "1",
                "--max-chunks",
                "1",
            )
        with self.assertRaisesMessage(CommandError, "does not match the approved v2 plan"):
            call_command(
                "run_discovery_wave",
                "--manifest",
                self.manifest_file,
                "--plan-sha256",
                "f" * 64,
                "--manifest-sha256",
                self.manifest["v2_manifest_sha256"],
                "--wave",
                "1",
                "--max-chunks",
                "1",
                "--execute",
            )
        begin_discovery_attempt(self.remaining[0].logical_key)
        with self.assertRaisesMessage(CommandError, "already running"):
            self.run_wave(WaveSuccessClient(self.replacement), wave=1, max_chunks=1)

    def test_checkpoints_contain_no_secrets_or_prices(self):
        client = WaveSuccessClient(self.replacement, fail_on_ordinals={22})
        stdout = StringIO()
        with (
            patch(
                "market.management.commands.run_discovery_wave.OandaClient",
                return_value=client,
            ),
            self.assertRaises(CommandError),
        ):
            call_command(
                "run_discovery_wave",
                "--manifest",
                self.manifest_file,
                "--plan-sha256",
                self.manifest["v2_plan_sha256"],
                "--manifest-sha256",
                self.manifest["v2_manifest_sha256"],
                "--wave",
                "1",
                "--max-chunks",
                "5",
                "--execute",
                stdout=stdout,
            )
        output = stdout.getvalue()
        for marker in FORBIDDEN_OUTPUT_MARKERS:
            self.assertNotIn(marker, output)
        self.assertNotIn("mocked-discovery-token", output)
