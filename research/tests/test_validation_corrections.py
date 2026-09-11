"""Adversarial review reproductions; synthetic data only, never sealed prices."""

import copy
import json
import sqlite3
import unittest
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

    def fixture(self):
        fixture = fixtures.CatalogTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
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

    def test_r4_daily_exposure_mapping_exists(self):
        self.assertIsNotNone(getattr(validation_batch, "forecast_step", None))

    def test_r5_canonical_round_trip_keeps_english_bytes(self):
        body = validation_reports.report(
            "carry-readiness-v1",
            "EUR_USD",
            [],
            "synthetic",
            ("baseline", "adverse_cost", "extra_interval_latency"),
        )
        self.assertEqual(
            validation_reports.plain_english(body),
            validation_reports.plain_english(json.loads(canonical_json(body))),
        )
