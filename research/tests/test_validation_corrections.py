"""Adversarial review reproductions; synthetic data only, never sealed prices."""

import copy
import json
import sqlite3
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import Mock, patch

import research.tests.test_validation_engine as fixtures
from market.state.canonical import canonical_json, identity_digest
from research import validation_batch, validation_data, validation_reports
from research.validation_registration import Catalog


class ReviewReproductions(unittest.TestCase):
    def test_r1_audit_never_requests_sealed_blob(self):
        records = {
            "sentinel": {
                "request": {
                    "period": "sealed_first",
                    "instrument": "EUR_USD",
                    "granularity": "H1",
                },
                "acquired_at": "2026-09-11T00:00:00+00:00",
            }
        }
        with (
            patch.object(validation_data, "connect", return_value=Mock()),
            patch.object(validation_data, "metadata", return_value=("unregistered", records)),
            patch.object(
                validation_data, "_verified_blob", side_effect=AssertionError("BLOB_READ")
            ) as blob,
        ):
            with self.assertRaises(ValueError):
                validation_data.audit_cache("synthetic")
            blob.assert_not_called()

    def test_r1_sql_authorizer_and_decompression_denial(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE chunk (blob BLOB)")
        db.execute("INSERT INTO chunk VALUES ('SECRET_PRICE_SENTINEL')")
        with (
            patch.object(validation_data, "connect", return_value=db),
            patch.object(
                validation_data,
                "metadata",
                side_effect=lambda c: c.execute("SELECT blob FROM chunk").fetchall(),
            ),
            patch.object(
                validation_data.gzip, "decompress", side_effect=AssertionError("DECOMPRESS")
            ) as decompress,
        ):
            with self.assertRaisesRegex(ValueError, "^frozen_coverage_metadata_unavailable$"):
                validation_data.audit_cache("synthetic")
            decompress.assert_not_called()

    def test_r1_seal_precedes_any_sql_and_sanitizes_errors(self):
        for request in (
            {
                "period": "sealed_first",
                "start": "2025-01-06T00:00:00+00:00",
                "end": "2025-02-01T00:00:00+00:00",
            },
            {
                "period": "development",
                "start": "2025-01-06T00:00:00+00:00",
                "end": "2025-02-01T00:00:00+00:00",
            },
            {"period": "development", "start": "SECRET_PRICE_SENTINEL"},
        ):
            db = Mock()
            with self.assertRaisesRegex(ValueError, "^sealed_or_invalid_blob_request$"):
                validation_data._verified_blob(db, "sentinel", {"request": request})
            db.execute.assert_not_called()
        with patch.object(
            validation_data,
            "connect",
            side_effect=sqlite3.OperationalError("SECRET_PRICE_SENTINEL"),
        ):
            with self.assertRaisesRegex(ValueError, "^frozen_coverage_metadata_unavailable$"):
                validation_data.audit_cache("synthetic")

    def test_r1_relabelled_key_cannot_select_blob(self):
        db = Mock()
        db.execute.return_value.fetchone.return_value = (
            canonical_json({"registration": "synthetic", "request": {"period": "sealed_second"}}),
            "invalid",
        )
        meta = {
            "request": {
                "period": "development",
                "start": "2019-01-07T00:00:00+00:00",
                "end": "2019-02-01T00:00:00+00:00",
            }
        }
        with self.assertRaisesRegex(ValueError, "^blob_metadata_identity_mismatch$"):
            validation_data._verified_blob(db, "sealed-key", meta)
        self.assertEqual(db.execute.call_count, 1)
        self.assertNotIn("SELECT blob", db.execute.call_args.args[0])

    def fixture(self):
        fixture = fixtures.CatalogTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.addCleanup(fixture.doCleanups)
        return fixture

    def insert_mutation(self, fixture, body):
        catalog = Catalog(Path(fixture.directory.name) / "attack.sqlite3")
        self.addCleanup(catalog.close)
        catalog.register(fixture.audit)
        with self.assertRaises(sqlite3.IntegrityError):
            catalog.db.execute(
                "INSERT INTO checkpoint VALUES (?,?,?,?)",
                (
                    identity_digest(body["key"]),
                    body["registration"],
                    canonical_json(body),
                    identity_digest(body),
                ),
            )
        catalog.db.rollback()

    def test_r2_rehashed_carry_no_setup_and_forged_state(self):
        f = self.fixture()
        rows = copy.deepcopy(f.rows)
        for result in rows[0]["scenarios"].values():
            result.update(state="no_setup", reason="invented_safe")
        self.insert_mutation(
            f,
            {
                "schema": "phase55/checkpoint-v1",
                "registration": f.identity,
                "key": f.key,
                "rows": rows,
                "predecessor": None,
                "end_state": {s: "2020-01-01T00:00:00+00:00" for s in f.state},
            },
        )

    def modeled(self):
        f = self.fixture()
        f.test_modeled_row_admission_accepts_finite_loss_and_refuses_nan()
        body = json.loads(f.catalog.db.execute("SELECT body FROM checkpoint").fetchone()[0])
        return f, body

    def test_r2_rehashed_loss_changed_to_no_setup(self):
        f, body = self.modeled()
        body["rows"][0]["scenarios"]["baseline"] = {"state": "no_setup", "reason": "hidden_loss"}
        self.insert_mutation(f, body)

    def test_r2_rehashed_false_profit(self):
        f, body = self.modeled()
        row = body["rows"][0]
        result = row["scenarios"]["baseline"]
        result["net_CAD"] = "999999"
        result["identity"] = identity_digest(
            {
                "setup": row["decision"]["outputs"][0],
                "instrument": body["key"]["instrument"],
                "scenario": "baseline",
                "result": {k: v for k, v in result.items() if k != "identity"},
            }
        )
        self.insert_mutation(f, body)

    def test_r2_balanced_profit_and_cross_attribution_time_are_refused(self):
        f, original = self.modeled()
        for field, value in (
            ("session", "new_york"),
            ("instrument", "EUR_USD"),
            ("strategy", "pullback-h1-v1"),
            ("opportunity", "2019-01-07T08:00:00-01:00"),
        ):
            body = copy.deepcopy(original)
            body["rows"][0][field] = value
            self.insert_mutation(f, body)
        body = copy.deepcopy(original)
        result = body["rows"][0]["scenarios"]["baseline"]
        result["gross_CAD"] = str(D(result["gross_CAD"]) + 999999)
        result["net_CAD"] = str(D(result["net_CAD"]) + 999999)
        result["net_account_return"] = str(D(result["net_CAD"]) / 100000)
        result["identity"] = identity_digest(
            {
                "setup": body["rows"][0]["decision"]["outputs"][0],
                "instrument": "USD_CAD",
                "scenario": "baseline",
                "result": {k: v for k, v in result.items() if k != "identity"},
            }
        )
        self.insert_mutation(f, body)

    def test_r2_cached_and_fresh_resume_reject_forged_ancestor(self):
        f = self.fixture()
        start = datetime(2019, 1, 7, tzinfo=UTC)
        validation_batch.run(
            f.catalog,
            f.identity,
            "absent",
            "carry-readiness-v1",
            "EUR_USD",
            start,
            start + timedelta(days=2),
        )
        # Deliberately bypass immutability as a corruption fixture, not admission.
        text = f.catalog.db.execute(
            "SELECT body FROM checkpoint WHERE identity=?", (identity_digest(f.key),)
        ).fetchone()[0]
        original = json.loads(text)
        for field, value in (
            ("predecessor", identity_digest(original)),
            ("end_state", {s: "2024-01-01T00:00:00+00:00" for s in f.state}),
            ("rows", []),
        ):
            body = {**original, field: value}
            f.catalog.db.execute("DROP TRIGGER IF EXISTS checkpoint_UPDATE")
            f.catalog.db.execute(
                "UPDATE checkpoint SET body=?,body_sha256=? WHERE identity=?",
                (canonical_json(body), identity_digest(body), identity_digest(f.key)),
            )
            f.catalog.db.commit()
            for catalog in (f.catalog, Catalog(f.path)):
                try:
                    with self.assertRaises(ValueError):
                        validation_batch.run(
                            catalog,
                            f.identity,
                            "absent",
                            "carry-readiness-v1",
                            "EUR_USD",
                            start + timedelta(days=2),
                            start + timedelta(days=3),
                        )
                finally:
                    if catalog is not f.catalog:
                        catalog.close()

    def test_r2_legitimate_active_state_is_replayed_not_reset(self):
        f, first = self.modeled()
        # Same synthetic setup remains validly reserved into the next day's
        # session when execution accounting is unavailable at its horizon.
        setup = copy.deepcopy(first["rows"][0]["decision"]["outputs"][0])
        setup["exit_at"] = "2019-01-09T10:00:00.000000+00:00"
        decision = {**first["rows"][0]["decision"], "outputs": [setup]}
        path = Path(f.directory.name) / "active.sqlite3"
        with (
            patch.object(validation_batch, "selection", return_value=(decision, setup)),
            patch(
                "research.validation_batch.simulate",
                return_value={"state": "unavailable", "reason": "outcome_interval_gap"},
            ),
        ):
            c = Catalog(path)
            c.register(f.audit)
            start = datetime(2019, 1, 7, tzinfo=UTC)
            validation_batch.run(
                c,
                f.identity,
                "synthetic",
                "orb-m15-wick-v1:london",
                "USD_CAD",
                start,
                start + timedelta(days=1),
            )
            c.close()
            c = Catalog(path)
            self.addCleanup(c.close)
            validation_batch.run(
                c,
                f.identity,
                "synthetic",
                "orb-m15-wick-v1:london",
                "USD_CAD",
                start + timedelta(days=1),
                start + timedelta(days=2),
            )
            rows, state, _ = c.verify_chain(
                f.identity, "orb-m15-wick-v1:london", "USD_CAD", stop=start + timedelta(days=2)
            )
            self.assertEqual(
                rows[1]["scenarios"]["baseline"],
                {"state": "occupied", "reason": "prior_position_active"},
            )
            self.assertEqual(state["baseline"], setup["exit_at"])

    def test_r3_arbitrary_rows_cannot_certify_report(self):
        f, body = self.modeled()
        with self.assertRaises((ValueError, TypeError)):
            validation_reports.report(
                "orb-m15-fvg-v1:new_york",
                "EUR_USD",
                body["rows"],
                "invented-registration",
                f.body["scenarios"],
            )

    def test_r3_population_completeness_and_labels_are_derived(self):
        f = self.fixture()
        for strategy, instrument, baseline in (
            ("carry-readiness-v1", "EUR_USD", None),
            ("carry-readiness-v1", "aggregate", None),
            ("fixed-risk-v1", "EUR_USD", "carry-readiness-v1"),
            ("orb-m15-fvg-v1:new_york", "EUR_USD", None),
        ):
            with self.assertRaisesRegex(ValueError, "incomplete"):
                validation_reports.report(
                    f.catalog, f.identity, strategy, instrument, baseline=baseline
                )
        for extra in (
            {"accounts": 1},
            {"rows": []},
            {"session": "new_york"},
            {"timeframe": "H1"},
            {"period": "holdout"},
            {"era": "old"},
        ):
            with self.assertRaises(TypeError):
                validation_reports.report(
                    f.catalog, f.identity, "carry-readiness-v1", "EUR_USD", **extra
                )
        with self.assertRaises(ValueError):
            validation_reports.report(f.catalog, "made-up", "carry-readiness-v1", "EUR_USD")
        with self.assertRaises(ValueError):
            validation_reports.report(
                f.catalog, f.identity, "fixed-risk-v1", "EUR_USD", baseline="macro-risk-v1"
            )

    def test_r3_complete_verified_report_and_corrupt_population_refusal(self):
        from research import validation_registration

        # Disposable two-day protocol, never the real registered population.
        with patch.object(
            validation_registration,
            "DEVELOPMENT",
            ("2019-01-07T00:00:00+00:00", "2019-01-09T00:00:00+00:00"),
        ):
            f = self.fixture()
            start, end = map(datetime.fromisoformat, f.body["development"])
            validation_batch.run(
                f.catalog, f.identity, "absent", "carry-readiness-v1", "EUR_USD", start, end
            )
            report = validation_reports.report(
                f.catalog, f.identity, "carry-readiness-v1", "EUR_USD"
            )
            self.assertEqual(report["scenarios"]["baseline"]["planned_opportunities"], 2)
            self.assertEqual(report["account_allocation"]["independent_CAD_accounts"], 1)
            self.assertEqual(report["timeframe"], "D")
            self.assertEqual(report["session"], "regular_fx")
            self.assertEqual(report["period_bounds"], f.body["development"])
            self.assertEqual(report["checkpoint_bindings"][0]["daily_checkpoints"], 2)
            destination = Path(f.directory.name) / "reports"
            published = validation_reports.export_report(
                f.catalog, f.identity, "carry-readiness-v1", "EUR_USD", destination
            )
            self.assertEqual(published, report["identity"])
            loaded = json.loads((destination / f"{published}.json").read_text())
            self.assertEqual(
                (destination / f"{published}.txt").read_text(),
                validation_reports.plain_english(loaded),
            )
            original = f.catalog.db.execute("SELECT * FROM checkpoint ORDER BY identity").fetchall()
            f.catalog.db.execute("DROP TRIGGER checkpoint_DELETE")
            f.catalog.db.execute("DROP TRIGGER checkpoint_identity")
            for kind in ("omit", "duplicate", "outside_period", "ancestor", "cross_family"):
                f.catalog.db.execute("DELETE FROM checkpoint")
                f.catalog.db.executemany("INSERT INTO checkpoint VALUES (?,?,?,?)", original)
                identity, registration, text, digest = original[0]
                body = json.loads(text)
                if kind in ("omit", "outside_period", "ancestor", "cross_family"):
                    f.catalog.db.execute("DELETE FROM checkpoint WHERE identity=?", (identity,))
                if kind == "duplicate":
                    f.catalog.db.execute(
                        "INSERT INTO checkpoint VALUES (?,?,?,?)",
                        ("duplicate", registration, text, digest),
                    )
                elif kind != "omit":
                    if kind == "outside_period":
                        body["key"]["start"] = "2019-01-09T00:00:00+00:00"
                    elif kind == "ancestor":
                        body["predecessor"] = digest
                    else:
                        body["rows"][0]["strategy"] = "pullback-h1-v1"
                    f.catalog.db.execute(
                        "INSERT INTO checkpoint VALUES (?,?,?,?)",
                        (identity, registration, canonical_json(body), identity_digest(body)),
                    )
                f.catalog.db.commit()
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    validation_reports.report(
                        f.catalog, f.identity, "carry-readiness-v1", "EUR_USD"
                    )

    def test_r4_daily_exposure_mapping_exists(self):
        self.assertIsNotNone(getattr(validation_batch, "forecast_step", None))

    def test_r4_asymmetric_mapping_buffer_turnover_and_resume(self):
        from market.strategy.contracts import Component
        from market.strategy.trend import combine
        from research.validation_replay import Series

        f = self.fixture()

        def bars(day):
            at = datetime(2019, 1, day, 22, tzinfo=UTC)
            return Series(
                [
                    {
                        **fixtures.candle(at, close="100"),
                        "granularity": "D",
                        "end": (at + timedelta(days=1)).isoformat(),
                    }
                ]
            ).bars

        for strategy, formula, initial, expected in (
            ("ewmac-d-v1", "ewmac", "11", "62.5"),
            ("breakout-d-v1", "breakout", "-7", "-37.5"),
        ):
            target = D(initial)

            def decision(*args, previous, **kwargs):
                return combine(strategy, [Component("synthetic", target, target, None)], previous)

            with (
                patch.object(validation_batch, formula, side_effect=decision) as calculate,
                patch.object(validation_batch, "sigma", return_value=D(2)),
            ):

                def step(day, previous=None, scenario="baseline", spread=D("0.2")):
                    return validation_batch.forecast_step(
                        strategy,
                        "USD_CAD",
                        bars(day),
                        costs={},
                        cutoff=bars(day)[-1].end,
                        registration=f.body,
                        scenario=scenario,
                        conversion_rate=D(2),
                        execution_spread=spread,
                        previous=previous,
                    )

                first, state = step(7)
                self.assertEqual(D(first["baseline_units_cap"]), 125)
                self.assertEqual(D(state["units"]), D(expected))
                self.assertEqual(state["execute_at"], "2019-01-08T22:00:00+00:00")
                self.assertEqual(D(first["spread_CAD"]), abs(D(expected)) * D("0.2"))
                self.assertEqual(D(first["commission_CAD"]), abs(D(expected)) * D("0.0001"))
                self.assertEqual(D(first["slippage_CAD"]), abs(D(expected)) * D("0.4"))
                adverse, _ = step(7, scenario="adverse_cost")
                self.assertEqual(D(adverse["slippage_CAD"]), abs(D(expected)) * D("0.8"))
                self.assertEqual(D(adverse["commission_CAD"]), abs(D(expected)) * D("0.0002"))
                missing, unchanged = step(7, spread=None)
                self.assertEqual(missing["state"], "unavailable")
                self.assertIsNone(unchanged)
                second, continued = step(8, json.loads(canonical_json(state)))
                self.assertEqual(D(second["units_change"]), 0)
                self.assertEqual(D(second["turnover_CAD"]), 0)
                for name in ("spread_CAD", "commission_CAD", "slippage_CAD"):
                    self.assertEqual(D(second[name]), 0)
                self.assertEqual((second, continued), step(8, state))
                target += D("0.01") if target > 0 else D("-0.01")
                third, _ = step(9, continued)
                self.assertEqual(abs(D(third["units_change"])), D("0.0625"))
                # Execution spread cannot resize the decision or change its buffer.
                wide, same = step(9, continued, spread=D(3))
                self.assertEqual(wide["units_change"], third["units_change"])
                self.assertEqual(same["buffered"], str(target - (1 if target > 0 else -1)))
                self.assertGreater(D(wide["slippage_CAD"]), D(third["slippage_CAD"]))
                late, late_state = step(7, scenario="extra_interval_latency")
                self.assertEqual(late_state["execute_at"], "2019-01-09T22:00:00+00:00")
                self.assertIsNone(late["financing_CAD"])
                self.assertGreater(calculate.call_count, 0)
                with self.assertRaisesRegex(ValueError, "predecessor"):
                    step(7, state)
                forged = {
                    **state,
                    "strategy": "breakout-d-v1" if strategy == "ewmac-d-v1" else "ewmac-d-v1",
                }
                forged["identity"] = identity_digest(
                    {k: v for k, v in forged.items() if k != "identity"}
                )
                with self.assertRaisesRegex(ValueError, "predecessor"):
                    step(8, forged)
                target = -D(initial)
                reversed_result, reversed_state = step(8, state)
                self.assertEqual(D(reversed_state["units"]), -D(expected))
                self.assertEqual(abs(D(reversed_result["units_change"])), 2 * abs(D(expected)))
                with patch.object(validation_batch, "sigma", return_value=D("0.01")):
                    capped, _ = step(7)
                    self.assertEqual(D(capped["baseline_units_cap"]), 500)

    def test_r4_real_financing_gate_reads_no_prices_for_either_identity(self):
        f = self.fixture()
        for strategy in ("ewmac-d-v1", "breakout-d-v1"):
            with patch.object(
                validation_batch, "series_for", side_effect=AssertionError("PRICE_READ")
            ):
                self.assertEqual(
                    validation_batch.data_for("absent", f.body, strategy, "EUR_USD"), ({}, {})
                )
                output, setup = validation_batch.selection(
                    strategy, "EUR_USD", datetime(2019, 1, 7, 22, tzinfo=UTC), {}
                )
                self.assertIsNone(setup)
                self.assertEqual(output["reason"], "genuine_financing_rollover_unavailable")

    def test_r5_canonical_round_trip_keeps_english_bytes(self):
        # Pure renderer fixture, not a verified publication or an outcome claim.
        body = {
            "strategy": "carry-readiness-v1",
            "instrument": "EUR_USD",
            "session": "regular_fx",
            "proposal": "inconclusive",
            "baseline_identity": None,
            "validation_revision": 3,
            "registration": "synthetic",
            "scenarios": {
                s: validation_reports.summarize([], s)
                for s in ("baseline", "adverse_cost", "extra_interval_latency")
            },
        }
        self.assertEqual(
            validation_reports.plain_english(body),
            validation_reports.plain_english(json.loads(canonical_json(body))),
        )
