import ast
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from market.provider_observed_acquisition import REPLACEMENT_DATASET_NAME
from market.provider_observed_gate8e import (
    SUCCESSOR_CONTRACT_SHA256,
    SUCCESSOR_DATA_IDENTITY,
    SUCCESSOR_DATASET_MANIFEST_SHA256,
)
from market.provider_observed_gate8g import SUCCESSOR_GLOBAL_SEMANTIC_INVENTORY_SHA256
from research.failed_break_detector_v2_governance import (
    ARTIFACT_SHA256 as DETECTOR_ARTIFACT_SHA256,
)
from research.failed_break_detector_v2_governance import (
    DETECTOR_IDENTITY,
    STRATEGY_IDENTITY,
    load_v2_policy,
)
from research.failed_break_v2_s0 import (
    V2_S0_AS_OF,
    V2_S0_JOB_NAME,
    V2_S0_PRICE_FIELDS,
    V2S0Error,
    build_v2_s0_evidence,
    validate_v2_s0_prerequisites,
    validate_v2_strategy,
)
from research.failed_break_v2_s0_governance import (
    ACCEPTED_AUTHORIZATION,
    ACCEPTED_OPERATIONAL_ANCHORS,
    OUTCOME_ARTIFACT_PATH,
    OUTCOME_ARTIFACT_SHA256,
    OUTCOME_SELF_SHA256,
    PREREG_ARTIFACT_PATH,
    PREREG_ARTIFACT_SHA256,
    PREREG_SELF_SHA256,
    V2S0GovernanceRefusal,
    canonical_bytes,
    canonical_hash,
    load_v2_s0_outcome_acceptance,
    load_v2_s0_preregistration,
    select_persistent_v2_s0_evidence,
    v2_s0_code_readiness,
    validate_stored_v2_s0_evidence,
    verify_v2_s0_acceptance,
)


