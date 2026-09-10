"""Closed wire contracts. Structural validation only, never strategy formulas."""

import re
from datetime import datetime
from decimal import Decimal

from market.strategy.contracts import arithmetic

FIELDS = {
    "unavailable": {"strategy": "text", "reason": "text"},
    "risk": {"strategy": "text", "multiplier": "decimal?", "reason": "text", "evidence": "texts"},
    "continuous": {
        "strategy": "text",
        "value": "decimal?",
        "buffered": "decimal?",
        "reason": "text?",
        "components": "components",
    },
    "setup": {
        "strategy": "text",
        "direction": "direction",
        "available_at": "time",
        "signal_start": "time",
        "granularity": "granularity",
        "reference": "decimal",
        "stop": "decimal",
        "target": "decimal",
        "entry_at": "time",
        "expires_at": "time",
        "exit_at": "time",
        "evidence": "texts",
    },
    "intent": {
        "candidate_sha256": "hash",
        "simulator_sha256": "hash",
        "cost_sha256": "hash",
        "calendar_sha256": "hash",
    },
    "execution": {
        "intent_sha256": "hash",
        "entered_at": "time",
        "exited_at": "time",
        "entry": "decimal",
        "exit": "decimal",
        "gross_quote": "decimal",
        "costs_quote": "decimal",
        "net_quote": "decimal",
        "net_account": "decimal",
        "outcome_evidence": "hashes",
        "reason": "text",
    },
}
COMPONENT = {"name": "text", "raw": "decimal?", "capped": "decimal?", "exclusion": "text?"}


def _value(value, kind):
    if kind.endswith("?"):
        return value is None or _value(value, kind[:-1])
    if kind in ("texts", "hashes", "components"):
        if not isinstance(value, list) or len(value) > 1801:
            return False
        if kind == "components":
            return all(
                _object(c, COMPONENT)
                and (c["raw"] is None) == (c["capped"] is None)
                and (c["raw"] is not None or c["exclusion"] is not None)
                and (c["capped"] is None or abs(Decimal(c["capped"])) <= 20)
                for c in value
            )
        return all(_value(v, "text" if kind == "texts" else "hash") for v in value)
    if kind == "direction":
        return type(value) is int and value in (-1, 1)
    if not isinstance(value, str):
        return False
    if kind == "text":
        return bool(value.strip())
    if kind == "hash":
        return re.fullmatch(r"[0-9a-f]{64}", value) is not None
    if kind == "decimal":
        return re.fullmatch(r"-?(0|[1-9][0-9]{0,26})\.[0-9]{6}", value) is not None
    if kind == "granularity":
        return value in ("M15", "H1")
    if kind == "time":
        if (
            re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00:00", value
            )
            is None
        ):
            return False
        try:
            datetime.fromisoformat(value)
            return True
        except ValueError:
            return False
    return False


def _object(value, fields):
    return (
        isinstance(value, dict)
        and set(value) == set(fields)
        and all(_value(value[k], kind) for k, kind in fields.items())
    )


@arithmetic
def validate_part(part, kind, *, strategy=None):
    if kind not in FIELDS or not _object(part, FIELDS[kind] | {"schema": "text"}):
        raise ValueError("phase5_output_shape")
    if part["schema"] != f"phase5/{kind}-v1" or (
        strategy is not None and part.get("strategy") != strategy
    ):
        raise ValueError("phase5_output_attribution")
    if kind == "continuous":
        if (
            (part["value"] is None) != (part["buffered"] is None)
            or (part["value"] is None) != (part["reason"] is not None)
            or any(
                part[k] is not None and abs(Decimal(part[k])) > 20 for k in ("value", "buffered")
            )
        ):
            raise ValueError("phase5_continuous_missingness")
    if (
        kind == "risk"
        and part["multiplier"] is not None
        and not 0 <= Decimal(part["multiplier"]) <= 1
    ):
        raise ValueError("phase5_risk_bounds")
    if kind == "setup":
        if not (
            part["signal_start"]
            < part["available_at"]
            <= part["entry_at"]
            <= part["expires_at"]
            < part["exit_at"]
        ):
            raise ValueError("phase5_setup_chronology")
        reference, stop, target = (Decimal(part[k]) for k in ("reference", "stop", "target"))
        if (
            min(reference, stop, target) <= 0
            or part["direction"] * (reference - stop) <= 0
            or part["direction"] * (target - reference) <= 0
        ):
            raise ValueError("phase5_setup_geometry")
    if kind == "execution" and (
        part["entered_at"] >= part["exited_at"]
        or not part["outcome_evidence"]
        or min(Decimal(part["entry"]), Decimal(part["exit"])) <= 0
    ):
        raise ValueError("phase5_execution_contract")


def validate_evaluation(output, strategy):
    if (
        not isinstance(output, dict)
        or set(output) != {"schema", "strategy", "outputs", "activation"}
        or output["schema"] != "phase5/evaluation-v1"
        or output["strategy"] != strategy
        or output["activation"] != "forbidden"
        or not isinstance(output["outputs"], list)
    ):
        raise ValueError("phase5_evaluation_shape")
    parts = output["outputs"]
    if len(parts) > 3 or any(
        not isinstance(p, dict) or not isinstance(p.get("schema"), str) for p in parts
    ):
        raise ValueError("phase5_output_shape")
    kinds = [p.get("schema", "").removeprefix("phase5/").removesuffix("-v1") for p in parts]
    if strategy in ("ewmac-d-v1", "breakout-d-v1"):
        valid = kinds == ["continuous"]
    elif strategy == "fast-mr-h1-v1":
        valid = (
            len(kinds) in (2, 3)
            and kinds[0] in ("setup", "unavailable")
            and kinds[1] == "risk"
            and (len(kinds) == 2 or kinds[2] == "continuous")
        )
    elif strategy == "macro-risk-v1":
        valid = kinds == ["risk", "unavailable"]
    elif strategy == "carry-readiness-v1":
        valid = kinds == ["unavailable"]
    elif strategy in ("fixed-risk-v1", "ewma-risk-v1", "garch-t-risk-v1"):
        valid = kinds == ["risk"]
    else:
        from market.strategy.definitions import STRATEGIES

        valid = strategy in STRATEGIES and len(kinds) == 1 and kinds[0] in ("setup", "unavailable")
    if not valid:
        raise ValueError("phase5_strategy_output_kind")
    for part, kind in zip(parts, kinds):
        validate_part(part, kind, strategy=strategy)
