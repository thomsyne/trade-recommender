import json
import threading
from datetime import UTC
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.test import override_settings

from market.historical_acquisition import (
    begin_historical_attempt,
    run_historical_chunk,
    stable_hash,
)
from market.models import (
    AuditEvent,
    Candle,
    DatasetRegistration,
    HistoricalIngestionAttempt,
    HistoricalIngestionChunk,
    IngestionManifest,
    IngestionRun,
)
from market.oanda import CandleData
from market.provider_observed_canary import ACQUISITION_CANARY_LOGICAL_KEY
from market.provider_observed_waves import (
    build_acquisition_wave_manifest,
    build_canary_success_record,
    canary_success_artifact_path,
    load_committed_wave_manifest,
    verify_live_canary_success,
    wave_manifest_artifact_path,
)
from market.services import DatasetQualityError
from market.tests.test_gate7a_acquisition_canary import Gate7AFixtureTestCase
from market.tests.test_replacement_canary_activation import MIGRATION_0021, migrate_to


class ForcedRollback(Exception):
    pass


class WaveClient:
    """Mocked transport returning each chunk's sealed observations."""

    def __init__(self, fail_on_keys=()):
        self.fail_on_keys = set(fail_on_keys)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def fetch_historical_chunk(
        self, instrument, granularity, start, end, canonical_request_sha256=None
    ):
        chunk = HistoricalIngestionChunk.objects.select_related("discovery_inventory").get(
            canonical_request_sha256=canonical_request_sha256,
            data_contract_sha256__isnull=False,
        )
        self.calls.append(chunk.logical_key)
        rows = list(
            chunk.discovery_inventory.observations.order_by("timestamp").values(
                "timestamp", "volume", "complete"
            )
        )
        if chunk.logical_key in self.fail_on_keys:
            rows = rows[:-1]
        candles = [
            CandleData(
                timestamp=row["timestamp"].astimezone(UTC),
                complete=row["complete"],
                volume=row["volume"],
                bid_open=Decimal("1.1000"),
                bid_high=Decimal("1.1020"),
                bid_low=Decimal("1.0990"),
                bid_close=Decimal("1.1010"),
                ask_open=Decimal("1.1002"),
                ask_high=Decimal("1.1022"),
                ask_low=Decimal("1.0992"),
                ask_close=Decimal("1.1012"),
            )
            for row in rows
        ]
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
            "requests": [
                {
                    "endpoint_identity": (
                        f"oanda-v20-practice:GET:/v3/instruments/{instrument}/candles"
                    ),
                    "http_method": "GET",
                    "oanda_environment": "practice",
                    "http_status": 200,
                    "provider_request_id": f"wave-{len(self.calls)}",
                    "canonical_request_sha256": canonical_request_sha256,
                }
            ],
        }
        return candles, manifest