class V2S0GovernanceTests(SimpleTestCase):
    def setUp(self):
        self.preregistration = load_v2_s0_preregistration()
        accepted_v1 = self.preregistration["v1_reuse"]
        dataset_binding = self.preregistration["dataset"]
        self.lineage_strategy = SimpleNamespace(
            pk=1,
            version="failed-break-phase-1-freeze-v1",
            detector_version="failed-break-detector-v1",
            content_hash="f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882",
            data_identity="oanda-ba-ny17-friday-v1",
        )
        self.contract = SimpleNamespace(
            pk=2,
            identity=SUCCESSOR_DATA_IDENTITY,
            sha256=SUCCESSOR_CONTRACT_SHA256,
            global_semantic_inventory_sha256=SUCCESSOR_GLOBAL_SEMANTIC_INVENTORY_SHA256,
            strategy_version=self.lineage_strategy,
        )
        self.registration = SimpleNamespace(
            configuration_sha256=dataset_binding["registration_configuration_sha256"],
            report_sha256=dataset_binding["registration_report_sha256"],
        )
        self.dataset = SimpleNamespace(
            pk=3,
            name=REPLACEMENT_DATASET_NAME,
            version="phase-2b1r-v2",
            manifest_sha256=SUCCESSOR_DATASET_MANIFEST_SHA256,
            registration=self.registration,
        )
        strategy_policy = self.preregistration["strategy"]
        self.parameter = SimpleNamespace(
            payload=load_v2_policy(),
            sha256=DETECTOR_ARTIFACT_SHA256,
            phase1_spec_hash="47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd",
            phase1_manifest_hash=(
                "f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882"
            ),
        )
        self.strategy = SimpleNamespace(
            pk=2,
            definition=SimpleNamespace(key=strategy_policy["definition"]),
            version=STRATEGY_IDENTITY,
            detector_version=DETECTOR_IDENTITY,
            data_identity=SUCCESSOR_DATA_IDENTITY,
            event_identity=strategy_policy["event_identity"],
            execution_identity=strategy_policy["execution_identity"],
            cost_identity=strategy_policy["cost_identity"],
            portfolio_identity=strategy_policy["portfolio_identity"],
            pair_metadata=strategy_policy["pair_metadata"],
            timeframe_metadata=strategy_policy["timeframe_metadata"],
            content_hash=DETECTOR_ARTIFACT_SHA256,
            strategyparametermanifest=self.parameter,
        )
        self.parameter.pk = 2
        self.registration.data_contract = self.contract
        self.v1_job = SimpleNamespace(
            pk=1,
            job_name="failed-break-signal-count-s0",
            config_hash=accepted_v1["configuration_sha256"],
        )

    def _exact_job(self):
        derived = self.preregistration["expected_numerical_evidence"]
        with patch(
            "research.failed_break_v2_s0.contract_for_dataset",
            return_value=self.contract,
        ):
            configuration, output = build_v2_s0_evidence(
                dataset=self.dataset,
                strategy=self.strategy,
                numerical_evidence=derived,
            )
        return SimpleNamespace(
            pk=4,
            job_name=V2_S0_JOB_NAME,
            strategy_version_id=self.strategy.pk,
            dataset_version_id=self.dataset.pk,
            status="succeeded",
            as_of=V2_S0_AS_OF,
            config_hash=output.configuration_sha256,
            evidence={"configuration": configuration, "report": output.as_dict()},
        )

    def _assert_rehashed_outcome_refused(self, mutate):
        forged = json.loads(OUTCOME_ARTIFACT_PATH.read_bytes())
        mutate(forged)
        forged.pop("acceptance_sha256")
        forged["acceptance_sha256"] = canonical_hash(forged)
        raw = canonical_bytes(forged) + b"\n"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / OUTCOME_ARTIFACT_PATH.name
            path.write_bytes(raw)
            with (
                patch(
                    "research.failed_break_v2_s0_governance.OUTCOME_ARTIFACT_PATH",
                    path,
                ),
                patch(
                    "research.failed_break_v2_s0_governance.OUTCOME_ARTIFACT_SHA256",
                    hashlib.sha256(raw).hexdigest(),
                ),
                self.assertRaisesRegex(V2S0GovernanceRefusal, "identity changed"),
            ):
                load_v2_s0_outcome_acceptance()

    def test_preregistration_remains_canonical_and_historically_truthful(self):
        raw = PREREG_ARTIFACT_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), PREREG_ARTIFACT_SHA256)
        self.assertEqual(canonical_bytes(self.preregistration) + b"\n", raw)
        body = dict(self.preregistration)
        claimed = body.pop("preregistration_sha256")
        self.assertEqual(claimed, PREREG_SELF_SHA256)
        self.assertEqual(claimed, canonical_hash(body))
        self.assertEqual(
            self.preregistration["outcome_acceptance"]["status"],
            "ABSENT_NOT_ACCEPTED",
        )

    def test_outcome_is_canonical_self_hashed_and_keeps_all_later_authority_closed(self):
        raw = OUTCOME_ARTIFACT_PATH.read_bytes()
        outcome = load_v2_s0_outcome_acceptance()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), OUTCOME_ARTIFACT_SHA256)
        self.assertEqual(canonical_bytes(outcome) + b"\n", raw)
        body = dict(outcome)
        claimed = body.pop("acceptance_sha256")
        self.assertEqual(claimed, OUTCOME_SELF_SHA256)
        self.assertEqual(claimed, canonical_hash(body))
        self.assertEqual(outcome["authorization"], ACCEPTED_AUTHORIZATION)
        self.assertEqual(outcome["operational_anchors"], ACCEPTED_OPERATIONAL_ANCHORS)
        readiness = v2_s0_code_readiness()
        self.assertFalse(readiness["persistent_s0_execution_authorized"])
        self.assertTrue(readiness["outcome_acceptance_present"])
        self.assertEqual(readiness["v2_s0_outcome"], "ACCEPTED")
        self.assertFalse(readiness["v2_s1_implementation_authorized"])
        self.assertFalse(readiness["v2_s1_execution_authorized"])
        self.assertFalse(readiness["returns_or_backtesting_authorized"])
        self.assertFalse(readiness["promotion_or_live_trading_authorized"])

    def test_exact_v2_strategy_and_independently_sourced_dataset_bindings_pass(self):
        self.assertEqual(self.dataset.name, REPLACEMENT_DATASET_NAME)
        self.assertEqual(self.contract.identity, SUCCESSOR_DATA_IDENTITY)
        self.assertNotEqual(self.dataset.name, self.contract.identity)
        self.assertEqual(self.dataset.manifest_sha256, SUCCESSOR_DATASET_MANIFEST_SHA256)
        self.assertEqual(self.contract.sha256, SUCCESSOR_CONTRACT_SHA256)
        validate_v2_strategy(self.strategy, self.preregistration)
        with (
            patch(
                "research.failed_break_v2_s0.contract_for_dataset",
                return_value=self.contract,
            ),
            patch("research.failed_break_v2_s0.validate_registered_successor"),
            patch(
                "research.failed_break_v2_s0._validate_dataset_contract",
                return_value={"accepted": ()},
            ),
        ):
            ranges, contract, preregistration = validate_v2_s0_prerequisites(
                dataset=self.dataset,
                strategy=self.strategy,
                as_of=V2_S0_AS_OF,
            )
        self.assertEqual(ranges, {"accepted": ()})
        self.assertIs(contract, self.contract)
        self.assertEqual(preregistration, self.preregistration)

    def test_strategy_identity_detector_and_content_mutations_fail_closed(self):
        for field, wrong in (
            ("version", "failed-break-phase-1-freeze-v1"),
            ("detector_version", "failed-break-detector-v1"),
            ("content_hash", "0" * 64),
        ):
            with self.subTest(field=field):
                altered = copy.copy(self.strategy)
                setattr(altered, field, wrong)
                with self.assertRaisesRegex(V2S0Error, "identity or content"):
                    validate_v2_strategy(altered, self.preregistration)
        altered_parameter = copy.copy(self.parameter)
        altered_parameter.sha256 = "0" * 64
        altered = copy.copy(self.strategy)
        altered.strategyparametermanifest = altered_parameter
        with self.assertRaisesRegex(V2S0Error, "parameter binding"):
            validate_v2_strategy(altered, self.preregistration)

    def test_dataset_contract_swaps_and_all_other_identity_drift_fail_closed(self):
        mutations = (
            (self.dataset, "name", SUCCESSOR_DATA_IDENTITY),
            (self.contract, "identity", REPLACEMENT_DATASET_NAME),
            (self.dataset, "version", "wrong-version"),
            (self.dataset, "manifest_sha256", "0" * 64),
            (self.contract, "sha256", "0" * 64),
            (self.contract, "global_semantic_inventory_sha256", "0" * 64),
            (self.registration, "configuration_sha256", "0" * 64),
            (self.registration, "report_sha256", "0" * 64),
        )
        for target, field, wrong in mutations:
            with self.subTest(field=field):
                original = getattr(target, field)
                setattr(target, field, wrong)
                try:
                    with (
                        patch(
                            "research.failed_break_v2_s0.contract_for_dataset",
                            return_value=self.contract,
                        ),
                        patch("research.failed_break_v2_s0.validate_registered_successor"),
                        patch("research.failed_break_v2_s0._validate_dataset_contract"),
                        self.assertRaisesRegex(V2S0Error, "dataset binding"),
                    ):
                        validate_v2_s0_prerequisites(
                            dataset=self.dataset,
                            strategy=self.strategy,
                            as_of=V2_S0_AS_OF,
                        )
                finally:
                    setattr(target, field, original)

    def test_v1_job_cannot_authorize_v2(self):
        with self.assertRaisesRegex(V2S0GovernanceRefusal, "v1 S0 evidence"):
            verify_v2_s0_acceptance(
                job=self.v1_job,
                dataset=self.dataset,
                strategy=self.strategy,
            )

    def test_exact_accepted_stored_evidence_reconstructs(self):
        job = self._exact_job()
        matching = MagicMock()
        matching.count.return_value = 1
        matching.get.return_value = job
        derived = self.preregistration["expected_numerical_evidence"]
        with (
            patch(
                "research.failed_break_v2_s0.validate_v2_s0_prerequisites",
                return_value=({}, self.contract, self.preregistration),
            ),
            patch(
                "research.failed_break_v2_s0.derive_v2_s0_numerical_evidence",
                return_value=derived,
            ),
            patch(
                "research.failed_break_v2_s0.contract_for_dataset",
                return_value=self.contract,
            ),
            patch("research.models.JobRun.objects.filter", return_value=matching),
        ):
            accepted = verify_v2_s0_acceptance(
                job=job,
                dataset=self.dataset,
                strategy=self.strategy,
            )
        self.assertEqual(accepted["status"], "ACCEPTED_RETURN_BLIND_V2_S0_EVIDENCE")
        self.assertEqual(
            accepted["s0"]["configuration_sha256"],
            "d4a61a87ed54f3a479f05a81f83cb52a97c46a2b4bf6be5f5cc735462a56d1ba",
        )
        self.assertEqual(
            accepted["s0"]["report_sha256"],
            "cebaab3f8ff2157d0f40159f5d4e931d76a17edfc5237be54f39781cfefa424c",
        )

    def test_configuration_report_and_identity_rehashed_forgeries_fail_closed(self):
        mutations = (
            lambda artifact: artifact["s0"].__setitem__("configuration_sha256", "0" * 64),
            lambda artifact: artifact["s0"].__setitem__("report_sha256", "0" * 64),
            lambda artifact: artifact["strategy"].__setitem__("identity", "substituted-v1"),
            lambda artifact: artifact["strategy"].__setitem__("detector_artifact_sha256", "0" * 64),
            lambda artifact: artifact["dataset"].__setitem__("version", "substituted"),
            lambda artifact: artifact["dataset"].__setitem__("contract_sha256", "0" * 64),
            lambda artifact: artifact["dataset"].__setitem__(
                "registration_report_sha256", "0" * 64
            ),
            lambda artifact: artifact["authorization"].__setitem__(
                "v2_s1_persistent_execution_authorized", True
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self._assert_rehashed_outcome_refused(mutate)

    def test_semantic_selectors_require_exactly_one_strategy_and_parameter_manifest(self):
        for count in (0, 2):
            strategies = MagicMock()
            strategies.count.return_value = count
            with (
                patch("research.models.StrategyVersion.objects.filter", return_value=strategies),
                self.assertRaisesRegex(V2S0GovernanceRefusal, "strategy evidence"),
            ):
                select_persistent_v2_s0_evidence()

        strategies = MagicMock()
        strategies.count.return_value = 1
        strategies.get.return_value = self.strategy
        for count in (0, 2):
            manifests = MagicMock()
            manifests.count.return_value = count
            with (
                patch("research.models.StrategyVersion.objects.filter", return_value=strategies),
                patch(
                    "research.models.StrategyParameterManifest.objects.filter",
                    return_value=manifests,
                ),
                self.assertRaisesRegex(V2S0GovernanceRefusal, "parameter evidence"),
            ):
                select_persistent_v2_s0_evidence()

    def test_semantic_selectors_require_exactly_one_dataset_and_job(self):
        strategy_rows = MagicMock()
        strategy_rows.count.return_value = 1
        strategy_rows.get.return_value = self.strategy
        manifest_rows = MagicMock()
        manifest_rows.count.return_value = 1
        for count in (0, 2):
            dataset_rows = MagicMock()
            dataset_rows.count.return_value = count
            with (
                patch(
                    "research.models.StrategyVersion.objects.filter",
                    return_value=strategy_rows,
                ),
                patch(
                    "research.models.StrategyParameterManifest.objects.filter",
                    return_value=manifest_rows,
                ),
                patch("market.models.DatasetVersion.objects.filter", return_value=dataset_rows),
                self.assertRaisesRegex(V2S0GovernanceRefusal, "dataset evidence"),
            ):
                select_persistent_v2_s0_evidence()

        dataset_rows = MagicMock()
        dataset_rows.count.return_value = 1
        dataset_rows.get.return_value = self.dataset
        for count in (0, 2):
            job_rows = MagicMock()
            job_rows.count.return_value = count
            with (
                patch(
                    "research.models.StrategyVersion.objects.filter",
                    return_value=strategy_rows,
                ),
                patch(
                    "research.models.StrategyParameterManifest.objects.filter",
                    return_value=manifest_rows,
                ),
                patch("market.models.DatasetVersion.objects.filter", return_value=dataset_rows),
                patch("research.models.JobRun.objects.filter", return_value=job_rows),
                self.assertRaisesRegex(V2S0GovernanceRefusal, "evidence is missing or duplicated"),
            ):
                select_persistent_v2_s0_evidence()

    def test_semantic_selectors_do_not_use_database_ids(self):
        source = Path(__file__).resolve().parents[1] / "failed_break_v2_s0_governance.py"
        tree = ast.parse(source.read_text())
        selector = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "select_persistent_v2_s0_evidence"
        )
        filter_keywords = {
            keyword.arg
            for node in ast.walk(selector)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "filter"
            for keyword in node.keywords
        }
        self.assertFalse({"id", "pk", "job_run_id", "strategy_version_id"} & filter_keywords)

    def test_partial_altered_and_claimed_only_reports_fail_independent_reconstruction(self):
        derived = self.preregistration["expected_numerical_evidence"]
        with patch(
            "research.failed_break_v2_s0.contract_for_dataset",
            return_value=self.contract,
        ):
            configuration, output = build_v2_s0_evidence(
                dataset=self.dataset,
                strategy=self.strategy,
                numerical_evidence=derived,
            )
            exact_job = SimpleNamespace(
                pk=4,
                job_name=V2_S0_JOB_NAME,
                strategy_version_id=self.strategy.pk,
                dataset_version_id=self.dataset.pk,
                status="succeeded",
                as_of=V2_S0_AS_OF,
                config_hash=output.configuration_sha256,
                evidence={"configuration": configuration, "report": output.as_dict()},
            )
            validate_stored_v2_s0_evidence(
                job=exact_job,
                dataset=self.dataset,
                strategy=self.strategy,
                derived_numerical=derived,
            )
            wrong_configuration = copy.deepcopy(exact_job)
            wrong_configuration.config_hash = "0" * 64
            wrong_report = copy.deepcopy(exact_job)
            wrong_report.evidence["report"]["report_sha256"] = "0" * 64
            for altered in (wrong_configuration, wrong_report):
                with self.assertRaisesRegex(V2S0GovernanceRefusal, "partial or changed"):
                    validate_stored_v2_s0_evidence(
                        job=altered,
                        dataset=self.dataset,
                        strategy=self.strategy,
                        derived_numerical=derived,
                    )
            partial = copy.copy(exact_job)
            partial.evidence = {"configuration": configuration}
            with self.assertRaisesRegex(V2S0GovernanceRefusal, "partial or changed"):
                validate_stored_v2_s0_evidence(
                    job=partial,
                    dataset=self.dataset,
                    strategy=self.strategy,
                    derived_numerical=derived,
                )
            false_claim = copy.deepcopy(exact_job)
            false_claim.evidence["report"]["numerical_evidence"][
                "eligible_session_observations"
            ] += 1
            with self.assertRaisesRegex(V2S0GovernanceRefusal, "partial or changed"):
                validate_stored_v2_s0_evidence(
                    job=false_claim,
                    dataset=self.dataset,
                    strategy=self.strategy,
                    derived_numerical=derived,
                )

    def test_duplicate_v2_s0_jobs_fail_before_any_numerical_reader(self):
        job = SimpleNamespace(job_name=V2_S0_JOB_NAME, pk=4)
        duplicated = MagicMock()
        duplicated.count.return_value = 2
        with (
            patch(
                "research.failed_break_v2_s0.validate_v2_s0_prerequisites",
                return_value=({}, self.contract, self.preregistration),
            ),
            patch("research.models.JobRun.objects.filter", return_value=duplicated),
            patch(
                "research.failed_break_v2_s0.derive_v2_s0_numerical_evidence"
            ) as forbidden_reader,
            self.assertRaisesRegex(V2S0GovernanceRefusal, "missing or duplicated"),
        ):
            verify_v2_s0_acceptance(
                job=job,
                dataset=self.dataset,
                strategy=self.strategy,
            )
        forbidden_reader.assert_not_called()

    def test_return_blind_allowlist_and_s1_execution_authority_remains_closed(self):
        self.assertEqual(
            V2_S0_PRICE_FIELDS,
            {"instrument__code", "timestamp", "bid_open", "ask_open"},
        )
        source_path = Path(__file__).resolve().parents[1] / "failed_break_v2_s0.py"
        tree = ast.parse(source_path.read_text())
        research_model_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "research.models"
            for alias in node.names
        }
        self.assertEqual(
            research_model_imports,
            {"JobRun", "StrategyDefinition", "StrategyParameterManifest", "StrategyVersion"},
        )
        self.assertTrue(
            (
                Path(__file__).resolve().parents[1] / "management/commands/signal_count_s1_v2.py"
            ).exists()
        )
        from research.failed_break_v2_s1_governance import (
            load_v2_s1_execution_authorization,
            load_v2_s1_policy,
        )

        self.assertFalse(load_v2_s1_policy()["authorization"]["persistent_v2_s1_execution"])
        self.assertIsNone(load_v2_s1_execution_authorization())
        self.assertFalse(load_v2_policy()["detector"]["persistent_runner_exposed"])
        self.assertFalse(self.preregistration["methodology"]["post_entry_or_outcome_access"])
        self.assertFalse(self.preregistration["authorization"]["v2_s1_execution"])
        governance_path = Path(__file__).resolve().parents[1] / "failed_break_v2_s0_governance.py"
        governance_tree = ast.parse(governance_path.read_text())
        governed_model_imports = {
            alias.name
            for node in ast.walk(governance_tree)
            if isinstance(node, ast.ImportFrom)
            and node.module in {"market.models", "research.models"}
            for alias in node.names
        }
        self.assertEqual(
            governed_model_imports,
            {"DatasetVersion", "JobRun", "StrategyParameterManifest", "StrategyVersion"},
        )
        imported_modules = {
            alias.name
            for node in ast.walk(governance_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertNotIn("requests", imported_modules)

    def test_v1_governed_sources_remain_byte_identical(self):
        root = Path(__file__).resolve().parents[2]
        expected = {
            "research/signal_count.py": (
                "376b3fa5fc1f064f560d0b352f49c90285bd0b2dd741c42813781ffb462ed7b5"
            ),
            "research/s0_acceptance.py": (
                "ec41714c2a1a6e805a1db8ff730b2946e2ac5696eeb72b3715e10562939b952d"
            ),
            "docs/strategy/failed-break/v1/phase-2b1r-pre-s1-s0-acceptance.json": (
                "225c5365219bd7653c99d8f25e113df9c5f4ad24d95b35b36f7928479bee9583"
            ),
        }
        for relative_path, expected_hash in expected.items():
            self.assertEqual(
                hashlib.sha256((root / relative_path).read_bytes()).hexdigest(),
                expected_hash,
            )
