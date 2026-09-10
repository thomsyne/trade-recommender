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

    def test_h1_sweep_and_acceptance_require_later_m15_bos(self):
        bars = tuple(
            bar(START + timedelta(minutes=15 * i), open="100", high="101", low="99", close="100")
            for i in range(15)
        )
        hourly = (
            bar(START - timedelta(hours=1), low="97")._replace(
                end=START, observed_at=START, granularity="H1"
            ),
        )
        event = {
            "status": "confirmed",
            "confirmation_available_at": START.isoformat(),
            "breach_at": START.isoformat(),
            "confirmation_at": START.isoformat(),
            "level": "99",
            "level_id": "established-h1-level",
        }
        liquidity = {
            "state": "available",
            "version": "sweep-v2",
            "sweep_below": event,
            "acceptance_above": event,
        }
        bos = {"state": "available", "version": "bos-v1", "broken": True, "direction": "up"}
        inputs = SimpleNamespace(
            series=lambda g: bars if g == "M15" else hourly,
            payload={
                "granularities": {
                    "H1": {"liquidity": liquidity},
                    "M15": {"higher_timeframe": {"break_of_structure": bos}},
                }
            },
        )
        reversal = failed_break(inputs)
        continuation = failed_break(inputs, continuation=True)
        self.assertEqual(reversal.stop, D("96.5"))
        self.assertEqual(continuation.stop, D("98.5"))
        self.assertNotEqual(reversal.strategy, continuation.strategy)
        event["status"] = "invalidated"
        self.assertEqual(failed_break(inputs).reason, "no_unique_confirmed_failed_break")
        hourly = ()
        self.assertEqual(
            failed_break(inputs).reason, "h1_level_not_available_before_m15_confirmation"
        )
