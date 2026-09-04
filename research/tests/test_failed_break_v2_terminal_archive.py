"""Focused offline tests for the failed-break v2 terminal archive."""

import ast
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research import failed_break_v2_terminal_archive as archive


class TerminalArtifactTests(unittest.TestCase):
    def test_exact_canonical_artifact_and_binder_reconstruct(self):
        terminal = archive.load_terminal_freeze()
        self.assertEqual(terminal["status"], archive.STATUS)
        self.assertEqual(terminal["terminal_sha256"], archive.TERMINAL_SHA256)
        self.assertEqual(
            hashlib.sha256(archive.ARTIFACT_PATH.read_bytes()).hexdigest(),
            archive.ARTIFACT_SHA256,
        )
        self.assertEqual(
            archive.canonical_bytes(terminal) + b"\n", archive.ARTIFACT_PATH.read_bytes()
        )
        self.assertEqual(archive.verify_binder(), archive.BINDER_SHA256)
        for name, (path, expected) in archive.SOURCE_ARTIFACTS.items():
            with self.subTest(source=name):
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_rehashed_forgery_still_fails_semantic_boundary(self):
        terminal = copy.deepcopy(archive.load_terminal_freeze())
        terminal["authorization"]["promotion"] = True
        body = dict(terminal)
        body.pop("terminal_sha256")
        terminal["terminal_sha256"] = archive.digest(body)
        raw = archive.canonical_bytes(terminal) + b"\n"
        with tempfile.TemporaryDirectory() as directory:
            forged = Path(directory) / "forged.json"
            forged.write_bytes(raw)
            with (
                patch.object(archive, "ARTIFACT_PATH", forged),
                patch.object(archive, "ARTIFACT_SHA256", hashlib.sha256(raw).hexdigest()),
                patch.object(archive, "TERMINAL_SHA256", terminal["terminal_sha256"]),
                self.assertRaisesRegex(archive.TerminalArchiveRefusal, "authority changed"),
            ):
                archive.load_terminal_freeze()

    def test_no_database_provider_execution_or_outcome_import(self):
        tree = ast.parse(Path(archive.__file__).read_text())
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
        self.assertTrue(
            {
                "django",
                "psycopg",
                "requests",
                "subprocess",
                "exploratory_returns_v2",
                "exploratory_return_runner_v2",
            }.isdisjoint(imported)
        )


class PermanentBoundaryTests(unittest.TestCase):
    def test_all_actions_and_every_override_are_permanently_refused(self):
        actions = (
            "additional_execution",
            "retry",
            "replacement",
            "return_recalculation",
            "strategy_tuning",
            "promotion",
            "live_trading",
        )
        overrides = (
            {"owner": True},
            {"cli": True},
            {"environment": True},
            {"database": True},
            {"favourable_result": True},
            {"pair_removal": "GBP_USD"},
            {"direction_removal": "LONG"},
            {"capital_scaling": "40000"},
            {"threshold_reinterpretation": True},
        )
        for action in actions:
            for override in overrides:
                with self.subTest(action=action, override=override):
                    with self.assertRaisesRegex(
                        archive.TerminalArchiveRefusal, "permanently prohibited"
                    ):
                        archive.require_prohibited_action(action, **override)

    def test_readiness_is_terminal_and_future_work_requires_new_identity(self):
        readiness = archive.readiness()
        self.assertEqual(readiness["status"], "COMPLETED_NEGATIVE_EXPLORATORY_RESULT")
        self.assertEqual(readiness["additional_execution"], "PERMANENTLY_REFUSED")
        self.assertEqual(
            readiness["future_research"],
            [
                "NEW_STRATEGY_IDENTITY",
                "NEW_PREREGISTRATION",
                "GENUINELY_UNTOUCHED_VALIDATION_EVIDENCE",
            ],
        )

    def test_accepted_result_and_historical_preservation_are_exact(self):
        terminal = archive.load_terminal_freeze()
        self.assertEqual(terminal["final_result"], archive.EXPECTED_RESULT)
        self.assertTrue(all(terminal["historical_preservation"].values()))
        self.assertEqual(terminal["closed_cohort"]["physical_events"], 82)
        self.assertEqual(terminal["source_bindings"]["geometry"]["book_memberships"], 186)
        self.assertTrue(terminal["source_bindings"]["s2_policy"]["exploratory_only"])
        self.assertTrue(
            terminal["source_bindings"]["s2_policy"]["promotion_permanently_prohibited"]
        )
