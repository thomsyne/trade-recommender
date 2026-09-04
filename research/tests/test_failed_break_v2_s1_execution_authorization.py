from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from research import failed_break_v2_s1_execution as execution
from research import failed_break_v2_s1_governance as governance
from research.failed_break_v2_s1 import V2S1Refusal
from research.failed_break_v2_s1_governance import (
    V2S1GovernanceRefusal,
    canonical_bytes,
    canonical_hash,
    inspect_v2_s1_execution_authorization,
)


class V2S1ExecutionAuthorizationTests(SimpleTestCase):
    def authorization(self):
        return inspect_v2_s1_execution_authorization()

    def test_exact_authority_is_single_complete_return_blind_operation(self):
        authorization = self.authorization()
        self.assertEqual(
            authorization["command"],
            {
                "argv": ["python", "manage.py", "signal_count_s1_v2", "--execute"],
                "execution_parameters_allowed": False,
                "operational_ceiling_seconds": 1800,
                "persistence": "ONE_ATOMIC_TRANSACTION",
            },
        )
        self.assertEqual(
            authorization["authorization"],
            {
                "alternate_dataset_strategy_or_s0": False,
                "deployment": False,
                "exactly_one_complete_invocation": True,
                "persistent_v2_s1_execution": True,
                "production_access": False,
                "promotion_or_live_trading": False,
                "provider_or_credential_access": False,
                "resume_retry_or_truncation": False,
                "returns_or_backtesting": False,
                "s0_rerun": False,
                "v1_s1_modification": False,
            },
        )
        self.assertEqual(authorization["full_projection"]["row_counts"]["analysis_runs"], 344817)
        self.assertEqual(
            authorization["full_projection"]["data_quality"],
            {
                "analysis_data_incomplete": 0,
                "cancelled": 0,
            },
        )

    def test_missing_authorization_refuses_before_database_access(self):
        with (
            mock.patch.object(
                execution,
                "inspect_v2_s1_execution_authorization",
                side_effect=V2S1GovernanceRefusal("missing authorization"),
            ),
            mock.patch.object(execution, "select_persistent_v2_s0_evidence") as database,
            self.assertRaisesRegex(V2S1GovernanceRefusal, "missing authorization"),
        ):
            execution.execute_authorized_v2_s1()
        database.assert_not_called()

    def test_rehashed_projection_count_mutation_refuses(self):
        authorization = json.loads(governance.EXECUTION_ARTIFACT_PATH.read_bytes())
        authorization["full_projection"]["row_counts"]["levels"] += 1
        body = dict(authorization)
        body.pop("authorization_sha256")
        authorization["authorization_sha256"] = canonical_hash(body)
        raw = canonical_bytes(authorization) + b"\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authorization.json"
            path.write_bytes(raw)
            with (
                mock.patch.object(governance, "EXECUTION_ARTIFACT_PATH", path),
                mock.patch.object(
                    governance,
                    "EXECUTION_ARTIFACT_SHA256",
                    hashlib.sha256(raw).hexdigest(),
                ),
                mock.patch.object(
                    governance,
                    "EXECUTION_POLICY_SHA256",
                    authorization["authorization_sha256"],
                ),
                self.assertRaisesRegex(V2S1GovernanceRefusal, "projection changed"),
            ):
                inspect_v2_s1_execution_authorization()

    def test_exact_authorization_and_pristine_state_open_readiness(self):
        authorization = self.authorization()
        policy = {"artifact_sha256": authorization["bindings"]["runner_artifact_sha256"]}
        values = (
            policy,
            SimpleNamespace(pk=4),
            SimpleNamespace(pk=3),
            SimpleNamespace(pk=2),
            {code: object() for code in authorization["full_projection"]["inventory_counts"]},
            SimpleNamespace(sha256=authorization["bindings"]["dataset"]["contract_sha256"]),
        )
        with (
            mock.patch.object(
                execution, "inspect_v2_s1_execution_authorization", return_value=authorization
            ),
            mock.patch.object(execution, "_verify_repository_and_sources"),
            mock.patch.object(execution, "_validated_inputs", return_value=values),
        ):
            result = execution.authorization_readiness_v2_s1()
        self.assertEqual(result["status"], "AUTHORIZED_NOT_EXECUTED")
        self.assertTrue(result["persistent_execution_authorized"])
        self.assertEqual(result["dataset_id"], 3)
        self.assertEqual(result["strategy_version_id"], 2)
        self.assertEqual(result["s0_job_id"], 4)

    def test_projection_drift_refuses_before_first_write(self):
        authorization = self.authorization()
        values = (
            {"artifact_sha256": authorization["bindings"]["runner_artifact_sha256"]},
            SimpleNamespace(pk=4),
            SimpleNamespace(pk=3),
            SimpleNamespace(pk=2),
            {},
            object(),
        )
        with (
            mock.patch.object(
                execution, "inspect_v2_s1_execution_authorization", return_value=authorization
            ),
            mock.patch.object(execution, "_verify_repository_and_sources"),
            mock.patch.object(execution, "_operational_ceiling", return_value=nullcontext()),
            mock.patch.object(execution.transaction, "atomic", return_value=nullcontext()),
            mock.patch.object(execution, "_validated_inputs", return_value=values),
            mock.patch.object(execution, "project_v2_s1", return_value=object()),
            mock.patch.object(
                execution,
                "_verify_projection",
                side_effect=V2S1Refusal("projection differs"),
            ),
            mock.patch.object(execution, "persist_projection") as persist,
            self.assertRaisesRegex(V2S1Refusal, "projection differs"),
        ):
            execution.execute_authorized_v2_s1()
        persist.assert_not_called()

    def test_any_preexisting_v2_evidence_refuses(self):
        authorization = self.authorization()
        observed = dict(authorization["expected_pre_state"])
        observed["analysis_runs_v2"] = 1
        with (
            mock.patch.object(execution, "load_v2_s1_policy", return_value={}),
            mock.patch.object(
                execution,
                "select_persistent_v2_s0_evidence",
                return_value=(object(), object(), object()),
            ),
            mock.patch.object(execution, "verify_v2_s0_acceptance", return_value={}),
            mock.patch.object(
                execution,
                "validate_v2_s0_prerequisites",
                return_value=({}, object(), {}),
            ),
            mock.patch.object(execution, "_verify_lineage"),
            mock.patch.object(execution, "_observed_pre_state", return_value=observed),
            mock.patch.object(execution, "_assert_pristine") as pristine,
            self.assertRaisesRegex(V2S1Refusal, "exact authorized pristine state"),
        ):
            execution._validated_inputs(authorization)
        pristine.assert_not_called()

    def test_v1_or_alternate_lineage_cannot_substitute(self):
        authorization = self.authorization()
        binding = authorization["bindings"]
        dataset = SimpleNamespace(
            pk=3,
            name=binding["dataset"]["name"],
            version=binding["dataset"]["version"],
            manifest_sha256=binding["dataset"]["manifest_sha256"],
            registration=SimpleNamespace(
                configuration_sha256=binding["dataset"]["registration_configuration_sha256"],
                report_sha256=binding["dataset"]["registration_report_sha256"],
            ),
        )
        parameter = SimpleNamespace(
            pk=2,
            sha256=binding["strategy"]["detector_artifact_sha256"],
        )
        strategy = SimpleNamespace(
            pk=2,
            version=binding["strategy"]["identity"],
            detector_version=binding["strategy"]["detector_identity"],
            content_hash=binding["strategy"]["content_sha256"],
            strategyparametermanifest=parameter,
        )
        contract = SimpleNamespace(
            sha256=binding["dataset"]["contract_sha256"],
            identity=binding["dataset"]["effective_data_identity"],
            global_semantic_inventory_sha256=binding["dataset"]["global_semantic_inventory_sha256"],
        )
        acceptance = {"acceptance_sha256": binding["s0"]["acceptance_self_sha256"]}
        s0 = SimpleNamespace(
            pk=4,
            job_name=binding["s0"]["job_identity"],
            config_hash=binding["s0"]["configuration_sha256"],
            evidence={"report": {"report_sha256": binding["s0"]["report_sha256"]}},
        )
        execution._verify_lineage(
            authorization=authorization,
            acceptance=acceptance,
            s0_job=s0,
            dataset=dataset,
            strategy=strategy,
            contract=contract,
        )
        mutations = (
            (strategy, "version", "failed-break-phase-1-freeze-v1"),
            (dataset, "pk", 4),
            (s0, "config_hash", "0" * 64),
        )
        for target, field, replacement in mutations:
            with self.subTest(field=field):
                original = getattr(target, field)
                setattr(target, field, replacement)
                try:
                    with self.assertRaisesRegex(V2S1Refusal, "lineage changed"):
                        execution._verify_lineage(
                            authorization=authorization,
                            acceptance=acceptance,
                            s0_job=s0,
                            dataset=dataset,
                            strategy=strategy,
                            contract=contract,
                        )
                finally:
                    setattr(target, field, original)

    def test_full_projection_record_is_two_run_deterministic(self):
        authorization = self.authorization()
        phase1 = authorization["phase1"]
        projection = authorization["full_projection"]
        self.assertTrue(phase1["stable_snapshot"])
        self.assertFalse(phase1["persistent_writes"])
        self.assertFalse(phase1["forbidden_evidence_accessed"])
        self.assertEqual(len(phase1["runs"]), 2)
        self.assertTrue(projection["determinism"]["identical"])
        self.assertEqual(
            projection["canonical_evidence_sha256"],
            projection["projection_sha256"],
        )

    def test_authorized_path_has_no_outcome_provider_production_or_retry_surface(self):
        source = inspect.getsource(execution).lower()
        command_source = (
            (execution.ROOT / "research/management/commands/signal_count_s1_v2.py")
            .read_text()
            .lower()
        )
        for forbidden in (
            "tradereturn",
            "profit_loss",
            "drawdown",
            "oanda_token",
            "api-fxtrade",
            "trade_recommender_production",
        ):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, command_source)
        self.assertNotIn("--max", command_source)
        self.assertNotIn("--retry", command_source)
        self.assertNotIn("--resume", command_source)
        self.assertLess(source.index("_verify_projection("), source.index("persist_projection("))

    def test_phase1_and_runtime_write_only_the_preregistered_tables(self):
        authorization = self.authorization()
        preregistration = json.loads(
            (
                execution.ROOT / "docs/strategy/failed-break/v2/s1-runner-preregistration-v2.json"
            ).read_bytes()
        )
        self.assertEqual(
            set(authorization["full_projection"]["row_counts"]),
            {
                "analysis_runs",
                "attributions",
                "entry_eligibility",
                "job_runs",
                "levels",
                "lifecycle_events",
                "setups",
                "transitions",
            },
        )
        self.assertEqual(len(preregistration["persistence"]["model_tables"]), 8)
