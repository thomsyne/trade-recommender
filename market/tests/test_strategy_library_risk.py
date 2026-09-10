from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from market.strategy.risk import (
    carry_readiness,
    garch_overlay,
    macro_overlay,
    risk_ratio,
    surprise_readiness,
)
from market.tests.test_strategy_library_simulation import START


class RiskTests(SimpleTestCase):
    def test_policy_rates_are_not_carry_and_empty_is_not_safe(self):
        inputs = SimpleNamespace(
            payload={
                "macro_regime": {"policy_rate": "5"},
                "event_state": {"version": "event-state-v2", "events": []},
            },
            cutoff=START,
        )
        self.assertEqual(carry_readiness(inputs).schema, "phase5/unavailable-v1")
        self.assertEqual(
            surprise_readiness(inputs).reason, "pit_consensus_release_pair_unavailable"
        )
        self.assertIsNone(macro_overlay(inputs).multiplier)

    def test_named_vintage_endpoint_and_late_knowledge(self):
        window = {
            "state": "available",
            "available_at": START.isoformat(),
            "starts_at": START.isoformat(),
            "ends_at": (START + timedelta(hours=1)).isoformat(),
        }
        event = {"event_type": "CPI", "vintage_id": "v1", "intraday_risk_window": window}
        inputs = SimpleNamespace(
            payload={"event_state": {"version": "event-state-v2", "events": [event]}}, cutoff=START
        )
        self.assertEqual(macro_overlay(inputs).multiplier, 0)
        inputs.cutoff = START + timedelta(hours=1)
        self.assertEqual(macro_overlay(inputs).multiplier, 0)
        inputs.cutoff += timedelta(microseconds=1)
        self.assertIsNone(macro_overlay(inputs).multiplier)
        inputs.cutoff = START
        window["available_at"] = (START + timedelta(microseconds=1)).isoformat()
        self.assertIsNone(macro_overlay(inputs).multiplier)

    def test_risk_cannot_exceed_baseline_or_hide_solver_failure(self):
        self.assertEqual(risk_ratio("x", D(2), D(4)).multiplier, D("0.5"))
        self.assertEqual(risk_ratio("x", D(4), D(2)).multiplier, D(1))
        self.assertIsNone(risk_ratio("x", D(4), D("NaN")).multiplier)
        self.assertEqual(garch_overlay((D(1),) * 249, D(1)).reason, "garch_warmup_or_nonfinite")
        with patch("market.strategy.risk.version", return_value="wrong"):
            self.assertEqual(
                garch_overlay((D(1),) * 250, D(1)).reason, "solver_version_unavailable"
            )
