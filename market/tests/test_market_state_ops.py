"""Phase 4 slice 8 — durable task, integrity report and dry-run CLIs."""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from market.models import MarketStateSnapshot
from market.services import store_ingestion
from market.state.compute import ensure_descriptor_definition
from market.state.integrity import verify_snapshots
from market.state.tasks import run_compute_market_state
from market.tests.factories import candle
from market.tests.test_live_observations import make_market

MON_0800 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


class IntegrityAndTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def store(self, starts, observed_at, batch):
        candles = [candle(s) for s in starts]
        with patch("market.services.timezone.now", return_value=observed_at):
            return store_ingestion(
                self.source,
                self.instrument,
                "H1",
                starts[0],
                starts[-1] + timedelta(hours=1),
                candles,
                {"batch": batch, "requests": []},
            )

    def _seed_snapshot(self):
        self.store([MON_0800, MON_0800 + timedelta(hours=1)], MON_0800 + timedelta(hours=2), "a")
        return run_compute_market_state(
            {
                "instrument": self.instrument.code,
                "cutoff": (MON_0800 + timedelta(hours=2)).isoformat(),
                "granularities": ["H1"],
            }
        )

    def test_task_is_idempotent(self):
        first = self._seed_snapshot()
        second = run_compute_market_state(
            {
                "instrument": self.instrument.code,
                "cutoff": (MON_0800 + timedelta(hours=2)).isoformat(),
                "granularities": ["H1"],
            }
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(MarketStateSnapshot.objects.count(), 1)

    def test_clean_snapshot_has_no_violations(self):
        self._seed_snapshot()
        report = verify_snapshots(MarketStateSnapshot.objects.all())
        self.assertEqual(report["violation_count"], 0)
        self.assertEqual(report["axis"], "semantic_integrity")

    def test_forged_snapshot_is_detected(self):
        definition = ensure_descriptor_definition()
        manifest = [
            {
                "granularity": "H1",
                "timestamp": "2026-06-01T00:00:00.000000+00:00",  # interval ends after cutoff
                "revision": 1,
                "content_sha256": "deadbeef",  # no such observation
            }
        ]
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO market_marketstatesnapshot "
                "(instrument_id, definition_id, information_cutoff, created_at, input_manifest, "
                "input_manifest_sha256, evidence_manifest, output_payload, output_sha256, "
                "data_quality_status, idempotency_key) "
                "VALUES (%s,%s,%s, now(), %s,%s,%s,%s,%s,%s,%s)",
                [
                    self.instrument.pk,
                    definition.pk,
                    MON_0800,
                    json.dumps(manifest),
                    "0" * 64,
                    json.dumps({}),
                    json.dumps({"definition": ["wrong", "9.9.9"]}),
                    "0" * 64,
                    "complete",
                    "forged-key",
                ],
            )
        report = verify_snapshots(MarketStateSnapshot.objects.all())
        codes = {v["code"] for v in report["violations"]}
        self.assertIn("output_hash_mismatch", codes)
        self.assertIn("input_manifest_hash_mismatch", codes)
        self.assertIn("idempotency_key_mismatch", codes)
        self.assertIn("payload_definition_mismatch", codes)
        self.assertIn("input_after_cutoff", codes)
        self.assertIn("missing_candle_identity", codes)

    def test_integrity_cli_exit_codes(self):
        self._seed_snapshot()
        call_command("market_state_integrity", stdout=StringIO())  # clean -> exit 0
        # Forge a row, then the CLI must exit nonzero.
        definition = ensure_descriptor_definition()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO market_marketstatesnapshot "
                "(instrument_id, definition_id, information_cutoff, created_at, input_manifest, "
                "input_manifest_sha256, evidence_manifest, output_payload, output_sha256, "
                "data_quality_status, idempotency_key) "
                "VALUES (%s,%s,%s, now(), %s,%s,%s,%s,%s,%s,%s)",
                [
                    self.instrument.pk,
                    definition.pk,
                    MON_0800,
                    json.dumps([]),
                    "0" * 64,
                    json.dumps({}),
                    json.dumps({}),
                    "0" * 64,
                    "complete",
                    "forged-key-2",
                ],
            )
        with self.assertRaises(SystemExit):
            call_command("market_state_integrity", stdout=StringIO())


class DryRunCliTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def test_preview_does_not_persist(self):
        out = StringIO()
        call_command(
            "preview_market_state",
            self.instrument.code,
            "--cutoff",
            MON_0800.isoformat(),
            "--granularities",
            "H1",
            stdout=out,
        )
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["preview"])
        self.assertEqual(MarketStateSnapshot.objects.count(), 0)  # nothing persisted

    def test_estimate_is_labelled_unmeasured(self):
        out = StringIO()
        call_command("estimate_m15_cost", "--instruments", "12", stdout=out)
        report = json.loads(out.getvalue())
        self.assertFalse(report["measured"])
        self.assertEqual(report["estimates"]["m15_records_per_instrument_week"], 480)


class InstrumentIsolationTests(TestCase):
    def test_bad_instrument_raises_without_touching_others(self):
        with self.assertRaises(Exception):
            run_compute_market_state({"instrument": "NOPE_XXX"})
        self.assertEqual(MarketStateSnapshot.objects.count(), 0)
