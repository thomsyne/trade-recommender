"""Independent asymmetric pure-contract and formula fixtures."""

from decimal import Decimal as D

from django.test import SimpleTestCase

from market.strategy.contracts import ContinuousForecast, RiskOverlay, decimal, encoded
from market.strategy.definitions import STRATEGIES, definition, definition_digest


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
