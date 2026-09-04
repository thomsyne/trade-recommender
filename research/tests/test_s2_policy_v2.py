"""Focused offline tests for the effective exploratory-only v2 S2 freeze."""

import ast
import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from research import s2_policy as v1
from research import s2_policy_v2 as s2


class ArtifactTests(unittest.TestCase):
    def test_canonical_artifact_self_hash_report_and_fixed_sources(self):
        policy = s2.load_policy()
        self.assertEqual(policy["policy_sha256"], s2.POLICY_SHA256)
        self.assertEqual(
            hashlib.sha256(s2.ARTIFACT_PATH.read_bytes()).hexdigest(), s2.ARTIFACT_SHA256
        )
        self.assertEqual(hashlib.sha256(s2.REPORT_PATH.read_bytes()).hexdigest(), s2.REPORT_SHA256)
        self.assertEqual(s2.canonical_bytes(policy) + b"\n", s2.ARTIFACT_PATH.read_bytes())
        self.assertEqual(
            policy["source_bindings"]["v2_s1_acceptance"]["artifact_sha256"], s2.S1_ARTIFACT_SHA256
        )
        self.assertEqual(
            policy["source_bindings"]["v2_geometry"]["artifact_sha256"], s2.GEOMETRY_ARTIFACT_SHA256
        )
        self.assertEqual(
            policy["source_bindings"]["v2_geometry"]["event_set_sha256"], s2.EVENT_SET_SHA256
        )
        self.assertEqual(
            policy["source_bindings"]["v2_geometry"]["memberships_sha256"], s2.MEMBERSHIPS_SHA256
        )

    def test_v1_policy_is_separate_unchanged_and_all_seven_decisions_reused(self):
        original = v1.load_policy()
        policy = s2.load_policy()
        source = policy["source_bindings"]["accepted_v1_policy"]
        self.assertFalse(source["v1_automatic_governance_of_v2"])
        self.assertEqual(source["artifact_sha256"], v1.ARTIFACT_SHA256)
        self.assertEqual(source["policy_sha256"], v1.POLICY_SHA256)
        self.assertEqual(source["decision_hashes"], s2.V1_DECISION_HASHES)
        self.assertEqual(
            [row["id"] for row in original["decision_ledger"]], [f"S2-{n:02d}" for n in range(1, 8)]
        )
        self.assertEqual(
            hashlib.sha256(v1.ARTIFACT_PATH.read_bytes()).hexdigest(), s2.V1_ARTIFACT_SHA256
        )

    def test_v1_decision_or_geometry_mutation_fails_closed(self):
        altered_v1 = copy.deepcopy(v1.load_policy())
        altered_v1["decision_ledger"][0]["recommendation"]["margin"] = "BROKER_LEVERAGE"
        with patch.object(s2.policy_v1, "load_policy", return_value=altered_v1):
            with self.assertRaisesRegex(s2.V2PolicyRefusal, "v1 decision bytes changed"):
                s2.load_policy()
        geometry = s2.geometry_v2.verify_committed()
        altered_geometry = copy.deepcopy(geometry)
        altered_geometry["memberships_sha256"] = "0" * 64
        with patch.object(s2.geometry_v2, "verify_committed", return_value=altered_geometry):
            with self.assertRaisesRegex(s2.V2PolicyRefusal, "geometry identity changed"):
                s2.load_policy()

    def test_rehashed_forgery_still_fails_fixed_file_digest(self):
        artifact = copy.deepcopy(s2.load_policy())
        artifact["boundary"]["promotion_eligible"] = True
        body = dict(artifact)
        body.pop("policy_sha256")
        artifact["policy_sha256"] = s2.digest(body)
        with tempfile.TemporaryDirectory() as directory:
            forged = Path(directory) / "forged.json"
            forged.write_bytes(s2.canonical_bytes(artifact) + b"\n")
            with patch.object(s2, "ARTIFACT_PATH", forged):
                with self.assertRaisesRegex(s2.V2PolicyRefusal, "artifact file digest mismatch"):
                    s2.load_policy()


