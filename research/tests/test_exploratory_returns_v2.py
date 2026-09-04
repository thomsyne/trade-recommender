"""Focused synthetic-only tests for the v2 exploratory return calculator."""

import ast
import copy
import hashlib
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from research import exploratory_returns_v2 as calc
from research import exploratory_returns_v2_governance as governance
from research.benchmarks.benchmark_exploratory_returns_v2 import synthetic_event


def replace_bar(event, **values):
    event["h1"][0].update(values)
    return event


def short_event(index=1):
    event = synthetic_event(index)
    event.update(
        direction="short",
        entry_bid="1.0200",
        entry_ask="1.0202",
        stop="1.0210",
        target="1.0180",
        supporting_swing="1.0300",
    )
    replace_bar(
        event,
        ask_high="1.0208",
        ask_low="1.0178",
        bid_high="1.0206",
        bid_low="1.0176",
    )
    return event


class ResolutionTests(unittest.TestCase):
    def test_long_and_short_target_and_stop(self):
        long_target = synthetic_event(0)
        self.assertEqual(calc.resolve_event(long_target)["terminal"], "TARGET")
        long_stop = replace_bar(synthetic_event(1), bid_high="1.0205", bid_low="1.0190")
        self.assertEqual(calc.resolve_event(long_stop)["terminal"], "STOP")
        self.assertEqual(calc.resolve_event(short_event(2))["terminal"], "TARGET")
        short_stop = replace_bar(short_event(3), ask_low="1.0195", ask_high="1.0212")
        self.assertEqual(calc.resolve_event(short_stop)["terminal"], "STOP")

    def test_same_candle_is_stop_first_and_adverse_gap_is_worse(self):
        event = replace_bar(synthetic_event(4), bid_low="1.0185", bid_high="1.0225")
        result = calc.resolve_event(event)
        self.assertEqual((result["terminal"], result["ambiguity"]), ("STOP", True))
        event = synthetic_event(5)
        event["h1"][0].update(bid_high="1.0210", bid_low="1.0193")
        adverse_at = calc.stamp(calc.timestamp(event["entry_at"]) + timedelta(hours=2))
        adverse = copy.deepcopy(event["h1"][0])
        adverse.update(start=adverse_at, bid_open="1.0188", bid_low="1.0185", bid_high="1.0190")
        event["expected_h1_starts"].insert(1, adverse_at)
        event["h1"].insert(1, adverse)
        evidence = copy.deepcopy(next(iter(event["conversion"].values())))
        exit_at = calc.stamp(calc.timestamp(adverse_at) + timedelta(hours=1))
        evidence["as_of"] = exit_at
        event["conversion"] = {exit_at: evidence}
        result = calc.resolve_event(event)
        self.assertEqual(result["exit_price"], "1.0188")

    def test_horizon_and_daily_structure_use_next_sealed_h1_open(self):
        event = synthetic_event(6)
        _, horizon = event["expected_h1_starts"]
        event["h1"][0].update(bid_high="1.0210", bid_low="1.0193")
        event["conversion"] = {
            horizon: {
                **next(iter(event["conversion"].values())),
                "as_of": horizon,
            }
        }
        self.assertEqual(calc.resolve_event(event)["terminal"], "HORIZON")
        structure = copy.deepcopy(event)
        structure["daily"][0]["mid_close"] = "1.0099"
        self.assertEqual(calc.resolve_event(structure)["terminal"], "DAILY_STRUCTURE")

    def test_missing_conflict_conversion_and_lookahead_fail_closed(self):
        missing = synthetic_event(7)
        missing["h1"].pop()
        self.assertEqual(calc.resolve_event(missing)["terminal"], "UNRESOLVED_DATA")
        conflict = synthetic_event(8)
        conflict["h1"][0]["conflict"] = True
        self.assertEqual(calc.resolve_event(conflict)["terminal"], "UNRESOLVED_DATA")
        conversion = synthetic_event(9)
        conversion["conversion"] = {}
        self.assertEqual(calc.resolve_event(conversion)["terminal"], "UNRESOLVED_DATA")
        future = synthetic_event(10)
        evidence = next(iter(future["conversion"].values()))
        evidence["legs"][0]["completed_at"] = evidence["as_of"]
        self.assertEqual(calc.resolve_event(future)["terminal"], "UNRESOLVED_DATA")

    def test_fixed_direct_inverse_and_two_leg_cad_routes(self):
        at = calc.timestamp("2014-01-06T14:00:00+00:00")
        prior = "2014-01-06T13:00:00+00:00"

        def evidence(currency, legs):
            return {"as_of": calc.stamp(at), "currency": currency, "legs": legs}

        def leg(pair, direction, midpoint):
            return {
                "complete": True,
                "completed_at": prior,
                "conflict": False,
                "direction": direction,
                "midpoint_close": midpoint,
                "pair": pair,
                "sealed": True,
            }

        self.assertEqual(calc.conversion_rate(evidence("CAD", []), "CAD", at), Decimal(1))
        self.assertEqual(
            calc.conversion_rate(evidence("USD", [leg("USD_CAD", "multiply", "1.25")]), "USD", at),
            Decimal("1.25"),
        )
        self.assertEqual(
            calc.conversion_rate(
                evidence(
                    "GBP",
                    [leg("GBP_USD", "multiply", "1.2"), leg("USD_CAD", "multiply", "1.25")],
                ),
                "GBP",
                at,
            ),
            Decimal("1.5"),
        )
        self.assertEqual(
            calc.conversion_rate(
                evidence(
                    "JPY",
                    [leg("USD_JPY", "divide", "100"), leg("USD_CAD", "multiply", "1.25")],
                ),
                "JPY",
                at,
            ),
            Decimal("0.0125"),
        )

    def test_preentry_session_or_spread_payload_is_refused_not_reinterpreted(self):
        for field in ("session_eligible", "spread_eligible"):
            event = synthetic_event(11)
            event[field] = False
            self.assertEqual(calc.resolve_event(event)["terminal"], "UNRESOLVED_DATA")

    def test_future_daily_outcome_cannot_replace_an_earlier_target(self):
        event = synthetic_event(14)
        event["daily"][0]["mid_close"] = "0.5000"
        self.assertEqual(calc.resolve_event(event)["terminal"], "TARGET")


