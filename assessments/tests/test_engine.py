from copy import deepcopy
from datetime import datetime
from unittest import TestCase

from assessments.contracts import METHOD_DIGEST, ROLES
from assessments.engine import build_assessment
from market.state.canonical import identity_digest
from market.strategy.definitions import definition_digest

CUTOFF = "2026-09-11T12:30:00.000000+00:00"
HASH = "a" * 64
STRATEGY = "orb-m15-confirmed-v1:london"


def snapshot():
    granularities = {
        timeframe: {
            "state": "available",
            "trend": {"state": "available", "direction": "up"},
            "structure": {
                "support_resistance_zones": {
                    "state": "available",
                    "zones": [
                        {
                            "age_bars": 7,
                            "test_count": 2,
                            "invalidated": False,
                            "range_low": "1.090000",
                            "range_high": "1.091000",
                        }
                    ],
                }
            },
        }
        for timeframe in ("W", "D", "H4", "H1", "M15")
    }
    return {
        "information_cutoff": CUTOFF,
        "granularities": granularities,
        "monthly_context": {
            "state": "available",
            "completed_months": ["2026-08"],
            "trend": {"state": "available", "direction": "up"},
        },
        "macro_regime": {"state": "unavailable", "reason_code": "macro_vintage_unavailable"},
        "event_state": {
            "state": "available",
            "coverage": "attested_complete",
            "events": [],
            "active_window_vintages": [],
        },
    }


def eligibility(strategy=STRATEGY, role=None, required=()):
    return {
        "identity": "b" * 64,
        "entries": [
            {
                "strategy": strategy,
                "definition_sha256": definition_digest(strategy),
                "role": role or ROLES[strategy],
                "required_evidence_ids": list(required),
            }
        ],
    }


def evaluation(strategy=STRATEGY, *, direction=1, wick=False):
    setup = {
        "schema": "phase5/setup-v1",
        "strategy": strategy,
        "direction": direction,
        "available_at": "2026-09-11T12:15:00.000000+00:00",
        "signal_start": "2026-09-11T12:00:00.000000+00:00",
        "granularity": "M15",
        "reference": "1.100000",
        "stop": "1.098000" if direction == 1 else "1.102000",
        "target": "1.104000" if direction == 1 else "1.096000",
        "entry_at": "2026-09-11T12:30:00.000000+00:00",
        "expires_at": "2026-09-11T12:45:00.000000+00:00",
        "exit_at": "2026-09-11T19:00:00.000000+00:00",
        "evidence": ["wick_through"] if wick else ["strict_completed_close"],
    }
    output = {
        "schema": "phase5/evaluation-v1",
        "strategy": strategy,
        "activation": "forbidden",
        "outputs": [setup],
    }
    return {
        "id": 1,
        "identity": identity_digest([strategy, direction, wick]),
        "strategy": strategy,
        "definition_sha256": definition_digest(strategy),
        "evidence_sha256": HASH,
        "output_sha256": identity_digest(output),
        "output": output,
    }


def cost(**components):
    values = {
        "spread": "0.000100",
        "commission": "0.000020",
        "slippage_latency": "0.000030",
        "financing": "0.000000",
        **components,
    }
    return {
        "identity": "c" * 64,
        "known_at": "2026-09-11T12:14:59.123456+00:00",
        "stale_after": "2026-09-11T12:31:00.123456+00:00",
        "components": values,
    }


def capacity(
    aggregate="available", base="available", quote="available", directions=("long", "short")
):
    return {
        "identity": "d" * 64,
        "policy_identity": "hard-risk-v3@abc",
        "source_identity": "frozen-capacity:42",
        "aggregate": aggregate,
        "currency_legs": [
            {"currency": "EUR", "direction": directions[0], "disposition": base},
            {"currency": "USD", "direction": directions[1], "disposition": quote},
        ],
    }


def calculate(**overrides):
    values = {
        "method_digest": METHOD_DIGEST,
        "snapshot": snapshot(),
        "eligibility": eligibility(),
        "evaluations": [evaluation()],
        "cost": cost(),
        "capacity": capacity(),
    }
    values.update(overrides)
    return build_assessment(**values)


