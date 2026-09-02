import hashlib
import json
from importlib import import_module
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from market.management.commands.register_failed_break_dataset import Command
from market.provider_observed_gate8e import (
    SUCCESSOR_CONTRACT_SHA256,
    SUCCESSOR_DATASET_MANIFEST_SHA256,
)
from market.provider_observed_gate8g import SUCCESSOR_ACQUISITION_PLAN_SHA256
from market.provider_observed_gate8i import (
    ARTIFACT_PATH,
    CANDLE_SHARD_SIZE,
    COMBINED_H1_WARMUP,
    DECOMPOSED_SNAPSHOT,
    EXTENSION_CANDLE_COUNT,
    FINAL_ACCEPTANCE_ARTIFACT_SHA256,
    PREDECESSOR_CANDLE_COUNT,
    REQUIRED_H1_WARMUP,
    SUCCESSOR_CANDLE_COUNT,
    _candle_shards,
    build_gate8i_acceptance,
    decomposed_operational_snapshot,
    decomposed_snapshot_summary,
    is_successor_registration,
    load_committed_gate8i_acceptance,
    verify_successor_registration_readiness,
)
from market.services import DatasetQualityError


class Gate8IArtifactTests(SimpleTestCase):
    def test_canonical_artifact_file_self_hash_and_accepted_counts(self):
        document = load_committed_gate8i_acceptance()

        self.assertEqual(
            hashlib.sha256(ARTIFACT_PATH.read_bytes()).hexdigest(),
            FINAL_ACCEPTANCE_ARTIFACT_SHA256,
        )
        self.assertEqual(document, build_gate8i_acceptance())
        self.assertEqual(document["candle_count"], SUCCESSOR_CANDLE_COUNT)
        self.assertEqual(
            document["predecessor_overlap"]["identical_overlap_count"],
            PREDECESSOR_CANDLE_COUNT,
        )
        self.assertEqual(document["successor_extension"]["candle_count"], EXTENSION_CANDLE_COUNT)
        self.assertEqual(len(document["warmup_proof"]), 6)
        self.assertTrue(
            all(
                item["combined_completed_warmup_observations"] == COMBINED_H1_WARMUP
                and item["required_warmup_observations"] == REQUIRED_H1_WARMUP
                for item in document["warmup_proof"]
            )
        )

    def test_snapshot_is_bounded_and_binds_all_23_sections(self):
        summary = decomposed_snapshot_summary(DECOMPOSED_SNAPSHOT)

        self.assertEqual(summary["section_count"], 23)
        self.assertEqual(summary["candles"]["row_count"], 732834)
        self.assertEqual(summary["candles"]["shard_size"], CANDLE_SHARD_SIZE)
        self.assertEqual(summary["candles"]["shard_count"], 15)
        self.assertLessEqual(
            max(item["row_count"] for item in DECOMPOSED_SNAPSHOT["sections"]["candles"]["shards"]),
            CANDLE_SHARD_SIZE,
        )
        self.assertEqual(
            summary["snapshot_sha256"],
            load_committed_gate8i_acceptance()["final_acquisition_snapshot_sha256"],
        )

    def test_artifact_contains_no_operational_secret_or_execution_authority(self):
        document = load_committed_gate8i_acceptance()
        encoded = str(document).lower()
        for prohibited in (
            "provider_request_id",
            "credential",
            "token",
            "account_id",
            "raw_body",
            "header",
            "database_id",
        ):
            self.assertNotIn(prohibited, encoded)
        self.assertIn("does not itself register or seal", document["authorization_scope"])
        self.assertIn("does not authorize provider access", document["authorization_scope"])


class ScriptedCursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.parameters = []

    def execute(self, _statement, parameters):
        self.parameters.append(parameters)

    def fetchone(self):
        return next(self.rows)


class Gate8ISnapshotUnitTests(SimpleTestCase):
    @patch("market.provider_observed_gate8i._candle_shards")
    @patch("market.provider_observed_gate8i._single_section")
    @patch("market.provider_observed_gate8i.SNAPSHOT_SECTIONS", (("candles", "table", "c", "id"),))
    def test_time_zone_is_transaction_local(self, single_section, candle_shards):
        cursor = Mock()
        candle_shards.return_value = {
            "mode": "keyset-sharded-jsonb",
            "order_by": "id",
            "shard_size": 2,
            "row_count": 0,
            "shards": [],
        }

        decomposed_operational_snapshot(cursor, candle_shard_size=2)

        cursor.execute.assert_called_once_with("SET LOCAL TIME ZONE %s", ["America/Toronto"])
        single_section.assert_not_called()

    def test_keyset_shards_are_ordered_bounded_and_include_gaps(self):
        cursor = ScriptedCursor(
            [
                (2, 2, 3, "a" * 64),
                (1, 9, 9, "b" * 64),
                (0, None, None, None),
            ]
        )

        result = _candle_shards(cursor, shard_size=2)

        self.assertEqual(result["row_count"], 3)
        self.assertEqual([item["ordinal"] for item in result["shards"]], [1, 2])
        self.assertEqual([item["last_id"] for item in result["shards"]], [3, 9])
        self.assertEqual(cursor.parameters, [[0, 2], [3, 2], [9, 2]])

    def test_nonpositive_shard_size_fails_before_query(self):
        with self.assertRaisesMessage(ValueError, "shard size must be positive"):
            _candle_shards(ScriptedCursor([]), shard_size=0)


