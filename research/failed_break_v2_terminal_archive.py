"""Fixed-path, offline verification of the failed-break v2 terminal archive.

This module has no database, provider, outcome-calculation, or write path.  It
verifies the committed terminal declaration and exposes only refusal helpers.
Historical evidence remains governed by the artifacts that created it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = ROOT / "docs/strategy/failed-break/v2/failed-break-v2-terminal-freeze.json"
BINDER_PATH = ROOT / "docs/strategy/failed-break/v2/failed-break-v2-final-research-binder.md"
SOURCE_ARTIFACTS = {
    "detector": (
        ROOT / "docs/strategy/failed-break/v2/detector-admission-correction-v2.json",
        "3b9188749c10581d7518e25838a2cb65704d1329e7ebe3061cd7fe4b82115861",
    ),
    "s0": (
        ROOT / "docs/strategy/failed-break/v2/s0-outcome-acceptance-v2.json",
        "7c438598d6ad8f9b94aa1d264eaa57040f1d91bc1e4f758b1231dda5a9801548",
    ),
    "s1": (
        ROOT / "docs/strategy/failed-break/v2/s1-outcome-acceptance-v2.json",
        "5760dd2dd60a2d6a6087b5116b085a8a3774db1512962af0622bc0e3eeed93d5",
    ),
    "geometry": (
        ROOT / "docs/strategy/failed-break/v2/s1-geometry-v2.json",
        "b3bc76fa4ac226793a24f11a9a65f9b549e7231ace11e399f6d81c1599e41fdc",
    ),
    "s2": (
        ROOT / "docs/strategy/failed-break/v2/s2-exploratory-policy-freeze-v2.json",
        "1d4b1f451a60d7c2ac37a2fe91849d463254b7751529324e52198003de1ae8dc",
    ),
    "return_authorization": (
        ROOT / "docs/strategy/failed-break/v2/exploratory-return-rollover-authorization-v2.json",
        "d77c1b5d69061a7bc80a99aacf82e92ed65287fc4a3029bc61f3853590ddb31a",
    ),
    "return_calculator": (
        ROOT / "docs/strategy/failed-break/v2/exploratory-return-rollover-correction-v2.json",
        "61896776164b05822dd6ccc45a0d3b61cd1995938742390732eeea066cf05d8b",
    ),
}

SCHEMA = "failed-break-v2-terminal-freeze-v1"
IDENTITY = "failed-break-v2-terminal-negative-exploratory-archive-v1"
STATUS = "COMPLETED_NEGATIVE_EXPLORATORY_RESULT"
ARTIFACT_SHA256 = "39c513a071ff624fc3d931e540603a030f643264bc2ac5a501d41e4708cfeca8"
TERMINAL_SHA256 = "2ce9107113bdc632e9c4f1e84fd625e1db7324ecbf954649564ec12f6e60d485"
BINDER_SHA256 = "64745a9e32fd5302e2d44ead4e53075a251460b87922359fcbb59e449071d9f1"

EXPECTED_AUTHORIZATION = {
    "additional_execution": False,
    "backtesting": False,
    "deployment": False,
    "live_trading": False,
    "promotion": False,
    "provider_access": False,
    "replacement": False,
    "retry": False,
    "return_recalculation": False,
    "strategy_tuning": False,
}
EXPECTED_OVERRIDES = {
    "capital_scaling": "PROHIBITED",
    "cli": "PROHIBITED",
    "database": "PROHIBITED",
    "direction_removal": "PROHIBITED",
    "environment": "PROHIBITED",
    "favourable_result": "PROHIBITED",
    "owner": "PROHIBITED",
    "pair_removal": "PROHIBITED",
    "threshold_reinterpretation": "PROHIBITED",
}
EXPECTED_FUTURE_REQUIREMENTS = [
    "NEW_STRATEGY_IDENTITY",
    "NEW_PREREGISTRATION",
    "GENUINELY_UNTOUCHED_VALIDATION_EVIDENCE",
]
EXPECTED_RESULT = {
    "application_count_sha256": (
        "11a017314eb55d75ecc096e53519310c87932af57de3ff73520cc47392ab1316"
    ),
    "configuration_sha256": ("3f90135bba1ef0cce20906e5f3799a4cf921a62c772c16466d40a21b832d1e93"),
    "event_results_sha256": ("da25f8cc33f02f17a235fd1b8b62c569bb090a6bd999e208672eb6e5cb2efe4e"),
    "evidence_sha256": ("ebbbca6c5d9f63d5138bbcb0c3b44be7057d052aa116baee577e3adc1acae288"),
    "idempotency_key_rows": 1,
    "report_sha256": ("a27d92e9408382258210d7f1b1d0e8f4eacb10b75d6ff43975c25611998485d9"),
    "result_file_sha256": ("205f60f4f8bc73eb8984e5ac38f5c089a8035ae288fb2ff11000455e6b9fc718"),
    "result_rows": 1,
    "terminal_classifications": 82,
}


class TerminalArchiveRefusal(ValueError):
    """The archive identity or its permanent boundary did not reconstruct."""


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise TerminalArchiveRefusal(message)


def load_terminal_freeze() -> dict:
    for name, (path, expected) in SOURCE_ARTIFACTS.items():
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, f"{name} source drift")
    raw = ARTIFACT_PATH.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ARTIFACT_SHA256, "artifact digest mismatch")
    try:
        document = json.loads(raw)
        require(canonical_bytes(document) + b"\n" == raw, "artifact bytes are not canonical")
        body = dict(document)
        claimed = body.pop("terminal_sha256")
        require(claimed == TERMINAL_SHA256 == digest(body), "terminal self-hash mismatch")
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise TerminalArchiveRefusal("invalid terminal-freeze artifact") from error

    require(document["schema"] == SCHEMA, "schema substitution")
    require(document["identity"] == IDENTITY, "archive identity substitution")
    require(document["status"] == STATUS, "terminal status substitution")
    require(document["authorization"] == EXPECTED_AUTHORIZATION, "authority changed")
    require(document["override_prohibition"] == EXPECTED_OVERRIDES, "override boundary changed")
    require(
        document["future_research_requirements"] == EXPECTED_FUTURE_REQUIREMENTS,
        "future research boundary changed",
    )
    require(document["final_result"] == EXPECTED_RESULT, "accepted final result changed")
    require(
        document["closed_cohort"]
        == {
            "development_period": "2010-01-01/2018-12-31",
            "exploratory_result_job_identity": "failed-break-exploratory-returns-v2",
            "exploratory_result_job_operational_id": 6,
            "physical_events": 82,
            "strategy_identity": "failed-break-phase-1-admission-correction-v2",
            "strategy_operational_id": 2,
        },
        "strategy or cohort changed",
    )
    require(
        document["historical_preservation"]
        == {
            "artifacts_immutable": True,
            "authorizations_immutable": True,
            "code_history_immutable": True,
            "database_evidence_immutable": True,
            "deletion_prohibited": True,
        },
        "historical preservation changed",
    )
    source = document["source_bindings"]
    require(
        source["strategy"]["identity"] == document["closed_cohort"]["strategy_identity"],
        "strategy binding changed",
    )
    require(source["geometry"]["physical_events"] == 82, "physical-event set changed")
    require(source["geometry"]["book_memberships"] == 186, "membership set changed")
    require(
        source["return_execution"]
        == {
            "authorization_artifact_sha256": SOURCE_ARTIFACTS["return_authorization"][1],
            "calculator_artifact_sha256": SOURCE_ARTIFACTS["return_calculator"][1],
            "calculator_self_sha256": (
                "6e51fbcfd672f1a758ae0146b95f5479305391d4304291fb63e02986f4c0015c"
            ),
            "calculator_source_sha256": (
                "9daa42e9bf7b4ac059c3ccb618aac3c96db0cba203985b7d2ad2d36be50f3a4c"
            ),
            "command": "calculate_exploratory_returns_v2 --execute",
            "exactly_once": "CONSUMED_SUCCESSFULLY",
        },
        "return execution binding changed",
    )
    require(source["s2_policy"]["exploratory_only"] is True, "exploratory boundary changed")
    require(
        source["s2_policy"]["promotion_permanently_prohibited"] is True,
        "promotion boundary changed",
    )
    return document


def verify_binder() -> str:
    actual = hashlib.sha256(BINDER_PATH.read_bytes()).hexdigest()
    require(actual == BINDER_SHA256, "binder digest mismatch")
    return actual


def readiness() -> dict:
    terminal = load_terminal_freeze()
    return {
        "status": terminal["status"],
        "additional_execution": "PERMANENTLY_REFUSED",
        "retry_or_replacement": "PERMANENTLY_REFUSED",
        "strategy_tuning": "PERMANENTLY_REFUSED",
        "promotion_or_live_trading": "PERMANENTLY_REFUSED",
        "future_research": EXPECTED_FUTURE_REQUIREMENTS,
    }


def require_prohibited_action(action: str, **overrides):
    load_terminal_freeze()
    prohibited = {
        "additional_execution",
        "retry",
        "replacement",
        "return_recalculation",
        "strategy_tuning",
        "promotion",
        "live_trading",
    }
    require(action in prohibited, "unknown terminal action")
    del overrides
    raise TerminalArchiveRefusal(
        f"{action} is permanently prohibited for the closed failed-break v2 identity"
    )
