"""Synthetic/disposable tests; no strategy result from acquired candles is read."""

import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from market.state.canonical import canonical_json, identity_digest
from research.validation_batch import opportunities, run, shadow_readiness
from research.validation_data import expected_times, regular_open
from research.validation_execution import conversion, crosses_rollover, simulate
from research.validation_registration import Catalog, validate_registration
from research.validation_replay import ReplayInput, Series
from research.validation_reports import effective_weeks, paired_increment


def candle(at, opening="100", high="103", low="99", close="102", spread="0.2"):
    from decimal import Decimal as D

    return {
        "timestamp": at.isoformat(),
        "end": (at + timedelta(hours=1)).isoformat(),
        "granularity": "H1",
        "acquired_at": "2026-09-11T00:00:00+00:00",
        "chunk_identity": "synthetic",
        "volume": 1,
        **{
            f"{side}_{name}": str(D(value) + sign * D(spread) / 2)
            for side, sign in (("bid", -1), ("ask", 1))
            for name, value in (("open", opening), ("high", high), ("low", low), ("close", close))
        },
    }


class ClockExecutionTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2020, 1, 6, 10, tzinfo=UTC)
        self.registration = {
            "scenarios": ["baseline", "adverse_cost", "extra_interval_latency"],
            "slippage_spreads_per_side": {
                "baseline": "1",
                "adverse_cost": "2",
                "extra_interval_latency": "1",
            },
            "commission_CAD_per_base_side": {
                "baseline": "0.0001",
                "adverse_cost": "0.0002",
                "extra_interval_latency": "0.0001",
            },
            "research_equity_CAD": "100000",
            "risk_fraction": "0.005",
        }
        self.setup = {
            "direction": 1,
            "reference": "100",
            "stop": "98",
            "target": "104",
            "strategy": "pullback-h1-v1",
            "entry_at": self.at.isoformat(),
            "exit_at": (self.at + timedelta(hours=3)).isoformat(),
            "signal_start": (self.at - timedelta(hours=1)).isoformat(),
            "available_at": self.at.isoformat(),
            "expires_at": (self.at + timedelta(hours=1)).isoformat(),
            "granularity": "H1",
            "evidence": [],
        }

    def test_real_acquisition_clock_and_future_prefix_invariance(self):
        data = Series([candle(self.at), candle(self.at + timedelta(hours=1), close="999")])
        cutoff = self.at + timedelta(hours=1)
        bars = ReplayInput("USD_CAD", cutoff, {"H1": data}, "fixed-risk-v1").series("H1")
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].observed_at, datetime(2026, 9, 11, tzinfo=UTC))
        self.assertEqual(bars[0].available_at, cutoff)

    def test_daily_opportunity_is_not_removed_by_UTC_midnight(self):
        day = self.at.replace(hour=0)
        self.assertEqual(list(opportunities("carry-readiness-v1", day)), [day.replace(hour=22)])
        self.assertEqual(list(expected_times(day, day + timedelta(days=1), "D")), [])
        self.assertFalse(regular_open(datetime(2017, 10, 6, 21, tzinfo=UTC), "D"))
        self.assertTrue(regular_open(datetime(2017, 10, 6, 21, tzinfo=UTC), "W"))

    def test_dual_hit_loss_accounting_and_terminal_missing_suffix(self):
        series = Series([candle(self.at, high="105", low="97")])
        result = simulate(self.setup, "USD_CAD", series, {}, self.registration, "baseline")
        # 500 CAD risk / 2 CAD stop = 250 units. Gross -500; two half-spreads
        # cost 50; two full spreads cost 100; commission reserve costs .05.
        self.assertEqual(result["state"], "modeled")
        self.assertEqual(result["reason"], "stop_adverse_path")
        from decimal import Decimal as D

        self.assertEqual(D(result["units"]), 250)
        self.assertEqual(D(result["gross_CAD"]), -500)
        self.assertEqual(D(result["spread_CAD"]), 50)
        self.assertEqual(D(result["slippage_CAD"]), 100)
        self.assertEqual(D(result["commission_CAD"]), D("0.05"))
        self.assertEqual(D(result["net_CAD"]), D("-650.05"))
        adverse = simulate(self.setup, "USD_CAD", series, {}, self.registration, "adverse_cost")
        self.assertEqual(D(adverse["net_CAD"]), D("-750.10"))
        self.assertEqual(
            result, simulate(self.setup, "USD_CAD", series, {}, self.registration, "baseline")
        )

    def test_each_missing_cost_blocks_or_refuses_and_financing_never_substitutes(self):
        series = Series([candle(self.at, high="105")])
        for key in ("slippage_spreads_per_side", "commission_CAD_per_base_side"):
            body = copy.deepcopy(self.registration)
            del body[key]
            with self.assertRaises(KeyError):
                simulate(self.setup, "USD_CAD", series, {}, body, "baseline")
        self.assertEqual(
            simulate(
                self.setup,
                "USD_CAD",
                Series([candle(self.at, spread="0")]),
                {},
                self.registration,
                "baseline",
            )["reason"],
            "spread_unavailable",
        )
        self.assertEqual(
            simulate(self.setup, "EUR_USD", series, {}, self.registration, "baseline")["reason"],
            "decision_conversion_unavailable",
        )
        rollover = self.at.replace(hour=22)
        self.assertTrue(crosses_rollover(rollover - timedelta(hours=1), rollover))
        self.assertTrue(crosses_rollover(rollover, rollover + timedelta(hours=1)))
        self.assertFalse(
            crosses_rollover(rollover + timedelta(seconds=1), rollover + timedelta(hours=1))
        )

    def test_short_stop_gap_and_limit_touch_are_not_favorable_fills(self):
        setup = {**self.setup, "direction": -1, "stop": "102", "target": "96"}
        series = Series(
            [
                candle(self.at, high="101", close="100.5"),
                candle(
                    self.at + timedelta(hours=1), opening="104", high="105", low="103", close="104"
                ),
            ]
        )
        result = simulate(setup, "USD_CAD", series, {}, self.registration, "baseline")
        self.assertEqual(result["reason"], "stop_gap")
        from decimal import Decimal as D

        self.assertEqual(D(result["gross_CAD"]), -1000)
        limit = {**self.setup, "strategy": "fast-mr-h1-v1"}
        self.assertEqual(
            simulate(limit, "USD_CAD", series, {}, self.registration, "baseline")["reason"],
            "limit_intrabar_fill_unavailable",
        )

    def test_conversion_uses_credit_debit_sides_and_never_future_bar(self):
        from decimal import Decimal as D

        data = {
            "USD_CAD": Series(
                [
                    candle(
                        self.at,
                        opening="1.34",
                        high="1.36",
                        low="1.33",
                        close="1.35",
                        spread="0.02",
                    )
                ]
            )
        }
        self.assertIsNone(conversion("USD", self.at, data))
        mid, credit, debit, _ = conversion("USD", self.at + timedelta(hours=1), data)
        self.assertEqual((mid, credit, debit), (D("1.35"), D("1.34"), D("1.36")))

    def test_holdout_horizon_refused_without_outcome_series_access(self):
        setup = {**self.setup, "exit_at": "2025-01-06T01:00:00+00:00"}
        self.assertEqual(
            simulate(setup, "USD_CAD", None, {}, self.registration, "baseline")["reason"],
            "sealed_outcome_horizon",
        )

    def test_weeks_not_trades_and_missing_comparator_is_not_zero(self):
        trades = [
            {"entered_at": "2020-12-27T23:00:00+00:00", "exited_at": "2020-12-28T01:00:00+00:00"}
        ] * 7
        self.assertEqual(effective_weeks(trades), (1, ["2020-W52", "2020-W53"]))

        def row(day, state, net="0"):
            return {
                "instrument": "EUR_USD",
                "session": "LONDON",
                "opportunity": f"2020-01-{day}T08:00:00+00:00",
                "scenarios": {"baseline": {"state": state, "net_CAD": net}},
            }

        result = paired_increment(
            [row("06", "modeled", "9"), row("07", "unavailable")],
            [row("06", "modeled", "12"), row("07", "modeled", "99")],
            "baseline",
        )
        self.assertEqual(result["total_increment_CAD"], "-3")
        self.assertEqual(result["unavailable_or_unmatched"], 1)
        self.assertEqual(
            shadow_readiness(datetime(2026, 9, 11, tzinfo=UTC))["elapsed_complete_weeks"], 0
        )

    def test_paired_overlay_scales_losses_and_costs_without_new_opportunities(self):
        from decimal import Decimal as D
        from decimal import localcontext

        from research.validation_reports import overlay_rows

        result = simulate(
            self.setup,
            "USD_CAD",
            Series([candle(self.at, high="105", low="97")]),
            {},
            self.registration,
            "baseline",
        )
        row = {
            "evaluation_identity": "synthetic",
            "strategy": "pullback-h1-v1",
            "opportunity": self.at.isoformat(),
            "scenarios": {"baseline": result},
            "overlays": {"ewma-risk-v1": {"multiplier": "0.3", "reason": "capped_at_baseline"}},
        }
        with localcontext() as context:
            context.prec = 3
            actual = overlay_rows([row], "ewma-risk-v1")[0]
        self.assertEqual(actual["opportunity"], row["opportunity"])
        self.assertEqual(D(actual["scenarios"]["baseline"]["net_CAD"]), D("-195.015"))
        self.assertEqual(D(actual["scenarios"]["baseline"]["commission_CAD"]), D("0.015"))
        row["overlays"]["ewma-risk-v1"]["multiplier"] = "1.01"
        with self.assertRaisesRegex(ValueError, "exceeds_baseline"):
            overlay_rows([row], "ewma-risk-v1")

    def test_direct_decision_seal_and_gap_index_both_sides(self):
        with self.assertRaisesRegex(ValueError, "sealed"):
            ReplayInput("EUR_USD", datetime(2025, 1, 6, tzinfo=UTC), {}, "fixed-risk-v1")
        rows = [
            candle(self.at),
            candle(self.at + timedelta(hours=2)),
            candle(self.at + timedelta(hours=3)),
        ]
        series = Series(rows)
        cutoff = self.at + timedelta(hours=4)
        self.assertEqual(len(series.before(cutoff, 2, require_contiguous=True)), 2)
        self.assertEqual(series.before(cutoff, 3, require_contiguous=True), ())

    def test_orb_first_failed_attempt_is_terminal_not_selected_later_success(self):
        from research.validation_batch import selection

        first = {
            "outputs": [
                {"schema": "phase5/unavailable-v1", "reason": "same_direction_fvg_unavailable"}
            ]
        }
        with patch("research.validation_batch.decision", return_value=first) as choose:
            output, setup = selection("orb-m15-fvg-v1:london", "EUR_USD", self.at, {})
        self.assertIsNone(setup)
        self.assertEqual(output, first)
        self.assertEqual(choose.call_count, 1)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        # Coverage-only artifact. No acquired candle or strategy outcome is read.
        self.audit = json.loads(Path("docs/phase5.5/acquired-coverage.json").read_text())
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "catalog.sqlite3"
        self.catalog = Catalog(self.path)
        self.identity, self.body = self.catalog.register(self.audit)
        self.key = {
            "registration": self.identity,
            "strategy": "carry-readiness-v1",
            "instrument": "EUR_USD",
            "start": "2019-01-07T00:00:00+00:00",
            "end": "2019-01-08T00:00:00+00:00",
        }
        self.state = {s: None for s in self.body["scenarios"]}
        self.rows = [
            {
                "opportunity": "2019-01-07T22:00:00+00:00",
                "strategy": "carry-readiness-v1",
                "instrument": "EUR_USD",
                "scenarios": {
                    s: {"state": "unavailable", "reason": "synthetic_missing_forwards"}
                    for s in self.state
                },
            }
        ]

    def tearDown(self):
        self.catalog.close()
        self.directory.cleanup()

    def test_all_registration_fields_are_bound_in_SQL_and_Python(self):
        for field, value in (
            ("risk_fraction", "0.01"),
            ("min_trades", 1),
            ("holdout_access", "released"),
            ("manifest", {}),
            ("periods", []),
            ("report_schema", "other"),
        ):
            body = {**self.body, field: value}
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_registration(body)
                with self.assertRaises(sqlite3.IntegrityError):
                    self.catalog.db.execute(
                        "INSERT INTO registration VALUES (?,?,?)",
                        (identity_digest(body), canonical_json(body), "2026-09-11"),
                    )
                self.catalog.db.rollback()

    def test_restart_deterministic_bytes_and_conflicting_retry(self):
        key = self.catalog.checkpoint(self.key, self.rows, end_state=self.state, predecessor=None)
        before = self.catalog.db.execute("SELECT * FROM checkpoint").fetchall()
        self.catalog.close()
        self.catalog = Catalog(self.path)
        self.assertEqual(
            key,
            self.catalog.checkpoint(self.key, self.rows, end_state=self.state, predecessor=None),
        )
        self.assertEqual(before, self.catalog.db.execute("SELECT * FROM checkpoint").fetchall())
        with self.assertRaisesRegex(ValueError, "conflict"):
            self.catalog.checkpoint(
                self.key,
                self.rows,
                end_state={**self.state, "baseline": self.key["end"]},
                predecessor=None,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.catalog.db.execute("DELETE FROM checkpoint")

    def test_holdout_is_refused_before_loading_and_SQL_cannot_bypass(self):
        with patch("research.validation_batch.load_development") as loader:
            with self.assertRaisesRegex(ValueError, "sealed"):
                run(
                    self.catalog,
                    self.identity,
                    "absent",
                    "pullback-h1-v1",
                    "EUR_USD",
                    datetime(2025, 1, 6, tzinfo=UTC),
                    datetime(2025, 1, 7, tzinfo=UTC),
                )
            loader.assert_not_called()
        key = {**self.key, "start": "2025-01-06T00:00:00+00:00", "end": "2025-01-07T00:00:00+00:00"}
        body = {
            "schema": "phase55/checkpoint-v1",
            "registration": self.identity,
            "key": key,
            "rows": [],
            "end_state": self.state,
            "predecessor": None,
        }
        with self.assertRaises(sqlite3.IntegrityError):
            self.catalog.db.execute(
                "INSERT INTO checkpoint VALUES (?,?,?,?)",
                (identity_digest(key), self.identity, canonical_json(body), identity_digest(body)),
            )

    def test_missing_predecessor_and_population_refuse(self):
        key = {**self.key, "start": self.key["end"], "end": "2019-01-09T00:00:00+00:00"}
        with self.assertRaises(sqlite3.IntegrityError):
            self.catalog.checkpoint(
                key,
                [{**self.rows[0], "opportunity": "2019-01-08T22:00:00+00:00"}],
                end_state=self.state,
                predecessor=None,
            )
        with self.assertRaisesRegex(ValueError, "population"):
            self.catalog.checkpoint(
                {**self.key, "instrument": "BTC_USD"}, [], end_state=self.state, predecessor=None
            )

    def test_omitted_opportunities_and_incomplete_report_refuse(self):
        from research.validation_reports import saved_rows

        with self.assertRaises(sqlite3.IntegrityError):
            self.catalog.checkpoint(self.key, [], end_state=self.state, predecessor=None)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            list(saved_rows(self.catalog, self.identity, "carry-readiness-v1", "EUR_USD"))

    def test_blocked_batch_restarts_without_reading_prices(self):
        start = datetime(2019, 1, 7, tzinfo=UTC)
        with patch("research.validation_batch.series_for") as prices:
            first = run(
                self.catalog,
                self.identity,
                "absent",
                "carry-readiness-v1",
                "EUR_USD",
                start,
                start + timedelta(days=2),
            )
            again = run(
                self.catalog,
                self.identity,
                "absent",
                "carry-readiness-v1",
                "EUR_USD",
                start,
                start + timedelta(days=2),
            )
            self.assertEqual(first, again)
            rows = [
                json.loads(b[0])
                for b in self.catalog.db.execute(
                    "SELECT body FROM checkpoint ORDER BY json_extract(body,'$.key.start')"
                )
            ]
            self.assertEqual([len(b["rows"]) for b in rows], [1, 1])
            self.assertEqual(
                rows[0]["rows"][0]["scenarios"]["baseline"]["reason"],
                "pit_forwards_financing_rollover_ranking_unavailable",
            )
            prices.assert_not_called()

    def test_concurrent_identical_workers_have_one_immutable_checkpoint(self):
        from concurrent.futures import ThreadPoolExecutor

        def worker():
            catalog = Catalog(self.path)
            try:
                return catalog.checkpoint(
                    self.key, self.rows, end_state=self.state, predecessor=None
                )
            finally:
                catalog.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            identities = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(identities[0], identities[1])
        self.assertEqual(
            self.catalog.db.execute("SELECT count(*) FROM checkpoint").fetchone()[0], 1
        )

    def test_failed_insert_rolls_back_and_retry_works(self):
        def authorizer(action, table, *_):
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and table == "checkpoint"
                else sqlite3.SQLITE_OK
            )

        self.catalog.db.set_authorizer(authorizer)
        with self.assertRaises(sqlite3.DatabaseError):
            self.catalog.checkpoint(self.key, self.rows, end_state=self.state, predecessor=None)
        self.catalog.db.set_authorizer(None)
        self.assertEqual(
            self.catalog.db.execute("SELECT count(*) FROM checkpoint").fetchone()[0], 0
        )
        self.catalog.checkpoint(self.key, self.rows, end_state=self.state, predecessor=None)