class PolicyBoundaryTests(unittest.TestCase):
    def test_geometry_and_primary_accounting_unit_are_exact(self):
        policy = s2.load_policy()
        geometry = policy["geometry_policy"]
        unit = policy["primary_return_unit"]
        self.assertEqual(geometry["geometry_eligible_physical_events"], 82)
        self.assertEqual(geometry["book_memberships"], 186)
        self.assertEqual(geometry["entry_dates"], 76)
        self.assertEqual(geometry["effective_sample"]["entry_week_kish_exact"], "1681/28")
        self.assertEqual(geometry["effective_sample"]["shared_factor_kish_exact"], "3362/55")
        self.assertEqual(unit["unit"], "UNIQUE_PHYSICAL_EVENT")
        self.assertEqual(unit["primary_result"], "NORMALIZED_PHYSICAL_EVENT_RETURN_R")
        self.assertEqual(unit["terminal_classification_required"], 82)
        self.assertFalse(unit["book_memberships_are_independent_trades"])
        self.assertFalse(unit["duplicated_capital_for_multiple_books"])

    def test_multiple_books_collapse_to_one_event_risk_budget(self):
        rows = [
            {"physical_event_key": "event-a", "book": "combined"},
            {"physical_event_key": "event-a", "book": "daily"},
            {"physical_event_key": "event-b", "book": "combined"},
        ]
        budgets = s2.physical_event_risk_budgets(rows, "25")
        self.assertEqual(set(budgets), {"event-a", "event-b"})
        self.assertEqual(
            budgets["event-a"], {"books": ["combined", "daily"], "shared_risk_cad": "25"}
        )
        self.assertEqual(sum(float(row["shared_risk_cad"]) for row in budgets.values()), 50)
        with self.assertRaisesRegex(s2.V2PolicyRefusal, "duplicate"):
            s2.physical_event_risk_budgets(rows + [rows[0]], "25")

    def test_fixed_cad_10000_diagnostic_is_exact_and_non_compounding(self):
        diagnostic = s2.load_policy()["fixed_capital_diagnostic"]
        self.assertEqual(diagnostic["reference_capital_cad"], "10000")
        self.assertEqual(
            diagnostic["risk_grid"],
            [
                {"cad_per_physical_event": "25", "fraction_of_reference_capital": "0.0025"},
                {"cad_per_physical_event": "50", "fraction_of_reference_capital": "0.0050"},
                {"cad_per_physical_event": "100", "fraction_of_reference_capital": "0.0100"},
            ],
        )
        self.assertFalse(diagnostic["compounding"])
        self.assertFalse(diagnostic["deposits_or_withdrawals"])
        self.assertFalse(diagnostic["retrospective_position_size_adjustment"])
        self.assertTrue(diagnostic["same_event_books_share_risk"])
        self.assertEqual(
            diagnostic["concurrent_event_risk"],
            "EACH_OPEN_PHYSICAL_EVENT_RETAINS_ITS_INDIVIDUAL_FIXED_RISK",
        )
        self.assertTrue(diagnostic["diagnostic_only"])
        self.assertTrue(diagnostic["no_leveraged_target_forcing_scenario"])
        self.assertIn("peak_aggregate_open_risk_cad", diagnostic["outputs_each_risk_level"])
        self.assertEqual(len(diagnostic["outputs_each_risk_level"]), 16)

    def test_cost_grid_and_optimistic_slippage_limit_are_exact(self):
        cost = s2.load_policy()["cost_policy"]
        grid = cost["sensitivity_grid"]
        self.assertEqual(cost["additional_slippage_pips"], "0")
        self.assertEqual(cost["additional_slippage_model"], "NONE")
        self.assertEqual(
            grid["axes"], ["round_turn_commission_pips", "annual_notional_financing_rates"]
        )
        self.assertEqual(grid["round_turn_commission_pips"], [0, 0.5, 1])
        self.assertEqual(grid["annual_notional_financing_rates"], [-0.06, -0.03, 0, 0.03, 0.06])
        self.assertEqual(grid["cell_count"], 15)
        self.assertFalse(grid["slippage_axis"])
        self.assertEqual(cost["optimistic_limitation"]["assessment"], "OPTIMISTIC_LIMITATION")
        self.assertIn("GROSS_R", cost["net_R"])

    def test_statistical_grids_bootstrap_and_descriptive_metrics_are_frozen(self):
        statistical = s2.load_policy()["statistical_policy"]
        self.assertEqual(statistical["geometry_mde_diagnostic"]["sigma_R"], ["0.5", "1.0", "1.5"])
        self.assertEqual(
            statistical["geometry_mde_diagnostic"]["adequacy"],
            {"0.5": "ADEQUATE", "1.0": "INADEQUATE", "1.5": "INADEQUATE"},
        )
        self.assertEqual(
            statistical["hypothetical_statistical_sensitivity"]["sigma_R"], ["0.5", "1.0", "2.0"]
        )
        self.assertFalse(statistical["grids_interchangeable"])
        self.assertEqual(statistical["bootstrap"]["replicates"], 10_000)
        self.assertEqual(statistical["bootstrap"]["confidence_level"], "0.95")
        self.assertEqual(
            statistical["sharpe_sortino"], "DESCRIPTIVE_ONLY_NOT_TUNING_SELECTION_OR_ACCEPTANCE"
        )
        self.assertEqual(statistical["confirmatory_or_promotional_interpretation"], "PROHIBITED")

    def test_permanent_nonpromotion_and_every_override_are_powerless(self):
        policy = s2.load_policy()
        self.assertTrue(policy["boundary"]["exploratory_only"])
        self.assertFalse(policy["boundary"]["promotion_eligible"])
        self.assertTrue(policy["boundary"]["promotion_permanently_prohibited"])
        for override in (
            {"owner": True},
            {"cli": True},
            {"environment": True},
            {"database": True},
            {"data_only": True},
            {"successful_future_outcome": True},
            {"threshold_reinterpretation_after_results": True},
        ):
            with self.subTest(override=override):
                with self.assertRaisesRegex(s2.V2PolicyRefusal, "permanently prohibited"):
                    s2.require_strategy_promotion(**override)

    def test_return_implementation_and_execution_remain_separately_unauthorized(self):
        for function in (
            s2.require_return_calculator_implementation,
            s2.require_persistent_return_execution,
        ):
            for override in ({}, {"owner": True}, {"successful_future_outcome": True}):
                with self.subTest(function=function.__name__, override=override):
                    with self.assertRaisesRegex(s2.V2PolicyRefusal, "separately unauthorized"):
                        function(**override)
        readiness = s2.readiness()
        self.assertTrue(readiness["returns_blocked"])
        self.assertFalse(readiness["return_calculator_implementation_authorized"])
        self.assertFalse(readiness["persistent_return_execution_authorized"])


