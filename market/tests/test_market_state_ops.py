"""Phase 4 slice 8 — durable task, integrity report and dry-run CLIs."""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from market.models import MarketStateDefinition, MarketStateSnapshot
from market.state.compute import (
    DESCRIPTOR_DEFINITION,
    DESCRIPTOR_KEY,
    DESCRIPTOR_VERSION,
    ensure_descriptor_definition,
)
from market.state.definitions import register_definition
from market.state.integrity import verify_snapshots
from market.state.tasks import run_compute_market_state
from market.tests.factories import candle
from market.tests.legacy_state_evidence import store_ingestion
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

    def test_missing_cutoff_raises(self):
        # A durable job must freeze its cutoff before execution; defaulting to
        # now() would make two retries produce different snapshots (P2-14a).
        with self.assertRaisesMessage(
            ValueError, "cutoff is required for a durable market-state computation"
        ):
            run_compute_market_state({"instrument": self.instrument.code})
        self.assertEqual(MarketStateSnapshot.objects.count(), 0)

    def test_register_definition_is_atomically_idempotent(self):
        # Happy path: a second registration of the same body returns the same row.
        first = register_definition(DESCRIPTOR_KEY, DESCRIPTOR_VERSION, DESCRIPTOR_DEFINITION)
        again = register_definition(DESCRIPTOR_KEY, DESCRIPTOR_VERSION, DESCRIPTOR_DEFINITION)
        self.assertEqual(first.pk, again.pk)

        # Race path: force the pre-checks to miss so the create fires against an
        # already-present row, raising IntegrityError. The nested atomic must roll
        # back and the except clause must re-fetch and return the existing winner.
        original_filter = MarketStateDefinition.objects.filter

        class _Miss:
            def first(self):
                return None

        calls = {"n": 0}

        def _side_effect(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] <= 2:  # existing-by-digest and key/version pre-checks
                return _Miss()
            return original_filter(*args, **kwargs)

        with patch.object(MarketStateDefinition.objects, "filter", side_effect=_side_effect):
            raced = register_definition(DESCRIPTOR_KEY, DESCRIPTOR_VERSION, DESCRIPTOR_DEFINITION)
        self.assertEqual(first.pk, raced.pk)
        self.assertEqual(MarketStateDefinition.objects.count(), 1)

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
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
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
                    "1" * 64,
                ],
            )
        # Historical contradictions remain inspectable without bypassing the new
        # prospective guard or weakening the original diagnostic assertions.
        report = verify_snapshots(
            [
                MarketStateSnapshot(
                    pk=1,
                    instrument=self.instrument,
                    definition=definition,
                    information_cutoff=MON_0800,
                    input_manifest=manifest,
                    input_manifest_sha256="0" * 64,
                    evidence_manifest={},
                    output_payload={"definition": ["wrong", "9.9.9"]},
                    output_sha256="0" * 64,
                    data_quality_status="complete",
                    idempotency_key="1" * 64,
                )
            ]
        )
        codes = {v["code"] for v in report["violations"]}
        self.assertIn("output_hash_mismatch", codes)
        self.assertIn("input_manifest_hash_mismatch", codes)
        self.assertIn("idempotency_key_mismatch", codes)
        # The forged payload lacks the required top-level keys.
        self.assertIn("malformed_payload_schema", codes)
        self.assertIn("input_after_cutoff", codes)
        self.assertIn("missing_candle_identity", codes)

    def test_integrity_cli_exit_codes(self):
        self._seed_snapshot()
        call_command("market_state_integrity", stdout=StringIO())  # clean -> exit 0
        # Forge a row, then the CLI must exit nonzero.
        definition = ensure_descriptor_definition()
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
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
                    "2" * 64,
                ],
            )
        historical = MarketStateSnapshot(
            pk=1,
            instrument=self.instrument,
            definition=definition,
            information_cutoff=MON_0800,
            input_manifest=[],
            input_manifest_sha256="0" * 64,
            evidence_manifest={},
            output_payload={},
            output_sha256="0" * 64,
            data_quality_status="complete",
            idempotency_key="2" * 64,
        )
        with patch.object(MarketStateSnapshot.objects, "all", return_value=[historical]):
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
        # A read-only preview must persist NOTHING: neither a snapshot nor a
        # definition row (P2-13 — it must not call register_definition).
        self.assertEqual(MarketStateSnapshot.objects.count(), 0)
        self.assertEqual(MarketStateDefinition.objects.count(), 0)

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
