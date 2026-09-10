from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from django.test import SimpleTestCase

from market.state.features import Bar
from market.strategy.contracts import Component
from market.strategy.costs import CostEvidence
from market.strategy.trend import breakout, buffer, cap, combine, ema, ewmac, sigma

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def cost(name, amount="0.1"):
    return CostEvidence(
        name,
        "synthetic-test-only",
        "1",
        "a" * 64,
        "USD",
        NOW,
        NOW,
        NOW,
        D(amount),
        D(0),
        D(0),
        D(0),
        0,
    )


def bars(count):
    return tuple(
        Bar(NOW + timedelta(days=i), D(100 + i), D(103 + i), D(99 + i), D(101 + i))
        for i in range(count)
    )


class TrendTests(SimpleTestCase):
    def test_ema_seed_and_volatility_are_not_sample_std(self):
        self.assertEqual(ema((D(1), D(5), D(2)), 3), D("2.5"))
        self.assertIsNone(sigma(tuple(D(i) for i in range(96))))
        self.assertEqual(sigma(tuple(D(i) for i in range(97))), D(1))
        self.assertIsNone(sigma((D(4),) * 100))

    def test_buffer_cap_and_equal_not_risk_weighted_combination(self):
        self.assertEqual(buffer(D(4), D(3)), D(3))
        self.assertEqual(buffer(D("4.01"), D(3)), D("3.01"))
        self.assertEqual(buffer(D(-8), D(3)), D(-7))
        self.assertEqual(cap(D(30)), D(20))
        self.assertEqual(cap(D(-21)), D(-20))
        result = combine(
            "fixture",
            (
                Component("a", D(3), D(3), None),
                Component("b", D(9), D(9), None),
                Component("c", D(20), D(20), "unaffordable"),
            ),
        )
        self.assertEqual((result.value, result.buffered), (D(6), D(5)))

    def test_ewmac_warmup_and_affordability_inclusive(self):
        good = {
            f"ewmac-{f}-{s}": cost(f"ewmac-{f}-{s}")
            for f, s in ((2, 8), (4, 16), (8, 32), (16, 64), (32, 128), (64, 256))
        }
        result = ewmac(bars(400), costs=good, cutoff=NOW)
        self.assertEqual(sum(c.exclusion is None for c in result.components), 5)
        self.assertEqual(result.components[-1].exclusion, "warmup_or_zero_range")
        self.assertTrue(D("19.99") < result.components[0].capped <= 20)
        bad = ewmac(bars(400), costs={n: cost(n, "0.100001") for n in good}, cutoff=NOW)
        self.assertIsNone(bad.value)
        self.assertEqual(bad.components[0].exclusion, "unaffordable")
        self.assertIsNone(ewmac(bars(96), costs=good, cutoff=NOW).value)

    def test_breakout_completed_high_low_and_quarter_warmup(self):
        # Constant range 0..10, close=8 gives 40*(8-5)/10 = 12, not close-range 20.
        sample = tuple(Bar(NOW + timedelta(days=i), D(5), D(10), D(0), D(8)) for i in range(18))
        result = breakout(sample, costs={}, cutoff=NOW)
        self.assertEqual(result.components[0].raw, D(12))
        self.assertEqual(result.components[0].exclusion, "volatility_unavailable")
        self.assertIsNone(breakout(sample[:-1], costs={}, cutoff=NOW).components[0].raw)
        long = breakout(bars(400), costs={}, cutoff=NOW)
        self.assertIsNone(long.components[-1].raw)
        self.assertNotEqual(long.strategy, ewmac(bars(400), costs={}, cutoff=NOW).strategy)
