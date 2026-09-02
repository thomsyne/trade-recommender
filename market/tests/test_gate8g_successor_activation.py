import hashlib
from importlib import import_module
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from market.provider_observed_gate8g import (
    ARTIFACT_PATH,
    CANARY_INGESTION_MANIFEST_SHA256,
    GATE8F_OUTCOME_ARTIFACT_SHA256,
    GATE8G_CHUNK_COUNT,
    GATE8G_ORDERED_MANIFEST_SHA256,
    SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY,
    build_gate8f_outcome,
    evaluate_gate8g_readiness,
    load_committed_gate8f_outcome,
)


class Gate8GArtifactTests(SimpleTestCase):
    def test_artifact_file_pin_self_hash_and_manifest_reconstruct(self):
        document = load_committed_gate8f_outcome()

        self.assertEqual(
            hashlib.sha256(ARTIFACT_PATH.read_bytes()).hexdigest(),
            GATE8F_OUTCOME_ARTIFACT_SHA256,
        )
        self.assertEqual(document, build_gate8f_outcome())
        self.assertEqual(
            document["accepted_canary"]["ingestion_manifest_sha256"],
            CANARY_INGESTION_MANIFEST_SHA256,
        )
        self.assertTrue(document["accepted_canary"]["permanently_closed"])
        self.assertEqual(len(document["gate8g"]["chunks"]), GATE8G_CHUNK_COUNT)
        self.assertEqual(
            document["gate8g"]["ordered_manifest_sha256"],
            GATE8G_ORDERED_MANIFEST_SHA256,
        )
        self.assertNotIn(
            SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY,
            {entry["logical_key"] for entry in document["gate8g"]["chunks"]},
        )

    def test_artifact_excludes_operational_secrets_and_database_identity(self):
        prohibited = {
            "credential",
            "token",
            "approver",
            "username",
            "provider_request_id",
            "raw_body",
            "headers",
            "database_id",
            "hostname",
            "local_path",
        }

        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        self.assertFalse(prohibited & set(keys(load_committed_gate8f_outcome())))


class Gate8GReadinessTransitionTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.artifact = load_committed_gate8f_outcome()
        cls.canary_key = cls.artifact["accepted_canary"]["logical_key"]
        cls.remaining = [entry["logical_key"] for entry in cls.artifact["gate8g"]["chunks"]]

    def succeeded(self, key):
        return {
            "attempt_number": 1,
            "idempotency_key": f"failed-break-ingestion-attempt:{key}:1",
            "status": "succeeded",
            "accepted_manifest": True,
        }

    def state(self, **overrides):
        state = {self.canary_key: [self.succeeded(self.canary_key)]}
        state.update(overrides)
        return state

    def evaluate(self, states=None, *, canary_valid=True, registered=False):
        return evaluate_gate8g_readiness(
            artifact=self.artifact,
            attempt_states=self.state() if states is None else states,
            canary_valid=canary_valid,
            registered=registered,
        )

    def test_exact_canary_opens_exact_ordered_131_and_closes_canary(self):
        result = self.evaluate()

        self.assertTrue(result.canary_permanently_closed)
        self.assertEqual(result.ready_keys, tuple(self.remaining))
        self.assertNotIn(self.canary_key, result.ready_keys)
        self.assertFalse(result.complete)

    def test_absent_or_altered_canary_exposes_no_keys(self):
        self.assertEqual(self.evaluate({}, canary_valid=False).ready_keys, ())
        altered = self.state()
        altered[self.canary_key][0]["accepted_manifest"] = False
        self.assertEqual(self.evaluate(altered, canary_valid=False).ready_keys, ())

    def test_running_or_failed_successor_attempt_blocks_remaining_plan(self):
        key = self.remaining[0]
        for status in ("running", "failed", "quarantined"):
            attempt = self.succeeded(key)
            attempt["status"] = status
            attempt["accepted_manifest"] = False
            with self.subTest(status=status):
                self.assertEqual(self.evaluate(self.state(**{key: [attempt]})).ready_keys, ())

    def test_predecessor_registration_does_not_enter_successor_scope(self):
        # The evaluator intentionally has no global-registration input.  Only
        # the exact successor dataset's scoped ``registered`` flag can block.
        result = self.evaluate(registered=False)
        self.assertEqual(len(result.ready_keys), GATE8G_CHUNK_COUNT)

    def test_successor_registration_blocks_readiness(self):
        result = self.evaluate(registered=True)
        self.assertEqual(result.ready_keys, ())
        self.assertEqual(result.blocked_reason, "successor dataset is registered")

    def test_attempt_two_is_refused(self):
        key = self.remaining[0]
        attempt = self.succeeded(key)
        attempt["attempt_number"] = 2
        attempt["idempotency_key"] = f"failed-break-ingestion-attempt:{key}:2"
        result = self.evaluate(self.state(**{key: [attempt]}))
        self.assertEqual(result.ready_keys, ())
        self.assertIn("attempt", result.blocked_reason)

    def test_accepted_attempts_are_removed_in_manifest_order(self):
        completed = {key: [self.succeeded(key)] for key in self.remaining[:3]}
        result = self.evaluate(self.state(**completed))

        self.assertEqual(result.ready_keys, tuple(self.remaining[3:]))

    def test_complete_requires_all_132_accepted_manifests(self):
        states = self.state(**{key: [self.succeeded(key)] for key in self.remaining})
        result = self.evaluate(states)
        self.assertTrue(result.complete)
        self.assertEqual(result.ready_keys, ())

        states[self.remaining[-1]][0]["accepted_manifest"] = False
        result = self.evaluate(states)
        self.assertFalse(result.complete)
        self.assertEqual(result.ready_keys, ())


