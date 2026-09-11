"""Pure deterministic Phase 6A projection from authenticated frozen envelopes."""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from market.state.canonical import format_decimal, identity_digest

from .contracts import METHOD_DIGEST, REASONS, ROLES

_PENDING_REASONS = frozenset({"same_direction_fvg_unavailable"})
_REJECTED_REASONS = frozenset(
    {
        "ambiguous_dual_breach",
        "not_a_unique_range_edge",
        "no_unique_confirmed_failed_break",
    }
)
_INVALIDATED_REASONS = frozenset(
    {
        "confirmation_too_late_for_next_interval",
        "fvg_interval_mismatch",
        "invalid_geometry",
        "opening_range_geometry",
        "snapshot_cutoff_after_entry",
        "target_not_ahead",
        "zero_range",
    }
)
_EXPIRED_REASONS = frozenset({"no_confirmation_before_expiry"})
_M15_UNAVAILABLE_REASONS = frozenset({"opening_interval_missing"})


def _state(state, **values):
    return {"state": state, **values}


def _new_gates():
    return {reason: {"reason": reason, "state": "available", "detail": ""} for reason in REASONS}


def _close(gates, reason, detail=""):
    gate = gates[reason]
    gate["state"] = "closed"
    if detail:
        details = set(filter(None, gate["detail"].split(";")))
        details.add(detail)
        gate["detail"] = ";".join(sorted(details))


def _primary(gates):
    return next((reason for reason in REASONS if gates[reason]["state"] == "closed"), None)


def _unavailable_reason(reason):
    if reason in _M15_UNAVAILABLE_REASONS:
        return "m15_confirmation_unavailable"
    if reason in _PENDING_REASONS:
        return "trigger_pending"
    if reason in _REJECTED_REASONS:
        return "trigger_rejected"
    if reason in _INVALIDATED_REASONS:
        return "trigger_invalidated"
    if reason in _EXPIRED_REASONS:
        return "trigger_expired"
    return "technical_setup_absent"


def _trigger_sides(setups, unavailable):
    pending = sorted(
        (
            {"identity": item["identity"], "reason": item["reason"]}
            for item in unavailable
            if item["gate"] == "trigger_pending"
        ),
        key=lambda item: (item["identity"], item["reason"]),
    )
    rejected = sorted(
        (
            {"identity": item["identity"], "reason": item["reason"]}
            for item in unavailable
            if item["gate"] in {"trigger_rejected", "trigger_invalidated", "trigger_expired"}
        ),
        key=lambda item: (item["identity"], item["reason"]),
    )
    result = {}
    for direction, side in ((1, "bull"), (-1, "bear")):
        result[side] = {
            "supporting": sorted(
                item["identity"] for item in setups if item["setup"]["direction"] == direction
            ),
            "opposing": sorted(
                item["identity"] for item in setups if item["setup"]["direction"] == -direction
            ),
            "pending": pending,
            "rejected": rejected,
        }
    return result


def _market_fields(snapshot):
    granularities = snapshot.get("granularities", {})
    monthly = snapshot.get("monthly_context", {})
    missing = [
        timeframe
        for timeframe in ("W", "D", "H4", "H1", "M15")
        if granularities.get(timeframe, {}).get("state") != "available"
    ]
    if monthly.get("state") != "available":
        missing.insert(0, "monthly-context-v1")
    htf = {
        timeframe: granularities.get(timeframe, {"state": "unavailable"}).get(
            "trend", granularities.get(timeframe, {"state": "unavailable"})
        )
        for timeframe in ("W", "D", "H4")
    }
    event = snapshot.get("event_state", {})
    htf.update(
        monthly=monthly,
        macro=snapshot.get("macro_regime", {"state": "unavailable"}),
        event=event,
        sentiment={"state": "unavailable", "reason": "no_frozen_sentiment_contract"},
    )
    zones = []
    for timeframe in ("W", "D", "H4", "H1"):
        block = granularities.get(timeframe, {})
        for zone in block.get("structure", {}).get("support_resistance_zones", {}).get("zones", []):
            zones.append({"timeframe": timeframe, **zone})
    return granularities, monthly, event, missing, htf, zones


