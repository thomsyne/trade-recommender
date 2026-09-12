"""Discriminating artifact checks; no acquired data, DB service or simulation."""

import sqlite3
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from market.state.canonical import canonical_json, identity_digest
from research.validation_reconciliation import differences, numeric_equal, read_reports
from research.validation_reconciliation_checkpoints import scan
from research.validation_reconciliation_metrics import check_populations, dependence, week


class ReportReconciliationTests(unittest.TestCase):
    def test_fvg_pairing_uses_same_session_not_self_or_unavailable_zero(self):
        rows = []
        for source, net in (("orb-m15-fvg-v1:london", "-7"), ("orb-m15-confirmed-v1:london", "3")):
            for day, result in (
                ("07", {"state": "modeled", "net_CAD": net}),
                ("08", {"state": "unavailable", "reason": "missing"}),
            ):
                rows.append(
                    {
                        "strategy": source,
                        "instrument": "EUR_USD",
                        "session": "london",
                        "opportunity": f"2019-01-{day}T08:00:00+00:00",
                        "scenarios": {"baseline": result},
                        "overlays": {
                            v: {"multiplier": "1", "reason": "missing"}
                            for v in (
                                "fixed-risk-v1",
                                "ewma-risk-v1",
                                "garch-t-risk-v1",
                                "macro-risk-v1",
                            )
                        },
                    }
                )
        report = {
            "scenarios": {
                "baseline": {
                    "states": {"modeled": 1, "unavailable": 1},
                    "unavailable_reasons": {"missing": 1},
                }
            },
            "paired_comparator": {
                "baseline": {
                    "matched_opportunities": 1,
                    "unavailable_or_unmatched": 1,
                    "paired_UTC_week_increment_CAD": {"2019-W02": "-10"},
                    "total_increment_CAD": "-10",
                }
            },
        }
        reports = {("orb-m15-fvg-v1:london", "EUR_USD", None): report}
        check_populations(reports, rows)
        changed = deepcopy(reports)
        changed[next(iter(changed))]["paired_comparator"]["baseline"]["total_increment_CAD"] = "0"
        with self.assertRaisesRegex(ValueError, "numeric"):
            check_populations(changed, rows)
        with self.assertRaisesRegex(ValueError, "duplicate_paired"):
            check_populations(reports, [*rows, rows[0]])
        rows[2]["session"] = "new_york"
        with self.assertRaisesRegex(ValueError, "same_session"):
            check_populations(reports, rows)

    def test_iso_week_and_transitive_exposure_groups(self):
        self.assertEqual(week("2021-01-01T23:00:00+00:00"), "2020-W53")
        trades = [
            {"entered_at": "2020-12-28T00:00:00+00:00", "exited_at": "2021-01-04T01:00:00+00:00"},
            {"entered_at": "2021-01-10T23:00:00+00:00", "exited_at": "2021-01-11T01:00:00+00:00"},
            {"entered_at": "2021-02-01T01:00:00+00:00", "exited_at": "2021-02-01T02:00:00+00:00"},
        ]
        self.assertEqual(dependence(trades), (2, ["2020-W53", "2021-W01", "2021-W02", "2021-W05"]))
        self.assertEqual(dependence(list(reversed(trades))), dependence(trades))

    def test_rounding_does_not_hide_material_error_or_cancellation(self):
        self.assertEqual(numeric_equal("-13.25", D("-13.25"), 2, D("30")), 0)
        for actual, expected, scale in [
            ("13.25", D("-13.25"), D("30")),
            ("0.01", D(0), D(0)),
            ("1.001", D(1), D("100000")),
        ]:
            with self.subTest(actual=actual), self.assertRaisesRegex(ValueError, "numeric"):
                numeric_equal(actual, expected, 100, scale)
        self.assertGreater(numeric_equal("1.000000000000000000000000000000001", D(1), 2, D(1)), 0)

    def test_delta_preserves_sign_null_and_nested_reason(self):
        before = {"net": "-2", "halves": [{"trades": 3}], "reason": {"missing": 1}}
        after = {"net": "2", "halves": [{"trades": 4}], "reason": {"missing": None}}
        self.assertEqual(
            list(differences(before, after)),
            [
                {"path": "/halves/0/trades", "before": 3, "after": 4},
                {"path": "/net", "before": "-2", "after": "2"},
                {"path": "/reason/missing", "before": 1, "after": None},
            ],
        )

    def test_distinct_hashes_cannot_duplicate_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            for net in ("-2", "999999"):
                body = {
                    "strategy": "s",
                    "instrument": "EUR_USD",
                    "baseline_identity": None,
                    "net": net,
                }
                body["identity"] = identity_digest(body)
                (Path(directory) / (body["identity"] + ".json")).write_text(
                    canonical_json(body) + "\n"
                )
            with self.assertRaisesRegex(ValueError, "duplicate_attribution"):
                read_reports(directory)