class Gate7BFixtureTestCase(Gate7AFixtureTestCase):
    """Gate 7A lineage under migration 0021 with sealed observations for
    all 132 inventories and the canary completed through the reviewed
    pipeline, yielding a live fixture canary-success record."""

    retention_policy = "gate7b fixture"

    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0021)
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_historicaltimestampobservation DISABLE TRIGGER USER")
            try:
                cursor.execute(
                    """INSERT INTO market_historicaltimestampobservation
                       (inventory_id, timestamp, complete, volume, bid_present, ask_present)
                       -- each fixture inventory already holds one discovery
                       -- observation at requested_from; extend it to exactly
                       -- observation_count sealed rows
                       SELECT i.id, c.requested_from + make_interval(hours => g.n),
                              true, 100 + g.n %% 251, true, true
                       FROM market_historicaltimestampinventory i
                       JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
                       CROSS JOIN LATERAL generate_series(1, i.observation_count - 1) AS g(n)
                       WHERE c.plan_id=%s AND c.ordinal <> 2""",
                    [self.replacement.pk],
                )
            finally:
                cursor.execute(
                    "ALTER TABLE market_historicaltimestampobservation ENABLE TRIGGER USER"
                )
        run_historical_chunk(ACQUISITION_CANARY_LOGICAL_KEY, self.canary_client())
        self.fixture_record = self.build_fixture_success_record()

    def build_fixture_success_record(self):
        evidence = AuditEvent.objects.get(event_type="market.replacement_canary_succeeded")
        manifest = IngestionManifest.objects.get(
            ingestion_run=self.canary_chunk.attempts.get().ingestion_run
        )
        record = dict(build_canary_success_record())
        record["ingestion_manifest_sha256"] = manifest.sha256
        record["candle_key_hash"] = evidence.payload["candle_key_hash"]
        record["candle_payload_hash"] = evidence.payload["candle_payload_hash"]
        record["terminal_event_sha256"] = evidence.payload["terminal_event_sha256"]
        record["operational_evidence_sha256"] = evidence.payload["operational_evidence_sha256"]
        return record

    def begin_probe(self, logical_key):
        """Prove attempt 1 is permitted without persisting anything."""
        with self.assertRaises(ForcedRollback), transaction.atomic():
            attempt, created = begin_historical_attempt(logical_key)
            assert created and attempt.attempt_number == 1
            raise ForcedRollback

    def run_wave(self, *, wave, max_chunks, execute=False, resume=False, client=None):
        stdout = StringIO()
        client = client or WaveClient()
        args = ["--wave", str(wave), "--max-chunks", str(max_chunks)]
        if execute:
            args.append("--execute")
        if resume:
            args.append("--resume")
        with (
            patch(
                "market.management.commands.run_replacement_acquisition_wave.OandaClient",
                return_value=client,
            ),
            patch(
                "market.management.commands.run_replacement_acquisition_wave."
                "verify_live_canary_success",
                side_effect=lambda: verify_live_canary_success(self.fixture_record),
            ),
            override_settings(
                OANDA_ENVIRONMENT="practice", OANDA_DISCOVERY_TOKEN="safe-test-token"
            ),
        ):
            call_command("run_replacement_acquisition_wave", *args, stdout=stdout)
        return client, [json.loads(line) for line in stdout.getvalue().splitlines()]