class EngineTests(TestCase):
    def test_wrong_method_identity_refuses(self):
        with self.assertRaisesRegex(ValueError, "input_integrity_failure"):
            calculate(method_digest="0" * 64)

    def test_empty_eligibility_sits_out_despite_perfect_setup(self):
        output, candidate = calculate(eligibility={"identity": "b" * 64, "entries": []})
        self.assertEqual(output["decision"]["primary_reason"], "no_economically_admitted_strategy")
        self.assertIsNone(candidate)
        self.assertEqual(len(output) - 3, 9)

    def test_exact_admitted_setup_emits_candidate_not_execution_authority(self):
        output, candidate = calculate()
        self.assertEqual(output["status"], "available")
        self.assertIsNone(output["decision"]["primary_reason"])
        self.assertEqual(candidate["schema"], "phase6a/eligible-trade-intent-candidate-v1")
        self.assertEqual(
            candidate["authority"], "research_candidate_only_no_execution_or_trade_permission"
        )
        self.assertFalse(set(candidate) & {"order", "fill", "recommendation", "size", "execution"})
        self.assertEqual(output["reward_and_cost"]["gross_r"], "2.000000")
        self.assertEqual(output["reward_and_cost"]["net_r"], "1.925000")

    def test_roles_do_not_manufacture_shapes(self):
        strategy = "ewmac-d-v1"
        forecast = {
            "id": 2,
            "identity": "e" * 64,
            "strategy": strategy,
            "definition_sha256": definition_digest(strategy),
            "evidence_sha256": HASH,
            "output_sha256": HASH,
            "output": {
                "schema": "phase5/evaluation-v1",
                "strategy": strategy,
                "activation": "forbidden",
                "outputs": [],
            },
        }
        output, candidate = calculate(eligibility=eligibility(strategy), evaluations=[forecast])
        self.assertEqual(
            output["decision"]["primary_reason"], "strategy_role_cannot_originate_intent"
        )
        self.assertIsNone(candidate)

    def test_monthly_and_m15_missing_are_unavailable_but_m1_is_not_a_gate(self):
        market = snapshot()
        market["monthly_context"] = {"state": "unavailable"}
        market["granularities"]["M15"] = {"state": "unavailable"}
        output, candidate = calculate(snapshot=market)
        self.assertEqual(output["decision"]["primary_reason"], "required_timeframe_unavailable")
        self.assertFalse(output["mechanical_trigger"]["m1_inferred"])
        self.assertNotIn("M1,", output["decision"]["gates"][3]["detail"] + ",")
        self.assertIsNone(candidate)

    def test_wick_and_close_are_distinct_and_entry_is_next_m15(self):
        wick_strategy = "orb-m15-wick-v1:london"
        _, close = calculate()
        _, wick = calculate(
            eligibility=eligibility(wick_strategy),
            evaluations=[evaluation(wick_strategy, wick=True)],
        )
        self.assertNotEqual(close["semantic_identity"], wick["semantic_identity"])
        self.assertEqual(wick["trigger"], ["wick_through"])
        self.assertGreater(
            datetime.fromisoformat(wick["entry"]), datetime.fromisoformat(wick["confirmation"])
        )

    def test_cost_precision_staleness_spread_and_net_fail_closed(self):
        cases = [
            (None, "spread_unknown"),
            ({**cost(), "stale_after": "2026-09-11T12:29:59.999999+00:00"}, "cost_evidence_stale"),
            (cost(spread=None), "spread_unknown"),
            (cost(spread="0.000201"), "spread_exceeds_strategy_limit"),
            (
                cost(
                    spread="0.000100",
                    commission="0.002000",
                    slippage_latency="0.002000",
                ),
                "net_reward_nonpositive",
            ),
        ]
        for costs, reason in cases:
            with self.subTest(reason=reason):
                output, candidate = calculate(cost=costs)
                self.assertEqual(output["decision"]["primary_reason"], reason)
                self.assertIsNone(candidate)

    def test_historical_capacity_and_both_currency_legs_are_frozen(self):
        for cap, reason in (
            (None, "capacity_assessment_missing"),
            (capacity(aggregate="exceeded"), "aggregate_capacity_exceeded"),
            (capacity(base="exceeded"), "currency_direction_capacity_exceeded"),
            (capacity(quote="exceeded"), "currency_direction_capacity_exceeded"),
            (capacity(directions=("short", "long")), "currency_direction_capacity_exceeded"),
        ):
            with self.subTest(reason=reason):
                output, candidate = calculate(capacity=cap)
                self.assertEqual(output["decision"]["primary_reason"], reason)
                self.assertIsNone(candidate)

    def test_required_evidence_is_strategy_bound_and_ai_text_has_no_authority(self):
        required = "f" * 64
        blocked = eligibility(required=(required,))
        output, _ = calculate(eligibility=blocked, evidence={"authority": "trade now"})
        self.assertEqual(output["decision"]["primary_reason"], "required_evidence_not_ready")
        ready = {"identity": "9" * 64, "readiness": "ready", "required_ids": [required]}
        output, candidate = calculate(eligibility=blocked, evidence=ready)
        self.assertEqual(output["status"], "available")
        self.assertEqual(candidate["required_evidence"], ready["identity"])

    def test_event_unknown_active_conflict_and_duplicate_precedence(self):
        unknown = snapshot()
        unknown["event_state"] = {"state": "unavailable", "reason_code": "unknown"}
        self.assertEqual(
            calculate(snapshot=unknown)[0]["decision"]["primary_reason"], "event_state_unknown"
        )
        active = snapshot()
        active["event_state"]["active_window_vintages"] = [HASH]
        self.assertEqual(
            calculate(snapshot=active)[0]["decision"]["primary_reason"], "event_window_blocked"
        )
        opposite = evaluation(direction=-1)
        opposite["id"] = 2
        opposite["identity"] = "8" * 64
        self.assertEqual(
            calculate(evaluations=[evaluation(), opposite])[0]["decision"]["primary_reason"],
            "conflicting_eligible_setups",
        )
        self.assertEqual(
            calculate(duplicate=True)[0]["decision"]["primary_reason"],
            "unchanged_duplicate_intent",
        )

    def test_later_inputs_do_not_mutate_old_bytes(self):
        output, candidate = calculate()
        frozen = deepcopy((output, candidate))
        later = eligibility()
        later["identity"] = "1" * 64
        later["entries"][0]["required_evidence_ids"] = ["2" * 64]
        calculate(eligibility=later)
        self.assertEqual((output, candidate), frozen)
