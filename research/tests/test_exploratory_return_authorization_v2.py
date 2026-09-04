from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.db import connection

from research import exploratory_return_adapter_v2 as django_adapter
from research import exploratory_return_runner_v2 as runner
from research import exploratory_return_runner_v2_governance as governance
from research.benchmarks.benchmark_exploratory_returns_v2 import synthetic_event


def cohort():
    return [synthetic_event(index) for index in range(82)]


def exact_environment():
    return {
        "EXPLORATORY_RETURN_NETWORK_POLICY": governance.REQUIRED_NETWORK_POLICY,
        "PATH": f"/usr/bin:{governance.REQUIRED_POSTGRES_PATH}",
        "POSTGRES_CONN_MAX_AGE": "0",
        "POSTGRES_DB": governance.REQUIRED_DATABASE,
        "POSTGRES_HOST": governance.REQUIRED_DATABASE_HOST,
    }


def write_rehashed(document, directory):
    body = copy.deepcopy(document)
    body.pop("authorization_sha256", None)
    document["authorization_sha256"] = governance.digest(body)
    raw = governance.canonical_bytes(document) + b"\n"
    path = Path(directory) / "authorization.json"
    path.write_bytes(raw)
    return path, raw, document["authorization_sha256"]


class ExploratoryReturnExecutionAuthorizationTests(unittest.TestCase):
    def test_exact_artifact_and_authority(self):
        authorization = governance.inspect_execution_authorization()
        self.assertEqual(authorization["status"], "AUTHORIZED_NOT_EXECUTED")
        self.assertEqual(authorization["bindings"]["geometry"]["physical_events"], 82)
        self.assertEqual(authorization["bindings"]["geometry"]["nonadditive_book_memberships"], 186)
        self.assertEqual(authorization["command"]["operational_ceiling_seconds"], 900)
        self.assertEqual(
            authorization["command"]["memory_ceiling_bytes"],
            1_073_741_824,
        )
        self.assertEqual(
            authorization["result"]["expected_delta"],
            {"research_jobrun": 1, "every_other_application_table": 0},
        )
        self.assertEqual(authorization["authority"]["promotion"], "PERMANENTLY_PROHIBITED")
        self.assertEqual(authorization["authority"]["live_trading"], "PERMANENTLY_PROHIBITED")

    def test_predecessor_is_consumed_and_failure_query_count_is_unknown(self):
        predecessor = governance.inspect_predecessor_authorization_history()
        failure = governance.inspect_failed_execution()
        self.assertEqual(predecessor["status"], "CONSUMED_PRE_OUTCOME_FAILURE_RETRY_PROHIBITED")
        self.assertEqual(failure["attempt"]["total_sql_query_count"], "UNKNOWN_NOT_INSTRUMENTED")
        self.assertFalse(failure["attempt"]["reached_outcome_loading"])
        self.assertFalse(failure["attempt"]["reached_transaction_entry"])
        self.assertEqual(failure["persistent_state"]["persistent_writes"], 0)
        with self.assertRaisesRegex(governance.RunnerGovernanceRefusal, "consumed"):
            governance.require_predecessor_execution_authorization()
        self.assertEqual(
            hashlib.sha256(governance.PREDECESSOR_AUTHORIZATION_PATH.read_bytes()).hexdigest(),
            governance.PREDECESSOR_AUTHORIZATION_ARTIFACT_SHA256,
        )

    def test_missing_or_rehashed_forged_failure_refuses_successor(self):
        failure = json.loads(governance.FAILURE_PATH.read_bytes())
        failure["persistent_state"]["result_rows"] = 1
        body = copy.deepcopy(failure)
        body.pop("failure_sha256")
        failure["failure_sha256"] = governance.digest(body)
        raw = governance.canonical_bytes(failure) + b"\n"
        with tempfile.TemporaryDirectory() as directory:
            forged = Path(directory) / "failure.json"
            forged.write_bytes(raw)
            with (
                mock.patch.object(governance, "FAILURE_PATH", Path(directory) / "missing.json"),
                self.assertRaises(governance.RunnerGovernanceRefusal),
            ):
                governance.inspect_execution_authorization()
            with (
                mock.patch.object(governance, "FAILURE_PATH", forged),
                mock.patch.object(
                    governance, "FAILURE_ARTIFACT_SHA256", hashlib.sha256(raw).hexdigest()
                ),
                mock.patch.object(governance, "FAILURE_SELF_SHA256", failure["failure_sha256"]),
                self.assertRaisesRegex(
                    governance.RunnerGovernanceRefusal, "persistent failure state"
                ),
            ):
                governance.inspect_execution_authorization()

    def test_missing_or_rehashed_forged_authority_refuses(self):
        document = json.loads(governance.AUTHORIZATION_PATH.read_bytes())
        document["authority"]["promotion"] = "AUTHORIZED"
        with tempfile.TemporaryDirectory() as directory:
            forged, raw, self_hash = write_rehashed(document, directory)
            missing = Path(directory) / "missing.json"
            with (
                mock.patch.object(governance, "AUTHORIZATION_PATH", missing),
                self.assertRaises(governance.RunnerGovernanceRefusal),
            ):
                governance.inspect_execution_authorization()
            with (
                mock.patch.object(governance, "AUTHORIZATION_PATH", forged),
                mock.patch.object(
                    governance, "AUTHORIZATION_ARTIFACT_SHA256", hashlib.sha256(raw).hexdigest()
                ),
                mock.patch.object(governance, "AUTHORIZATION_SELF_SHA256", self_hash),
                self.assertRaisesRegex(governance.RunnerGovernanceRefusal, "authority changed"),
            ):
                governance.inspect_execution_authorization()

    def test_predecessor_artifact_cannot_substitute_for_successor(self):
        with (
            mock.patch.object(
                governance, "AUTHORIZATION_PATH", governance.PREDECESSOR_AUTHORIZATION_PATH
            ),
            mock.patch.object(
                governance,
                "AUTHORIZATION_ARTIFACT_SHA256",
                governance.PREDECESSOR_AUTHORIZATION_ARTIFACT_SHA256,
            ),
            mock.patch.object(
                governance,
                "AUTHORIZATION_SELF_SHA256",
                governance.PREDECESSOR_AUTHORIZATION_SELF_SHA256,
            ),
            self.assertRaises(governance.RunnerGovernanceRefusal),
        ):
            governance.inspect_execution_authorization()

    def test_every_upstream_hash_mutation_refuses_even_when_rehashed(self):
        original = json.loads(governance.AUTHORIZATION_PATH.read_bytes())

        def hash_paths(value, path=()):
            for key, child in value.items():
                child_path = (*path, key)
                if key.endswith("sha256") and isinstance(child, str):
                    yield child_path
                elif isinstance(child, dict):
                    yield from hash_paths(child, child_path)

        paths = list(hash_paths(original["bindings"], ("bindings",)))
        self.assertGreaterEqual(len(paths), 20)
        for path in paths:
            with self.subTest(path=".".join(path)), tempfile.TemporaryDirectory() as directory:
                document = copy.deepcopy(original)
                target = document
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = "0" * 64
                forged, raw, self_hash = write_rehashed(document, directory)
                with (
                    mock.patch.object(governance, "AUTHORIZATION_PATH", forged),
                    mock.patch.object(
                        governance,
                        "AUTHORIZATION_ARTIFACT_SHA256",
                        hashlib.sha256(raw).hexdigest(),
                    ),
                    mock.patch.object(governance, "AUTHORIZATION_SELF_SHA256", self_hash),
                    self.assertRaises(governance.RunnerGovernanceRefusal),
                ):
                    governance.inspect_execution_authorization()

    def test_exact_environment_passes_and_every_boundary_mutation_refuses(self):
        with (
            mock.patch.dict(os.environ, exact_environment(), clear=True),
            mock.patch.object(sys, "executable", str(governance.ROOT / ".venv/bin/python")),
            mock.patch.object(governance.platform, "machine", return_value="arm64"),
        ):
            self.assertEqual(
                governance.validate_execution_environment()["database"],
                "trade_recommender_research",
            )
        mutations = (
            ("POSTGRES_DB", "trade_recommender"),
            ("POSTGRES_HOST", "localhost"),
            ("POSTGRES_CONN_MAX_AGE", "60"),
            ("EXPLORATORY_RETURN_NETWORK_POLICY", "ALLOW_ALL"),
            ("PATH", "/usr/bin"),
            ("OANDA_TOKEN", "present"),
        )
        for key, value in mutations:
            environment = exact_environment()
            environment[key] = value
            with (
                self.subTest(key=key),
                mock.patch.dict(os.environ, environment, clear=True),
                mock.patch.object(sys, "executable", str(governance.ROOT / ".venv/bin/python")),
                mock.patch.object(governance.platform, "machine", return_value="arm64"),
                self.assertRaises(governance.RunnerGovernanceRefusal),
            ):
                governance.validate_execution_environment()

    def test_failed_authorization_or_environment_precedes_adapter_import(self):
        sys.modules.pop("research.exploratory_return_adapter_v2", None)
        with (
            mock.patch.object(
                governance,
                "inspect_execution_authorization",
                side_effect=governance.RunnerGovernanceRefusal("missing"),
            ),
            self.assertRaises(governance.RunnerGovernanceRefusal),
        ):
            runner.execute_persistent()
        self.assertNotIn("research.exploratory_return_adapter_v2", sys.modules)

    def test_limit_setup_failure_precedes_worker_outcomes_and_writes(self):
        watchdog = mock.Mock()
        with (
            mock.patch.object(governance, "load_preregistration"),
            mock.patch.object(
                governance,
                "require_execution_authorization",
                return_value=runner.synthetic_authorization(
                    artifact_sha256=governance.AUTHORIZATION_ARTIFACT_SHA256,
                    policy_sha256=governance.S2_POLICY_SHA256,
                ),
            ),
            mock.patch.object(governance, "governed_event_keys", return_value=tuple(range(82))),
            mock.patch.object(
                runner.memory_boundary,
                "operational_boundary",
                side_effect=runner.memory_boundary.MemoryBoundaryFailure("setup failed"),
            ),
            mock.patch.object(runner.memory_boundary, "run_isolated_worker", watchdog),
            self.assertRaisesRegex(runner.RunnerRefusal, "setup failed"),
        ):
            runner.execute_persistent()
        watchdog.assert_not_called()
        with (
            mock.patch.object(
                governance,
                "validate_execution_environment",
                side_effect=governance.RunnerGovernanceRefusal("environment"),
            ),
            self.assertRaises(governance.RunnerGovernanceRefusal),
        ):
            runner.execute_persistent()
        self.assertNotIn("research.exploratory_return_adapter_v2", sys.modules)

    def test_prior_or_partial_result_refuses_before_outcome_loading(self):
        rows = cohort()
        adapter = runner.SyntheticEvidenceAdapter(rows, runner.synthetic_lineage())
        store = runner.SyntheticAtomicStore({runner.IDEMPOTENCY_KEY: {"partial": True}})
        with self.assertRaisesRegex(runner.RunnerRefusal, "already exists"):
            runner.run_authorized(
                authorization=runner.synthetic_authorization(),
                expected_keys=tuple(row["physical_event_key"] for row in rows),
                adapter=adapter,
                store=store,
                bootstrap=False,
            )
        self.assertNotIn("sealed_outcome_preload", adapter.query_counts)
        self.assertEqual(store.rows, {runner.IDEMPOTENCY_KEY: {"partial": True}})

    def test_wrong_database_identity_refuses_before_upstream_or_outcome_access(self):
        cursor = mock.MagicMock()
        cursor.__enter__.return_value.fetchone.return_value = ("trade_recommender", None)
        adapter = django_adapter.DjangoSealedEvidenceAdapter()
        with (
            mock.patch.object(django_adapter.connection, "cursor", return_value=cursor),
            mock.patch.object(
                django_adapter.s1_outcome, "load_v2_s1_outcome_acceptance"
            ) as upstream,
            self.assertRaisesRegex(runner.RunnerRefusal, "exact local research database"),
        ):
            adapter.verify_return_blind_lineage()
        upstream.assert_not_called()
        self.assertNotIn("sealed_outcome_preload", adapter.query_counts)

    def test_progress_is_count_only_and_favourable_result_cannot_promote(self):
        rows = cohort()
        messages = []
        payload = runner.run_authorized(
            authorization=runner.synthetic_authorization(),
            expected_keys=tuple(row["physical_event_key"] for row in rows),
            adapter=runner.SyntheticEvidenceAdapter(rows, runner.synthetic_lineage()),
            store=runner.SyntheticAtomicStore(),
            bootstrap=False,
            progress=lambda stage, completed, total: messages.append((stage, completed, total)),
        )
        self.assertEqual(
            messages,
            [
                ("upstream_evidence", 1, 1),
                ("cohort_reconstruction", 82, 82),
                ("entry_evidence", 82, 82),
                ("sealed_inventory", 82, 82),
                ("evidence_plan", 82, 82),
                ("sealed_candles", 82, 82),
                ("normalization", 82, 82),
                ("normalized", 82, 82),
                ("calculation", 0, 82),
                ("calculation", 82, 82),
                ("commit", 0, 1),
                ("commit", 1, 1),
            ],
        )
        rendered = repr(messages).lower()
        for forbidden in ("return", "pnl", "profit", "win", "loss", "drawdown"):
            self.assertNotIn(forbidden, rendered)
        self.assertTrue(payload["authority"]["promotion_permanently_prohibited"])
        with self.assertRaisesRegex(governance.RunnerGovernanceRefusal, "permanently"):
            governance.require_promotion(payload)

    def test_calculator_adapter_and_command_sources_remain_exact(self):
        expected = {
            "research/management/commands/calculate_exploratory_returns_v2.py": (
                governance.COMMAND_SHA256
            ),
            "research/exploratory_returns_v2.py": governance.calculator_governance.CALCULATOR_SHA256,
        }
        for relative, digest in expected.items():
            self.assertEqual(
                hashlib.sha256((governance.ROOT / relative).read_bytes()).hexdigest(), digest
            )

    def test_exact_migrations_are_checked_before_wrapped_lineage(self):
        wrapped = SimpleNamespace(
            query_counts={}, verify_return_blind_lineage=mock.Mock(return_value={})
        )
        adapter = runner._MigrationCheckedAdapter(wrapped)
        cursor = mock.MagicMock()
        cursor.__enter__.return_value.fetchall.return_value = [
            ("market", "0027_gate8i_final_dataset_acceptance", 27),
            ("research", "0015_pre_s1_inventory_entry_boundary", 15),
        ]
        with mock.patch.object(connection, "cursor", return_value=cursor):
            self.assertEqual(adapter.verify_return_blind_lineage(), {})
        wrapped.verify_return_blind_lineage.assert_called_once_with()
        cursor.__enter__.return_value.fetchall.return_value[-1] = (
            "research",
            "0014_enforce_entry_boundary",
            14,
        )
        wrapped.verify_return_blind_lineage.reset_mock()
        with (
            mock.patch.object(connection, "cursor", return_value=cursor),
            self.assertRaisesRegex(runner.RunnerRefusal, "migration state"),
        ):
            adapter.verify_return_blind_lineage()
        wrapped.verify_return_blind_lineage.assert_not_called()

    def test_readiness_sql_audit_refuses_writes_prices_and_outcome_rows(self):
        audit = runner._ReadOnlyQueryAudit()
        execute = mock.Mock(return_value="ok")
        self.assertEqual(audit(execute, "SELECT count(*) FROM market_candle", (), False, {}), "ok")
        for sql in (
            "INSERT INTO research_jobrun VALUES (1)",
            "SELECT bid_open FROM market_candle",
            "SELECT * FROM forecasts_papertraderesult",
        ):
            with self.subTest(sql=sql), self.assertRaises(runner.RunnerRefusal):
                audit(execute, sql, (), False, {})

    def test_committed_disposable_rehearsal_proves_unique_and_rollback(self):
        path = governance.DOCS / "exploratory-return-authorization-rehearsal-v2.json"
        rehearsal = json.loads(path.read_bytes())
        self.assertEqual(
            rehearsal["authorization_artifact_sha256"],
            governance.PREDECESSOR_AUTHORIZATION_ARTIFACT_SHA256,
        )
        self.assertEqual(
            rehearsal["concurrency"]["outcomes"],
            ["COMMITTED", "UNIQUE_CONSTRAINT_REFUSAL"],
        )
        self.assertEqual(rehearsal["concurrency"]["rows_after"], 1)
        self.assertEqual(rehearsal["rollback"]["insert"]["rows_after"], 0)
        self.assertEqual(rehearsal["rollback"]["readback"]["rows_after"], 0)
        self.assertEqual(
            rehearsal["rows_written_by_table"],
            {"research_jobrun": 1, "every_other_application_table": 0},
        )

    def test_successor_rehearsal_proves_watchdog_rollback_and_unique_refusal(self):
        evidence = governance.inspect_correction_evidence()
        rehearsal = json.loads(governance.PERFORMANCE_EVIDENCE_PATH.read_bytes())
        self.assertEqual(evidence["rehearsal_sha256"], governance.PERFORMANCE_EVIDENCE_SHA256)
        self.assertTrue(rehearsal["synthetic"]["deterministic_hashes"])
        self.assertLess(rehearsal["synthetic"]["maximum_duration_seconds"], 10)
        self.assertLess(rehearsal["synthetic"]["maximum_process_tree_rss_bytes"], 1_073_741_824)


if __name__ == "__main__":
    unittest.main()