class CostAndAccountingTests(unittest.TestCase):
    def test_cost_grid_is_exact_commission_times_financing_without_slippage(self):
        event = synthetic_event(0)
        event["h1"][0].update(bid_high="1.0210", bid_low="1.0193")
        horizon = event["horizon_at"]
        template = copy.deepcopy(next(iter(event["conversion"].values())))
        template["as_of"] = horizon
        event["conversion"] = {horizon: template}
        event["rollovers"] = []
        for rollover, multiplier in calc._rollover_times(
            calc.timestamp(event["entry_at"]), calc.timestamp(horizon)
        ):
            rollover_at = calc.stamp(rollover)
            evidence = copy.deepcopy(template)
            evidence["as_of"] = rollover_at
            event["rollovers"].append(
                {
                    "at": rollover_at,
                    "conversion": evidence,
                    "midpoint": "1.02",
                    "multiplier": multiplier,
                }
            )
        result = calc.resolve_event(event)
        cells = calc.cost_grid(event, result, Decimal("25"))
        self.assertEqual(len(cells), 15)
        self.assertEqual(
            {(row["commission_pips"], row["annual_financing_rate"]) for row in cells},
            {
                (calc.rendered(c), calc.rendered(f))
                for c in calc.COMMISSIONS
                for f in calc.FINANCING_RATES
            },
        )
        self.assertTrue(all(row["additional_slippage_R"] == "0" for row in cells))
        self.assertLess(Decimal(cells[0]["financing_R"]), 0)
        self.assertGreater(Decimal(cells[4]["financing_R"]), 0)

    def test_multiple_books_are_one_event_and_all_108_months_are_present(self):
        event = synthetic_event(13)
        event["books"] = [
            "failed-break-any-level-deduplicated-v1",
            "failed-break-daily-swing-v1",
            "failed-break-weekly-extreme-v1",
        ]
        result = calc.resolve_event(event)
        diagnostic = calc.fixed_capital_diagnostic(
            [event],
            [result],
            {event["physical_event_key"]: Decimal(result["gross_R"])},
            Decimal(25),
        )
        self.assertEqual(len(diagnostic["month_rows"]), 108)
        self.assertEqual(diagnostic["total_pnl_cad"], "45")
        self.assertEqual(diagnostic["peak_aggregate_open_risk_cad"], "25")

    def test_overlapping_physical_events_retain_separate_fixed_risk(self):
        events = [synthetic_event(20), synthetic_event(20)]
        events[1]["physical_event_key"] = "overlap-b"
        results = [calc.resolve_event(event) for event in events]
        diagnostic = calc.fixed_capital_diagnostic(
            events,
            results,
            {row["physical_event_key"]: Decimal(row["gross_R"]) for row in results},
            Decimal(25),
        )
        self.assertEqual(diagnostic["peak_aggregate_open_risk_cad"], "50")

    def test_daily_equity_uses_side_aware_mark_and_requires_its_conversion(self):
        event = synthetic_event(0)
        event["h1"][0].update(bid_high="1.0210", bid_low="1.0193")
        horizon = event["horizon_at"]
        mark = "2014-01-06T22:00:00+00:00"
        template = copy.deepcopy(next(iter(event["conversion"].values())))
        template["as_of"] = horizon
        event["conversion"] = {horizon: template}
        mark_conversion = copy.deepcopy(template)
        event["marks"] = []
        for current in calc._calendar_marks():
            if calc.timestamp(event["entry_at"]) <= current < calc.timestamp(horizon):
                evidence = copy.deepcopy(mark_conversion)
                evidence["as_of"] = calc.stamp(current)
                event["marks"].append(
                    {"at": calc.stamp(current), "conversion": evidence, "side_close": "1.0210"}
                )
        result = calc.resolve_event(event)
        rows = calc.daily_equity_series(
            [event],
            [result],
            {event["physical_event_key"]: Decimal(result["gross_R"])},
            Decimal(25),
        )
        row = next(item for item in rows if item["at"] == mark)
        self.assertEqual(row["equity_cad"], "10020")
        event["marks"] = event["marks"][1:]
        with self.assertRaisesRegex(calc.ReturnRefusal, "missing governed daily equity mark"):
            calc.daily_equity_series(
                [event],
                [result],
                {event["physical_event_key"]: Decimal(result["gross_R"])},
                Decimal(25),
            )

    def test_winning_losing_and_flat_undefined_ratios_are_null(self):
        self.assertIsNone(calc.summary_metrics([Decimal("1")])["payoff_ratio"])
        self.assertIsNone(calc.summary_metrics([Decimal("1")])["profit_factor"])
        self.assertIsNone(calc.summary_metrics([Decimal("-1")])["payoff_ratio"])
        flat = calc.summary_metrics([Decimal("0")])
        self.assertIsNone(flat["payoff_ratio"])
        self.assertIsNone(flat["profit_factor"])

    def test_complete_event_set_order_independence_and_set_refusals(self):
        events = [synthetic_event(index) for index in range(82)]
        expected = {row["physical_event_key"] for row in events}
        first = calc.calculate_synthetic_cohort(events, expected, "a" * 64, bootstrap=False)
        second = calc.calculate_synthetic_cohort(
            list(reversed(events)), expected, "a" * 64, bootstrap=False
        )
        self.assertEqual(first["report_sha256"], second["report_sha256"])
        self.assertEqual(first["event_count"], 82)
        with self.assertRaisesRegex(calc.ReturnRefusal, "missing or extra"):
            calc.calculate_synthetic_cohort(events[:-1], expected, "a" * 64, bootstrap=False)
        with self.assertRaisesRegex(calc.ReturnRefusal, "duplicate"):
            calc.calculate_synthetic_cohort(
                events + [events[0]], expected, "a" * 64, bootstrap=False
            )
        extra = events + [synthetic_event(100)]
        with self.assertRaisesRegex(calc.ReturnRefusal, "missing or extra"):
            calc.calculate_synthetic_cohort(extra, expected, "a" * 64, bootstrap=False)

    def test_bootstrap_is_deterministic_and_sigma_grids_stay_distinct(self):
        rows = [
            {"entry_at": synthetic_event(index)["entry_at"], "net_R": str(index % 3 - 1)}
            for index in range(12)
        ]
        first = calc.week_cluster_bootstrap(rows, "b" * 64)
        self.assertEqual(first, calc.week_cluster_bootstrap(list(reversed(rows)), "b" * 64))
        self.assertEqual(first["replicates"], 10_000)
        self.assertNotEqual(calc.GEOMETRY_SIGMA_GRID, calc.SENSITIVITY_SIGMA_GRID)


