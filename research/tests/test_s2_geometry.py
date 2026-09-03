"""Small return-blind metadata fixtures; no live query or outcome values."""

import ast
import unittest
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from research import s2_geometry as g
from research.s2_policy import COMBINED_BOOK, PolicyRefusal, load_policy


def event(key, *, day=1, hour=14, pair="EUR_USD", direction="long", risk="0.01", end_day=15):
    base, quote = pair.split("_")
    return {
        "physical_key": key,
        "entry_at": datetime(2018, 1, day, hour, tzinfo=UTC).isoformat(),
        "horizon_at": datetime(2018, 1, end_day, hour, tzinfo=UTC).isoformat(),
        "base": base,
        "quote": quote,
        "instrument": pair,
        "direction": direction,
        "risk_per_unit_cad": risk,
        "books": [COMBINED_BOOK],
        "families": ["PREVIOUS_WEEKLY_EXTREME"],
    }


def rational_capacity_reference(events):
    """Independent exact-Fraction oracle, scanning prior allocations each time."""
    ledger = []
    by_key = {row["physical_key"]: row for row in events}
    for at in sorted({row["entry_at"] for row in events}):
        group = sorted(
            (row for row in events if row["entry_at"] == at), key=lambda row: row["physical_key"]
        )
        active = [row for row in ledger if by_key[row["key"]]["horizon_at"] >= at]
        budget = Fraction(100) - sum((row["risk"] for row in active), Fraction(0))
        fraction = min(Fraction(1), max(Fraction(0), budget) / (25 * len(group)))
        used_buckets = {bucket for row in group for bucket in g.buckets(row)}
        for bucket in used_buckets:
            used = sum(
                (row["risk"] for row in active if bucket in g.buckets(by_key[row["key"]])),
                Fraction(0),
            )
            demand = sum(bucket in g.buckets(row) for row in group) * 25
            fraction = min(fraction, max(Fraction(0), 50 - used) / demand)
        for row in group:
            unit_risk = Fraction(row["risk_per_unit_cad"])
            request_units = 25 * fraction / unit_risk
            units = request_units.numerator // request_units.denominator
            ledger.append({"key": row["physical_key"], "units": units, "risk": units * unit_risk})
    return ledger