class Gate7BArtifactTests(Gate7BFixtureTestCase):
    def test_committed_artifacts_reconstruct_and_reject_alteration(self):
        record = build_canary_success_record()
        assert (
            canary_success_artifact_path().read_bytes()
            == json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        )
        body = {k: v for k, v in record.items() if k != "record_sha256"}
        self.assertEqual(record["record_sha256"], stable_hash(body))
        for marker in ('"id":', '"pk":', "provider_request_id", "/Users/"):
            self.assertNotIn(marker, json.dumps(record))

        manifest = load_committed_wave_manifest()
        assert (
            wave_manifest_artifact_path().read_bytes()
            == json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        )
        self.assertEqual(
            [wave["chunk_count"] for wave in manifest["waves"]], [17, 24, 24, 24, 24, 18]
        )
        self.assertEqual(
            [chunk["ordinal"] for chunk in manifest["waves"][0]["chunks"]],
            [1, 22, 23, 24, 44, 45, 46, 66, 67, 68, 88, 89, 90, 110, 111, 112, 132],
        )
        all_keys = [chunk["logical_key"] for wave in manifest["waves"] for chunk in wave["chunks"]]
        self.assertEqual(len(all_keys), 131)
        self.assertEqual(len(set(all_keys)), 131)
        self.assertNotIn(ACQUISITION_CANARY_LOGICAL_KEY, all_keys)
        self.assertEqual(sum(wave["expected_candle_total"] for wave in manifest["waves"]), 362021)
        self.assertEqual(manifest["remaining_candles"], 362021)
        with (
            patch(
                "market.provider_observed_waves.WAVE_ONE_ORDINALS",
                (2, 22, 23, 24, 44, 45, 46, 66, 67, 68, 88, 89, 90, 110, 111, 112, 132),
            ),
            self.assertRaises(ValueError),
        ):
            build_acquisition_wave_manifest()
        with (
            patch("market.provider_observed_waves.WAVE_SIZES", (16, 24, 24, 24, 24, 19)),
            self.assertRaises(ValueError),
        ):
            build_acquisition_wave_manifest()

    def test_canary_prerequisite_reconstructs_and_forgeries_fail(self):
        verify_live_canary_success(self.fixture_record)
        target = load_committed_wave_manifest()["waves"][0]["chunks"][0]["logical_key"]
        self.begin_probe(target)

        attempt = self.canary_chunk.attempts.get()
        run = attempt.ingestion_run
        forgeries = (
            (
                "market_ingestionrun",
                "UPDATE market_ingestionrun SET stored_count=2931 WHERE id=%s",
                [run.pk],
                "UPDATE market_ingestionrun SET stored_count=2932 WHERE id=%s",
                [run.pk],
            ),
            (
                "market_candle",
                "UPDATE market_candle SET volume=volume+1 WHERE ingestion_run_id=%s"
                " AND timestamp=(SELECT min(timestamp) FROM market_candle"
                " WHERE ingestion_run_id=%s)",
                [run.pk, run.pk],
                "UPDATE market_candle SET volume=volume-1 WHERE ingestion_run_id=%s"
                " AND timestamp=(SELECT min(timestamp) FROM market_candle"
                " WHERE ingestion_run_id=%s)",
                [run.pk, run.pk],
            ),
            (
                "market_auditevent",
                "UPDATE market_auditevent SET payload=jsonb_set(payload,"
                " '{terminal_event_sha256}', to_jsonb('f'::text || repeat('0', 63)))"
                " WHERE event_type='market.replacement_canary_succeeded'",
                [],
                None,
                None,
            ),
        )
        original_payload = AuditEvent.objects.get(
            event_type="market.replacement_canary_succeeded"
        ).payload
        for table, forge_sql, forge_args, restore_sql, restore_args in forgeries:
            with connection.cursor() as cursor:
                cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
                try:
                    cursor.execute(forge_sql, forge_args)
                finally:
                    cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
            try:
                with (
                    self.assertRaisesMessage(
                        DatabaseError, "replacement canary success does not reconstruct"
                    ),
                    transaction.atomic(),
                ):
                    begin_historical_attempt(target)
                with self.assertRaises(DatasetQualityError):
                    verify_live_canary_success(self.fixture_record)
            finally:
                with connection.cursor() as cursor:
                    cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
                    try:
                        if restore_sql is not None:
                            cursor.execute(restore_sql, restore_args)
                        else:
                            cursor.execute(
                                "UPDATE market_auditevent SET payload=%s::jsonb WHERE"
                                " event_type='market.replacement_canary_succeeded'",
                                [json.dumps(original_payload)],
                            )
                    finally:
                        cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        verify_live_canary_success(self.fixture_record)
        self.begin_probe(target)
        forged_record = {**self.fixture_record, "candle_key_hash": "f" * 64}
        with self.assertRaises(DatasetQualityError):
            verify_live_canary_success(forged_record)

    def test_canary_is_permanently_closed(self):
        # the service returns the completed attempt idempotently without
        # touching the provider; every write path is rejected in PostgreSQL
        existing, created = begin_historical_attempt(ACQUISITION_CANARY_LOGICAL_KEY)
        self.assertFalse(created)
        attempt = self.canary_chunk.attempts.get()
        self.assertEqual(existing.pk, attempt.pk)
        with (
            self.assertRaisesMessage(
                DatabaseError,
                "replacement acquisition activation rejects this ingestion run",
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
                    self.canary_chunk.granularity,
                    self.canary_chunk.requested_from,
                    self.canary_chunk.requested_to,
                    json.dumps(self.canary_chunk.canonical_request),
                    "1" * 64,
                    self.canary_chunk.instrument_id,
                    self.source.pk,
                    self.dataset.pk,
                ],
            )
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
        with (
            override_settings(
                OANDA_ENVIRONMENT="practice", OANDA_DISCOVERY_TOKEN="safe-test-token"
            ),
            self.assertRaisesMessage(
                CommandError,
                "acquisition canary attempt already exists; retry is prohibited",
            ),
        ):
            call_command(
                "acquire_replacement_canary",
                "--logical-key",
                ACQUISITION_CANARY_LOGICAL_KEY,
                "--execute",
                stdout=StringIO(),
            )
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)

    def test_all_131_remaining_chunks_permit_attempt_one_only(self):
        manifest = load_committed_wave_manifest()
        permitted = 0
        for wave in manifest["waves"]:
            for chunk in wave["chunks"]:
                self.begin_probe(chunk["logical_key"])
                permitted += 1
        self.assertEqual(permitted, 131)
        self.assertEqual(HistoricalIngestionAttempt.objects.count(), 1)

        target = HistoricalIngestionChunk.objects.get(
            logical_key=manifest["waves"][0]["chunks"][0]["logical_key"]
        )
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_historicalingestionchunk DISABLE TRIGGER USER")
            try:
                cursor.execute(
                    "UPDATE market_historicalingestionchunk SET logical_key=%s WHERE id=%s",
                    ["a" * 64, target.pk],
                )
            finally:
                cursor.execute("ALTER TABLE market_historicalingestionchunk ENABLE TRIGGER USER")
        try:
            with (
                self.assertRaisesMessage(
                    DatabaseError, "replacement acquisition activation rejects this attempt"
                ),
                transaction.atomic(),
            ):
                begin_historical_attempt("a" * 64)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE market_historicalingestionchunk DISABLE TRIGGER USER")
                try:
                    cursor.execute(
                        "UPDATE market_historicalingestionchunk SET logical_key=%s WHERE id=%s",
                        [target.logical_key, target.pk],
                    )
                finally:
                    cursor.execute(
                        "ALTER TABLE market_historicalingestionchunk ENABLE TRIGGER USER"
                    )

    def test_audit_evidence_cardinality_enforced_in_postgresql(self):
        attempt = self.canary_chunk.attempts.get()
        run = attempt.ingestion_run
        evidence = AuditEvent.objects.get(event_type="market.replacement_canary_succeeded")
        cases = (
            (
                "duplicate attempt evidence",
                "market.replacement_canary_succeeded",
                "HistoricalIngestionAttempt",
                str(attempt.pk),
                evidence.payload,
            ),
            (
                "conflicting failure evidence",
                "market.historical_ingestion_failed",
                "HistoricalIngestionAttempt",
                str(attempt.pk),
                {"error_code": "X", "logical_chunk_key": self.canary_chunk.logical_key},
            ),
            (
                "duplicate run terminal",
                "market.ingestion_succeeded",
                "IngestionRun",
                str(run.pk),
                {"fetched": 2932},
            ),
            (
                "wrong event type for canary",
                "market.replacement_acquisition_succeeded",
                "HistoricalIngestionAttempt",
                str(attempt.pk),
                evidence.payload,
            ),
        )
        for label, event_type, subject_type, subject_id, payload in cases:
            with (
                self.assertRaisesMessage(
                    DatabaseError, "replacement acquisition audit evidence rejected"
                ),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    """INSERT INTO market_auditevent
                       (event_type,actor,subject_type,subject_id,payload,occurred_at)
                       VALUES (%s,'gate7b-test',%s,%s,%s::jsonb,now())""",
                    [event_type, subject_type, subject_id, json.dumps(payload)],
                )
        discovery_run = (
            IngestionRun.objects.filter(dataset_version__isnull=True).order_by("id").first()
        )
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO market_auditevent
                   (event_type,actor,subject_type,subject_id,payload,occurred_at)
                   VALUES ('market.ingestion_succeeded','gate7b-test','IngestionRun',
                           %s,'{}'::jsonb,now())""",
                [str(discovery_run.pk)],
            )
        self.assertTrue(True)

    def test_wave_runner_dry_run_bounds_and_read_only(self):
        before = (
            HistoricalIngestionAttempt.objects.count(),
            IngestionRun.objects.count(),
            Candle.objects.count(),
        )
        client, lines = self.run_wave(wave=1, max_chunks=5)
        self.assertEqual(client.calls, [])
        report = lines[-1]
        self.assertEqual(report["checkpoint"], "dry-run")
        self.assertTrue(report["read_only"])
        self.assertEqual(report["provider_requests_performed"], 0)
        self.assertEqual(len(report["planned_executions"]), 5)
        self.assertEqual(report["planned_executions"][0]["ordinal"], 1)
        self.assertEqual(
            (
                HistoricalIngestionAttempt.objects.count(),
                IngestionRun.objects.count(),
                Candle.objects.count(),
            ),
            before,
        )
        with self.assertRaisesMessage(
            CommandError, "wave number is not part of the governed manifest"
        ):
            self.run_wave(wave=7, max_chunks=1)
        with self.assertRaisesMessage(CommandError, "max-chunks must be positive"):
            self.run_wave(wave=1, max_chunks=0)
        with self.assertRaisesMessage(CommandError, "max-chunks must be positive"):
            self.run_wave(wave=1, max_chunks=18)

    def test_wave_execution_order_resume_and_failure_stop(self):
        manifest = load_committed_wave_manifest()
        wave_one = manifest["waves"][0]["chunks"]
        client, lines = self.run_wave(wave=1, max_chunks=2, execute=True)
        self.assertEqual(client.calls, [wave_one[0]["logical_key"], wave_one[1]["logical_key"]])
        succeeded = [line for line in lines if line["checkpoint"] == "succeeded"]
        self.assertEqual([line["ordinal"] for line in succeeded], [1, 22])
        for entry, line in zip(wave_one[:2], succeeded):
            stored = Candle.objects.filter(
                ingestion_run__historical_attempt__chunk__logical_key=entry["logical_key"]
            ).count()
            self.assertEqual(stored, entry["expected_observation_count"])
            self.assertEqual(line["stored_count"], entry["expected_observation_count"])
        self.assertFalse(IngestionRun.objects.filter(status="running").exists())
        acquisition_events = AuditEvent.objects.filter(
            event_type="market.replacement_acquisition_succeeded"
        )
        self.assertEqual(acquisition_events.count(), 2)

        with self.assertRaisesMessage(
            CommandError, "wave contains a completed chunk; rerun with --resume"
        ):
            self.run_wave(wave=1, max_chunks=1, execute=True)

        failing = wave_one[3]["logical_key"]
        client = WaveClient(fail_on_keys={failing})
        with self.assertRaisesMessage(CommandError, "wave stopped at ordinal 24"):
            self.run_wave(wave=1, max_chunks=3, execute=True, resume=True, client=client)
        self.assertEqual(client.calls, [wave_one[2]["logical_key"], failing])
        failed_attempt = HistoricalIngestionAttempt.objects.get(chunk__logical_key=failing)
        self.assertEqual(failed_attempt.ingestion_run.status, IngestionRun.Status.FAILED)
        self.assertFalse(
            HistoricalIngestionAttempt.objects.filter(
                chunk__logical_key=wave_one[4]["logical_key"]
            ).exists()
        )
        with self.assertRaisesMessage(CommandError, "wave contains a failed or running chunk"):
            self.run_wave(wave=1, max_chunks=1, execute=True, resume=True)
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement acquisition activation rejects this ingestion run"
            ),
            transaction.atomic(),
        ):
            begin_historical_attempt(failing)

    def test_single_global_running_acquisition(self):
        manifest = load_committed_wave_manifest()
        first = manifest["waves"][0]["chunks"][0]["logical_key"]
        second = manifest["waves"][0]["chunks"][1]["logical_key"]
        attempt, created = begin_historical_attempt(first)
        self.assertTrue(created)
        with (
            self.assertRaisesMessage(
                DatabaseError, "replacement acquisition activation rejects this ingestion run"
            ),
            transaction.atomic(),
        ):
            begin_historical_attempt(second)
        self.assertEqual(
            HistoricalIngestionAttempt.objects.exclude(
                chunk__logical_key=ACQUISITION_CANARY_LOGICAL_KEY
            ).count(),
            1,
        )

    def test_partial_dataset_cannot_register_or_reach_s0s1(self):
        self.run_wave(wave=1, max_chunks=1, execute=True)
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
                    self.dataset.pk,
                    self.plan.pk,
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
        from market.services import provider_observed_contract

        with self.assertRaises(DatasetQualityError):
            provider_observed_contract(self.dataset)
        self.assertFalse(DatasetRegistration.objects.exists())


class Gate7BFullCoverageTests(Gate7BFixtureTestCase):
    def test_complete_coverage_reaches_registration_boundary_unregistered(self):
        for wave in load_committed_wave_manifest()["waves"]:
            self.run_wave(
                wave=wave["wave"],
                max_chunks=wave["chunk_count"],
                execute=True,
                resume=True,
            )
        self.assertEqual(
            HistoricalIngestionAttempt.objects.filter(
                chunk__data_contract_sha256__isnull=False
            ).count(),
            132,
        )
        self.assertEqual(Candle.objects.filter(dataset_version=self.dataset).count(), 364953)
        self.assertEqual(
            IngestionRun.objects.filter(dataset_version=self.dataset, status="succeeded").count(),
            132,
        )
        self.assertFalse(DatasetRegistration.objects.exists())
        from market.services import provider_observed_contract

        with self.assertRaises(DatasetQualityError):
            provider_observed_contract(self.dataset)


class Gate7BConcurrencyTests(Gate7BFixtureTestCase):
    def worker_results(self, target):
        results = []
        barrier = threading.Barrier(2)

        def worker(index):
            try:
                target(barrier, index)
                results.append("committed")
            except Exception as error:  # noqa: BLE001 - the label is the assertion
                results.append(f"rejected: {type(error).__name__}"[:80])
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        return results

    def test_concurrent_service_starts_yield_one_winner(self):
        manifest = load_committed_wave_manifest()
        keys = [
            manifest["waves"][0]["chunks"][0]["logical_key"],
            manifest["waves"][0]["chunks"][1]["logical_key"],
        ]

        def target(barrier, index):
            barrier.wait(timeout=30)
            begin_historical_attempt(keys[index])

        results = self.worker_results(target)
        self.assertEqual(len(results), 2, results)
        self.assertEqual(
            sorted(item.split(":")[0] for item in results),
            ["committed", "rejected"],
            results,
        )
        self.assertEqual(
            HistoricalIngestionAttempt.objects.exclude(
                chunk__logical_key=ACQUISITION_CANARY_LOGICAL_KEY
            ).count(),
            1,
        )

    def test_concurrent_raw_sql_starts_yield_one_winner(self):
        manifest = load_committed_wave_manifest()
        chunks = [
            HistoricalIngestionChunk.objects.select_related("instrument").get(
                logical_key=manifest["waves"][0]["chunks"][index]["logical_key"]
            )
            for index in range(2)
        ]

        def target(barrier, index):
            chunk = chunks[index]
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
                        {"attempt": (f"failed-break-ingestion-attempt:{chunk.logical_key}:1")}
                    ),
                )
                with connection.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO market_historicalingestionattempt
                           (chunk_id,ingestion_run_id,attempt_number,
                            idempotency_key,created_at)
                           VALUES (%s,%s,1,%s,now())""",
                        [
                            chunk.pk,
                            run.pk,
                            f"failed-break-ingestion-attempt:{chunk.logical_key}:1",
                        ],
                    )

        results = self.worker_results(target)
        self.assertEqual(len(results), 2, results)
        self.assertEqual(
            sorted(item.split(":")[0] for item in results),
            ["committed", "rejected"],
            results,
        )
        self.assertEqual(
            HistoricalIngestionAttempt.objects.exclude(
                chunk__logical_key=ACQUISITION_CANARY_LOGICAL_KEY
            ).count(),
            1,
        )
