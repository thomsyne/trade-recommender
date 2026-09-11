"""Frozen safe replay projection for canonical-empty Phase 6A method 1.0.0 rows."""

_V11_REASONS = (
    "input_integrity_failure",
    "no_economically_admitted_strategy",
    "strategy_not_admitted_for_instrument",
    "strategy_role_cannot_originate_intent",
    "required_timeframe_unavailable",
    "m15_confirmation_unavailable",
    "required_evidence_not_ready",
    "event_state_unknown",
    "event_window_blocked",
    "technical_setup_absent",
    "trigger_pending",
    "trigger_rejected",
    "trigger_invalidated",
    "trigger_expired",
    "spread_unknown",
    "spread_exceeds_strategy_limit",
    "cost_evidence_missing",
    "cost_evidence_stale",
    "net_reward_nonpositive",
    "capacity_assessment_missing",
    "aggregate_capacity_exceeded",
    "currency_direction_capacity_exceeded",
    "conflicting_eligible_setups",
    "unsupported_intent_shape",
    "unchanged_duplicate_intent",
)


def build_v1_empty_assessment(snapshot):
    """Reproduce v1 bytes only for its canonical empty, dependency-free input."""
    granularities = snapshot.get("granularities", {})
    missing = [
        timeframe
        for timeframe in ("W", "D", "H4", "H1", "M15")
        if granularities.get(timeframe, {}).get("state") != "available"
    ]
    monthly = snapshot.get("monthly_context", {})
    if monthly.get("state") != "available":
        missing.insert(0, "monthly-context-v1")
    event = snapshot.get("event_state", {})
    event_known = event.get("state") == "available" and event.get("coverage") == "attested_complete"
    active_events = sorted(event.get("active_window_vintages", []))
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

    gates = [
        ("no_economically_admitted_strategy", False, "canonical eligibility is empty"),
        ("required_timeframe_unavailable", not missing, ",".join(missing)),
        ("technical_setup_absent", True, ""),
        ("trigger_pending", True, ""),
        ("trigger_rejected", True, ""),
        ("trigger_invalidated", True, ""),
        ("trigger_expired", True, ""),
        ("m15_confirmation_unavailable", True, "v1 has no H1-to-M15 entry adapter"),
        (
            "unsupported_intent_shape",
            True,
            "only exact Phase 5 M15 setup geometry is supported",
        ),
        ("required_evidence_not_ready", True, ""),
        (
            "event_state_unknown",
            event_known,
            event.get("reason_code", event.get("coverage", "")),
        ),
        ("event_window_blocked", not active_events, ",".join(active_events)),
        ("cost_evidence_missing", False, "all exact components required"),
        ("cost_evidence_stale", True, ""),
        ("spread_unknown", False, "exact spread required"),
        ("spread_exceeds_strategy_limit", True, ""),
        ("net_reward_nonpositive", False, "unknown"),
        ("capacity_assessment_missing", False, ""),
        ("aggregate_capacity_exceeded", False, ""),
        ("currency_direction_capacity_exceeded", False, ""),
        ("conflicting_eligible_setups", True, "both directions present"),
        ("unchanged_duplicate_intent", True, ""),
    ]
    states = [
        {"reason": reason, "state": "available" if passed else "closed", "detail": detail}
        for reason, passed, detail in gates
    ]
    empty_sides = {
        "bull": {"supporting": [], "opposing": [], "pending": [], "rejected": []},
        "bear": {"supporting": [], "opposing": [], "pending": [], "rejected": []},
    }
    return {
        "schema": "phase6a/assessment-v1",
        "status": "closed",
        "information_cutoff": snapshot["information_cutoff"],
        "htf_regime": {"state": "available" if not missing else "unavailable", "values": htf},
        "major_zones": {
            "state": "available" if not missing else "unavailable",
            "values": zones,
        },
        "eligible_strategies": {"state": "available", "values": []},
        "directional_triggers": {"state": "available", "values": empty_sides},
        "mechanical_trigger": {
            "state": "unavailable",
            "trigger": [],
            "confirmation": None,
            "earliest_next_m15_entry": None,
            "broker_executable": False,
            "m1_inferred": False,
        },
        "reward_and_cost": {
            "state": "unavailable",
            "gross_r": None,
            "components": None,
            "cost_identity": None,
            "net_r": None,
        },
        "capacity": {
            "state": "unavailable",
            "identity": None,
            "policy_identity": None,
            "source_identity": None,
            "aggregate": None,
            "currency_legs": None,
        },
        "terminal_state": {
            "state": "unavailable",
            "invalidation": None,
            "expires_at": None,
            "supersession": "append_only_candidate_link",
        },
        "decision": {
            "state": "closed",
            "primary_reason": "no_economically_admitted_strategy",
            "gates": states,
        },
    }


def build_v11_empty_assessment(snapshot):
    """Reproduce v1.1 bytes only for its canonical empty, dependency-free input."""
    output = build_v1_empty_assessment(snapshot)
    missing = []
    granularities = snapshot.get("granularities", {})
    if snapshot.get("monthly_context", {}).get("state") != "available":
        missing.append("monthly-context-v1")
    missing.extend(
        timeframe
        for timeframe in ("W", "D", "H4", "H1", "M15")
        if granularities.get(timeframe, {}).get("state") != "available"
    )
    event = snapshot.get("event_state", {})
    closed = {
        "no_economically_admitted_strategy": "canonical eligibility is empty",
        "spread_unknown": "exact spread required",
        "cost_evidence_missing": "all exact components required",
        "net_reward_nonpositive": "unknown",
        "capacity_assessment_missing": "",
        "aggregate_capacity_exceeded": "unknown",
        "currency_direction_capacity_exceeded": "unknown",
    }
    if missing:
        closed["required_timeframe_unavailable"] = ",".join(missing)
    if not (event.get("state") == "available" and event.get("coverage") == "attested_complete"):
        closed["event_state_unknown"] = event.get("reason_code", event.get("coverage", ""))
    active_events = sorted(event.get("active_window_vintages", []))
    if active_events:
        closed["event_window_blocked"] = ",".join(active_events)
    output["schema"] = "phase6a/assessment-v2"
    output["decision"]["gates"] = [
        {
            "reason": reason,
            "state": "closed" if reason in closed else "available",
            "detail": closed.get(reason, ""),
        }
        for reason in _V11_REASONS
    ]
    return output