class IsolationTests(unittest.TestCase):
    def test_loader_uses_only_fixed_offline_artifacts_and_never_live_projection(self):
        with patch.object(
            s2.geometry_v2, "read_research_once", side_effect=AssertionError("live access")
        ) as live:
            policy = s2.load_policy()
        live.assert_not_called()
        self.assertEqual(
            policy["freeze_provenance"],
            {
                "candle_or_post_entry_price_access": False,
                "database_access": False,
                "outcome_evidence_access": False,
                "provider_credential_or_network_access": False,
                "return_or_pnl_calculated": False,
                "sources": [
                    "COMMITTED_EFFECTIVE_V1_S2_POLICY",
                    "COMMITTED_ACCEPTED_V2_S1_OUTCOME",
                    "COMMITTED_RETURN_BLIND_V2_GEOMETRY",
                    "OWNER_AUTHORIZATION_2026-09-04",
                ],
            },
        )
        tree = ast.parse(s2.Path(s2.__file__).read_text())
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported |= {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertTrue({"django", "psycopg", "requests", "subprocess"}.isdisjoint(imported))

    def test_cli_readiness_and_all_refusal_modes(self):
        for flag in ("--require-frozen",):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                s2.main([flag])
            result = json.loads(stdout.getvalue())
            self.assertEqual(
                result["status"], "EFFECTIVE_V2_EXPLORATORY_ONLY_RETURNS_SEPARATELY_UNAUTHORIZED"
            )
        for flag in (
            "--require-return-implementation",
            "--require-return-execution",
            "--require-promotion",
        ):
            with self.subTest(flag=flag):
                stderr = io.StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
                    s2.main([flag])
                self.assertEqual(stopped.exception.code, 2)
                self.assertIn("refused", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
