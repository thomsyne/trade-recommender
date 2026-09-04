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
ARTIFACT_PATH = DOCS / "exploratory-return-runner-preregistration-v2.json"
REPORT_PATH = DOCS / "exploratory-return-runner-architecture.md"
PREDECESSOR_AUTHORIZATION_PATH = DOCS / "exploratory-return-execution-authorization-v2.json"
FAILURE_PATH = DOCS / "exploratory-return-execution-failure-v2.json"
AUTHORIZATION_PATH = DOCS / "exploratory-return-replacement-authorization-v2.json"
CORRECTION_REPORT_PATH = DOCS / "exploratory-return-rlimit-correction-v2.md"
REHEARSAL_PATH = DOCS / "exploratory-return-rlimit-rehearsal-v2.json"

REPOSITORY_BASELINE = "efd125f1a5c6fe9778cfdc966c36b1a33f918c07"
SCHEMA = "failed-break-v2-exploratory-return-runner-preregistration-v1"
IDENTITY = "failed-break-v2-exploratory-return-runner-v1"
ARTIFACT_SHA256 = "3e465e56af7eb0bc5eef175618dc8c38d0e8fafcc7a867d6b31e70946de3a93a"
SELF_SHA256 = "b8877148c25b8982867e3df77314142b4b0d18924d820ea7777275292de4fca7"
REPORT_SHA256 = "cb4fa82a1a4d8e7a2f358e56589d12492b866a33a54a4fb9636b0a90bf25cb37"
RUNNER_SHA256 = "11f8d31684f7306b2ba4aed2715eb404e982c1e63875f0dc8cb2fc6d487eeeb2"
MEMORY_BOUNDARY_SHA256 = "7e39e860419e677a811ad7fe755747c81d1ba4d8be329a1cbdfdf09f2bb8a182"
ADAPTER_SHA256 = "6ec419cd8d6d250aeef54fa98a867aeaa89f91b5092ff3614b6d8888e6f142d0"
COMMAND_SHA256 = "4d41b1021837c59f71fde4ce6edd20c30c9064334f35548801233e9b05913d52"
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
AUTHORIZATION_ARTIFACT_SHA256 = "e84b1b4b4a8b6b6c25ff4eefca21ab649b4a460a0b3db04b09c0433888407868"
AUTHORIZATION_SELF_SHA256 = "d6b3e312f80a8395418726e95e384463c29feb11352e0306e46f9398c5f833a5"
AUTHORIZATION_SCHEMA = "failed-break-v2-exploratory-return-replacement-authorization-v1"
AUTHORIZATION_IDENTITY = "failed-break-v2-exploratory-return-single-replacement-v1"
AUTHORIZED_BASELINE = "9a391a711669984eb9c705aae5076d233d362478"
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