class GovernanceAndIsolationTests(unittest.TestCase):
    def test_artifact_hashes_sources_and_complete_governed_event_set(self):
        artifact = governance.load_preregistration()
        self.assertEqual(artifact["implementation_sha256"], governance.SELF_SHA256)
        self.assertEqual(
            hashlib.sha256(governance.ARTIFACT_PATH.read_bytes()).hexdigest(),
            governance.ARTIFACT_SHA256,
        )
        self.assertEqual(len(governance.governed_event_keys()), 82)
        self.assertNotIn(governance.BOUNDARY_PURGED_EVENT_KEY, governance.governed_event_keys())
        self.assertEqual(
            hashlib.sha256(governance.REPORT_PATH.read_bytes()).hexdigest(),
            governance.REPORT_SHA256,
        )

    def test_rehashed_policy_or_authority_forgery_fails_fixed_file_digest(self):
        artifact = copy.deepcopy(governance.load_preregistration())
        artifact["authority"]["persistent_return_execution"] = True
        body = dict(artifact)
        body.pop("implementation_sha256")
        artifact["implementation_sha256"] = governance.digest(body)
        with tempfile.TemporaryDirectory() as directory:
            forged = Path(directory) / "forged.json"
            forged.write_bytes(governance.canonical_bytes(artifact) + b"\n")
            with patch.object(governance, "ARTIFACT_PATH", forged):
                with self.assertRaisesRegex(governance.GovernanceRefusal, "file digest"):
                    governance.load_preregistration()

    def test_execution_promotion_and_all_override_channels_refuse(self):
        for function in (governance.calculate_governed_real_cohort, governance.require_promotion):
            for override in ({}, {"owner": True}, {"successful_outcome": True}):
                with self.subTest(function=function.__name__, override=override):
                    with self.assertRaises(governance.GovernanceRefusal):
                        function(**override)

    def test_calculator_has_no_orm_database_network_or_process_import(self):
        tree = ast.parse(Path(calc.__file__).read_text())
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported |= {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertTrue(
            {"django", "psycopg", "requests", "socket", "subprocess", "urllib"}.isdisjoint(imported)
        )
        with patch("builtins.open", side_effect=AssertionError("I/O attempted")):
            self.assertEqual(calc.resolve_event(synthetic_event(200))["terminal"], "TARGET")
