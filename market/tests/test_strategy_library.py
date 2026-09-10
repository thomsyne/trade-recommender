"""Independent asymmetric pure-contract and formula fixtures."""

import json
from decimal import Decimal as D

from django.test import SimpleTestCase

from market.strategy.contracts import ContinuousForecast, RiskOverlay, decimal, encoded
from market.strategy.definitions import STRATEGIES, definition, definition_digest
from market.strategy.evaluate import cost_from_payload
from market.strategy.trend import ewmac
from market.tests.test_strategy_library_trend import NOW, bars, cost


class ContractTests(SimpleTestCase):
    def test_missingness_and_risk_bounds(self):
        with self.assertRaises(ValueError):
            ContinuousForecast("x", None, None, ())
        for value in (D("1.000001"), D("-0.1"), D("NaN")):
            with self.assertRaises(ValueError):
                RiskOverlay("x", value, "fixture")
        result = RiskOverlay("x", None, "unknown")
        self.assertIn('"multiplier":null', encoded(result))
        with self.assertRaises(TypeError):
            RiskOverlay("x", D(1), "fixture", direction=1)

    def test_definitions_are_fresh_and_distinct(self):
        self.assertEqual(len({definition_digest(s) for s in STRATEGIES}), len(STRATEGIES))
        body = definition(STRATEGIES[0])
        body["population"]["holdout"][0] = "yesterday"
        self.assertNotEqual(body, definition(STRATEGIES[0]))
        with self.assertRaises(ValueError):
            definition("orb-m1-v1")
        for value in (True, 0.2, "NaN", "Infinity"):
            with self.assertRaises(ValueError):
                decimal(value)

    def test_exact_cost_evidence_cannot_round_across_affordability_boundary(self):
        original = cost("ewmac-2-8", "0.1000004")
        body = json.loads(encoded(original, exact=True))
        self.assertEqual(body["spread"], "0.1000004")
        restored = cost_from_payload(body)
        self.assertEqual(restored, original)
        for evidence in (original, restored):
            result = ewmac(bars(97), costs={evidence.component: evidence}, cutoff=NOW)
            self.assertEqual(result.components[0].exclusion, "unaffordable")
        # Demonstrate the competing lossy interpretation would change the decision.
        rounded = cost_from_payload(json.loads(encoded(original)))
        self.assertIsNone(
            ewmac(bars(97), costs={rounded.component: rounded}, cutoff=NOW).components[0].exclusion
        )
        for value, expected in (("0.1234565", "0.123456"), ("0.1234575", "0.123458")):
            self.assertEqual(
                json.loads(encoded(RiskOverlay("x", D(value), "fixture")))["multiplier"], expected
            )