def build_assessment(
    *,
    method_digest,
    snapshot,
    eligibility,
    evaluations,
    cost=None,
    capacity=None,
    evidence=None,
    duplicate=False,
    predecessor_terminal_state="open",
):
    """Return one closed-schema assessment and optional research-only candidate."""
    if method_digest != METHOD_DIGEST:
        raise ValueError("input_integrity_failure")
    cutoff = datetime.fromisoformat(snapshot["information_cutoff"])
    entries = eligibility["entries"]
    gates = _new_gates()
    if not entries:
        _close(gates, "no_economically_admitted_strategy", "canonical eligibility is empty")

    admitted = {
        (entry["strategy"], entry["definition_sha256"], entry["role"]): entry for entry in entries
    }
    attributed, unavailable = [], []
    for item in evaluations:
        key = (item["strategy"], item["definition_sha256"], ROLES[item["strategy"]])
        if key not in admitted:
            _close(gates, "strategy_not_admitted_for_instrument", item["strategy"])
            continue
        if ROLES[item["strategy"]] != "setup":
            _close(gates, "strategy_role_cannot_originate_intent", item["strategy"])
            continue
        outputs = item["output"]["outputs"]
        setup = next((part for part in outputs if part["schema"] == "phase5/setup-v1"), None)
        if setup is None:
            reason = next(
                (part["reason"] for part in outputs if part["schema"] == "phase5/unavailable-v1"),
                "technical_setup_absent",
            )
            gate = _unavailable_reason(reason)
            _close(gates, gate, f"{item['strategy']}:{reason}")
            unavailable.append({"identity": item["identity"], "reason": reason, "gate": gate})
        else:
            attributed.append({**item, "setup": setup, "eligibility": admitted[key]})

    missing_evaluations = sorted(
        {entry["strategy"] for entry in entries}
        - {evaluation["strategy"] for evaluation in evaluations}
    )
    if missing_evaluations:
        _close(
            gates, "technical_setup_absent", "missing evaluations:" + ",".join(missing_evaluations)
        )

    granularities, monthly, event, missing, htf, zones = _market_fields(snapshot)
    if missing:
        _close(gates, "required_timeframe_unavailable", ",".join(missing))

    m15_setups = [item for item in attributed if item["setup"].get("granularity") == "M15"]
    if len(m15_setups) != len(attributed):
        _close(gates, "m15_confirmation_unavailable", "v2 has no H1-to-M15 entry adapter")
        _close(
            gates, "unsupported_intent_shape", "only exact Phase 5 M15 setup geometry is supported"
        )
    if len(m15_setups) > 1:
        _close(gates, "conflicting_eligible_setups", "exactly one originatable setup required")

    setup = m15_setups[0]["setup"] if len(m15_setups) == 1 else None
    if setup:
        try:
            confirmation = datetime.fromisoformat(setup["available_at"])
            entry_at = datetime.fromisoformat(setup["entry_at"])
        except (KeyError, ValueError):
            _close(gates, "unsupported_intent_shape", "invalid completed-candle timestamps")
        else:
            if entry_at != confirmation + timedelta(minutes=15):
                _close(gates, "unsupported_intent_shape", "entry must be exact next M15")

    required_ids = sorted(
        {
            required
            for item in attributed
            for required in item["eligibility"]["required_evidence_ids"]
        }
    )
    if required_ids:
        _close(gates, "required_evidence_not_ready", "method v2 defines no Phase 7 requirements")
    elif evidence is not None:
        _close(gates, "input_integrity_failure", "unrequired evidence packet")

    event_known = event.get("state") == "available" and event.get("coverage") == "attested_complete"
    if not event_known:
        _close(gates, "event_state_unknown", event.get("reason_code", event.get("coverage", "")))
    active_events = sorted(event.get("active_window_vintages", []))
    if active_events:
        _close(gates, "event_window_blocked", ",".join(active_events))

    complete_cost = cost is not None and all(
        cost["components"].get(name) is not None
        for name in ("spread", "commission", "slippage_latency", "financing")
    )
    if not complete_cost:
        _close(gates, "cost_evidence_missing", "all exact components required")
    if cost is None or cost["components"].get("spread") is None:
        _close(gates, "spread_unknown", "exact spread required")
    if cost is not None and datetime.fromisoformat(cost["stale_after"]) < cutoff:
        _close(gates, "cost_evidence_stale", cost["stale_after"])

    gross_r = net_r = None
    if setup and complete_cost:
        try:
            reference, stop, target = (
                Decimal(setup[key]) for key in ("reference", "stop", "target")
            )
            stop_distance = abs(reference - stop)
            if stop_distance <= 0:
                raise InvalidOperation
            gross_value = abs(target - reference) / stop_distance
            component_values = [
                Decimal(cost["components"][name]) for name in sorted(cost["components"])
            ]
            net_value = gross_value - sum(component_values) / stop_distance
            spread_ratio = Decimal(cost["components"]["spread"]) / stop_distance
        except (InvalidOperation, KeyError, ZeroDivisionError):
            _close(gates, "unsupported_intent_shape", "invalid exact geometry")
        else:
            gross_r, net_r = format_decimal(gross_value), format_decimal(net_value)
            if spread_ratio > Decimal("0.100000"):
                _close(gates, "spread_exceeds_strategy_limit")
            if net_value <= 0:
                _close(gates, "net_reward_nonpositive", net_r)
    elif len(m15_setups) <= 1:
        _close(gates, "net_reward_nonpositive", "unknown")

    if capacity is None:
        _close(gates, "capacity_assessment_missing")
        _close(gates, "aggregate_capacity_exceeded", "unknown")
        _close(gates, "currency_direction_capacity_exceeded", "unknown")
    else:
        if capacity["aggregate"] != "available":
            _close(gates, "aggregate_capacity_exceeded", capacity["aggregate"])
        expected = None
        if setup:
            expected = ("long", "short") if setup["direction"] == 1 else ("short", "long")
        directions = tuple(leg["direction"] for leg in capacity["currency_legs"])
        if any(leg["disposition"] != "available" for leg in capacity["currency_legs"]) or (
            expected is not None and directions != expected
        ):
            _close(gates, "currency_direction_capacity_exceeded")
    if duplicate:
        _close(gates, "unchanged_duplicate_intent")

    primary = _primary(gates)
    output = {
        "schema": "phase6a/assessment-v2",
        "status": "available" if primary is None else "closed",
        "information_cutoff": snapshot["information_cutoff"],
        "htf_regime": _state("available" if not missing else "unavailable", values=htf),
        "major_zones": _state("available" if not missing else "unavailable", values=zones),
        "eligible_strategies": _state("available", values=entries),
        "directional_triggers": _state("available", values=_trigger_sides(attributed, unavailable)),
        "mechanical_trigger": _state(
            "available" if setup else "unavailable",
            trigger=(setup or {}).get("evidence", []),
            confirmation=(setup or {}).get("available_at"),
            earliest_next_m15_entry=(setup or {}).get("entry_at"),
            broker_executable=False,
            m1_inferred=False,
        ),
        "reward_and_cost": _state(
            "available" if gross_r is not None else "unavailable",
            gross_r=gross_r,
            components=(cost or {}).get("components"),
            cost_identity=(cost or {}).get("identity"),
            net_r=net_r,
        ),
        "capacity": _state(
            "available" if capacity is not None else "unavailable",
            identity=(capacity or {}).get("identity"),
            policy_identity=(capacity or {}).get("policy_identity"),
            source_identity=(capacity or {}).get("source_identity"),
            aggregate=(capacity or {}).get("aggregate"),
            currency_legs=(capacity or {}).get("currency_legs"),
        ),
        "terminal_state": _state(
            "available" if setup else "unavailable",
            invalidation=(setup or {}).get("stop"),
            expires_at=(setup or {}).get("expires_at"),
            supersession="append_only_candidate_link",
        ),
        "decision": _state(
            "available" if primary is None else "closed",
            primary_reason=primary,
            gates=[gates[reason] for reason in REASONS],
        ),
    }

    candidate = None
    if primary is None and setup is not None:
        source = m15_setups[0]
        semantic = {
            "strategy": source["strategy"],
            "definition_sha256": source["definition_sha256"],
            "evaluation_identity": source["identity"],
            "evaluation_evidence_sha256": source["evidence_sha256"],
            "evaluation_output_sha256": source["output_sha256"],
            "direction": setup["direction"],
            "trigger": setup["evidence"],
            "confirmation": setup["available_at"],
            "entry": setup["entry_at"],
            "reference": setup["reference"],
            "stop": setup["stop"],
            "target": setup["target"],
            "invalidation": setup["stop"],
            "expiry": setup["expires_at"],
            "eligibility": eligibility["identity"],
            "cost": cost["identity"],
            "capacity": capacity["identity"],
            "required_evidence": evidence["identity"] if evidence else None,
            "predecessor_terminal_state": predecessor_terminal_state,
        }
        candidate = {
            "schema": "phase6a/eligible-trade-intent-candidate-v2",
            "authority": "research_candidate_only_no_execution_or_trade_permission",
            **semantic,
            "semantic_identity": identity_digest(semantic),
        }
    return output, candidate
