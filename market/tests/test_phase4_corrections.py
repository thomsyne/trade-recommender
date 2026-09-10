"""Adversarial regressions reproduced against 064f98a before corrections."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from market.state import compute, features, liquidity, orb, structure, terminology
from market.state.canonical import identity_digest
from market.state.definitions import DefinitionError


def bar(hour, close=11):
    start = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(hours=hour)
    price = Decimal(str(close))
    return features.Bar(start, price, price, price, price, start + timedelta(hours=1))


class CorrectionBoundaryTests(SimpleTestCase):
    def test_unknown_definition_identity_is_rejected(self):
        definition = SimpleNamespace(
            key="unknown",
            version="nonsense",
            definition=compute.DESCRIPTOR_DEFINITION,
            definition_sha256=identity_digest(compute.DESCRIPTOR_DEFINITION),
        )
        with self.assertRaises(DefinitionError):
            compute._require_governing_definition(definition)

    def test_bad_definition_digest_is_rejected(self):
        definition = SimpleNamespace(
            key=compute.DESCRIPTOR_KEY,
            version=compute.DESCRIPTOR_VERSION,
            definition=compute.DESCRIPTOR_DEFINITION,
            definition_sha256="0" * 64,
        )
        with self.assertRaises(DefinitionError):
            compute._require_governing_definition(definition)

    def test_arbitrary_classification_is_not_registered_terminology(self):
        self.assertIn(
            "noncanonical_terminology",
            terminology.terminology_violations(
                {"version": "trend-v1", "classification": "arbitrary institutional claim"}
            ),
        )

    def test_atr_cannot_span_missing_internal_interval(self):
        bars = [bar(i) for i in range(16) if i != 7]
        self.assertEqual(features.atr_feature(bars)["state"], "unavailable")

    def test_acceptance_cannot_span_missing_reclaim_interval(self):
        bars = [bar(i) for i in (0, 1, 3, 4)]
        self.assertIsNone(
            liquidity.detect_acceptance(bars, Decimal(1), Decimal(10), "above", level_id="test")
        )

    def test_failure_across_opposite_boundary_is_terminal_in_both_directions(self):
        for closes in ((11, 8, 11), (8, 11, 8)):
            with self.subTest(closes=closes):
                state = orb._breakout_state(
                    Decimal(10), Decimal(9), [bar(i, c) for i, c in enumerate(closes)]
                )
                self.assertTrue(state["failed"])
                self.assertFalse(state["retest"])

    def test_failed_breakout_cannot_later_retest_without_a_new_breakout(self):
        bars = [bar(0, 11), bar(1, 9.5), bar(2, 11)._replace(low=Decimal(10))]
        state = orb._breakout_state(Decimal(10), Decimal(9), bars)
        self.assertTrue(state["failed"])
        self.assertFalse(state["retest"])

    def test_consolidation_opposite_boundary_failure(self):
        bars = [bar(i, 10 if i % 2 else 9) for i in range(20)]
        bars += [bar(20, 11), bar(21, 8), bar(22, 11), bar(23, 11)]
        state = structure.consolidation_state(bars, Decimal(1))
        self.assertTrue(state["failed"])
        self.assertFalse(state["retest"])

    def test_newly_confirmed_zone_has_no_tests_or_invalidation(self):
        bars = [bar(i, c) for i, c in enumerate((10, 5, 6, 7, 10, 7, 6))]
        zones = structure.support_resistance_zones(bars, Decimal(1), "EUR_USD", "H1")["zones"]
        high = next(z for z in zones if z["range_high"] == "10.000000")
        self.assertEqual(high["distinct_tests"], 0)
        self.assertFalse(high["invalidated"])


class RegisteredCalendarCorrectionTests(SimpleTestCase):
    def test_weekend_successors_and_real_gaps(self):
        from market.quality import NEW_YORK
        from market.services import live_candle_completion

        for granularity, first, successor in (
            (
                "H1",
                datetime(2026, 3, 6, 16, tzinfo=NEW_YORK),
                datetime(2026, 3, 8, 17, tzinfo=NEW_YORK),
            ),
            (
                "D",
                datetime(2026, 3, 5, 17, tzinfo=NEW_YORK),
                datetime(2026, 3, 8, 17, tzinfo=NEW_YORK),
            ),
        ):
            with self.subTest(granularity=granularity):
                a = bar(0)._replace(
                    timestamp=first.astimezone(UTC),
                    granularity=granularity,
                    end=live_candle_completion(first, granularity),
                )
                b = a._replace(
                    timestamp=successor.astimezone(UTC),
                    end=live_candle_completion(successor, granularity),
                )
                self.assertTrue(features.bars_are_consecutive(a, b))
                self.assertFalse(
                    features.bars_are_consecutive(
                        a, b._replace(timestamp=b.timestamp + timedelta(days=1))
                    )
                )

    def test_swing_availability_is_confirmation_observation_not_pivot_start(self):
        bars = [bar(i, close) for i, close in enumerate((2, 3, 7, 4, 2))]
        bars[-1] = bars[-1]._replace(observed_at=bars[-1].end + timedelta(minutes=3))
        swing = features.swing_feature(bars)["swings"][0]
        self.assertEqual(swing["timestamp"], "2026-01-05T02:00:00.000000+00:00")
        self.assertEqual(swing["formed_at"], "2026-01-05T03:00:00.000000+00:00")
        self.assertEqual(swing["available_at"], "2026-01-05T05:03:00.000000+00:00")

    def test_monthly_trend_is_feasible_in_production_lookback(self):
        from market.services import live_candle_completion

        highs = (5, 7, 12, 7, 6, 9, 15, 9, 8, 11, 18, 11, 10, 12)
        lows = (3, 4, 6, 4, 2, 4, 7, 5, 3, 5, 9, 7, 5, 6)
        rows = []
        for i, (high, low) in enumerate(zip(highs, lows)):
            for start in sorted(compute._expected_daily_opens(2024 + i // 12, i % 12 + 1)):
                end = live_candle_completion(start, "D")
                row = SimpleNamespace(
                    timestamp=start,
                    interval_end=end,
                    observed_at=end,
                    granularity="D",
                    revision=1,
                    content_sha256="a" * 64,
                )
                for side in ("bid", "ask"):
                    for field, value in (
                        ("open", low),
                        ("high", high),
                        ("low", low),
                        ("close", high),
                    ):
                        setattr(row, f"{side}_{field}", Decimal(value))
                rows.append(row)
        self.assertLessEqual(len(rows), compute.LOOKBACKS["D"])
        cutoff = datetime(2025, 3, 3, tzinfo=UTC)
        actual = compute._monthly_context(None, cutoff, rows)
        self.assertEqual(len(actual["completed_months"]), 14)
        # Independent monthly pivots: highs 12→15→18; lows 2→3 (5 not confirmed).
        self.assertEqual(actual["trend"]["classification"], "uptrend")
        self.assertEqual(actual["completed_months"][-1], "2025-02")
        missing = rows[:100] + rows[101:]
        self.assertEqual(
            compute._monthly_context(None, cutoff, missing)["trend"]["reason_code"],
            "missing_registered_interval",
        )

    def test_fvg_lifecycle_cannot_skip_first_following_interval(self):
        from market.state.fvg import find_fvgs

        bars = [bar(0, 10), bar(1, 12)._replace(open=Decimal(10)), bar(2, 12), bar(4, 9)]
        bars = [b._replace(spread=Decimal("0.1")) for b in bars]
        gap = find_fvgs(bars, Decimal(1), atr_override=Decimal(1))["fvgs"][0]
        self.assertEqual(gap["lifecycle"]["reason_code"], "missing_registered_interval")

    def test_displacement_candidate_keeps_creation_atr_after_regime_change(self):
        bars = [bar(i, 10)._replace(high=Decimal("10.5"), low=Decimal("9.5")) for i in range(20)]
        bars += [bar(20, 13)._replace(open=Decimal(10), low=Decimal(10)), bar(21, 14)]
        candidate = structure.structure_context(bars, features._current_atr(bars), "USD_CAD", "H1")[
            "displacement_candidates"
        ]["candidates"][0]
        self.assertEqual(candidate["body_atr"], "2.625000")  # 3 / ((13*1 + 3)/14)
        later = bars + [
            bar(i, 100)._replace(high=Decimal(200), low=Decimal(0)) for i in range(22, 36)
        ]
        candidates = structure.structure_context(
            later, features._current_atr(later), "USD_CAD", "H1"
        )["displacement_candidates"]["candidates"]
        self.assertIn(candidate, candidates)

    def test_orb_spread_and_availability_belong_to_breakout_not_opening(self):
        bars = [
            bar(1, 11)._replace(
                spread=Decimal("0.07"), observed_at=bar(1).end + timedelta(minutes=8)
            )
        ]
        result = orb._breakout_state(Decimal(10), Decimal(9), bars)
        self.assertEqual(result["breakout_at"], "2026-01-05T02:00:00.000000+00:00")
        self.assertEqual(result["breakout_available_at"], "2026-01-05T02:08:00.000000+00:00")
        self.assertEqual(result["breakout_spread"]["value"], "0.070000")

    def test_sweep_uses_its_historical_atr_and_confirmation_time(self):
        bars = [
            bar(0, 9)._replace(high=Decimal("10.5"), observed_at=bar(0).end + timedelta(minutes=9))
        ]
        kwargs = dict(level_id="fixture", atr_history={bars[0].timestamp: Decimal(1)})
        first = liquidity.detect_sweep(bars, Decimal(1), Decimal(10), "above", **kwargs)
        later = liquidity.detect_sweep(bars, Decimal(100), Decimal(10), "above", **kwargs)
        self.assertEqual(first, later)
        self.assertEqual(first["sweep_depth_atr"], "0.500000")
        self.assertEqual(first["available_at"], "2026-01-05T01:09:00.000000+00:00")

    def test_zone_and_equal_level_history_cannot_bridge_a_true_gap(self):
        bars = [bar(i, c) for i, c in zip((0, 1, 2, 4, 5, 6, 7), (2, 3, 7, 4, 2, 5, 1))]
        for value in (
            structure.support_resistance_zones(bars, Decimal(1), "USD_CAD", "H1"),
            structure.equal_levels(bars, Decimal(1)),
        ):
            self.assertEqual(value["reason_code"], "missing_registered_interval")

    def test_fvg_normalized_threshold_equality_and_rejection_both_directions(self):
        from market.state.fvg import find_fvgs

        bullish = [bar(0, 10), bar(1, 12)._replace(open=Decimal(10)), bar(2, 11)]
        bearish = [
            b._replace(open=30 - b.open, high=30 - b.low, low=30 - b.high, close=30 - b.close)
            for b in bullish
        ]
        for bars, direction in ((bullish, "bullish"), (bearish, "bearish")):
            bars = [b._replace(spread=Decimal(1)) for b in bars]
            result = find_fvgs(bars, Decimal(1), atr_override=Decimal(1))
            self.assertEqual(result["fvgs"][0]["direction"], direction)
            self.assertEqual(result["fvgs"][0]["spread_normalized"]["value"], "1.000000")
            wide = [b._replace(spread=Decimal("1.000001")) for b in bars]
            self.assertEqual(find_fvgs(wide, Decimal(1), atr_override=Decimal(1))["fvgs"], [])
            self.assertEqual(
                find_fvgs(bars, Decimal("1.000001"), atr_override=Decimal(1))["fvgs"], []
            )
            self.assertEqual(find_fvgs(bars, Decimal(1))["reason_code"], "atr_unavailable")

    def test_zone_expiry_is_reachable_and_margin_survives_later_volatility(self):
        bars = [bar(i, 5)._replace(high=Decimal(6), low=Decimal(4)) for i in range(20)]
        bars += [bar(20, 10), bar(21, 7), bar(22, 5)]
        zones = structure.support_resistance_zones(bars, None, "USD_CAD", "H1")["zones"]
        zone = next(z for z in zones if z["range_high"] == "10.000000")
        later = bars + [bar(i, 5)._replace(high=Decimal(8), low=Decimal(0)) for i in range(23, 225)]
        updated = next(
            z
            for z in structure.support_resistance_zones(later, None, "USD_CAD", "H1")["zones"]
            if z["zone_id"] == zone["zone_id"]
        )
        self.assertFalse(zone["expired"])
        self.assertTrue(updated["expired"])
        self.assertEqual(updated["margin_price"], zone["margin_price"])

    def test_fvg_waits_for_late_atr_evidence_without_backdating_formation(self):
        from market.state.fvg import find_fvgs

        bars = [
            bar(i, 10)._replace(high=Decimal("10.5"), low=Decimal("9.5"), spread=Decimal("0.1"))
            for i in range(15)
        ]
        bars[3] = bars[3]._replace(observed_at=datetime(2026, 1, 6, 10, tzinfo=UTC))
        bars += [
            bar(15, 12)._replace(open=Decimal(10), spread=Decimal("0.1")),
            bar(16, 12)._replace(spread=Decimal("0.1")),
        ]
        gap = find_fvgs(bars, Decimal(1))["fvgs"][0]
        self.assertEqual(gap["created_at"], "2026-01-05T17:00:00.000000+00:00")
        self.assertEqual(gap["available_at"], "2026-01-06T10:00:00.000000+00:00")
