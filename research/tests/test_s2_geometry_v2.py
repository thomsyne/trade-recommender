"""Focused return-blind v2 geometry tests; no persistent database access."""

import hashlib
import json
import socket
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from research import s2_geometry_v2 as g
from research.s2_policy import COMBINED_BOOK


def event(key, *, day=1, pair="EUR_USD", direction="long", hour=14):
    base, quote = pair.split("_")
    return {
        "physical_key": key,
        "natural_key": [pair, direction, f"2018-01-{day:02d}T12:00:00+00:00"],
        "entry_at": datetime(2018, 1, day, hour, tzinfo=UTC).isoformat(),
        "horizon_at": datetime(2018, 1, min(day + 10, 28), hour, tzinfo=UTC).isoformat(),
        "base": base,
        "quote": quote,
        "instrument": pair,
        "direction": direction,
        "risk_per_unit_cad": "0.01",
        "books": [COMBINED_BOOK],
        "families": ["PREVIOUS_WEEKLY_EXTREME"],
    }


class QueryContractTests(unittest.TestCase):
    def test_extra_partial_and_unknown_queries_fail_before_execution(self):
        cursor = Mock()
        allowed = g.QUERIES["evaluations"][0]
        for fields in (allowed + ("entry_price",), allowed[:-1], ("*",)):
            with self.subTest(fields=fields), self.assertRaises(g.V2GeometryRefusal):
                g.read_allowed(cursor, "evaluations", fields)
        with self.assertRaises(g.V2GeometryRefusal):
            g.read_allowed(cursor, "market_candle", ("timestamp",))
        cursor.execute.assert_not_called()

    def test_query_descriptions_and_bounds_fail_closed(self):
        cursor = Mock()
        fields = g.QUERIES["isolation"][0]
        cursor.description = [Mock(name=name) for name in fields]
        for column, name in zip(cursor.description, fields, strict=True):
            column.name = name
        cursor.fetchmany.return_value = [(1, 2, 3, 4), (1, 2, 3, 4)]
        with self.assertRaises(g.V2GeometryRefusal):
            g.read_allowed(cursor, "isolation", fields)

    def test_sql_has_no_price_outcome_or_post_entry_candle_reader(self):
        sql = "\n".join(query.lower() for _fields, query, _limit in g.QUERIES.values())
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
            "mid_open",
            "entry_price",
            "stop_price",
            "target_price",
            "reward_risk",
            "tradeoutcome",
            "papertrade",
            "backtest",
            "profit_loss",
        ):
            self.assertNotIn(forbidden, sql)
        self.assertNotIn("select *", sql)


class DefinitionTests(unittest.TestCase):
    def test_established_cluster_assignment_and_kish_definitions(self):
        rows = [
            event("a", pair="EUR_GBP"),
            event("b", pair="GBP_USD", direction="short"),
            event("c", day=8, pair="AUD_USD"),
        ]
        result = g.geometry_with_assignments(rows)
        self.assertEqual(result["entry_weeks"]["raw_count"], 2)
        self.assertEqual(result["entry_weeks"]["kish_exact"], "9/5")
        self.assertEqual(sorted(result["shared_factors"]["sizes"].values()), [1, 2])
        self.assertEqual(
            result["shared_factors"]["membership_sha256"],
            g.digest(result["cluster_assignments"]["shared_factors"]),
        )

    def test_concentration_and_mde_are_return_blind_count_geometry(self):
        rows = [event("a"), event("b", pair="GBP_USD"), event("c", day=8)]
        geometry = g.geometry_with_assignments(rows)
        maximum = g._max_concentration(rows, geometry, {COMBINED_BOOK: 3})
        self.assertEqual(maximum["instrument"]["count"], 2)
        mde = g._mde(geometry, len(rows))
        self.assertEqual(set(mde["conservative_mde_R"]), {"0.5", "1.0", "1.5"})
        self.assertGreater(float(mde["conservative_mde_R"]["1.5"]), 0.20)

    def test_capacity_summary_does_not_claim_allocation_or_resolution(self):
        result = g._capacity_summary([event("a")])
        self.assertIsNone(result["actual_allocated_count"])
        self.assertIsNone(result["actual_resolved_allocated_count"])
        self.assertTrue(result["not_a_bound_on_actual_survival"])
        self.assertEqual(result["rows"], 1)


class CommittedGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        ):
            cls.artifact = g.verify_committed()

    def test_exact_source_acceptance_pins_and_authority(self):
        source = self.artifact["source_s1_acceptance"]
        self.assertEqual(source["artifact_sha256"], g.S1_ACCEPTANCE_FILE_SHA256)
        self.assertEqual(source["self_sha256"], g.S1_ACCEPTANCE_SELF_SHA256)
        self.assertEqual(source["aggregate_evidence_sha256"], g.S1_AGGREGATE_EVIDENCE_SHA256)
        self.assertEqual(source["projection_sha256"], g.S1_PROJECTION_SHA256)
        self.assertEqual(
            self.artifact["authority"],
            {
                "return_blind_geometry_analysis": "COMPLETED",
                "effective_s2_policy": False,
                "return_execution": False,
                "backtesting": False,
                "promotion_or_live_trading": False,
                "provider_production_or_deployment": False,
            },
        )

    def test_book_evaluations_collapse_to_physical_events_and_boundary_purge(self):
        rows = [*self.artifact["events"], *self.artifact["purged_events"]]
        self.assertEqual(self.artifact["source_entry_pending_evaluations"], 188)
        self.assertEqual(self.artifact["source_physical_events"], 83)
        self.assertEqual(len(rows), 83)
        self.assertEqual(sum(len(row["books"]) for row in rows), 188)
        self.assertEqual(len({row["physical_key"] for row in rows}), 83)
        self.assertEqual(len(self.artifact["purged_events"]), 1)
        self.assertEqual(self.artifact["purged_events"][0]["setup_id"], 1722)
        for row in rows:
            self.assertEqual(len(row["books"]), len(set(row["books"])))
            self.assertIn(COMBINED_BOOK, row["books"])
            self.assertEqual(row["physical_key"], g.digest(row["natural_key"]))

    def test_exact_geometry_clusters_concentration_and_mde(self):
        report = self.artifact["report"]
        combined = report["books"][COMBINED_BOOK]
        geometry = combined["geometry"]
        self.assertEqual(report["physical_events"], 82)
        self.assertEqual(report["book_memberships"], 186)
        self.assertEqual(geometry["entry_dates"]["raw_count"], 76)
        self.assertEqual(geometry["entry_weeks"]["raw_count"], 68)
        self.assertEqual(geometry["entry_weeks"]["kish_exact"], "1681/28")
        self.assertEqual(geometry["shared_factors"]["raw_count"], 69)
        self.assertEqual(geometry["shared_factors"]["kish_exact"], "3362/55")
        self.assertEqual(geometry["simultaneous"]["raw_count"], 81)
        self.assertEqual(geometry["allocation_phase_peak"], 3)
        self.assertEqual(len(geometry["maximum_horizon_overlap_edges"]), 34)
        self.assertEqual(
            combined["mde"]["target_0_20R_adequacy"],
            {"0.5": "ADEQUATE", "1.0": "INADEQUATE", "1.5": "INADEQUATE"},
        )
        self.assertEqual(report["maximum_concentration"]["instrument"]["exact"], "10/41")

    def test_per_book_counts_and_v1_v2_comparison(self):
        books = self.artifact["report"]["books"]
        self.assertEqual(
            {book: row["eligible_physical_count"] for book, row in books.items()},
            {
                COMBINED_BOOK: 82,
                "failed-break-breakout-flip-v1": 28,
                "failed-break-daily-swing-v1": 38,
                "failed-break-weekly-extreme-v1": 38,
            },
        )
        comparison = self.artifact["report"]["v1_v2_comparison"]
        self.assertEqual(comparison["semantic_event_overlap"], 75)
        self.assertEqual(comparison["numeric_delta"]["physical_events"], -8)
        self.assertEqual(comparison["numeric_delta"]["maximum_horizon_concurrency"], -2)
        self.assertEqual(len(comparison["v1_only_semantic_events"]), 15)
        self.assertEqual(len(comparison["v2_only_semantic_events"]), 7)

    def test_forged_rehashed_artifact_is_refused_by_fixed_digest(self):
        artifact = json.loads(g.ARTIFACT_PATH.read_bytes())
        artifact["authority"]["return_execution"] = True
        body = dict(artifact)
        body.pop("geometry_sha256")
        artifact["geometry_sha256"] = g.digest(body)
        raw = g.canonical_bytes(artifact) + b"\n"
        with self.assertRaises(g.V2GeometryRefusal):
            g._verify_artifact_bytes(raw, hashlib.sha256(raw).hexdigest())

    def test_artifact_and_report_fixed_hashes(self):
        self.assertEqual(
            hashlib.sha256(g.ARTIFACT_PATH.read_bytes()).hexdigest(), g.ARTIFACT_FILE_SHA256
        )
        self.assertEqual(self.artifact["geometry_sha256"], g.ARTIFACT_SELF_SHA256)
        self.assertEqual(
            hashlib.sha256(g.REPORT_PATH.read_bytes()).hexdigest(), g.DECISION_REPORT_FILE_SHA256
        )
        self.assertEqual(self.artifact["event_set_sha256"], g.digest(self.artifact["events"]))
        self.assertEqual(self.artifact["report_sha256"], g.digest(self.artifact["report"]))

    def test_no_forbidden_event_or_source_value_is_committed(self):
        forbidden = {
            "entry_price",
            "stop_price",
            "target_price",
            "reward_risk",
            "return",
            "pnl",
            "win",
            "loss",
            "drawdown",
        }
        for event_row in [*self.artifact["events"], *self.artifact["purged_events"]]:
            self.assertTrue(forbidden.isdisjoint(event_row))
        source = self.artifact["source_projection"]
        self.assertTrue(forbidden.isdisjoint(source))

    def test_report_does_not_claim_effectiveness(self):
        text = Path(g.REPORT_PATH).read_text()
        self.assertIn("Return execution, backtesting, effective S2 policy", text)
        self.assertIn("all remain unauthorized", text)
        self.assertFalse(self.artifact["report"]["recommendation"]["effective"])


if __name__ == "__main__":
    unittest.main()
