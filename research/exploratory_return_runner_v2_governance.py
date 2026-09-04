"""Fixed-path governance for the v2 exploratory-return runner."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from pathlib import Path

from research import exploratory_returns_v2_governance as calculator_governance
from research import s2_policy_v2

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs/strategy/failed-break/v2"
HISTORICAL_ARTIFACT_PATH = DOCS / "exploratory-return-runner-preregistration-v2.json"
LINEAGE_ARTIFACT_PATH = DOCS / "exploratory-return-lineage-performance-preregistration-v2.json"
LINEAGE_REPORT_PATH = DOCS / "exploratory-return-lineage-performance-correction-v2.md"
ARTIFACT_PATH = DOCS / "exploratory-return-rollover-preregistration-v2.json"
REPORT_PATH = DOCS / "exploratory-return-rollover-correction-v2.md"
PREDECESSOR_AUTHORIZATION_PATH = DOCS / "exploratory-return-execution-authorization-v2.json"
FAILURE_PATH = DOCS / "exploratory-return-execution-failure-v2.json"
CONSUMED_SUCCESSOR_AUTHORIZATION_PATH = (
    DOCS / "exploratory-return-replacement-authorization-v2.json"
)
SECOND_FAILURE_PATH = DOCS / "exploratory-return-lineage-timeout-failure-v2.json"
PERFORMANCE_EVIDENCE_PATH = DOCS / "exploratory-return-lineage-performance-rehearsal-v2.json"
CONSUMED_ROLLOVER_AUTHORIZATION_PATH = (
    DOCS / "exploratory-return-lineage-performance-authorization-v2.json"
)
ROLLOVER_FAILURE_PATH = DOCS / "exploratory-return-rollover-execution-failure-v2.json"
ROLLOVER_REHEARSAL_PATH = DOCS / "exploratory-return-rollover-rehearsal-v2.json"
AUTHORIZATION_PATH = DOCS / "exploratory-return-rollover-authorization-v2.json"
CORRECTION_REPORT_PATH = DOCS / "exploratory-return-rlimit-correction-v2.md"
REHEARSAL_PATH = DOCS / "exploratory-return-rlimit-rehearsal-v2.json"

LINEAGE_REPOSITORY_BASELINE = "d9a1c09df96649bc82c6259e5952adf613286be3"
LINEAGE_SCHEMA = "failed-break-v2-exploratory-return-lineage-performance-preregistration-v1"
LINEAGE_IDENTITY = "failed-break-v2-exploratory-return-lineage-performance-correction-v1"
LINEAGE_ARTIFACT_SHA256 = "786f727719c962948de1d6c330f6aa6e67af7ca22276ef80f6b6dc6b9b9d26b8"
LINEAGE_SELF_SHA256 = "00dc9e580d3680fe3a7227b78b43d04908c2f51c97a0b68e31115cf69289f2bf"
LINEAGE_REPORT_SHA256 = "b85fa0edc48ac3cecc71abe7da2af3c0efeaf0d92569d68ba45f2a5c2b124917"
REPOSITORY_BASELINE = "71260ab4a3797ecc0f7420da2f159b5a14381877"
SCHEMA = "failed-break-v2-exploratory-return-rollover-runner-correction-v1"
IDENTITY = "failed-break-v2-exploratory-return-rollover-runner-correction-v1"
ARTIFACT_SHA256 = "fa041f60701d089649fc4da57b35bdd38794e27b30d94166dca9442c548e0b32"
SELF_SHA256 = "bcd1f67b6e11c7fd5d8791058cdb1dfbe82b053a3828dd68dc0400d11c747157"
REPORT_SHA256 = "9fec559a810eabfdb2c7cde6b6140b4bbd08f87c7791752a271bf1b5521d678d"
RUNNER_SHA256 = "bdad1fd3e0c41bd43645d09d9aeccb4c8f4b8115c72a5ac30b7f3a37a9a052eb"
MEMORY_BOUNDARY_SHA256 = "7e39e860419e677a811ad7fe755747c81d1ba4d8be329a1cbdfdf09f2bb8a182"
ADAPTER_SHA256 = "c67b2d1449bbe0b8416f26593cd27481c83e4eb392c48df2581058995f1cdfab"
COMMAND_SHA256 = "4d41b1021837c59f71fde4ce6edd20c30c9064334f35548801233e9b05913d52"
BENCHMARK_SHA256 = "404c6cf996c13d54338fc61191416e00b57de6bf6fadf43af004121234cb2862"
PREDECESSOR_AUTHORIZATION_ARTIFACT_SHA256 = (
    "21c2a3ce7a8ae7eb46ca07a551160a1830f58b4938215491ab40d026f96c349c"
)
PREDECESSOR_AUTHORIZATION_SELF_SHA256 = (
    "e0904ae6885d55da3ad10d500018b35d6b48631334a98e342155e7eac859df9a"
)
PREDECESSOR_AUTHORIZATION_SCHEMA = "failed-break-v2-exploratory-return-execution-authorization-v1"
PREDECESSOR_AUTHORIZATION_IDENTITY = "failed-break-v2-exploratory-return-single-execution-v1"
FAILURE_ARTIFACT_SHA256 = "47f76090cd933002067d3f48594c8fcd68fdb6e48d2f121089212b20ebd910b0"
FAILURE_SELF_SHA256 = "7a76a6c0249f9f5d5eece84f90175880d712624ed1c79eb7a4821ab1b4d8030e"
FAILURE_SCHEMA = "failed-break-v2-exploratory-return-pre-outcome-failure-v1"
FAILURE_IDENTITY = "failed-break-v2-exploratory-return-first-authorization-consumed-v1"
CONSUMED_SUCCESSOR_AUTHORIZATION_ARTIFACT_SHA256 = (
    "e84b1b4b4a8b6b6c25ff4eefca21ab649b4a460a0b3db04b09c0433888407868"
)
CONSUMED_SUCCESSOR_AUTHORIZATION_SELF_SHA256 = (
    "d6b3e312f80a8395418726e95e384463c29feb11352e0306e46f9398c5f833a5"
)
SECOND_FAILURE_ARTIFACT_SHA256 = "ca8436767223bc0dd5d954241a96fe01e75e630055912381635d9d371565b325"
SECOND_FAILURE_SELF_SHA256 = "6e0ca64a7f26437936645e887afc5d379ec05b00b74ff072a7f0dbbe2c4aa6a6"
PERFORMANCE_EVIDENCE_SHA256 = "a0c40fa8140ae2bb95f7df99f1f11f8e1ac17d0bfbdb28c6ab31a6079aa8c120"
PERFORMANCE_EVIDENCE_SELF_SHA256 = (
    "87f77badb6c465ffcb3a877c593ba8ad14e0334e3d9a32ad1b0ba87c05bcae34"
)
CONSUMED_ROLLOVER_AUTHORIZATION_ARTIFACT_SHA256 = (
    "d3c05c54a6fd0ec9af65f88489e30948f9ace072835756dd5c4b999f91de0b85"
)
CONSUMED_ROLLOVER_AUTHORIZATION_SELF_SHA256 = (
    "0e61b6bb07810dc579ef770d39a8144ae5e7f01ff6c1cc6dee9e24a4871c036a"
)
ROLLOVER_FAILURE_ARTIFACT_SHA256 = (
    "425a75912ba991fb01f96d1eb88778c60e2c2a5c6874d954c2838d4f1c1b379b"
)
ROLLOVER_FAILURE_SELF_SHA256 = "c4de8dd992fb31e199b2015df49952fc116f0fee364ea64827062292a1d25732"
ROLLOVER_REHEARSAL_ARTIFACT_SHA256 = (
    "1b1e3c23641c99a26d18e3bdde3ab87fa0e338196385749517ab5cd3ab0acef1"
)
ROLLOVER_REHEARSAL_SELF_SHA256 = "51749b0daa69bf39bb2626c0f09e52c73f99bbe813deb1228645297d3096771f"
AUTHORIZATION_ARTIFACT_SHA256 = "d77c1b5d69061a7bc80a99aacf82e92ed65287fc4a3029bc61f3853590ddb31a"
AUTHORIZATION_SELF_SHA256 = "6daed2315f2353ab62a3b00dd531a6566f9597b5933e1e819e412aa4314f7180"
AUTHORIZATION_SCHEMA = "failed-break-v2-exploratory-return-rollover-successor-authorization-v1"
AUTHORIZATION_IDENTITY = "failed-break-v2-exploratory-return-single-rollover-successor-v1"
AUTHORIZED_BASELINE = REPOSITORY_BASELINE
CORRECTION_REPORT_SHA256 = "8bb06ab0456e99c0d2dcb19a75722957086fd6278dfd02933c0cce32aab5e11f"
REHEARSAL_SHA256 = "8b1e433337856f2b85d2ff26dc9f2d943879a126272599298cdff43ce11796a7"
REHEARSAL_SELF_SHA256 = "97351aa03080b7903cbb152ee250a1d945f0963979298f85f69ef2d199f2f10b"
REQUIRED_DATABASE = "trade_recommender_research"
REQUIRED_DATABASE_HOST = "/tmp"
REQUIRED_NETWORK_POLICY = "LOCAL_POSTGRES_UNIX_SOCKET_ONLY_V1"
REQUIRED_POSTGRES_PATH = "/Applications/Postgres.app/Contents/Versions/latest/bin"
PROVIDER_CREDENTIAL_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "EODHD_API_KEY",
    "EODHD_API_TOKEN",
    "OANDA_ACCOUNT_ID",
    "OANDA_API_KEY_TEST",
    "OANDA_TOKEN",
)
CALCULATOR_ARTIFACT_SHA256 = calculator_governance.ARTIFACT_SHA256
CALCULATOR_SELF_SHA256 = calculator_governance.SELF_SHA256
S2_ARTIFACT_SHA256 = s2_policy_v2.ARTIFACT_SHA256
S2_POLICY_SHA256 = s2_policy_v2.POLICY_SHA256
S1_ACCEPTANCE_SHA256 = s2_policy_v2.S1_ARTIFACT_SHA256
GEOMETRY_ARTIFACT_SHA256 = s2_policy_v2.GEOMETRY_ARTIFACT_SHA256
GEOMETRY_EVENT_SET_SHA256 = s2_policy_v2.EVENT_SET_SHA256
BOUNDARY_PURGED_EVENT_KEY = calculator_governance.BOUNDARY_PURGED_EVENT_KEY


class RunnerGovernanceRefusal(ValueError):
    """A fixed artifact, source identity, or authority failed closed."""


def require(condition, message):
    if not condition:
        raise RunnerGovernanceRefusal(message)


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def governed_event_keys() -> tuple[str, ...]:
    keys = calculator_governance.governed_event_keys()
    require(len(keys) == 82 and BOUNDARY_PURGED_EVENT_KEY not in keys, "event set changed")
    return keys


def inspect_lineage_preregistration_history() -> dict:
    """Verify the preceding lineage-performance correction as immutable history."""
    try:
        raw = LINEAGE_ARTIFACT_PATH.read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == LINEAGE_ARTIFACT_SHA256,
            "lineage artifact digest mismatch",
        )
        artifact = json.loads(raw)
        require(canonical_bytes(artifact) + b"\n" == raw, "artifact bytes are not canonical")
        body = dict(artifact)
        require(
            body.pop("implementation_sha256", None) == LINEAGE_SELF_SHA256 == digest(body),
            "lineage artifact self-hash mismatch",
        )
        require(
            artifact["schema"] == LINEAGE_SCHEMA
            and artifact["identity"] == LINEAGE_IDENTITY
            and artifact["repository_baseline"] == LINEAGE_REPOSITORY_BASELINE,
            "lineage runner identity changed",
        )
        require(
            artifact["authority"]
            == {
                "code_only_implementation": True,
                "persistent_execution": False,
                "post_entry_real_outcome_access": False,
                "real_outcome_access": False,
                "return_calculation": False,
                "synthetic_verification": True,
                "promotion_or_live_trading": False,
                "provider_production_or_deployment": False,
            },
            "implementation authority changed",
        )
        require(
            artifact["execution_authorization"]
            == {
                "artifact_present": True,
                "future_command": (
                    ".venv/bin/python manage.py calculate_exploratory_returns_v2 --execute"
                ),
                "retry": "PROHIBITED",
                "resume": "PROHIBITED",
                "status": "BOUND_BY_SEPARATE_SUCCESSOR_ARTIFACT",
            },
            "execution boundary changed",
        )
        bindings = artifact["bindings"]
        require(
            bindings["calculator"]
            == {
                "artifact_sha256": calculator_governance.HISTORICAL_ARTIFACT_SHA256,
                "self_sha256": calculator_governance.HISTORICAL_SELF_SHA256,
            }
            and bindings["effective_s2_policy"]
            == {
                "artifact_sha256": S2_ARTIFACT_SHA256,
                "policy_sha256": S2_POLICY_SHA256,
            }
            and bindings["s1_acceptance_sha256"] == S1_ACCEPTANCE_SHA256
            and bindings["geometry_artifact_sha256"] == GEOMETRY_ARTIFACT_SHA256
            and bindings["geometry_event_set_sha256"] == GEOMETRY_EVENT_SET_SHA256,
            "upstream governed identity changed",
        )
        require(
            _source_hash(HISTORICAL_ARTIFACT_PATH)
            == bindings["historical_preregistration_sha256"]
            == "3e465e56af7eb0bc5eef175618dc8c38d0e8fafcc7a867d6b31e70946de3a93a",
            "historical runner preregistration changed",
        )
        source_files = bindings["source_files"]
        expected_sources = {
            "research/exploratory_return_adapter_v2.py": (
                "a515909321aea59316c72289183dc2c94872643ddc4621317c5d8ff8e6ca7359"
            ),
            "research/exploratory_return_memory_v2.py": MEMORY_BOUNDARY_SHA256,
            "research/exploratory_return_runner_v2.py": RUNNER_SHA256,
            "research/management/commands/calculate_exploratory_returns_v2.py": COMMAND_SHA256,
        }
        require(source_files == expected_sources, "historical governed source map changed")
        require(
            _source_hash(LINEAGE_REPORT_PATH) == LINEAGE_REPORT_SHA256,
            "lineage report drift",
        )
        calculator_governance.inspect_historical_preregistration()
        policy = s2_policy_v2.load_policy()
        require(
            policy["status"] == "EFFECTIVE_EXPLORATORY_ONLY"
            and policy["boundary"]["promotion_permanently_prohibited"] is True,
            "effective exploratory-only policy changed",
        )
        require(
            artifact["expected"]["physical_event_count"] == len(governed_event_keys()) == 82
            and artifact["expected"]["one_complete_result"] is True,
            "expected result boundary changed",
        )
        return artifact
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise RunnerGovernanceRefusal("incomplete lineage runner history") from error


def load_preregistration() -> dict:
    """Verify the forward-only rollover runner correction."""
    try:
        history = inspect_lineage_preregistration_history()
        raw = ARTIFACT_PATH.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == ARTIFACT_SHA256, "artifact digest mismatch")
        artifact = json.loads(raw)
        require(canonical_bytes(artifact) + b"\n" == raw, "artifact bytes are not canonical")
        body = dict(artifact)
        require(
            body.pop("implementation_sha256", None) == SELF_SHA256 == digest(body),
            "artifact self-hash mismatch",
        )
        require(
            artifact["schema"] == SCHEMA
            and artifact["identity"] == IDENTITY
            and artifact["repository_baseline"] == REPOSITORY_BASELINE,
            "runner correction identity changed",
        )
        require(
            artifact["authority"]
            == {
                "code_only_correction": True,
                "disposable_real_data_validation": True,
                "persistent_execution": False,
                "post_entry_real_outcome_access": "DISPOSABLE_RESTORE_ONLY",
                "promotion_or_live_trading": False,
                "provider_production_or_deployment": False,
            },
            "runner correction authority changed",
        )
        bindings = artifact["bindings"]
        require(
            bindings["historical_runner_preregistration"]
            == {
                "artifact_sha256": LINEAGE_ARTIFACT_SHA256,
                "self_sha256": LINEAGE_SELF_SHA256,
            }
            and history["implementation_sha256"] == LINEAGE_SELF_SHA256,
            "historical runner binding changed",
        )
        require(
            bindings["calculator"]
            == {
                "artifact_sha256": CALCULATOR_ARTIFACT_SHA256,
                "self_sha256": CALCULATOR_SELF_SHA256,
                "source_sha256": calculator_governance.CALCULATOR_SHA256,
            }
            and bindings["effective_s2_policy"]
            == {
                "artifact_sha256": S2_ARTIFACT_SHA256,
                "self_sha256": S2_POLICY_SHA256,
            }
            and bindings["v2_s1_acceptance_sha256"] == S1_ACCEPTANCE_SHA256,
            "current calculator or upstream binding changed",
        )
        require(
            bindings["geometry"]
            == {
                "event_set_sha256": GEOMETRY_EVENT_SET_SHA256,
                "nonadditive_book_memberships": 186,
                "physical_events": 82,
            },
            "geometry binding changed",
        )
        expected_sources = {
            "research/benchmarks/benchmark_exploratory_returns_v2.py": BENCHMARK_SHA256,
            "research/exploratory_return_adapter_v2.py": ADAPTER_SHA256,
            "research/exploratory_return_memory_v2.py": MEMORY_BOUNDARY_SHA256,
            "research/exploratory_return_runner_v2.py": RUNNER_SHA256,
            "research/exploratory_returns_v2.py": calculator_governance.CALCULATOR_SHA256,
            "research/management/commands/calculate_exploratory_returns_v2.py": COMMAND_SHA256,
        }
        require(bindings["source_files"] == expected_sources, "governed source map changed")
        for relative, expected in expected_sources.items():
            require(_source_hash(ROOT / relative) == expected, f"source drift: {relative}")
        require(
            bindings["failure"]
            == {
                "artifact_sha256": ROLLOVER_FAILURE_ARTIFACT_SHA256,
                "self_sha256": ROLLOVER_FAILURE_SELF_SHA256,
            }
            and bindings["rehearsal"]
            == {
                "artifact_sha256": ROLLOVER_REHEARSAL_ARTIFACT_SHA256,
                "evidence_sha256": ROLLOVER_REHEARSAL_SELF_SHA256,
                "report_sha256": REPORT_SHA256,
            },
            "failure or rehearsal binding changed",
        )
        require(
            artifact["expected"]
            == {
                "nonadditive_book_memberships": 186,
                "one_complete_result": True,
                "physical_event_count": 82,
            }
            and artifact["status"] == "CORRECTED_DISPOSABLE_VALIDATED_AUTHORIZATION_SEPARATE",
            "runner correction expected boundary changed",
        )
        require(_source_hash(REPORT_PATH) == REPORT_SHA256, "correction report drift")
        calculator_governance.load_preregistration()
        return artifact
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise RunnerGovernanceRefusal("incomplete runner rollover correction") from error


def _all_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(map(_all_keys, value.values())))
    if isinstance(value, list):
        return set().union(*(map(_all_keys, value))) if value else set()
    return set()


def _expected_lineage(s1: dict) -> dict:
    dataset = s1["bindings"]["dataset"]
    strategy = s1["bindings"]["strategy"]
    return {
        "dataset": {
            "operational_id": 3,
            "name": dataset["name"],
            "version": dataset["version"],
            "manifest_sha256": dataset["manifest_sha256"],
            "contract_sha256": dataset["contract_sha256"],
            "effective_data_identity": dataset["effective_data_identity"],
            "global_semantic_inventory_sha256": dataset["global_semantic_inventory_sha256"],
            "registration_configuration_sha256": dataset["registration_configuration_sha256"],
            "registration_report_sha256": dataset["registration_report_sha256"],
        },
        "strategy": {
            "operational_id": 2,
            "identity": strategy["identity"],
            "detector_identity": strategy["detector_identity"],
            "content_sha256": strategy["content_sha256"],
        },
        "s0_job": {
            "operational_id": 4,
            "identity": s1["bindings"]["s0"]["job_identity"],
        },
        "s1_job": {
            "operational_id": 5,
            "identity": s1["execution"]["job_identity"],
        },
    }


def _expected_pristine_state(s1: dict) -> dict:
    return {
        "application_counts_sha256": s1["application_state"]["counts_sha256"],
        "application_current_totals": s1["application_state"]["current_totals"],
        "forbidden_result_rows": 0,
        "migration_state": {
            "market": "0027_gate8i_final_dataset_acceptance",
            "research": "0015_pre_s1_inventory_entry_boundary",
        },
        "return_result_idempotency_key_present": False,
        "successful_attempt1_chains": 132,
    }


def _expected_environment() -> dict:
    return {
        "architecture": "arm64",
        "database": REQUIRED_DATABASE,
        "database_host": REQUIRED_DATABASE_HOST,
        "external_network": "DENIED_EXCEPT_PRIVATE_TMP_POSTGRES_UNIX_SOCKET",
        "interpreter": ".venv/bin/python",
        "network_policy_attestation": REQUIRED_NETWORK_POLICY,
        "postgres_conn_max_age": "0",
        "postgres_socket": "/private/tmp/.s.PGSQL.5432",
        "postgresapp_path_required": REQUIRED_POSTGRES_PATH,
        "provider_credential_variables_unset": list(PROVIDER_CREDENTIAL_VARIABLES),
    }


def _expected_backup_and_verification() -> dict:
    return {
        "pre_operation_backup": {
            "non_overwriting": True,
            "mode": "0600",
            "sha256_sidecar": True,
            "pg_restore_list": "REQUIRED_SUCCESS",
        },
        "post_operation_backup": {
            "non_overwriting": True,
            "mode": "0600",
            "sha256_sidecar": True,
            "pg_restore_list": "REQUIRED_SUCCESS",
        },
        "post_commit_independent_reconstruction": {
            "all_82_events": True,
            "all_15_cost_cells_per_event_and_risk": True,
            "canonical_result_hashes": True,
            "every_other_application_table_delta_zero": True,
            "promotion_and_live_trading_remain_prohibited": True,
            "repeat_readiness_refuses": True,
        },
    }


def _load_canonical(path: Path, expected_sha256: str, self_field: str, expected_self: str):
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, f"{path.name} digest mismatch")
    document = json.loads(raw)
    require(canonical_bytes(document) + b"\n" == raw, f"{path.name} bytes not canonical")
    body = dict(document)
    claimed = body.pop(self_field, None)
    require(claimed == expected_self == digest(body), f"{path.name} self-hash mismatch")
    return document


def inspect_predecessor_authorization_history() -> dict:
    """Verify the immutable first authorization as consumed history only."""

    try:
        authorization = _load_canonical(
            PREDECESSOR_AUTHORIZATION_PATH,
            PREDECESSOR_AUTHORIZATION_ARTIFACT_SHA256,
            "authorization_sha256",
            PREDECESSOR_AUTHORIZATION_SELF_SHA256,
        )
        require(
            authorization["schema"] == PREDECESSOR_AUTHORIZATION_SCHEMA
            and authorization["identity"] == PREDECESSOR_AUTHORIZATION_IDENTITY
            and authorization["repository_baseline"] == "b38a8918b18e461900cb773d679bc14cca03ee12",
            "predecessor authorization identity changed",
        )
        require(
            authorization["command"]["argv"]
            == [
                ".venv/bin/python",
                "manage.py",
                "calculate_exploratory_returns_v2",
                "--execute",
            ]
            and authorization["result"]["idempotency_key"]
            == "failed-break-exploratory-returns-v2|phase-2b1r-v2|development-2010-2018",
            "predecessor execution identity changed",
        )
        return {
            **authorization,
            "artifact_sha256": PREDECESSOR_AUTHORIZATION_ARTIFACT_SHA256,
            "consumed": True,
            "status": "CONSUMED_PRE_OUTCOME_FAILURE_RETRY_PROHIBITED",
        }
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise RunnerGovernanceRefusal("missing or invalid predecessor authorization") from error


def inspect_failed_execution() -> dict:
    """Verify the immutable no-result failure that consumed the first authority."""

    try:
        failure = _load_canonical(
            FAILURE_PATH,
            FAILURE_ARTIFACT_SHA256,
            "failure_sha256",
            FAILURE_SELF_SHA256,
        )
        predecessor = inspect_predecessor_authorization_history()
        require(
            failure["schema"] == FAILURE_SCHEMA
            and failure["identity"] == FAILURE_IDENTITY
            and failure["repository_baseline"] == "9a391a711669984eb9c705aae5076d233d362478",
            "failed-execution identity changed",
        )
        require(
            failure["predecessor_authorization"]
            == {
                "artifact_sha256": PREDECESSOR_AUTHORIZATION_ARTIFACT_SHA256,
                "identity": PREDECESSOR_AUTHORIZATION_IDENTITY,
                "self_sha256": PREDECESSOR_AUTHORIZATION_SELF_SHA256,
                "status": "CONSUMED_PRE_OUTCOME_FAILURE_RETRY_PROHIBITED",
            }
            and predecessor["consumed"] is True,
            "failed execution does not consume the predecessor authority",
        )
        require(
            failure["attempt"]
            == {
                "argv": [
                    ".venv/bin/python",
                    "manage.py",
                    "calculate_exploratory_returns_v2",
                    "--execute",
                ],
                "exit_code": 1,
                "failure": (
                    "_operational_limits() raised ValueError: current limit exceeds maximum "
                    "limit while setting RLIMIT_AS"
                ),
                "peak_rss_bytes": 78_053_376,
                "reached_calculation": False,
                "reached_outcome_loading": False,
                "reached_persistence": False,
                "reached_transaction_entry": False,
                "runtime_seconds": "1.09",
                "total_sql_query_count": "UNKNOWN_NOT_INSTRUMENTED",
            },
            "accepted failure record changed",
        )
        require(
            failure["persistent_state"]
            == {
                "application_count_sha256_after": (
                    "5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097"
                ),
                "application_count_sha256_before": (
                    "5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097"
                ),
                "idempotency_key_rows": 0,
                "persistent_writes": 0,
                "result_rows": 0,
            }
            and failure["operational_evidence"]
            == {
                "failure_log_sha256": (
                    "ca04236cd5b6eb1dee7532bf1e9fd08c69bb291d92ba021fa8d8e34eccf6abfd"
                ),
                "pre_operation_backup_sha256": (
                    "8bf35a644315592d05361e488ffdd390fe2fc78c5135ed755a5c777ce373450c"
                ),
                "pre_operation_backup_size_bytes": 52_862_399,
            },
            "accepted persistent failure state changed",
        )
        require(
            failure["authority"]
            == {
                "no_outcome_calculated": True,
                "original_authorization_consumed": True,
                "replacement_requires_new_forward_authorization": True,
                "retry_under_original_authorization": False,
            },
            "failed-execution authority changed",
        )
        return {**failure, "artifact_sha256": FAILURE_ARTIFACT_SHA256, "status": "ACCEPTED"}
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise RunnerGovernanceRefusal("missing or invalid failed-execution artifact") from error


def validate_execution_environment() -> dict:
    """Validate non-secret runtime settings before any Django adapter import."""
    expected_python = ROOT / ".venv/bin/python"
    require(Path(sys.executable) == expected_python, ".venv/bin/python is required")
    require(platform.machine() == "arm64", "native arm64 interpreter is required")
    require(os.environ.get("POSTGRES_DB") == REQUIRED_DATABASE, "research database is required")
    require(os.environ.get("POSTGRES_HOST") == REQUIRED_DATABASE_HOST, "Unix socket host required")
    require(os.environ.get("POSTGRES_CONN_MAX_AGE") == "0", "persistent DB connections prohibited")
    require(
        os.environ.get("EXPLORATORY_RETURN_NETWORK_POLICY") == REQUIRED_NETWORK_POLICY,
        "local-socket-only network policy attestation required",
    )
    require(
        REQUIRED_POSTGRES_PATH in os.environ.get("PATH", "").split(os.pathsep),
        "compatible Postgres.app path is required",
    )
    present = [name for name in PROVIDER_CREDENTIAL_VARIABLES if name in os.environ]
    require(not present, "provider or unrelated API credential variable is present")
    require(os.environ.get("POSTGRES_DB") != "trade_recommender", "production database prohibited")
    return {
        "architecture": platform.machine(),
        "database": REQUIRED_DATABASE,
        "database_host": REQUIRED_DATABASE_HOST,
        "interpreter": ".venv/bin/python",
        "network_policy": REQUIRED_NETWORK_POLICY,
        "provider_credentials_present": 0,
    }


def inspect_consumed_successor_authorization_history() -> dict:
    """Verify the second, now-consumed authorization as immutable history."""

    authorization = _load_canonical(
        CONSUMED_SUCCESSOR_AUTHORIZATION_PATH,
        CONSUMED_SUCCESSOR_AUTHORIZATION_ARTIFACT_SHA256,
        "authorization_sha256",
        CONSUMED_SUCCESSOR_AUTHORIZATION_SELF_SHA256,
    )
    require(
        authorization["identity"] == "failed-break-v2-exploratory-return-single-replacement-v1"
        and authorization["repository_baseline"] == "9a391a711669984eb9c705aae5076d233d362478"
        and authorization["bindings"]["failure"]["artifact_sha256"] == FAILURE_ARTIFACT_SHA256
        and authorization["command"]["operational_ceiling_seconds"] == 900,
        "consumed successor authorization changed",
    )
    return {
        **authorization,
        "artifact_sha256": CONSUMED_SUCCESSOR_AUTHORIZATION_ARTIFACT_SHA256,
        "consumed": True,
        "status": "CONSUMED_TIMEOUT_FAILURE_RETRY_PROHIBITED",
    }


def inspect_second_failed_execution() -> dict:
    """Verify the timeout that consumed the second authorization."""

    failure = _load_canonical(
        SECOND_FAILURE_PATH,
        SECOND_FAILURE_ARTIFACT_SHA256,
        "failure_sha256",
        SECOND_FAILURE_SELF_SHA256,
    )
    consumed = inspect_consumed_successor_authorization_history()
    require(
        failure["identity"] == "failed-break-v2-exploratory-return-lineage-timeout-v1"
        and failure["consumed_authorization"]["artifact_sha256"]
        == CONSUMED_SUCCESSOR_AUTHORIZATION_ARTIFACT_SHA256
        and consumed["consumed"] is True,
        "second failure does not consume the successor authorization",
    )
    require(
        failure["attempt"]
        == {
            "argv": [
                ".venv/bin/python",
                "manage.py",
                "calculate_exploratory_returns_v2",
                "--execute",
            ],
            "duration_seconds": "901.421431",
            "error": "exploratory return execution exceeded 15-minute ceiling",
            "exit_code": 1,
            "invocations": 1,
            "last_progress": "stage=lineage completed=0 total=82",
            "normalized_completion_marker": False,
            "outcome_rows_read_before_timeout": "NOT_PROVABLE_FROM_CAPTURED_TELEMETRY",
            "sql_query_count": "UNKNOWN_NOT_CAPTURED",
        },
        "second failure execution record changed",
    )
    require(
        failure["persistent_state"]
        == {
            "application_count_sha256_after": (
                "5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097"
            ),
            "application_count_sha256_before": (
                "5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097"
            ),
            "application_table_delta": 0,
            "idempotency_rows": 0,
            "job_runs": 5,
            "result_rows": 0,
        }
        and failure["runtime"]
        == {
            "maximum_locks": 501,
            "parent_peak_rss_bytes": 76_414_976,
            "process_tree_peak_rss_bytes": 309_460_992,
            "waiting_locks": 0,
            "worker_peak_rss_bytes": 246_497_280,
        },
        "second failure persistent or runtime evidence changed",
    )
    require(
        failure["operational_evidence"]
        == {
            "execution_log_sha256": (
                "ce9b319517d762316d4cfe2876f6a0c3c34fc6b6d90451deae98369141d717e5"
            ),
            "pre_operation_backup_sha256": (
                "709121f0fda6c29cb321143701f3ce61259fb82586d56e304a1bb0353bf7c35e"
            ),
            "pre_operation_backup_size_bytes": 52_862_399,
            "runtime_metrics_sha256": (
                "d20ceeef0b5094c3f776fa849aeda50857eb1db8610ed4003897b9a2ba256f06"
            ),
        },
        "second failure operational evidence changed",
    )
    return {**failure, "artifact_sha256": SECOND_FAILURE_ARTIFACT_SHA256, "status": "ACCEPTED"}


def inspect_performance_evidence() -> dict:
    evidence = _load_canonical(
        PERFORMANCE_EVIDENCE_PATH,
        PERFORMANCE_EVIDENCE_SHA256,
        "evidence_sha256",
        PERFORMANCE_EVIDENCE_SELF_SHA256,
    )
    require(
        evidence["root_cause"]["prior_lookup_calls"] == 19_878
        and evidence["root_cause"]["legacy_inventory_elements_scanned"] == 1_141_664_450
        and evidence["corrected_persistent_read_only"]["needed_candles"] == 27_969
        and evidence["corrected_persistent_read_only"]["query_count_before_candle_loading"] == 3
        and evidence["synthetic"]["deterministic_hashes"] is True
        and evidence["synthetic"]["maximum_duration_seconds"] < 10
        and evidence["synthetic"]["maximum_process_tree_rss_bytes"] < 1_073_741_824,
        "performance evidence changed or lacks bounded headroom",
    )
    return evidence


def _inspect_lineage_performance_authorization_legacy() -> dict:
    """Retained source history; current authority is verified below."""

    try:
        authorization = _load_canonical(
            AUTHORIZATION_PATH,
            AUTHORIZATION_ARTIFACT_SHA256,
            "authorization_sha256",
            AUTHORIZATION_SELF_SHA256,
        )
        require(
            authorization["schema"] == AUTHORIZATION_SCHEMA
            and authorization["identity"] == AUTHORIZATION_IDENTITY
            and authorization["repository_baseline"] == AUTHORIZED_BASELINE,
            "execution authorization identity changed",
        )
        require(
            set(authorization)
            == {
                "authority",
                "authorization_sha256",
                "bindings",
                "command",
                "environment",
                "expected_pristine_state",
                "identity",
                "override_prohibition",
                "repository_baseline",
                "result",
                "schema",
            }
            and set(authorization["bindings"])
            == {
                "calculator",
                "consumed_authorizations",
                "effective_s2_policy",
                "failure_artifacts",
                "geometry",
                "lineage",
                "performance_evidence",
                "preregistration",
                "runner_sources",
            },
            "execution authorization shape changed",
        )
        expected_authority = {
            "exploratory_return_execution": "EXACTLY_ONE_NEW_REPLACEMENT",
            "further_retry_or_replacement": False,
            "live_trading": "PERMANENTLY_PROHIBITED",
            "post_entry_real_outcome_access": "ONLY_INSIDE_SINGLE_EXECUTION",
            "post_result_policy_tuning": False,
            "promotion": "PERMANENTLY_PROHIBITED",
            "provider_production_or_deployment": False,
            "result_replacement": False,
            "retry_or_resume": False,
        }
        require(authorization["authority"] == expected_authority, "execution authority changed")
        require(
            authorization["command"]
            == {
                "alternate_arguments": False,
                "argv": [
                    ".venv/bin/python",
                    "manage.py",
                    "calculate_exploratory_returns_v2",
                    "--execute",
                ],
                "atomic_transaction": True,
                "memory_ceiling_bytes": 1_073_741_824,
                "operational_ceiling_seconds": 900,
                "requires_fresh_verified_backup": True,
            },
            "execution command changed",
        )
        first = inspect_predecessor_authorization_history()
        first_failure = inspect_failed_execution()
        second = inspect_consumed_successor_authorization_history()
        second_failure = inspect_second_failed_execution()
        performance = inspect_performance_evidence()
        preregistration = load_preregistration()
        bindings = authorization["bindings"]
        require(
            bindings["consumed_authorizations"]
            == [
                PREDECESSOR_AUTHORIZATION_ARTIFACT_SHA256,
                CONSUMED_SUCCESSOR_AUTHORIZATION_ARTIFACT_SHA256,
            ]
            and bindings["failure_artifacts"]
            == [FAILURE_ARTIFACT_SHA256, SECOND_FAILURE_ARTIFACT_SHA256]
            and bindings["preregistration"]
            == {"artifact_sha256": ARTIFACT_SHA256, "self_sha256": SELF_SHA256}
            and bindings["performance_evidence"]
            == {
                "artifact_sha256": PERFORMANCE_EVIDENCE_SHA256,
                "self_sha256": PERFORMANCE_EVIDENCE_SELF_SHA256,
                "report_sha256": REPORT_SHA256,
            }
            and bindings["runner_sources"]
            == {
                "adapter_sha256": ADAPTER_SHA256,
                "command_sha256": COMMAND_SHA256,
                "memory_boundary_sha256": MEMORY_BOUNDARY_SHA256,
                "runner_sha256": RUNNER_SHA256,
            }
            and bindings["calculator"]
            == {
                "artifact_sha256": CALCULATOR_ARTIFACT_SHA256,
                "self_sha256": CALCULATOR_SELF_SHA256,
                "source_sha256": calculator_governance.CALCULATOR_SHA256,
            }
            and bindings["effective_s2_policy"]
            == {
                "artifact_sha256": S2_ARTIFACT_SHA256,
                "self_sha256": S2_POLICY_SHA256,
            }
            and bindings["geometry"]
            == {
                "artifact_sha256": s2_policy_v2.GEOMETRY_ARTIFACT_SHA256,
                "event_set_sha256": s2_policy_v2.EVENT_SET_SHA256,
                "memberships_sha256": s2_policy_v2.MEMBERSHIPS_SHA256,
                "nonadditive_book_memberships": 186,
                "physical_events": 82,
                "self_sha256": s2_policy_v2.GEOMETRY_SELF_SHA256,
            }
            and bindings["lineage"]
            == {
                "dataset_contract_sha256": (
                    "d630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c"
                ),
                "dataset_identity": "oanda-ba-ny17-friday-provider-observed-v2",
                "dataset_manifest_sha256": (
                    "11da094fc7ca6a30e946be33523757d7ab559a9ad1951c9142e8969539930014"
                ),
                "dataset_version": "phase-2b1r-v2",
                "s0_acceptance_sha256": (
                    "7c438598d6ad8f9b94aa1d264eaa57040f1d91bc1e4f758b1231dda5a9801548"
                ),
                "s1_acceptance_sha256": s2_policy_v2.S1_ARTIFACT_SHA256,
                "strategy_content_sha256": (
                    "3b9188749c10581d7518e25838a2cb65704d1329e7ebe3061cd7fe4b82115861"
                ),
                "strategy_identity": "failed-break-phase-1-admission-correction-v2",
            }
            and first["consumed"]
            and first_failure["status"] == "ACCEPTED"
            and second["consumed"]
            and second_failure["status"] == "ACCEPTED"
            and performance["authority"]["real_return_execution"] is False,
            "forward-only execution lineage changed",
        )
        require(
            authorization["result"]
            == {
                "expected_delta": {
                    "every_other_application_table": 0,
                    "research_jobrun": 1,
                },
                "idempotency_key": (
                    "failed-break-exploratory-returns-v2|phase-2b1r-v2|development-2010-2018"
                ),
                "job_identity": "failed-break-exploratory-returns-v2",
                "one_complete_canonical_json_result": True,
            }
            and authorization["expected_pristine_state"]
            == {
                "application_counts_sha256": (
                    "5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097"
                ),
                "idempotency_rows": 0,
                "job_runs": 5,
                "result_rows": 0,
            },
            "result or pristine-state authority changed",
        )
        require(authorization["environment"] == _expected_environment(), "environment changed")
        require(
            authorization["override_prohibition"]
            == [
                "ALTERNATE_ARTIFACT_PATH",
                "CLI",
                "DATABASE",
                "DATA_ONLY",
                "ENVIRONMENT",
                "FAVOURABLE_RESULT",
                "OWNER",
                "SUCCESSFUL_OUTCOME",
                "THRESHOLD_REINTERPRETATION",
            ],
            "override prohibition changed",
        )
        forbidden = {
            "drawdown",
            "equity",
            "expected_output_hash",
            "expected_pnl",
            "expected_return",
            "losses",
            "profit_factor",
            "terminal_counts",
            "wins",
        }
        require(
            not forbidden.intersection(_all_keys(authorization)),
            "authorization contains return-bearing expected output",
        )
        require(preregistration["status"] == "CORRECTED_NOT_EXECUTED", "preregistration changed")
        return {
            **authorization,
            "artifact_sha256": AUTHORIZATION_ARTIFACT_SHA256,
            "present": True,
            "status": "AUTHORIZED_NOT_EXECUTED",
        }
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise RunnerGovernanceRefusal("missing or invalid execution authorization") from error


def inspect_consumed_rollover_authorization_history() -> dict:
    """Verify the third authorization as consumed by the rollover refusal."""
    authorization = _load_canonical(
        CONSUMED_ROLLOVER_AUTHORIZATION_PATH,
        CONSUMED_ROLLOVER_AUTHORIZATION_ARTIFACT_SHA256,
        "authorization_sha256",
        CONSUMED_ROLLOVER_AUTHORIZATION_SELF_SHA256,
    )
    require(
        authorization["identity"] == "failed-break-v2-exploratory-return-single-successor-v1"
        and authorization["repository_baseline"] == "d9a1c09df96649bc82c6259e5952adf613286be3"
        and authorization["command"]["operational_ceiling_seconds"] == 900
        and authorization["result"]["idempotency_key"]
        == "failed-break-exploratory-returns-v2|phase-2b1r-v2|development-2010-2018",
        "consumed rollover authorization changed",
    )
    return {
        **authorization,
        "artifact_sha256": CONSUMED_ROLLOVER_AUTHORIZATION_ARTIFACT_SHA256,
        "consumed": True,
        "status": "CONSUMED_ROLLOVER_FAILURE_RETRY_PROHIBITED",
    }


def inspect_rollover_failure() -> dict:
    """Verify the atomic no-result failure that exposed the rollover defect."""
    failure = _load_canonical(
        ROLLOVER_FAILURE_PATH,
        ROLLOVER_FAILURE_ARTIFACT_SHA256,
        "failure_sha256",
        ROLLOVER_FAILURE_SELF_SHA256,
    )
    consumed = inspect_consumed_rollover_authorization_history()
    require(
        failure["identity"] == "failed-break-v2-exploratory-return-rollover-validation-failure-v1"
        and failure["repository_baseline"] == REPOSITORY_BASELINE
        and failure["consumed_authorization"]
        == {
            "artifact_sha256": CONSUMED_ROLLOVER_AUTHORIZATION_ARTIFACT_SHA256,
            "identity": "failed-break-v2-exploratory-return-single-successor-v1",
            "self_sha256": CONSUMED_ROLLOVER_AUTHORIZATION_SELF_SHA256,
        }
        and consumed["consumed"] is True,
        "rollover failure does not consume the preceding authorization",
    )
    require(
        failure["attempt"]
        == {
            "argv": [
                ".venv/bin/python",
                "manage.py",
                "calculate_exploratory_returns_v2",
                "--execute",
            ],
            "duration_seconds": "5.629354",
            "error": "worker failed closed: RunnerRefusal: missing or extra governed rollover",
            "exit_code": 1,
            "invocations": 1,
            "last_progress": "stage=calculation completed=0 total=82",
            "normalized_events": 82,
            "result_constructed": False,
        },
        "rollover failure attempt changed",
    )
    require(
        failure["persistent_state"]
        == {
            "application_count_sha256_after": (
                "5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097"
            ),
            "application_count_sha256_before": (
                "5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097"
            ),
            "application_table_delta": 0,
            "idempotency_rows": 0,
            "job_runs": 5,
            "result_rows": 0,
        },
        "rollover failure persistent state changed",
    )
    return {**failure, "artifact_sha256": ROLLOVER_FAILURE_ARTIFACT_SHA256, "status": "ACCEPTED"}


def inspect_rollover_rehearsal() -> dict:
    """Verify the two deterministic complete disposable calculations."""
    rehearsal = _load_canonical(
        ROLLOVER_REHEARSAL_PATH,
        ROLLOVER_REHEARSAL_ARTIFACT_SHA256,
        "evidence_sha256",
        ROLLOVER_REHEARSAL_SELF_SHA256,
    )
    require(
        rehearsal["diagnosis"]
        == {
            "all_82_events_checked": True,
            "all_provided_rollovers_match_governed_horizon": True,
            "exact_without_selection_correction": 4,
            "extra_rollover_histogram": {
                "0": 4,
                "2": 1,
                "3": 4,
                "4": 1,
                "5": 6,
                "6": 12,
                "7": 17,
                "8": 6,
                "9": 21,
                "10": 8,
                "11": 2,
            },
            "failure_class": "HORIZON_PRELOAD_COMPARED_TO_EARLY_RESOLVED_EXIT",
            "mismatch_events": 78,
            "physical_events": 82,
        },
        "rollover diagnosis changed",
    )
    proof = rehearsal["real_data_runs"]
    require(
        proof["runs"] == 2
        and proof["deterministic"] is True
        and proof["event_count"] == proof["resolved_terminal_count"] == 82
        and proof["complete_cost_cells"] == 3_690
        and proof["job_rows_each"] == 1
        and proof["partial_rows"] == 0
        and proof["readback_equal"] is True
        and max(map(float, proof["durations_seconds"])) < 15,
        "complete disposable rehearsal changed",
    )
    return rehearsal


def inspect_execution_authorization() -> dict:
    """Verify only the newest forward authorization without database access."""
    try:
        authorization = _load_canonical(
            AUTHORIZATION_PATH,
            AUTHORIZATION_ARTIFACT_SHA256,
            "authorization_sha256",
            AUTHORIZATION_SELF_SHA256,
        )
        require(
            authorization["schema"] == AUTHORIZATION_SCHEMA
            and authorization["identity"] == AUTHORIZATION_IDENTITY
            and authorization["repository_baseline"] == AUTHORIZED_BASELINE,
            "execution authorization identity changed",
        )
        require(
            authorization["authority"]
            == {
                "exploratory_return_execution": "EXACTLY_ONE_NEW_REPLACEMENT",
                "further_retry_or_replacement": False,
                "live_trading": "PERMANENTLY_PROHIBITED",
                "post_entry_real_outcome_access": "ONLY_INSIDE_SINGLE_EXECUTION",
                "post_result_policy_tuning": False,
                "promotion": "PERMANENTLY_PROHIBITED",
                "provider_production_or_deployment": False,
                "result_replacement": False,
                "retry_or_resume": False,
            },
            "execution authority changed",
        )
        require(
            authorization["command"]
            == {
                "alternate_arguments": False,
                "argv": [
                    ".venv/bin/python",
                    "manage.py",
                    "calculate_exploratory_returns_v2",
                    "--execute",
                ],
                "atomic_transaction": True,
                "memory_ceiling_bytes": 1_073_741_824,
                "operational_ceiling_seconds": 900,
                "requires_fresh_verified_backup": True,
            },
            "execution command changed",
        )
        first = inspect_predecessor_authorization_history()
        first_failure = inspect_failed_execution()
        second = inspect_consumed_successor_authorization_history()
        second_failure = inspect_second_failed_execution()
        third = inspect_consumed_rollover_authorization_history()
        third_failure = inspect_rollover_failure()
        rehearsal = inspect_rollover_rehearsal()
        preregistration = load_preregistration()
        bindings = authorization["bindings"]
        require(
            bindings["consumed_authorizations"]
            == [
                PREDECESSOR_AUTHORIZATION_ARTIFACT_SHA256,
                CONSUMED_SUCCESSOR_AUTHORIZATION_ARTIFACT_SHA256,
                CONSUMED_ROLLOVER_AUTHORIZATION_ARTIFACT_SHA256,
            ]
            and bindings["failure_artifacts"]
            == [
                FAILURE_ARTIFACT_SHA256,
                SECOND_FAILURE_ARTIFACT_SHA256,
                ROLLOVER_FAILURE_ARTIFACT_SHA256,
            ]
            and first["consumed"]
            and first_failure["status"] == "ACCEPTED"
            and second["consumed"]
            and second_failure["status"] == "ACCEPTED"
            and third["consumed"]
            and third_failure["status"] == "ACCEPTED"
            and rehearsal["real_data_runs"]["deterministic"] is True,
            "forward-only failure lineage changed",
        )
        require(
            bindings["correction"]
            == {
                "artifact_sha256": ARTIFACT_SHA256,
                "failure_artifact_sha256": ROLLOVER_FAILURE_ARTIFACT_SHA256,
                "failure_self_sha256": ROLLOVER_FAILURE_SELF_SHA256,
                "rehearsal_artifact_sha256": ROLLOVER_REHEARSAL_ARTIFACT_SHA256,
                "rehearsal_self_sha256": ROLLOVER_REHEARSAL_SELF_SHA256,
                "report_sha256": REPORT_SHA256,
                "self_sha256": SELF_SHA256,
            }
            and preregistration["implementation_sha256"] == SELF_SHA256,
            "rollover correction binding changed",
        )
        require(
            bindings["calculator"]
            == {
                "artifact_sha256": CALCULATOR_ARTIFACT_SHA256,
                "self_sha256": CALCULATOR_SELF_SHA256,
                "source_sha256": calculator_governance.CALCULATOR_SHA256,
            }
            and bindings["runner_sources"]
            == {
                "adapter_sha256": ADAPTER_SHA256,
                "command_sha256": COMMAND_SHA256,
                "memory_boundary_sha256": MEMORY_BOUNDARY_SHA256,
                "runner_sha256": RUNNER_SHA256,
            },
            "corrected source binding changed",
        )
        require(
            bindings["effective_s2_policy"]
            == {
                "artifact_sha256": S2_ARTIFACT_SHA256,
                "self_sha256": S2_POLICY_SHA256,
            }
            and bindings["geometry"]
            == {
                "artifact_sha256": s2_policy_v2.GEOMETRY_ARTIFACT_SHA256,
                "event_set_sha256": s2_policy_v2.EVENT_SET_SHA256,
                "memberships_sha256": s2_policy_v2.MEMBERSHIPS_SHA256,
                "nonadditive_book_memberships": 186,
                "physical_events": 82,
                "self_sha256": s2_policy_v2.GEOMETRY_SELF_SHA256,
            },
            "policy or geometry binding changed",
        )
        require(
            bindings["lineage"]
            == {
                "dataset_contract_sha256": (
                    "d630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c"
                ),
                "dataset_identity": "oanda-ba-ny17-friday-provider-observed-v2",
                "dataset_manifest_sha256": (
                    "11da094fc7ca6a30e946be33523757d7ab559a9ad1951c9142e8969539930014"
                ),
                "dataset_version": "phase-2b1r-v2",
                "s0_acceptance_sha256": (
                    "7c438598d6ad8f9b94aa1d264eaa57040f1d91bc1e4f758b1231dda5a9801548"
                ),
                "s1_acceptance_sha256": s2_policy_v2.S1_ARTIFACT_SHA256,
                "strategy_content_sha256": (
                    "3b9188749c10581d7518e25838a2cb65704d1329e7ebe3061cd7fe4b82115861"
                ),
                "strategy_identity": "failed-break-phase-1-admission-correction-v2",
            },
            "dataset or strategy lineage changed",
        )
        require(
            authorization["result"]
            == {
                "expected_delta": {
                    "every_other_application_table": 0,
                    "research_jobrun": 1,
                },
                "idempotency_key": (
                    "failed-break-exploratory-returns-v2|phase-2b1r-v2|development-2010-2018"
                ),
                "job_identity": "failed-break-exploratory-returns-v2",
                "one_complete_canonical_json_result": True,
            }
            and authorization["expected_pristine_state"]
            == {
                "application_counts_sha256": (
                    "5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097"
                ),
                "idempotency_rows": 0,
                "job_runs": 5,
                "result_rows": 0,
            },
            "result or pristine-state authority changed",
        )
        require(authorization["environment"] == _expected_environment(), "environment changed")
        require(
            authorization["override_prohibition"]
            == [
                "ALTERNATE_ARTIFACT_PATH",
                "CLI",
                "DATABASE",
                "DATA_ONLY",
                "ENVIRONMENT",
                "FAVOURABLE_RESULT",
                "OWNER",
                "SUCCESSFUL_OUTCOME",
                "THRESHOLD_REINTERPRETATION",
            ],
            "override prohibition changed",
        )
        forbidden = {
            "drawdown",
            "equity",
            "expected_output_hash",
            "expected_pnl",
            "expected_return",
            "losses",
            "profit_factor",
            "terminal_counts",
            "wins",
        }
        require(
            not forbidden.intersection(_all_keys(authorization)),
            "authorization contains return-bearing expected output",
        )
        return {
            **authorization,
            "artifact_sha256": AUTHORIZATION_ARTIFACT_SHA256,
            "present": True,
            "status": "AUTHORIZED_NOT_EXECUTED",
        }
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise RunnerGovernanceRefusal("missing or invalid execution authorization") from error


def inspect_correction_evidence() -> dict:
    """Verify the current rollover correction and its real-data rehearsal."""

    require(
        _source_hash(REPORT_PATH) == REPORT_SHA256,
        "correction report drift",
    )
    evidence = inspect_rollover_rehearsal()
    return {
        "correction_report_sha256": REPORT_SHA256,
        "rehearsal_sha256": ROLLOVER_REHEARSAL_ARTIFACT_SHA256,
        "rehearsal_self_sha256": ROLLOVER_REHEARSAL_SELF_SHA256,
        "deterministic_complete_result": evidence["real_data_runs"]["deterministic"],
    }


def require_execution_authorization() -> dict:
    """Fail before any outcome adapter or Django model can be imported."""
    authorization = inspect_execution_authorization()
    validate_execution_environment()
    return {
        "artifact_sha256": authorization["artifact_sha256"],
        "authority": {
            "exploratory_return_execution": True,
            "retry": False,
            "resume": False,
            "promotion": False,
            "live_trading": False,
        },
        "calculator_artifact_sha256": authorization["bindings"]["calculator"]["artifact_sha256"],
        "geometry_event_set_sha256": authorization["bindings"]["geometry"]["event_set_sha256"],
        "job_identity": authorization["result"]["job_identity"],
        "physical_event_count": authorization["bindings"]["geometry"]["physical_events"],
        "policy_sha256": authorization["bindings"]["effective_s2_policy"]["self_sha256"],
    }


def require_predecessor_execution_authorization(*_args, **_kwargs):
    inspect_predecessor_authorization_history()
    inspect_failed_execution()
    raise RunnerGovernanceRefusal(
        "predecessor authorization was consumed by the accepted pre-outcome failure"
    )


def require_consumed_successor_execution_authorization(*_args, **_kwargs):
    inspect_consumed_successor_authorization_history()
    inspect_second_failed_execution()
    raise RunnerGovernanceRefusal(
        "successor authorization was consumed by the accepted timeout failure"
    )


def require_consumed_rollover_execution_authorization(*_args, **_kwargs):
    inspect_consumed_rollover_authorization_history()
    inspect_rollover_failure()
    raise RunnerGovernanceRefusal(
        "rollover-era authorization was consumed by the accepted atomic refusal"
    )


def require_promotion(*_args, **_kwargs):
    load_preregistration()
    raise RunnerGovernanceRefusal("promotion and live trading are permanently prohibited")
