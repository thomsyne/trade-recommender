from __future__ import annotations

import ast
import copy
import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from research import failed_break_v2_s1_outcome as outcome
from research.failed_break_v2_s1_governance import canonical_bytes, canonical_hash
from research.failed_break_v2_s1_outcome import (
    ACCEPTANCE_SELF_SHA256,
    ARTIFACT_PATH,
    ARTIFACT_SHA256,
    AUTHORITY,
    CONFIGURATION_SHA256,
    EXPECTED_CURRENT_TOTALS,
    EXPECTED_ROW_COUNTS,
    EXPECTED_TOTAL_INSERTED_ROWS,
    PROJECTION_SHA256,
    REPORT_SHA256,
    V1_AGGREGATE_SHA256,
    V2S1OutcomeRefusal,
    load_v2_s1_outcome_acceptance,
    select_persistent_v2_s1_evidence,
    v2_s1_outcome_readiness,
    verify_reconstructed_v2_s1_outcome,
)


class V2S1OutcomeAcceptanceTests(SimpleTestCase):
    def setUp(self):
        self.artifact = load_v2_s1_outcome_acceptance()

    def reconstructed(self):
        return {
            "application_state": copy.deepcopy(self.artifact["application_state"]),
            "inventory": copy.deepcopy(self.artifact["inventory"]),
            "stored_evidence": copy.deepcopy(self.artifact["stored_evidence"]),
            "v1_preservation": copy.deepcopy(self.artifact["v1_preservation"]),
        }

    def test_artifact_is_canonical_self_hashed_and_exactly_return_blind(self):
        raw = ARTIFACT_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), ARTIFACT_SHA256)
        self.assertEqual(canonical_bytes(self.artifact) + b"\n", raw)
        body = dict(self.artifact)
        claimed = body.pop("acceptance_sha256")
        self.assertEqual(claimed, ACCEPTANCE_SELF_SHA256)
        self.assertEqual(claimed, canonical_hash(body))
        self.assertEqual(self.artifact["authority"], AUTHORITY)
        self.assertEqual(
            self.artifact["accepted_delta"],
            {
                "every_other_application_table": 0,
                "per_table": EXPECTED_ROW_COUNTS,
                "total_inserted_rows": EXPECTED_TOTAL_INSERTED_ROWS,
            },
        )
        self.assertEqual(
            self.artifact["application_state"]["current_totals"], EXPECTED_CURRENT_TOTALS
        )
        readiness = v2_s1_outcome_readiness()
        self.assertEqual(readiness["v2_s1_outcome"], "ACCEPTED")
        self.assertFalse(readiness["repeat_v2_s1_execution"])
        self.assertFalse(readiness["return_blind_geometry_implementation"])
        self.assertFalse(readiness["returns_or_backtesting"])
        self.assertFalse(readiness["promotion_or_live_trading"])

    def test_exact_reconstruction_passes(self):
        verify_reconstructed_v2_s1_outcome(self.reconstructed(), self.artifact)
        stored = self.artifact["stored_evidence"]
        self.assertEqual(
            stored["hashes"],
            {
                "configuration_sha256": CONFIGURATION_SHA256,
                "projection_sha256": PROJECTION_SHA256,
                "report_sha256": REPORT_SHA256,
            },
        )
        self.assertEqual(self.artifact["v1_preservation"]["aggregate_sha256"], V1_AGGREGATE_SHA256)

    def test_partial_count_and_hash_drift_all_fail_closed(self):
        mutations = {
            "partial table evidence": lambda value: value["stored_evidence"]["per_table"].pop(
                "research_level"
            ),
            "row count": lambda value: value["stored_evidence"]["per_table"][
                "research_level"
            ].__setitem__("rows", 17_934),
            "configuration": lambda value: value["stored_evidence"]["hashes"].__setitem__(
                "configuration_sha256", "0" * 64
            ),
            "report": lambda value: value["stored_evidence"]["hashes"].__setitem__(
                "report_sha256", "0" * 64
            ),
            "projection": lambda value: value["stored_evidence"]["hashes"].__setitem__(
                "projection_sha256", "0" * 64
            ),
            "fabricated aggregate": lambda value: value["stored_evidence"].__setitem__(
                "aggregate_evidence_sha256", "0" * 64
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                reconstructed = self.reconstructed()
                mutate(reconstructed)
                with self.assertRaises(V2S1OutcomeRefusal):
                    verify_reconstructed_v2_s1_outcome(reconstructed, self.artifact)

    def test_orphan_cross_strategy_duplicate_and_data_quality_fail_closed(self):
        mutations = {
            "orphan": lambda value: value["stored_evidence"]["integrity"].__setitem__(
                "cross_strategy_attributions", 1
            ),
            "cross strategy": lambda value: value["stored_evidence"]["integrity"].__setitem__(
                "cross_strategy_transitions", 1
            ),
            "duplicate": lambda value: value["stored_evidence"]["integrity"][
                "duplicate_groups"
            ].__setitem__("analysis", 1),
            "data quality": lambda value: value["stored_evidence"]["data_quality"].__setitem__(
                "analysis_data_incomplete", 1
            ),
            "evidence hash": lambda value: value["stored_evidence"]["integrity"].__setitem__(
                "analysis_evidence_hash_mismatches", 1
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                reconstructed = self.reconstructed()
                mutate(reconstructed)
                with self.assertRaises(V2S1OutcomeRefusal):
                    verify_reconstructed_v2_s1_outcome(reconstructed, self.artifact)

    def test_inventory_membership_and_v1_drift_fail_closed(self):
        inventory_drift = self.reconstructed()
        inventory_drift["inventory"]["instruments"]["AUD_USD"]["counts"]["H1"] -= 1
        with self.assertRaisesRegex(V2S1OutcomeRefusal, "inventory"):
            verify_reconstructed_v2_s1_outcome(inventory_drift, self.artifact)

        v1_drift = self.reconstructed()
        v1_drift["v1_preservation"]["digests"]["research_jobrun_v1"] = "0" * 64
        with self.assertRaisesRegex(V2S1OutcomeRefusal, "v1 evidence"):
            verify_reconstructed_v2_s1_outcome(v1_drift, self.artifact)

    def test_missing_or_duplicate_semantic_job_refuses(self):
        dataset = SimpleNamespace(pk=3)
        strategy = SimpleNamespace(pk=2)
        s0 = SimpleNamespace(pk=4)
        for count in (0, 2):
            jobs = mock.MagicMock()
            jobs.count.return_value = count
            with (
                mock.patch.object(
                    outcome, "load_v2_s1_outcome_acceptance", return_value=self.artifact
                ),
                mock.patch.object(
                    outcome,
                    "select_persistent_v2_s0_evidence",
                    return_value=(s0, dataset, strategy),
                ),
                mock.patch("research.models.JobRun.objects.filter", return_value=jobs),
                self.assertRaisesRegex(V2S1OutcomeRefusal, "missing or duplicated"),
            ):
                select_persistent_v2_s1_evidence()

    def test_v1_job_cannot_substitute_for_semantically_selected_v2_job(self):
        dataset = SimpleNamespace(pk=3)
        strategy = SimpleNamespace(pk=2)
        s0 = SimpleNamespace(pk=4)
        jobs = mock.MagicMock()
        jobs.count.return_value = 1
        jobs.get.return_value = SimpleNamespace(
            job_name="failed-break-signal-count-s1",
            strategy_version_id=1,
            dataset_version_id=3,
            config_hash=CONFIGURATION_SHA256,
            status="succeeded",
        )
        with (
            mock.patch.object(outcome, "load_v2_s1_outcome_acceptance", return_value=self.artifact),
            mock.patch.object(
                outcome,
                "select_persistent_v2_s0_evidence",
                return_value=(s0, dataset, strategy),
            ),
            mock.patch("research.models.JobRun.objects.filter", return_value=jobs),
            self.assertRaisesRegex(V2S1OutcomeRefusal, "cannot substitute"),
        ):
            select_persistent_v2_s1_evidence()

    def test_selector_uses_semantic_fields_not_operational_anchors(self):
        tree = ast.parse(Path(outcome.__file__).read_text())
        selector = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "select_persistent_v2_s1_evidence"
        )
        filter_keywords = {
            keyword.arg
            for node in ast.walk(selector)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "filter"
            for keyword in node.keywords
        }
        self.assertEqual(
            filter_keywords,
            {"config_hash", "dataset_version", "job_name", "status", "strategy_version"},
        )
        self.assertFalse({"id", "pk", "job_run_id"} & filter_keywords)

    def _assert_rehashed_forgery_refused(self, mutate):
        forged = copy.deepcopy(self.artifact)
        mutate(forged)
        forged.pop("acceptance_sha256")
        forged["acceptance_sha256"] = canonical_hash(forged)
        raw = canonical_bytes(forged) + b"\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ARTIFACT_PATH.name
            path.write_bytes(raw)
            with (
                mock.patch.object(outcome, "ARTIFACT_PATH", path),
                mock.patch.object(outcome, "ARTIFACT_SHA256", hashlib.sha256(raw).hexdigest()),
                mock.patch.object(outcome, "ACCEPTANCE_SELF_SHA256", forged["acceptance_sha256"]),
                self.assertRaisesRegex(V2S1OutcomeRefusal, "identity changed"),
            ):
                load_v2_s1_outcome_acceptance()

    def test_rehashed_artifact_forgery_is_not_independent_authority(self):
        self._assert_rehashed_forgery_refused(
            lambda artifact: artifact["stored_evidence"].__setitem__(
                "aggregate_evidence_sha256", "0" * 64
            )
        )

    def test_returns_and_promotion_cannot_be_authorized_by_artifact_mutation(self):
        for field in ("returns_or_backtesting", "promotion_or_live_trading"):
            with self.subTest(field=field):
                self._assert_rehashed_forgery_refused(
                    lambda artifact, field=field: artifact["authority"].__setitem__(field, True)
                )

    def test_persistent_verifier_sets_transaction_read_only_and_has_no_outcome_reader(self):
        source = Path(outcome.__file__).read_text()
        self.assertIn('cursor.execute("SET TRANSACTION READ ONLY")', source)
        tree = ast.parse(source)
        research_models = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "research.models"
            for alias in node.names
        }
        self.assertEqual(
            research_models,
            {
                "AnalysisRun",
                "EntryEligibilityEvaluation",
                "JobRun",
                "Level",
                "LevelLifecycleEvent",
                "SetupEvent",
                "SetupLevelAttribution",
                "SetupTransition",
            },
        )
        self.assertNotIn("forecasts.models", source)
        self.assertNotIn("entry-to-exit", source.lower())
