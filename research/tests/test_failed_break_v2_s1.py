from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase

from market.models import DatasetVersion, Instrument, SourceRegistry
from research import failed_break_v2_s1_governance as governance
from research.failed_break_v2_s0_governance import (
    V2S0GovernanceRefusal,
    verify_v2_s0_acceptance,
)
from research.failed_break_v2_s1 import (
    ProjectedAnalysis,
    ProjectedEvaluation,
    ProjectedLevel,
    ProjectedSetup,
    V2S1Projection,
    V2S1Refusal,
    _evaluate_entry,
    _project_instrument,
    _projection_report,
    persist_projection,
)
from research.failed_break_v2_s1_governance import (
    V2S1GovernanceRefusal,
    canonical_bytes,
    canonical_hash,
    inspect_v2_s1_execution_authorization,
    load_v2_s1_execution_authorization,
    load_v2_s1_policy,
)
from research.models import (
    AnalysisRun,
    EntryEligibilityEvaluation,
    JobRun,
    Level,
    LevelLifecycleEvent,
    SetupEvent,
    SetupLevelAttribution,
    SetupTransition,
    StrategyDefinition,
    StrategyVersion,
)
from research.strategy import Bias, EntryResult, LevelSpec, Role, Side, SweepEvent

ROOT = Path(__file__).resolve().parents[2]
AT = datetime(2018, 1, 2, 12, tzinfo=UTC)


