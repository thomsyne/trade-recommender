"""Synthetic/disposable tests; no strategy result from acquired candles is read."""

import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

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
    def test_standalone_liquidity_descriptor_registry_has_no_ORM_backend(self):
        script = """
from datetime import UTC, datetime
from unittest.mock import patch
from django.conf import settings
from research.validation_replay import ReplayInput, Series
from research.tests.test_validation_engine import candle
from market.state import liquidity
assert not settings.configured
at = datetime(2020, 1, 6, 10, tzinfo=UTC)
series = Series([candle(at)])
def descriptor(bars, *args):
    event = {'available_at': bars[0].end.isoformat()}
    liquidity._lifecycle(event, bars, 0, 0, bars[0].close, 'above')
    assert event['status'] == 'confirmed'
    assert event['expiry_intervals'] == 50
    return event
with patch.object(liquidity, 'liquidity_context', descriptor):
    value = ReplayInput('USD_CAD', series.bars[0].end,
                        {'H1': series}, 'phase5-sweep-reversal-v1').payload
assert value['granularities']['H1']['liquidity']['status'] == 'confirmed'
assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.dummy'
"""
        env = dict(os.environ)
        env.pop("DJANGO_SETTINGS_MODULE", None)
        result = subprocess.run(
            [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_report_accounts_costs_overlap_and_missingness_independently(self):
        from decimal import Decimal as D

        from research.validation_reports import summarize

        rows = []
        for instrument in ("USD_CAD", "AUD_CAD"):
            result = simulate(
                self.setup,
                instrument,
                Series([candle(self.at, high="105", low="97")]),
                {},
                self.registration,
                "baseline",
            )
            rows.append(
                {
                    "instrument": instrument,
                    "session": "regular_fx",
                    "opportunity": self.at.isoformat(),
                    "scenarios": {"baseline": result},
                }
            )
        rows.append(
            {"scenarios": {"baseline": {"state": "unavailable", "reason": "missing_calendar"}}}
        )
        result = summarize(rows, "baseline", accounts=2)
        self.assertEqual(result["planned_opportunities"], 3)
        self.assertEqual(result["eligible_opportunities"], 2)
        self.assertEqual(D(result["money"]["net_CAD"]), D("-1300.10"))
        self.assertEqual(D(result["money"]["commission_CAD"]), D("0.10"))
        self.assertEqual(D(result["diagnostic_net_account_return"]), D("-0.0065005"))
        self.assertIsNone(result["full_population_net_account_return"])
        self.assertEqual(result["effective_week_units"], 1)
        self.assertEqual(result["concurrent_positions_peak"], 2)
        self.assertEqual(result["overlapping_currency_trade_pairs"], 1)
        self.assertEqual(D(result["realized_drawdown_CAD"]), D("1300.10"))

    def test_atomic_report_publication_refuses_conflicts_and_recovers(self):
        from research.validation_reports import publish_immutable

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch(
                "research.validation_reports.os.link", side_effect=OSError("synthetic interruption")
            ):
                with self.assertRaises(OSError):
                    publish_immutable(path, "first")
            self.assertFalse(path.exists())
            publish_immutable(path, "first")
            publish_immutable(path, "first")
            with self.assertRaisesRegex(ValueError, "immutable_report_conflict"):
                publish_immutable(path, "second")
            self.assertEqual(path.read_text(), "first")
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["report.json"])

    def test_loader_skips_sealed_blobs_and_refuses_changed_manifest(self):
        from research.validation_data import load_development

        records = {
            name: {
                "metadata_sha256": name,
                "request": {"period": period, "instrument": "EUR_USD", "granularity": "H1"},
                "acquired_at": "2026-09-11T00:00:00+00:00",
            }
            for name, period in (("sealed", "sealed_first"), ("allowed", "development"))
        }
        manifest = {key: value["metadata_sha256"] for key, value in records.items()}

        def blob(_, key, __):
            self.assertEqual(key, "allowed")
            return [{"timestamp": "2020-01-06T01:00:00+00:00"}]

        with (
            patch("research.validation_data.connect", return_value=Mock()),
            patch("research.validation_data.metadata", return_value=("synthetic", records)),
            patch("research.validation_data._verified_blob", side_effect=blob) as read,
        ):
            rows = load_development("unused", manifest, "EUR_USD", "H1")
            self.assertEqual(len(rows), 1)
            self.assertEqual(read.call_count, 1)
            read.reset_mock()
            with self.assertRaisesRegex(ValueError, "manifest_mismatch"):
                load_development("unused", {}, "EUR_USD", "H1")
            read.assert_not_called()


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
                "session": "regular_fx",
                "decision": {
                    "schema": "phase55/readiness-v1",
                    "reason": "pit_forwards_financing_rollover_ranking_unavailable",
                },
                "volatility_stratum": "unavailable",
                "overlays": {
                    s: {"multiplier": None, "reason": "baseline_has_no_setup"}
                    for s in ("fixed-risk-v1", "ewma-risk-v1", "garch-t-risk-v1", "macro-risk-v1")
                },
                "scenarios": {
                    s: {
                        "state": "unavailable",
                        "reason": "pit_forwards_financing_rollover_ranking_unavailable",
                    }
                    for s in self.state
                },
            }
        ]
        self.rows[0]["overlays"]["macro-risk-v1"]["reason"] = (
            "mandatory_pit_event_vintages_unavailable"
        )
        self.rows[0]["evaluation_identity"] = identity_digest(
            {
                "registration": self.identity,
                **{
                    k: self.rows[0][k]
                    for k in ("opportunity", "instrument", "strategy", "decision")
                },
            }
        )

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
        with self.assertRaisesRegex(sqlite3.IntegrityError, "semantic"):
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
        row = {**self.rows[0], "opportunity": "2019-01-08T22:00:00+00:00"}
        row["evaluation_identity"] = identity_digest(
            {
                "registration": self.identity,
                **{k: row[k] for k in ("opportunity", "instrument", "strategy", "decision")},
            }
        )
        with self.assertRaisesRegex(ValueError, "chain_incomplete"):
            self.catalog.checkpoint(
                key,
                [row],
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

    def test_modeled_row_admission_accepts_finite_loss_and_refuses_nan(self):
        from decimal import Decimal as D

        from market.strategy.contracts import encoded
        from market.strategy.setups import candidate
        from research.validation_batch import day_rows

        strategy = "orb-m15-wick-v1:london"
        at = datetime(2019, 1, 7, 8, 30, tzinfo=UTC)

        def m15(at, **prices):
            return {
                **candle(at, **prices),
                "granularity": "M15",
                "end": (at + timedelta(minutes=15)).isoformat(),
            }

        signal = Series([m15(at - timedelta(minutes=15))]).bars[0]
        setup = json.loads(
            encoded(
                candidate(
                    strategy, signal, 1, D("98"), target=D("106"), exit_at=at + timedelta(hours=3)
                )
            )
        )
        output = {
            "schema": "phase5/evaluation-v1",
            "strategy": strategy,
            "outputs": [setup],
            "activation": "forbidden",
        }
        data = {"M15": Series([m15(at, high="107", low="97")])}
        for mocked in (
            patch("research.validation_batch.selection", return_value=(output, setup)),
            patch("research.validation_batch.data_for", return_value=(data, {})),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)
        active = dict(self.state)
        with patch("research.validation_batch.selection", return_value=(output, setup)):
            rows = day_rows(
                self.identity,
                self.body,
                strategy,
                "USD_CAD",
                at.replace(hour=0, minute=0),
                {"M15": Series([m15(at, high="107", low="97")])},
                {},
                active,
            )
        self.assertEqual(rows[0]["scenarios"]["baseline"]["state"], "modeled")
        self.assertLess(D(rows[0]["scenarios"]["baseline"]["net_CAD"]), 0)
        key = {**self.key, "strategy": strategy, "instrument": "USD_CAD"}
        invalid = copy.deepcopy(rows)
        result = invalid[0]["scenarios"]["baseline"]
        result["net_CAD"] = "NaN"
        result["identity"] = identity_digest(
            {
                "setup": setup,
                "instrument": "USD_CAD",
                "scenario": "baseline",
                "result": {k: v for k, v in result.items() if k != "identity"},
            }
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.catalog.checkpoint(key, invalid, end_state=active, predecessor=None)
        self.catalog.checkpoint(key, rows, end_state=active, predecessor=None)

    def test_proposals_distinguish_missing_from_complete_negative_evidence(self):
        from research.validation_reports import development_proposal

        baseline = {
            "integrity_clean": True,
            "states": {},
            "effective_week_units": 52,
            "eligible_opportunities": 100,
            "trades": 30,
            "usable_instruments": 3,
            "money": {"net_CAD": "100"},
            "remove_best_instrument_net_CAD": "40",
            "remove_best_month_net_CAD": "60",
            "halves": [{"effective_weeks": 26, "net_CAD": "50"}] * 2,
            "concentration": {"instrument": "0.4", "UTC_month": "0.3"},
        }
        body = {
            "strategy": "orb-m15-fvg-v1:london",
            "scenarios": {s: copy.deepcopy(baseline) for s in self.state},
            "paired_comparator": {
                s: {"unavailable_or_unmatched": 0, "total_increment_CAD": "1"} for s in self.state
            },
        }
        self.assertEqual(
            development_proposal(body, self.body)["proposal"],
            "candidate_for_independent_review_not_retained",
        )
        body["scenarios"]["adverse_cost"]["money"]["net_CAD"] = "0"
        self.assertEqual(development_proposal(body, self.body)["proposal"], "reject")
        body["scenarios"]["adverse_cost"]["states"]["unavailable"] = 1
        self.assertEqual(development_proposal(body, self.body)["proposal"], "inconclusive")
        body["scenarios"]["adverse_cost"]["states"].clear()
        body["scenarios"]["adverse_cost"]["money"]["net_CAD"] = "100"
        body["paired_comparator"]["baseline"]["total_increment_CAD"] = "-1"
        self.assertEqual(development_proposal(body, self.body)["proposal"], "reject")
        body["paired_comparator"]["baseline"]["unavailable_or_unmatched"] = 1
        self.assertEqual(development_proposal(body, self.body)["proposal"], "inconclusive")

    def test_shadow_time_gate_and_retrospective_type_refusal(self):
        from market.strategy.contracts import SnapshotInput
        from research.validation_batch import forward_shadow

        # Exercise the forward wrapper's time/type gates independently of the
        # existing Phase4 snapshot verifier, covered by its original tests.
        with patch.object(SnapshotInput, "__post_init__"):

            def snapshot(at, bars=()):
                return SnapshotInput(
                    1,
                    canonical_json(
                        {
                            "idempotency_key": "synthetic",
                            "output_payload": {
                                "information_cutoff": at.isoformat(),
                                "instrument": "EUR_USD",
                            },
                        }
                    ),
                    bars,
                )

            cutoff = datetime(2026, 9, 11, tzinfo=UTC)
            result = forward_shadow(self.body, snapshot(cutoff), "carry-readiness-v1")
            self.assertIsNone(result["execution"]["net_CAD"])
            self.assertEqual(result["activation"], "forbidden")
            with patch("research.validation_batch.evaluate") as evaluate:
                with self.assertRaisesRegex(ValueError, "future_unregistered"):
                    forward_shadow(
                        self.body,
                        snapshot(datetime.now(UTC) + timedelta(days=1)),
                        "carry-readiness-v1",
                    )
                with self.assertRaisesRegex(ValueError, "future_unregistered"):
                    forward_shadow(
                        self.body, snapshot(datetime(2025, 1, 6, tzinfo=UTC)), "carry-readiness-v1"
                    )
                with self.assertRaisesRegex(ValueError, "retrospective"):
                    forward_shadow(
                        self.body,
                        snapshot(cutoff, Series([candle(cutoff - timedelta(hours=1))]).bars),
                        "carry-readiness-v1",
                    )
                evaluate.assert_not_called()
            with self.assertRaisesRegex(ValueError, "same_snapshot_baseline"):
                forward_shadow(self.body, snapshot(cutoff), "fixed-risk-v1")
