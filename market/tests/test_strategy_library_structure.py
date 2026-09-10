import hashlib
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from market.strategy.setups import mean_reversion_risk
from market.strategy.structure import failed_break, pullback, range_reversion
from market.tests.test_strategy_library_simulation import START, bar


class StructureTests(SimpleTestCase):
    def test_unavailable_is_not_sideways_or_safe(self):
        empty = SimpleNamespace(series=lambda *a, **kw: (), payload={})
        for result in (
            pullback(empty, "M15"),
            range_reversion(empty),
            failed_break(empty),
            failed_break(empty, continuation=True),
        ):
            self.assertEqual(result.schema, "phase5/unavailable-v1")
        self.assertNotEqual(
            failed_break(empty).strategy, failed_break(empty, continuation=True).strategy
        )
        self.assertEqual(mean_reversion_risk(D(3), D(2)).multiplier, 1)
        self.assertEqual(mean_reversion_risk(D("3.000001"), D(2)).multiplier, D("0.5"))
        self.assertIsNone(mean_reversion_risk(None, D(2)).multiplier)

    def test_qualified_zone_and_continuation_both_required(self):
        bars = tuple(
            bar(START + timedelta(minutes=15 * i), open="100", high="101", low="99", close="100")
            for i in range(15)
        )
        bars = bars[:-2] + (
            bars[-2]._replace(close=D("101.5"), high=D(102)),
            bars[-1]._replace(close=D(103), high=D(104)),
        )
        zone = {
            "zone_id": "z",
            "range_low": "99",
            "range_high": "100",
            "available_at": START.isoformat(),
            "invalidated": False,
            "expired": False,
            "distinct_tests": 2,
            "age_intervals": 30,
        }
        trend = {
            "higher_timeframe": {
                "trend": {"state": "available", "version": "trend-v1", "classification": "uptrend"}
            }
        }
        payload = {
            "granularities": {
                "D": trend,
                "H4": trend
                | {
                    "structure": {
                        "support_resistance_zones": {
                            "state": "available",
                            "version": "zone-v1",
                            "zones": [zone],
                        }
                    }
                },
            }
        }
        inputs = SimpleNamespace(
            series=lambda g: bars if g == "M15" else (bar(START - timedelta(hours=1)),),
            payload=payload,
        )
        self.assertEqual(pullback(inputs, "M15").direction, 1)
        zone["invalidated"] = True
        self.assertEqual(pullback(inputs, "M15").reason, "no_qualified_pullback")

    def test_prior_negative_evidence_remains_a_terminal_binder(self):
        root = Path(__file__).resolve().parents[2]
        path = root / "docs/strategy/failed-break/v2/failed-break-v2-final-research-binder.md"
        expected = path.with_suffix(".md.sha256").read_text().split()[0]
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