class V2S1GovernanceTests(SimpleTestCase):
    def test_artifacts_are_canonical_and_direct_execution_stays_closed(self):
        policy = load_v2_s1_policy()
        raw = governance.ARTIFACT_PATH.read_bytes()
        body = dict(json.loads(raw))
        claimed = body.pop("v2_s1_policy_sha256")
        self.assertEqual(canonical_bytes(json.loads(raw)) + b"\n", raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), governance.ARTIFACT_SHA256)
        self.assertEqual(claimed, governance.POLICY_SHA256)
        self.assertEqual(canonical_hash(body), governance.POLICY_SHA256)
        self.assertTrue(policy["authorization"]["implementation"])
        self.assertFalse(policy["authorization"]["persistent_v2_s1_execution"])
        self.assertFalse(policy["authorization"]["returns_or_backtesting"])
        self.assertFalse(policy["authorization"]["promotion_or_live_trading"])
        authorization = inspect_v2_s1_execution_authorization()
        authorization_raw = governance.EXECUTION_ARTIFACT_PATH.read_bytes()
        authorization_body = dict(json.loads(authorization_raw))
        authorization_claimed = authorization_body.pop("authorization_sha256")
        self.assertEqual(canonical_bytes(json.loads(authorization_raw)) + b"\n", authorization_raw)
        self.assertEqual(
            hashlib.sha256(authorization_raw).hexdigest(),
            governance.EXECUTION_ARTIFACT_SHA256,
        )
        self.assertEqual(authorization_claimed, governance.EXECUTION_POLICY_SHA256)
        self.assertEqual(canonical_hash(authorization_body), authorization_claimed)
        self.assertTrue(authorization["authorization"]["persistent_v2_s1_execution"])
        with self.assertRaisesRegex(V2S1GovernanceRefusal, "direct v2 S1 execution"):
            load_v2_s1_execution_authorization()

    def test_rehashed_authorization_mutation_fails_closed(self):
        policy = json.loads(governance.ARTIFACT_PATH.read_bytes())
        policy["authorization"]["persistent_v2_s1_execution"] = True
        body = dict(policy)
        body.pop("v2_s1_policy_sha256")
        policy["v2_s1_policy_sha256"] = canonical_hash(body)
        raw = canonical_bytes(policy) + b"\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forged.json"
            path.write_bytes(raw)
            with (
                mock.patch.object(governance, "ARTIFACT_PATH", path),
                mock.patch.object(governance, "ARTIFACT_SHA256", hashlib.sha256(raw).hexdigest()),
                mock.patch.object(governance, "POLICY_SHA256", policy["v2_s1_policy_sha256"]),
                self.assertRaisesRegex(V2S1GovernanceRefusal, "governed boundary"),
            ):
                load_v2_s1_policy()

    def test_future_execution_artifact_cannot_authorize_returns_or_promotion(self):
        for mutation in (
            {"returns_or_backtesting": True},
            {"promotion_or_live_trading": True},
        ):
            authorization = json.loads(governance.EXECUTION_ARTIFACT_PATH.read_bytes())
            authorization["authorization"].update(mutation)
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
                    self.assertRaisesRegex(V2S1GovernanceRefusal, "authority changed"),
                ):
                    inspect_v2_s1_execution_authorization()

    def test_command_uses_only_the_authorized_readiness_and_execution_paths(self):
        with mock.patch(
            "research.management.commands.signal_count_s1_v2.authorization_readiness_v2_s1",
            return_value={"status": "AUTHORIZED_NOT_EXECUTED"},
        ) as readiness:
            call_command("signal_count_s1_v2")
        readiness.assert_called_once_with()
        with (
            mock.patch(
                "research.management.commands.signal_count_s1_v2.execute_authorized_v2_s1",
                side_effect=V2S1GovernanceRefusal("refused"),
            ) as execute,
            self.assertRaisesRegex(CommandError, "refused"),
        ):
            call_command("signal_count_s1_v2", "--execute")
        execute.assert_called_once()

    def test_source_has_no_outcome_return_provider_or_production_path(self):
        source = (ROOT / "research/failed_break_v2_s1.py").read_text().lower()
        for forbidden in (
            "tradereturn",
            "backtest",
            "profit_loss",
            "drawdown",
            "oanda_token",
            "api-fxtrade",
            "trade_recommender_production",
        ):
            self.assertNotIn(forbidden, source)

    def test_committed_benchmark_records_real_model_safety_and_determinism(self):
        results = json.loads(
            (
                ROOT / "docs/strategy/failed-break/v2/s1-runner-benchmark-results-v2.json"
            ).read_bytes()
        )
        harness = ROOT / "research/benchmarks/failed_break_v2_s1_runner_benchmark.py"
        self.assertEqual(
            results["environment"]["harness_sha256"],
            hashlib.sha256(harness.read_bytes()).hexdigest(),
        )
        self.assertEqual([run["batch_size"] for run in results["batch_runs"]], [500, 2000])
        self.assertTrue(results["determinism"]["batch_size_invariant"])
        self.assertTrue(results["determinism"]["two_restore_invariant"])
        self.assertTrue(results["safety"]["injected_failure_rollback_exact"])
        self.assertTrue(results["safety"]["reference_equivalence"])
        self.assertTrue(results["safety"]["v1_evidence_unchanged"])

    def test_exact_h1_floor_and_zero_data_quality_are_enforced(self):
        analysis = ProjectedAnalysis(1, "AUD_USD", AT, "NO_SETUP", (), {}, "a" * 64)
        report = _projection_report(
            (),
            (),
            (analysis,) * 344_817,
            {"AUD_USD": {"H1": 344_817, "D": 0, "W": 0}},
            {"AUD_USD": {"H1": "h", "D": "d", "W": "w"}},
            {},
        )
        self.assertEqual(report["observed_h1_analyses"], 344_817)
        with self.assertRaisesRegex(V2S1Refusal, "incomplete"):
            _projection_report(
                (),
                (),
                (analysis,) * 344_816,
                {},
                {},
                {},
            )

    def test_v1_s0_cannot_authorize_v2_s1(self):
        v1_job = SimpleNamespace(job_name="failed-break-signal-count-s0")
        with self.assertRaisesRegex(V2S0GovernanceRefusal, "v1 S0 evidence"):
            verify_v2_s0_acceptance(job=v1_job, dataset=None, strategy=None)

    def test_in_memory_projection_contains_no_orm_query(self):
        source = inspect.getsource(_project_instrument)
        self.assertNotIn(".objects", source)
        self.assertNotIn("connection.", source)

    def test_entry_uses_the_confirmed_v2_supporting_swing(self):
        setup = SimpleNamespace(
            event=SweepEvent(
                AT,
                Side.LONG,
                ("level",),
                Decimal("1.2"),
                Decimal("0.9"),
                Bias.BULLISH,
                Decimal("0.95"),
            ),
            confirmation=(
                "CONFIRMED",
                AT + timedelta(hours=1),
                {"supporting_swing": "1.01"},
                "a" * 64,
                "",
            ),
            evaluations=[],
        )
        opening = SimpleNamespace(timestamp=AT + timedelta(hours=2))
        with (
            mock.patch(
                "research.failed_break_v2_s1._cad_conversion",
                return_value=(Decimal("1"), AT, "conversion", {}),
            ),
            mock.patch("research.failed_break_v2_s1.entry_eligibility") as eligibility,
            mock.patch("research.failed_break_v2_s1._books", return_value=()),
        ):
            _evaluate_entry(
                setup,
                opening,
                Decimal("0.01"),
                [],
                {},
                {},
                SimpleNamespace(),
                SimpleNamespace(code="AUD_USD"),
                SimpleNamespace(content_hash="strategy"),
                SimpleNamespace(manifest_sha256="dataset"),
                Decimal("0.001"),
            )
        self.assertEqual(eligibility.call_args.args[0].provisional_swing, Decimal("1.01"))