class CheckpointReconciliationTests(unittest.TestCase):
    def fixture(self):
        registration = {
            "development": ["2019-01-07T00:00:00+00:00", "2019-01-09T00:00:00+00:00"],
            "research_equity_CAD": "100000",
        }
        rid = identity_digest(registration)
        key = {
            "registration": rid,
            "strategy": "carry-readiness-v1",
            "instrument": "EUR_USD",
            "start": registration["development"][0],
            "end": registration["development"][1],
        }
        key["end"] = "2019-01-08T00:00:00+00:00"
        decision = {"schema": "phase55/readiness-v1", "reason": "missing_financing"}
        row = {
            "opportunity": key["start"],
            "strategy": key["strategy"],
            "instrument": key["instrument"],
            "decision": decision,
            "scenarios": {
                s: {"state": "unavailable", "reason": "missing_financing"}
                for s in ("baseline", "adverse_cost", "extra_interval_latency")
            },
        }
        row["evaluation_identity"] = identity_digest(
            {
                "registration": rid,
                **{k: row[k] for k in ("opportunity", "strategy", "instrument", "decision")},
            }
        )
        body = {
            "key": key,
            "registration": rid,
            "predecessor": None,
            "rows": [row],
            "end_state": dict.fromkeys(row["scenarios"]),
        }
        return {"identity": rid, "body": registration}, body

    def inspect(self, frozen, body, *, acquisition=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.sqlite3"
            db = sqlite3.connect(path)
            db.executescript(
                "CREATE TABLE registration(identity TEXT,body TEXT); CREATE TABLE checkpoint(identity TEXT,registration_id TEXT,body TEXT,body_sha256 TEXT);"
            )
            db.execute(
                "INSERT INTO registration VALUES (?,?)",
                (frozen["identity"], canonical_json(frozen["body"])),
            )
            db.execute(
                "INSERT INTO checkpoint VALUES (?,?,?,?)",
                (
                    identity_digest(body["key"]),
                    frozen["identity"],
                    canonical_json(body),
                    identity_digest(body),
                ),
            )
            if acquisition:
                db.execute("CREATE TABLE chunk(blob BLOB)")
            db.commit()
            db.close()
            before = path.read_bytes()
            try:
                return scan(path, frozen)
            finally:
                self.assertEqual(before, path.read_bytes())

    def test_valid_unavailable_and_rehashed_no_setup(self):
        frozen, body = self.fixture()
        self.assertEqual(self.inspect(frozen, body)["checkpoints"], 1)
        body["rows"][0]["scenarios"]["baseline"]["state"] = "no_setup"
        with self.assertRaisesRegex(ValueError, "decision_state"):
            self.inspect(frozen, body)

    def test_expired_occupancy_compares_instants_not_timestamp_spelling(self):
        frozen, body = self.fixture()
        first = body["rows"][0]
        second = deepcopy(first)
        second["opportunity"] = "2019-01-07T00:15:00+00:00"
        horizon = "2019-01-07T00:15:00.000000+00:00"
        first["decision"] = {"outputs": [{"schema": "phase5/setup-v1", "exit_at": horizon}]}
        first.update(overlays={}, volatility_stratum="unavailable")
        body["rows"].append(second)
        for row in body["rows"]:
            row["evaluation_identity"] = identity_digest(
                {
                    "registration": frozen["identity"],
                    **{k: row[k] for k in ("opportunity", "strategy", "instrument", "decision")},
                }
            )
        body["end_state"] = dict.fromkeys(first["scenarios"], horizon)
        self.assertEqual(self.inspect(frozen, body)["chains"][0]["rows"], 2)

    def test_rehashed_end_state_and_missing_ancestor(self):
        frozen, body = self.fixture()
        changed = deepcopy(body)
        changed["end_state"]["baseline"] = "2019-01-08T12:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "end_state"):
            self.inspect(frozen, changed)
        body["predecessor"] = "invented"
        with self.assertRaisesRegex(ValueError, "chronology"):
            self.inspect(frozen, body)

    def test_non_evidence_database_and_sealed_period_refuse(self):
        frozen, body = self.fixture()
        with self.assertRaisesRegex(ValueError, "not_an_evidence_catalog"):
            self.inspect(frozen, body, acquisition=True)
        body["key"]["end"] = "2025-02-01T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "nondevelopment_catalog"):
            self.inspect(frozen, body)
        frozen["body"]["development"][1] = "2026-01-01T00:00:00+00:00"
        frozen["identity"] = identity_digest(frozen["body"])
        with patch(
            "research.validation_reconciliation_checkpoints.sqlite3.connect",
            side_effect=AssertionError("DB_READ"),
        ) as connect:
            with self.assertRaisesRegex(ValueError, "sealed_registration_period"):
                scan("never-open", frozen)
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