class Gate8IRoutingAndReadinessTests(SimpleTestCase):
    def successor(self):
        contract = SimpleNamespace(sha256=SUCCESSOR_CONTRACT_SHA256)
        plan = SimpleNamespace(
            sha256=SUCCESSOR_ACQUISITION_PLAN_SHA256,
            data_contract_id=1,
            data_contract=contract,
        )
        dataset = SimpleNamespace(manifest_sha256=SUCCESSOR_DATASET_MANIFEST_SHA256)
        return dataset, plan

    def test_only_the_complete_successor_identity_enters_gate8i(self):
        dataset, plan = self.successor()
        self.assertTrue(is_successor_registration(dataset, plan))

        dataset.manifest_sha256 = "f" * 64
        with self.assertRaisesMessage(DatasetQualityError, "partial successor"):
            is_successor_registration(dataset, plan)

    @patch("market.management.commands.register_failed_break_dataset.verify_registration_readiness")
    @patch(
        "market.management.commands.register_failed_break_dataset."
        "load_committed_registration_authorization"
    )
    @patch(
        "market.management.commands.register_failed_break_dataset."
        "verify_successor_registration_readiness"
    )
    @patch(
        "market.management.commands.register_failed_break_dataset.load_committed_gate8i_acceptance"
    )
    def test_command_routes_successor_dry_run_only_through_gate8i(
        self, successor_loader, successor_readiness, predecessor_loader, predecessor_readiness
    ):
        dataset, plan = self.successor()
        authorization = build_gate8i_acceptance()
        successor_loader.return_value = authorization
        successor_readiness.return_value = {
            "observed": {
                key: authorization[key]
                for key in (
                    "data_contract_sha256",
                    "replacement_plan_sha256",
                    "replacement_dataset_manifest_sha256",
                    "global_semantic_inventory_sha256",
                    "chunk_count",
                    "successful_attempt_count",
                    "ingestion_manifest_count",
                    "candle_count",
                    "granularity_candle_totals",
                    "logical_chunk_set_hash",
                    "successful_attempt_set_hash",
                    "ingestion_manifest_set_hash",
                    "candle_key_hash",
                    "candle_payload_hash",
                )
            }
        }
        output = StringIO()

        Command(stdout=output).handle_provider_observed(dataset, plan, {"execute": False})

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["checkpoint"], "dry-run")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["registrations_created"], 0)
        successor_readiness.assert_called_once_with(dataset, plan, authorization=authorization)
        predecessor_loader.assert_not_called()
        predecessor_readiness.assert_not_called()

    @patch("market.provider_observed_gate8i.current_decomposed_operational_snapshot")
    @patch("market.provider_observed_gate8i._successor_comparison")
    @patch("market.provider_observed_gate8i.verify_registration_readiness")
    @patch("market.provider_observed_gate8i.successor_gate8g_readiness")
    def test_readiness_reuses_existing_registration_path(
        self, gate8g, existing_readiness, comparison, snapshot
    ):
        dataset, plan = self.successor()
        authorization = build_gate8i_acceptance()
        gate8g.return_value = SimpleNamespace(complete=True, ready_keys=(), blocked_reason=None)
        existing_readiness.return_value = {"observed": {"candle_count": SUCCESSOR_CANDLE_COUNT}}
        comparison.return_value = {"overlap": PREDECESSOR_CANDLE_COUNT}
        snapshot.return_value = DECOMPOSED_SNAPSHOT

        result = verify_successor_registration_readiness(dataset, plan, authorization=authorization)

        existing_readiness.assert_called_once_with(dataset, plan, authorization=authorization)
        self.assertEqual(result["comparison"]["overlap"], PREDECESSOR_CANDLE_COUNT)
        self.assertEqual(result["decomposed_snapshot"], DECOMPOSED_SNAPSHOT)

    @patch("market.provider_observed_gate8i.successor_gate8g_readiness")
    def test_incomplete_acquisition_fails_before_registration_readiness(self, gate8g):
        dataset, plan = self.successor()
        gate8g.return_value = SimpleNamespace(
            complete=False, ready_keys=("still-ready",), blocked_reason=None
        )
        with self.assertRaisesMessage(DatasetQualityError, "not complete"):
            verify_successor_registration_readiness(
                dataset, plan, authorization=build_gate8i_acceptance()
            )


class Gate8IMigrationTests(SimpleTestCase):
    def test_one_function_delta_preserves_the_predecessor_body(self):
        migration = import_module("market.migrations.0027_gate8i_final_dataset_acceptance")

        self.assertTrue(migration.Migration.atomic)
        self.assertEqual(
            migration.Migration.dependencies,
            [("market", "0026_gate8g_successor_acquisition_activation")],
        )
        self.assertEqual(len(migration.Migration.operations), 1)
        self.assertEqual(len(migration.REQUIRED_0026_FUNCTIONS), 57)
        self.assertEqual(len(migration.REQUIRED_0026_TRIGGERS), 74)
        self.assertEqual(
            migration.GATE8I_REGISTRATION_PROSRC.replace(migration.SUCCESSOR_AUTHORITY_PROSRC, ""),
            migration.PRIOR_REGISTRATION_PROSRC,
        )
        self.assertIn(migration.FINAL_ACCEPTANCE_SHA256, migration.SUCCESSOR_AUTHORITY_PROSRC)
        self.assertIn("<>365055", migration.SUCCESSOR_AUTHORITY_PROSRC)
        self.assertIn("<>364953", migration.SUCCESSOR_AUTHORITY_PROSRC)
        self.assertIn("<>102", migration.SUCCESSOR_AUTHORITY_PROSRC)
        self.assertIn(")=17", migration.SUCCESSOR_AUTHORITY_PROSRC)
        self.assertIn(")=8", migration.SUCCESSOR_AUTHORITY_PROSRC)
        self.assertNotIn("CREATE TABLE", migration.GATE8I_REGISTRATION_PROSRC)
        self.assertNotIn("provider_request", migration.GATE8I_REGISTRATION_PROSRC)