class AllowlistTests(unittest.TestCase):
    def test_extra_or_partial_fields_fail_before_query(self):
        cursor = Mock()
        allowed = g.QUERIES["evaluations"][0]
        for fields in (allowed + ("bid_close",), allowed + ("evidence",), allowed[:-1], ("*",)):
            with self.subTest(fields=fields), self.assertRaises(PolicyRefusal):
                g.read_allowed(cursor, "evaluations", fields)
        cursor.execute.assert_not_called()

    def test_unknown_table_or_query_refused(self):
        cursor = Mock()
        with self.assertRaises(PolicyRefusal):
            g.read_allowed(cursor, "market_candle", ("timestamp",))
        cursor.execute.assert_not_called()

    def test_description_and_row_bounds_fail_closed(self):
        cursor = Mock()
        fields = g.QUERIES["isolation"][0]
        cursor.description = [SimpleNamespace(name=name) for name in fields + ("extra",)]
        with self.assertRaises(PolicyRefusal):
            g.read_allowed(cursor, "isolation", fields)
        cursor.description = [SimpleNamespace(name=name) for name in fields]
        cursor.fetchmany.return_value = [(1, 2, 3, 4), (1, 2, 3, 4)]
        with self.assertRaises(PolicyRefusal):
            g.read_allowed(cursor, "isolation", fields)

    def test_queries_never_read_market_price_or_outcome_tables(self):
        for _fields, query, _bound in g.QUERIES.values():
            self.assertNotIn("SELECT *", query)
            for forbidden in (
                "market_candle",
                "bid_open",
                "bid_high",
                "bid_low",
                "bid_close",
                "ask_open",
                "ask_high",
                "ask_low",
                "ask_close",
                "volume",
                "stop_price",
                "target_price",
                "entry_price",
                "tradeoutcome",
            ):
                self.assertNotIn(forbidden, query.lower())
        tree = ast.parse(Path(g.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    node.module,
                    (
                        "research.signal_count",
                        "research.failed_break_detector",
                        "research.strategy",
                        "market.models",
                        "forecasts.services",
                    ),
                )


class GeometryTests(unittest.TestCase):
    def test_week_is_new_york_not_utc(self):
        self.assertEqual(g.entry_week("2018-01-08T01:00:00+00:00"), "2018-W01")
        self.assertEqual(g.entry_week("2018-01-08T05:00:00+00:00"), "2018-W02")

    def test_kish_known_counterexample(self):
        result = g.cluster_summary({"week1": ["a", "b"], "week2": ["c"]})
        self.assertEqual(result["kish_exact"], "9/5")
        self.assertEqual(result["raw_count"], 2)

    def test_shared_factor_is_transitive_ignores_direction_but_not_week(self):
        rows = [
            event("a", pair="EUR_GBP"),
            event("b", pair="GBP_USD", direction="short"),
            event("c", pair="USD_JPY"),
            event("d", day=8, pair="EUR_GBP"),
        ]
        clusters = g.factor_clusters(rows)
        self.assertEqual(sorted(clusters["sizes"].values()), [1, 3])
        self.assertEqual(clusters["kish_exact"], "8/5")
        self.assertEqual(clusters, g.factor_clusters(list(reversed(rows))))

    def test_shared_week_alone_does_not_connect_disjoint_currencies(self):
        result = g.factor_clusters([event("a", pair="EUR_GBP"), event("b", pair="USD_JPY")])
        self.assertEqual(result["raw_count"], 2)
        self.assertEqual(result["kish_exact"], "2")

    def test_equal_horizon_boundary_keeps_capacity_for_entry_phase(self):
        rows = [event("a", end_day=2), event("b", day=2)]
        geometry = g.geometry(rows)
        self.assertEqual(geometry["half_open_peak"], 1)
        self.assertEqual(geometry["allocation_phase_peak"], 2)
        self.assertEqual(geometry["maximum_horizon_overlap_edges"], [["a", "b"]])

    def test_daily_completion_uses_new_york_wall_clock_across_dst(self):
        self.assertEqual(
            g.daily_completion("2018-03-10T22:00:00+00:00"), datetime(2018, 3, 11, 21, tzinfo=UTC)
        )
        self.assertEqual(
            g.daily_completion("2018-11-03T21:00:00+00:00"), datetime(2018, 11, 4, 22, tzinfo=UTC)
        )

    def test_currency_gross_limits_no_netting_and_common_fraction(self):
        rows = [event("a"), event("b", pair="GBP_USD"), event("c", pair="AUD_USD")]
        result = g.capacity_diagnostic(rows)
        self.assertEqual(len({row["common_fraction"] for row in result["rows"]}), 1)
        self.assertEqual([row["units"] for row in result["rows"]], [1666, 1666, 1666])
        self.assertEqual(result, g.capacity_diagnostic(list(reversed(rows))))
        self.assertEqual(g.buckets(event("d", direction="short")), ("short:EUR", "long:USD"))

    def test_unit_rounding_never_redistributes(self):
        rows = [
            event("a", risk="17"),
            event("b", pair="GBP_USD", risk="17"),
            event("c", pair="AUD_USD", risk="17"),
        ]
        result = g.capacity_diagnostic(rows)
        self.assertEqual(result["zero_unit_events"], 3)
        self.assertEqual(result["positive_unit_events"], 0)
        self.assertIsNone(result["actual_allocated_count"])
        self.assertIsNone(result["actual_resolved_allocated_count"])

    def test_closed_boundary_prevents_premature_release(self):
        rows = [event("a", end_day=2), event("b", hour=15, end_day=2), event("c", day=2)]
        result = g.capacity_diagnostic(rows)
        self.assertEqual(result["rows"][2]["units"], 0)

    def test_invalid_unit_risk_refused(self):
        for risk in ("0", "-1", "NaN"):
            with self.subTest(risk=risk), self.assertRaises(PolicyRefusal):
                g.capacity_diagnostic([event("a", risk=risk)])

    def test_family_fractional_and_currency_double_denominators(self):
        a, b = event("a"), event("b")
        a["families"] += ["CONFIRMED_DAILY_SWING"]
        result = g.concentration([a, b])
        self.assertEqual(result["family"]["PREVIOUS_WEEKLY_EXTREME"]["exact"], "3/4")
        self.assertEqual(result["currency_direction"]["long:EUR"]["exact"], "1/2")
        self.assertEqual(sum(Fraction(row["exact"]) for row in result["family"].values()), 1)

    def test_mde_grid_is_requested_sigma_and_decreases_with_effective_n(self):
        self.assertEqual(set(g.detectable_effect(90)), {"0.5", "1.0", "1.5"})
        self.assertGreater(
            float(g.detectable_effect(45)["1.0"]), float(g.detectable_effect(90)["1.0"])
        )
        self.assertGreater(float(g.detectable_effect(90)["1.0"]), 0.20)

    def test_resolved_and_paired_floors_are_not_fabricated_from_proxy(self):
        rows = [event(str(n), day=(n % 20) + 1, end_day=28) for n in range(60)]
        result = g.floors(COMBINED_BOOK, rows, g.geometry(rows), load_policy())
        for field in (
            "minimum_resolved_allocated_physical_trades",
            "minimum_paired_physical_events",
            "maximum_unresolved_data_count",
        ):
            self.assertEqual(result[field]["status"], "UNKNOWABLE")
            self.assertIsNone(result[field]["observed"])
        short = g.floors(COMBINED_BOOK, rows[:20], g.geometry(rows[:20]), load_policy())
        self.assertEqual(short["minimum_resolved_allocated_physical_trades"]["status"], "FAILED")


class CommittedProjectionTests(unittest.TestCase):
    def test_full_projection_reconstructs_offline_no_connection(self):
        with (
            patch("socket.socket.connect", side_effect=AssertionError("network forbidden")),
            patch.object(
                g, "read_once", side_effect=AssertionError("second live projection forbidden")
            ),
        ):
            artifact = g.verify_committed()
        self.assertEqual(len(artifact["events"]), 90)
        self.assertEqual(sum(len(row["books"]) for row in artifact["events"]), 204)
        self.assertFalse(artifact["authorization_effective"])
        self.assertEqual(artifact["report"]["recommendation"]["choice"], "B")
        self.assertFalse(artifact["report"]["recommendation"]["effective"])
        self.assertEqual(
            g.PROJECTION_FILE_SHA256,
            "4749633ac8c3f28e977e7697ba9f1b9d32425de84afde183a2d0fd98e4c7b27b",
        )
        self.assertEqual(
            g.PROJECTION_SHA256,
            "af2f0d6e2e865dcdc8d9825c039d5df650059e717cd09fad92b0f41ff72a8fb7",
        )
        reason = artifact["report"]["recommendation"]["reason"]
        self.assertIn("unconditionally immutable", reason)
        self.assertNotIn("merely", reason)
        self.assertNotIn("preregistered dispersion", reason)
        self.assertEqual(
            artifact["report"]["sigma_grid_governance"],
            {
                "interchangeable_with_s2_03": False,
                "observed_return_selection_or_reinterpretation": "PROHIBITED",
                "overrides_s2_03": False,
                "promotion_authority": False,
                "purpose": "RETURN_BLIND_GEOMETRY_MDE_DIAGNOSTIC",
                "sigma_R": ["0.5", "1.0", "1.5"],
            },
        )

    def test_actual_entry_clusters_pinned_not_confirmed_setup_or_book_counts(self):
        artifact = g.verify_committed()
        combined = artifact["report"]["books"][COMBINED_BOOK]
        geometry = combined["geometry"]
        self.assertEqual(geometry["entry_dates"]["raw_count"], 81)
        self.assertEqual(geometry["entry_weeks"]["raw_count"], 73)
        self.assertEqual(geometry["entry_weeks"]["kish_exact"], "2025/34")
        self.assertEqual(geometry["shared_factors"]["raw_count"], 74)
        self.assertEqual(geometry["shared_factors"]["kish_exact"], "4050/67")
        self.assertEqual(
            artifact["report"]["singleton_408_shared_currency_statistic"],
            "NON_AUTHORITATIVE_NOT_INDEPENDENCE_EVIDENCE",
        )
        self.assertEqual(
            artifact["report"]["confirmed_setup_kish"],
            "PROHIBITED_SUBSTITUTE_FOR_TRADE_LEVEL_EFFECTIVE_SAMPLE_SIZE",
        )

    def test_exact_rational_reference_matches_every_projected_book_allocation(self):
        artifact = g.verify_committed()
        for book in g.BOOKS:
            rows = [row for row in artifact["events"] if book in row["books"]]
            expected = rational_capacity_reference(rows)
            actual = artifact["report"]["books"][book]["capacity_diagnostic"]["rows"]
            self.assertEqual(
                [(row["key"], row["units"], row["risk"]) for row in expected],
                [
                    (row["physical_key"], row["units"], Fraction(row["planned_risk_cad"]))
                    for row in actual
                ],
            )

    def test_capacity_diagnostic_and_resolution_not_conflated(self):
        artifact = g.verify_committed()
        combined = artifact["report"]["books"][COMBINED_BOOK]
        self.assertEqual(combined["capacity_diagnostic"]["positive_unit_events"], 86)
        self.assertEqual(combined["capacity_diagnostic"]["zero_unit_events"], 4)
        self.assertIsNone(artifact["report"]["resolved_allocated_physical_trades"])
        self.assertIsNone(combined["actual_resolved_risk_weighted_concentration"])
        self.assertEqual(
            combined["s2_04_floors"]["minimum_resolved_allocated_physical_trades"]["status"],
            "UNKNOWABLE",
        )

    def test_retained_nullable_confirmation_job_matches_committed_detector_call(self):
        artifact = g.verify_committed()
        self.assertTrue(
            all(row["job_id"] is None for row in artifact["source_projection"]["evaluations"])
        )
        tree = ast.parse((Path(g.__file__).parent / "failed_break_detector.py").read_text())
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "persist_confirmation"
        ]
        self.assertTrue(calls)
        self.assertTrue(
            all("job_run" not in {keyword.arg for keyword in call.keywords} for call in calls)
        )


if __name__ == "__main__":
    unittest.main()