class Gate8GMigrationTests(SimpleTestCase):
    def test_delta_preserves_0025_body_and_predecessor_verifier(self):
        migration = import_module("market.migrations.0026_gate8g_successor_acquisition_activation")
        gate8e = import_module("market.migrations.0025_gate8e_successor_contract_materialization")

        self.assertEqual(migration.PRIOR_CANARY_PROSRC, gate8e.SUCCESSOR_CANARY_PROSRC)
        self.assertEqual(len(migration.REQUIRED_0025_FUNCTIONS), 56)
        self.assertEqual(len(migration.REQUIRED_0025_TRIGGERS), 74)
        self.assertEqual(
            migration.GATE8G_CANARY_PROSRC.count("market_verify_successor_canary_success"),
            1,
        )
        self.assertEqual(
            migration.GATE8G_CANARY_PROSRC.count("market_verify_replacement_canary_success"),
            1,
        )
        self.assertIn(
            "WHERE dr.dataset_version_id=dataset.id",
            migration.SUCCESSOR_VERIFY_PROSRC,
        )
        self.assertNotIn(
            "EXISTS (SELECT 1 FROM market_datasetregistration)", migration.SUCCESSOR_VERIFY_PROSRC
        )


class Gate8GCommandTests(SimpleTestCase):
    @patch("market.management.commands.run_successor_acquisition_wave.OandaClient")
    @patch("market.management.commands.run_successor_acquisition_wave.ready_gate8g_entries")
    @patch("market.management.commands.run_successor_acquisition_wave.successor_gate8g_readiness")
    @patch(
        "market.management.commands.run_successor_acquisition_wave.load_committed_gate8f_outcome"
    )
    def test_dry_run_is_explicitly_read_only_and_builds_no_client(
        self, load_artifact, readiness, entries, client
    ):
        from market.provider_observed_gate8g import Gate8GReadiness

        load_artifact.return_value = {"outcome_sha256": "accepted"}
        readiness.return_value = Gate8GReadiness(
            True, ("key",), False, None, GATE8G_ORDERED_MANIFEST_SHA256
        )
        entries.return_value = [
            {"ordinal": 2, "logical_key": "key", "expected_observation_count": 10}
        ]

        output = __import__("io").StringIO()
        call_command("run_successor_acquisition_wave", max_chunks=1, stdout=output)

        self.assertIn('"read_only": true', output.getvalue())
        self.assertIn('"provider_requests_performed": 0', output.getvalue())
        client.assert_not_called()
