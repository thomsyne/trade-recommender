"""Pure deterministic Phase 6A projection from authenticated frozen envelopes."""

from datetime import datetime
from decimal import Decimal

from market.state.canonical import format_decimal, identity_digest

from .contracts import METHOD_DIGEST, REASONS, ROLES


def _state(state, **values):
    return {"state": state, **values}


def _reason(parts):
    failed = {reason for reason, passed, _ in parts if not passed}
    return next((reason for reason in REASONS if reason in failed), None)


def _trigger_sides(setups, unavailable):
    result = {}
    for direction, side in ((1, "bull"), (-1, "bear")):
        supporting = [s["identity"] for s in setups if s["setup"]["direction"] == direction]
        opposing = [s["identity"] for s in setups if s["setup"]["direction"] == -direction]
        result[side] = {
            "supporting": supporting,
            "opposing": opposing,
            "pending": sorted(x["identity"] for x in unavailable if "pending" in x["reason"]),
            "rejected": sorted(
                x["identity"]
                for x in unavailable
                if any(term in x["reason"] for term in ("reject", "invalid", "expired"))
            ),
        }
    return result


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
):
    """Return closed assessment output and optional candidate payload.

    Inputs are plain canonical payloads already authenticated by the persistence
    boundary. No database, mutable policy, model text, or caller eligibility flag
    is consulted here.
    """
    if method_digest != METHOD_DIGEST:
        raise ValueError("input_integrity_failure")
    cutoff = datetime.fromisoformat(snapshot["information_cutoff"])
    entries = eligibility["entries"]
    gates = []

    def gate(reason, passed, detail=""):
        gates.append((reason, passed, detail))

    gate("no_economically_admitted_strategy", bool(entries), "canonical eligibility is empty")
    admitted = {(e["strategy"], e["definition_sha256"], e["role"]): e for e in entries}
    attributed, unavailable = [], []
    for item in evaluations:
        key = (item["strategy"], item["definition_sha256"], ROLES[item["strategy"]])
        is_admitted = key in admitted
        gate("strategy_not_admitted_for_instrument", is_admitted, item["strategy"])
        role_ok = ROLES[item["strategy"]] == "setup"
        gate("strategy_role_cannot_originate_intent", role_ok, item["strategy"])
        if not (is_admitted and role_ok):
            continue
        outputs = item["output"]["outputs"]
        setup = next((part for part in outputs if part["schema"] == "phase5/setup-v1"), None)
        if setup is None:
            reason = next(
                (part["reason"] for part in outputs if part["schema"] == "phase5/unavailable-v1"),
                "technical_setup_absent",
            )
            unavailable.append({"identity": item["identity"], "reason": reason})
        else:
            attributed.append({**item, "setup": setup, "eligibility": admitted[key]})

    granularities = snapshot.get("granularities", {})
    missing = [
        timeframe
        for timeframe in ("W", "D", "H4", "H1", "M15")
        if granularities.get(timeframe, {}).get("state") != "available"
    ]
    monthly = snapshot.get("monthly_context", {})
    if monthly.get("state") != "available":
        missing.insert(0, "monthly-context-v1")
    gate("required_timeframe_unavailable", not missing, ",".join(missing))

    missing_evaluations = sorted(
        {entry["strategy"] for entry in entries}
        - {evaluation["strategy"] for evaluation in evaluations}
    )
    if entries and (not attributed or missing_evaluations):
        reason_text = " ".join(x["reason"] for x in unavailable)
        gate("trigger_pending", "pending" not in reason_text, reason_text)
        gate("trigger_rejected", "reject" not in reason_text, reason_text)
        gate("trigger_invalidated", "invalid" not in reason_text, reason_text)
        gate("trigger_expired", "expired" not in reason_text, reason_text)
        gate(
            "technical_setup_absent",
            False,
            reason_text or "missing evaluations: " + ",".join(missing_evaluations),
        )
    else:
        for reason in (
            "technical_setup_absent",
            "trigger_pending",
            "trigger_rejected",
            "trigger_invalidated",
            "trigger_expired",
        ):
            gate(reason, True)

    m15_setups = [item for item in attributed if item["setup"]["granularity"] == "M15"]
    gate(
        "m15_confirmation_unavailable",
        not attributed or len(m15_setups) == len(attributed),
        "v1 has no H1-to-M15 entry adapter",
    )
    gate(
        "unsupported_intent_shape",
        not attributed or len(m15_setups) == len(attributed),
        "only exact Phase 5 M15 setup geometry is supported",
    )

    required_ids = sorted(
        {
            required
            for item in attributed
            for required in item["eligibility"]["required_evidence_ids"]
        }
    )
    evidence_ready = not required_ids or (
        evidence is not None
        and evidence.get("readiness") == "ready"
        and evidence.get("required_ids") == required_ids
    )
    gate("required_evidence_not_ready", evidence_ready, ",".join(required_ids))

    event = snapshot.get("event_state", {})
    event_known = event.get("state") == "available" and event.get("coverage") == "attested_complete"
    active_events = sorted(event.get("active_window_vintages", []))
    gate("event_state_unknown", event_known, event.get("reason_code", event.get("coverage", "")))
    gate("event_window_blocked", not active_events, ",".join(active_events))

    usable_cost = cost is not None
    complete_cost = usable_cost and all(
        cost["components"].get(name) is not None
        for name in ("spread", "commission", "slippage_latency", "financing")
    )
    gate("cost_evidence_missing", complete_cost, "all exact components required")
    stale = usable_cost and datetime.fromisoformat(cost["stale_after"]) < cutoff
    gate("cost_evidence_stale", not stale, cost["stale_after"] if usable_cost else "")
    spread_known = usable_cost and cost["components"].get("spread") is not None
    gate("spread_unknown", spread_known, "exact spread required")

    gross_r = net_r = None
    spread_exceeded = False
    if m15_setups and complete_cost:
        setup = m15_setups[0]["setup"]
        reference, stop, target = (Decimal(setup[k]) for k in ("reference", "stop", "target"))
        stop_distance = abs(reference - stop)
        gross_r_value = abs(target - reference) / stop_distance
        components = [Decimal(cost["components"][name]) for name in sorted(cost["components"])]
        net_r_value = gross_r_value - sum(components) / stop_distance
        spread_exceeded = Decimal(cost["components"]["spread"]) / stop_distance > Decimal(
            "0.100000"
        )
        gross_r, net_r = format_decimal(gross_r_value), format_decimal(net_r_value)
    gate("spread_exceeds_strategy_limit", not spread_exceeded)
    gate("net_reward_nonpositive", net_r is not None and Decimal(net_r) > 0, net_r or "unknown")

    gate("capacity_assessment_missing", capacity is not None)
    aggregate_open = capacity is not None and capacity["aggregate"] == "available"
    gate("aggregate_capacity_exceeded", aggregate_open, capacity["aggregate"] if capacity else "")
    directions = {item["setup"]["direction"] for item in m15_setups}
    expected_directions = (
        ("long", "short")
        if directions == {1}
        else ("short", "long")
        if directions == {-1}
        else None
    )
    currency_open = capacity is not None and all(
        leg["disposition"] == "available" for leg in capacity["currency_legs"]
    )
    if expected_directions:
        currency_open = (
            currency_open
            and tuple(leg["direction"] for leg in capacity["currency_legs"]) == expected_directions
        )
    gate("currency_direction_capacity_exceeded", currency_open)
    gate("conflicting_eligible_setups", len(directions) <= 1, "both directions present")
    gate("unchanged_duplicate_intent", not duplicate)

    primary = _reason(gates)
    setup = m15_setups[0]["setup"] if len(m15_setups) == 1 else None
    htf = {
        timeframe: granularities.get(timeframe, {"state": "unavailable"}).get(
            "trend", granularities.get(timeframe, {"state": "unavailable"})
        )
        for timeframe in ("W", "D", "H4")
    }
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

    output = {
        "schema": "phase6a/assessment-v1",
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
            gates=[
                {"reason": reason, "state": "available" if passed else "closed", "detail": detail}
                for reason, passed, detail in gates
            ],
        ),
    }

    candidate = None
    if primary is None and setup is not None:
        source = m15_setups[0]
        semantic = {
            "strategy": source["strategy"],
            "definition_sha256": source["definition_sha256"],
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
        }
        candidate = {
            "schema": "phase6a/eligible-trade-intent-candidate-v1",
            "authority": "research_candidate_only_no_execution_or_trade_permission",
            "evaluation_identity": source["identity"],
            **semantic,
            "semantic_identity": identity_digest(semantic),
        }
    return output, candidate