def load_preregistration() -> dict:
    try:
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
            "runner identity changed",
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
                "artifact_present": False,
                "future_command": "python manage.py calculate_exploratory_returns_v2 --execute",
                "retry": "PROHIBITED",
                "resume": "PROHIBITED",
                "status": "SEPARATELY_UNAUTHORIZED",
            },
            "execution boundary changed",
        )
        bindings = artifact["bindings"]
        require(
            bindings["calculator"]
            == {
                "artifact_sha256": CALCULATOR_ARTIFACT_SHA256,
                "self_sha256": CALCULATOR_SELF_SHA256,
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
        source_files = bindings["source_files"]
        expected_sources = {
            "research/exploratory_return_adapter_v2.py": ADAPTER_SHA256,
            "research/exploratory_return_memory_v2.py": MEMORY_BOUNDARY_SHA256,
            "research/exploratory_return_runner_v2.py": RUNNER_SHA256,
            "research/management/commands/calculate_exploratory_returns_v2.py": COMMAND_SHA256,
        }
        require(source_files == expected_sources, "governed source map changed")
        for relative, expected in expected_sources.items():
            require(_source_hash(ROOT / relative) == expected, f"source drift: {relative}")
        require(_source_hash(REPORT_PATH) == REPORT_SHA256, "architecture report drift")
        calculator_governance.load_preregistration()
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
        raise RunnerGovernanceRefusal("incomplete runner preregistration") from error


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
            and failure["repository_baseline"] == AUTHORIZED_BASELINE,
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


def inspect_execution_authorization() -> dict:
    """Verify only the successor replacement authorization without touching a database."""
    try:
        raw = AUTHORIZATION_PATH.read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == AUTHORIZATION_ARTIFACT_SHA256,
            "execution authorization artifact digest mismatch",
        )
        authorization = json.loads(raw)
        require(canonical_bytes(authorization) + b"\n" == raw, "authorization bytes not canonical")
        body = dict(authorization)
        claimed = body.pop("authorization_sha256", None)
        require(
            claimed == AUTHORIZATION_SELF_SHA256 == digest(body),
            "execution authorization self-hash mismatch",
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
                "code_only_runner_implementation": "ACCEPTED",
                "further_replacement_without_new_authorization": False,
                "post_entry_real_outcome_access": "ONLY_INSIDE_SINGLE_EXECUTION",
                "predecessor_authorization": "CONSUMED_PRE_OUTCOME_FAILURE",
                "replacement_exploratory_return_execution": "EXACTLY_ONCE",
                "retry_or_resume": False,
                "result_replacement": False,
                "post_result_policy_tuning": False,
                "promotion": "PERMANENTLY_PROHIBITED",
                "live_trading": "PERMANENTLY_PROHIBITED",
                "provider_production_or_deployment": False,
            },
            "execution authority changed",
        )
        require(
            authorization["command"]
            == {
                "argv": [
                    ".venv/bin/python",
                    "manage.py",
                    "calculate_exploratory_returns_v2",
                    "--execute",
                ],
                "alternate_arguments": False,
                "atomic_transaction": True,
                "memory_boundary": {
                    "ceiling_bytes": 1_073_741_824,
                    "mechanism": "ISOLATED_CHILD_PARENT_RSS_WATCHDOG_V1",
                    "poll_interval_milliseconds": 50,
                    "rlimit_as_used_on_darwin": False,
                    "worker_termination_closes_connection_and_rolls_back": True,
                },
                "operational_ceiling_seconds": 900,
            },
            "execution command changed",
        )
        bindings = authorization["bindings"]
        failure = inspect_failed_execution()
        preregistration = load_preregistration()
        calculator = calculator_governance.load_preregistration()
        s2_policy_v2.load_policy()
        geometry = s2_policy_v2.geometry_v2.verify_committed()
        s1 = s2_policy_v2.geometry_v2.load_s1_acceptance()
        from research.failed_break_v2_s0_governance import load_v2_s0_outcome_acceptance

        s0 = load_v2_s0_outcome_acceptance()
        require(
            bindings["failure"]
            == {
                "artifact_sha256": FAILURE_ARTIFACT_SHA256,
                "identity": FAILURE_IDENTITY,
                "self_sha256": FAILURE_SELF_SHA256,
            }
            and failure["status"] == "ACCEPTED"
            and bindings["predecessor_authorization"]
            == {
                "artifact_sha256": PREDECESSOR_AUTHORIZATION_ARTIFACT_SHA256,
                "identity": PREDECESSOR_AUTHORIZATION_IDENTITY,
                "self_sha256": PREDECESSOR_AUTHORIZATION_SELF_SHA256,
                "status": "CONSUMED_PRE_OUTCOME_FAILURE_RETRY_PROHIBITED",
            }
            and bindings["runner_preregistration"]
            == {
                "artifact_sha256": ARTIFACT_SHA256,
                "self_sha256": SELF_SHA256,
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
            },
            "runner, calculator, or S2 binding changed",
        )
        require(
            bindings["geometry"]
            == {
                "artifact_sha256": s2_policy_v2.GEOMETRY_ARTIFACT_SHA256,
                "self_sha256": s2_policy_v2.GEOMETRY_SELF_SHA256,
                "event_set_sha256": s2_policy_v2.EVENT_SET_SHA256,
                "memberships_sha256": s2_policy_v2.MEMBERSHIPS_SHA256,
                "physical_events": 82,
                "nonadditive_book_memberships": 186,
            }
            and len(geometry["events"]) == 82
            and sum(len(row["books"]) for row in geometry["events"]) == 186,
            "geometry authorization changed",
        )
        require(
            bindings["s1_acceptance"]
            == {
                "artifact_sha256": s2_policy_v2.S1_ARTIFACT_SHA256,
                "self_sha256": s2_policy_v2.S1_SELF_SHA256,
                "aggregate_evidence_sha256": s2_policy_v2.S1_AGGREGATE_SHA256,
                "projection_sha256": s1["stored_evidence"]["hashes"]["projection_sha256"],
                "configuration_sha256": s1["stored_evidence"]["hashes"]["configuration_sha256"],
                "report_sha256": s1["stored_evidence"]["hashes"]["report_sha256"],
            }
            and bindings["s0_acceptance"]
            == {
                "artifact_sha256": "7c438598d6ad8f9b94aa1d264eaa57040f1d91bc1e4f758b1231dda5a9801548",
                "self_sha256": s0["acceptance_sha256"],
                "configuration_sha256": s0["s0"]["configuration_sha256"],
                "report_sha256": s0["s0"]["report_sha256"],
            },
            "S0 or S1 acceptance binding changed",
        )
        require(bindings["lineage"] == _expected_lineage(s1), "authorized lineage changed")
        require(
            authorization["result"]
            == {
                "job_identity": "failed-break-exploratory-returns-v2",
                "idempotency_key": (
                    "failed-break-exploratory-returns-v2|phase-2b1r-v2|development-2010-2018"
                ),
                "expected_delta": {
                    "research_jobrun": 1,
                    "every_other_application_table": 0,
                },
                "one_complete_canonical_json_result": True,
            },
            "result persistence authority changed",
        )
        require(
            authorization["expected_pristine_state"] == _expected_pristine_state(s1),
            "authorized pristine state changed",
        )
        require(
            authorization["environment"] == _expected_environment(),
            "execution environment boundary changed",
        )
        require(
            authorization["backup_and_verification"] == _expected_backup_and_verification(),
            "backup or independent verification boundary changed",
        )
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
        require(
            authorization["supersession"]
            == {
                "failure_artifact_required": True,
                "original_authorization_available_for_reuse": False,
                "replacement_invocations_authorized": 1,
                "same_command_dataset_strategy_cohort_policy_and_financial_semantics": True,
            },
            "authorization supersession boundary changed",
        )
        forbidden_output_keys = {
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
            not forbidden_output_keys.intersection(_all_keys(authorization)),
            "authorization contains return-bearing expected output",
        )
        require(
            preregistration["status"] == "IMPLEMENTED_NOT_AUTHORIZED",
            "preregistration history changed",
        )
        require(
            calculator["authority"]["promotion"] is False, "calculator promotion boundary changed"
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
    require(
        _source_hash(CORRECTION_REPORT_PATH) == CORRECTION_REPORT_SHA256,
        "correction report drift",
    )
    rehearsal = _load_canonical(
        REHEARSAL_PATH,
        REHEARSAL_SHA256,
        "rehearsal_sha256",
        REHEARSAL_SELF_SHA256,
    )
    require(
        rehearsal["authority"]["successor_authorization_sha256"] == AUTHORIZATION_ARTIFACT_SHA256
        and rehearsal["authority"]["verified_failure_sha256"] == FAILURE_ARTIFACT_SHA256
        and rehearsal["rows_written_by_table"]
        == {"every_other_application_table": 0, "research_jobrun": 1}
        and rehearsal["memory_breach"]["rows_after"] == 0
        and rehearsal["timeout"]["rows_after"] == 0,
        "successor rehearsal evidence changed",
    )
    return {
        "correction_report_sha256": CORRECTION_REPORT_SHA256,
        "rehearsal_sha256": REHEARSAL_SHA256,
        "rehearsal_self_sha256": REHEARSAL_SELF_SHA256,
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


def require_promotion(*_args, **_kwargs):
    load_preregistration()
    raise RunnerGovernanceRefusal("promotion and live trading are permanently prohibited")