class V2S1PersistenceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        source = SourceRegistry.objects.create(
            name="v2-s1-fixture",
            tier="primary",
            base_url="https://invalid.example",
            acquisition_method="fixture",
            retention_policy="fixture",
        )
        self.instrument = Instrument.objects.create(
            code="AUD_USD",
            base_currency="AUD",
            quote_currency="USD",
            display_order=1,
        )
        self.dataset = DatasetVersion.objects.create(
            name="fixture",
            version="v2",
            source=source,
            manifest={"fixture": True},
        )
        definition = StrategyDefinition.objects.create(key="fixture", name="fixture")
        self.strategy = StrategyVersion.objects.create(
            definition=definition,
            version="failed-break-phase-1-admission-correction-v2",
            detector_version="failed-break-detector-v2-admission-correction",
            data_identity="fixture",
            event_identity="fixture",
            execution_identity="execution-h1-stop-first-v1",
            cost_identity="fixture",
            portfolio_identity="fixture",
            content_hash="1" * 64,
        )
        self.s0_job = JobRun.objects.create(
            job_name="failed-break-signal-count-s0-v2",
            strategy_version=self.strategy,
            dataset_version=self.dataset,
            config_hash="2" * 64,
            idempotency_key="fixture-s0",
            as_of=datetime(2019, 1, 1, 4, tzinfo=UTC),
            status=JobRun.Status.SUCCEEDED,
            evidence={"report": {"report_sha256": "3" * 64}},
        )

    def projection(self):
        spec = LevelSpec(
            "fixture-level",
            Level.Family.WEEKLY,
            Role.SUPPORT,
            Decimal("1.0000"),
            Decimal("0.9900"),
            Decimal("1.0100"),
            Decimal("0.1000"),
            AT - timedelta(days=1),
            AT - timedelta(days=8),
        )
        lifecycle_evidence = {
            "source_level_key": "a" * 64,
            "state": "expired",
            "effective_at": (AT + timedelta(days=7)).isoformat(),
        }
        level = ProjectedLevel(
            self.instrument.pk,
            self.instrument.code,
            spec,
            "a" * 64,
            lifecycle=[
                (
                    "expired",
                    AT + timedelta(days=7),
                    lifecycle_evidence,
                    hashlib.sha256(
                        json.dumps(
                            lifecycle_evidence,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                )
            ],
        )
        event = SweepEvent(
            AT,
            Side.LONG,
            (level.stable_key,),
            Decimal("1.1"),
            Decimal("0.9"),
            Bias.BULLISH,
            Decimal("0.95"),
        )
        setup_evidence = {
            "sweep": {"completed_at": AT.isoformat(), "side": "long", "extreme": "0.9"},
            "bias": {"value": "bullish"},
            "provisional_swing": {"price": "0.95"},
            "threshold": {"price": "1.1"},
        }
        transition_evidence = {
            "state": "CONFIRMED",
            "at": (AT + timedelta(hours=1)).isoformat(),
            "supporting_swing": "0.95",
        }
        evaluation_evidence = {
            "expected_entry_timestamp": (AT + timedelta(hours=1)).isoformat(),
            "decision": "BLOCKED_SESSION",
            "reason": "OUTSIDE_SESSION",
            "entry_open_present": True,
            "cad_conversion": {},
        }
        setup = ProjectedSetup(
            self.instrument.pk,
            self.instrument.code,
            event,
            setup_evidence,
            self.hash(setup_evidence),
            (level.stable_key,),
            (Level.Family.WEEKLY,),
            confirmation=(
                "CONFIRMED",
                AT + timedelta(hours=1),
                transition_evidence,
                self.hash(transition_evidence),
                "",
            ),
            evaluations=[
                ProjectedEvaluation(
                    "failed-break-any-level-deduplicated-v1",
                    EntryResult("BLOCKED_SESSION", "OUTSIDE_SESSION"),
                    AT + timedelta(hours=1),
                    None,
                    evaluation_evidence,
                    self.hash(evaluation_evidence),
                )
            ],
        )
        analysis_evidence = {
            "completed_h1_timestamp": AT.isoformat(),
            "result": "CANDIDATE_CREATED",
            "setup_keys": [setup.logical_key],
            "phase": "DEVELOPMENT",
        }
        analysis = ProjectedAnalysis(
            self.instrument.pk,
            self.instrument.code,
            AT,
            "CANDIDATE_CREATED",
            (setup.logical_key,),
            analysis_evidence,
            self.hash(analysis_evidence),
        )
        row_counts = {
            "analysis_runs": 1,
            "levels": 1,
            "lifecycle_events": 1,
            "setups": 1,
            "attributions": 1,
            "transitions": 2,
            "entry_eligibility": 1,
            "job_runs": 1,
        }
        return V2S1Projection(
            (level,),
            (setup,),
            (analysis,),
            {},
            {},
            {"row_counts": row_counts, "report_sha256": "4" * 64},
        )

    @staticmethod
    def hash(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def counts(self):
        return {
            "jobs": JobRun.objects.filter(job_name="failed-break-signal-count-s1-v2").count(),
            "analysis": AnalysisRun.objects.count(),
            "levels": Level.objects.count(),
            "lifecycle": LevelLifecycleEvent.objects.count(),
            "setups": SetupEvent.objects.count(),
            "attributions": SetupLevelAttribution.objects.count(),
            "transitions": SetupTransition.objects.count(),
            "evaluations": EntryEligibilityEvaluation.objects.count(),
        }

    def test_actual_models_rollback_atomically_and_refuse_duplicate_before_writes(self):
        projection = self.projection()
        before = self.counts()
        with self.assertRaisesRegex(V2S1Refusal, "injected"):
            persist_projection(
                projection=projection,
                dataset=self.dataset,
                strategy=self.strategy,
                s0_job=self.s0_job,
                governance={"artifact_sha256": "5" * 64},
                batch_size=1,
                inject_failure_after="entry_evaluations",
            )
        self.assertEqual(self.counts(), before)
        persist_projection(
            projection=projection,
            dataset=self.dataset,
            strategy=self.strategy,
            s0_job=self.s0_job,
            governance={"artifact_sha256": "5" * 64},
            batch_size=2,
        )
        after = self.counts()
        self.assertEqual(
            after,
            {
                "jobs": 1,
                "analysis": 1,
                "levels": 1,
                "lifecycle": 1,
                "setups": 1,
                "attributions": 1,
                "transitions": 2,
                "evaluations": 1,
            },
        )
        with self.assertRaisesRegex(V2S1Refusal, "duplicate"):
            persist_projection(
                projection=projection,
                dataset=self.dataset,
                strategy=self.strategy,
                s0_job=self.s0_job,
                governance={"artifact_sha256": "5" * 64},
                batch_size=1,
            )
        self.assertEqual(self.counts(), after)
        stored = EntryEligibilityEvaluation.objects.get()
        self.assertEqual(stored.evidence_hash, projection.setups[0].evaluations[0].evidence_hash)
        self.assertEqual(SetupTransition.objects.filter(job_run__isnull=False).count(), 2)

    def test_canonical_projection_is_batch_size_independent(self):
        projection = self.projection()
        first = projection.canonical_evidence()
        second = self.projection().canonical_evidence()
        self.assertEqual(first, second)
        self.assertEqual(self.hash(first), self.hash(second))
