"""Focused synthetic tests for the unauthorized v2 return runner."""

from __future__ import annotations

import ast
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError

from research import exploratory_return_runner_v2 as runner
from research import exploratory_return_runner_v2_governance as governance
from research import exploratory_returns_v2 as calculator
from research.benchmarks.benchmark_exploratory_returns_v2 import synthetic_event


def cohort():
    return [synthetic_event(index) for index in range(82)]


def execute(events=None, *, authorization=None, store=None, inject=None):
    rows = cohort() if events is None else events
    keys = tuple(sorted(row["physical_event_key"] for row in rows))
    adapter = runner.SyntheticEvidenceAdapter(rows, runner.synthetic_lineage())
    store = store or runner.SyntheticAtomicStore()
    payload = runner.run_authorized(
        authorization=authorization or runner.synthetic_authorization(),
        expected_keys=keys,
        adapter=adapter,
        store=store,
        bootstrap=False,
        inject_failure_after=inject,
    )
    return payload, adapter, store


class RunnerGovernanceTests(unittest.TestCase):
    def test_committed_preregistration_and_exact_82_keys(self):
        artifact = governance.load_preregistration()
        keys = governance.governed_event_keys()
        self.assertEqual((artifact["expected"]["physical_event_count"], len(set(keys))), (82, 82))
        self.assertNotIn(governance.BOUNDARY_PURGED_EVENT_KEY, keys)

    def test_default_command_reports_return_blind_authorized_readiness(self):
        output = io.StringIO()
        with mock.patch.object(
            runner,
            "readiness",
            return_value={
                "status": "AUTHORIZED_NOT_EXECUTED",
                "governed_physical_events": 82,
                "outcome_query_count": 0,
                "persistent_write_count": 0,
            },
        ):
            call_command("calculate_exploratory_returns_v2", stdout=output)
        self.assertIn("status=AUTHORIZED_NOT_EXECUTED", output.getvalue())
        self.assertIn("outcome_queries=0 writes=0", output.getvalue())

    def test_execute_environment_refusal_precedes_django_adapter_import(self):
        sys.modules.pop("research.exploratory_return_adapter_v2", None)
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            self.assertRaisesRegex(CommandError, "venv/bin/python|required"),
        ):
            call_command("calculate_exploratory_returns_v2", "--execute", stderr=io.StringIO())
        self.assertNotIn("research.exploratory_return_adapter_v2", sys.modules)

    def test_fixed_path_authorization_is_exact_and_has_no_override_api(self):
        state = governance.inspect_execution_authorization()
        self.assertEqual(state["status"], "AUTHORIZED_NOT_EXECUTED")
        self.assertTrue(state["present"])
        self.assertEqual(state["artifact_sha256"], governance.AUTHORIZATION_ARTIFACT_SHA256)
        self.assertNotIn("path", governance.require_execution_authorization.__code__.co_varnames)

    def test_forged_authority_and_promotion_fail_closed(self):
        forged = runner.synthetic_authorization()
        forged["authority"]["promotion"] = True
        with self.assertRaisesRegex(runner.RunnerRefusal, "authorization"):
            execute(authorization=forged)
        with self.assertRaisesRegex(governance.RunnerGovernanceRefusal, "permanently"):
            governance.require_promotion()

    def test_rehashed_preregistration_forgery_fails_closed(self):
        artifact = json.loads(governance.ARTIFACT_PATH.read_text())
        artifact["authority"]["persistent_execution"] = True
        body = dict(artifact)
        body.pop("implementation_sha256")
        artifact["implementation_sha256"] = governance.digest(body)
        with tempfile.TemporaryDirectory() as directory:
            forged = Path(directory) / "forged.json"
            forged.write_bytes(governance.canonical_bytes(artifact) + b"\n")
            with mock.patch.object(governance, "ARTIFACT_PATH", forged):
                with self.assertRaisesRegex(governance.RunnerGovernanceRefusal, "artifact digest"):
                    governance.load_preregistration()


class RunnerSyntheticPersistenceTests(unittest.TestCase):
    def test_complete_82_event_result_is_one_immutable_payload(self):
        payload, adapter, store = execute()
        self.assertEqual(payload["input_manifest"]["event_count"], 82)
        self.assertEqual(len(payload["report"]["event_results"]), 82)
        self.assertEqual(len(store.rows), 1)
        body = dict(payload)
        claimed = body.pop("evidence_sha256")
        self.assertEqual(claimed, calculator.digest(body))
        self.assertEqual(
            adapter.query_counts, {"return_blind_lineage": 1, "sealed_outcome_preload": 1}
        )
        self.assertEqual(
            store.query_counts,
            {"duplicate_check": 1, "result_insert": 1, "readback_verify": 1},
        )

    def test_missing_extra_duplicate_and_purged_event_refuse(self):
        original = cohort()
        cases = [
            original[:-1],
            [*original, synthetic_event(999)],
            [*original[:-1], copy.deepcopy(original[0])],
        ]
        for rows in cases:
            with self.subTest(size=len(rows)), self.assertRaises(runner.RunnerRefusal):
                keys = tuple(f"expected-{index}" for index in range(82))
                runner.run_authorized(
                    authorization=runner.synthetic_authorization(),
                    expected_keys=keys,
                    adapter=runner.SyntheticEvidenceAdapter(rows, runner.synthetic_lineage()),
                    store=runner.SyntheticAtomicStore(),
                    bootstrap=False,
                )
        purged = cohort()
        purged[0]["physical_event_key"] = governance.BOUNDARY_PURGED_EVENT_KEY
        with self.assertRaises(runner.RunnerRefusal):
            execute(purged)

    def test_book_memberships_are_nonadditive(self):
        rows = cohort()
        rows[0]["books"] = [
            "failed-break-any-level-deduplicated-v1",
            "failed-break-daily-swing-v1",
            "failed-break-weekly-extreme-v1",
        ]
        payload, _, _ = execute(rows)
        self.assertEqual(payload["report"]["event_count"], 82)
        self.assertEqual(len(payload["report"]["event_results"]), 82)

    def test_missing_conflicting_unsealed_or_unresolved_aborts_without_write(self):
        mutations = (
            lambda event: event["h1"].pop(),
            lambda event: event["h1"][0].update(conflict=True),
            lambda event: event["h1"][0].update(sealed=False),
            lambda event: event.update(conversion={}),
        )
        for mutate in mutations:
            rows = cohort()
            mutate(rows[0])
            store = runner.SyntheticAtomicStore()
            with self.assertRaises(runner.RunnerRefusal):
                execute(rows, store=store)
            self.assertEqual(store.rows, {})

    def test_wrong_lineage_and_v1_substitution_refuse_before_outcomes(self):
        for field, value in (
            ("dataset_version", "phase-2b1r-v1"),
            ("strategy_version", "failed-break-phase-1-freeze-v1"),
            ("s1_outcome", "UNACCEPTED"),
            ("s2_policy", "DRAFT"),
        ):
            lineage = runner.synthetic_lineage()
            lineage[field] = value
            adapter = runner.SyntheticEvidenceAdapter(cohort(), lineage)
            store = runner.SyntheticAtomicStore()
            with self.assertRaises(runner.RunnerRefusal):
                runner.run_authorized(
                    authorization=runner.synthetic_authorization(),
                    expected_keys=tuple(row["physical_event_key"] for row in cohort()),
                    adapter=adapter,
                    store=store,
                    bootstrap=False,
                )
            self.assertNotIn("sealed_outcome_preload", adapter.query_counts)
            self.assertEqual(store.rows, {})

    def test_duplicate_refusal_and_atomic_rollback_at_every_stage(self):
        store = runner.SyntheticAtomicStore()
        execute(store=store)
        with self.assertRaisesRegex(runner.RunnerRefusal, "already exists"):
            execute(store=store)
        for stage in ("calculation", "insert", "readback"):
            fresh = runner.SyntheticAtomicStore()
            with (
                self.subTest(stage=stage),
                self.assertRaisesRegex(runner.RunnerRefusal, "injected"),
            ):
                execute(store=fresh, inject=stage)
            self.assertEqual(fresh.rows, {})

    def test_report_and_section_hashes_reconstruct(self):
        payload, _, _ = execute()
        report = payload["report"]
        self.assertEqual(
            report["report_sha256"],
            calculator.digest({k: v for k, v in report.items() if k != "report_sha256"}),
        )
        self.assertEqual(
            report["hashes"]["event_results_sha256"], calculator.digest(report["event_results"])
        )
        self.assertEqual(
            report["hashes"]["cost_scenarios_sha256"], calculator.digest(report["cost_scenarios"])
        )
        self.assertEqual(
            payload["output_hashes"]["equity_paths_sha256"],
            calculator.digest(
                {
                    risk: body["daily_equity"]
                    for risk, body in sorted(report["fixed_capital"].items())
                }
            ),
        )
        self.assertTrue(payload["authority"]["promotion_permanently_prohibited"])

    def test_production_adapter_has_no_per_event_orm_lookup(self):
        source = Path("research/exploratory_return_adapter_v2.py").read_text()
        tree = ast.parse(source)
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_normalize_event"
        )
        rendered = ast.unparse(method)
        self.assertNotIn(".objects", rendered)
        self.assertNotIn("cursor", rendered)


if __name__ == "__main__":
    unittest.main()
