"""Discriminating tests for the PM's three mandatory scope omissions."""

import copy
import json
import tempfile
from datetime import timedelta
from importlib import import_module
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from market.state.canonical import identity_digest
from market.state.compute import DESCRIPTOR_DEFINITION, DESCRIPTOR_KEY, DESCRIPTOR_VERSION
from market.state.context import event_state
from market.state.liquidity import detect_acceptance, detect_sweep
from market.tests.test_market_state_context import CUTOFF, event, instrument, policy
from market.tests.test_market_state_liquidity import ATR1, LEVEL, ohlc
from operations.models import ScheduledJob


def fingerprint():
    result = {}
    with connection.cursor() as cursor:
        for table in sorted(connection.introspection.table_names()):
            quoted = connection.ops.quote_name(table)
            cursor.execute(
                f"SELECT count(*), md5(coalesce(string_agg(v, ',' ORDER BY v),'')) FROM (SELECT to_jsonb(t)::text v FROM {quoted} t) s"
            )
            result[table] = cursor.fetchone()
    return result


class OperationalSurfaceTests(TestCase):
    def setUp(self):
        self.inst = instrument()

    def run_readonly(self, name, *args, exit_code=0, **kwargs):
        before = fingerprint()
        output = StringIO()
        with CaptureQueriesContext(connection) as traced:
            if exit_code:
                with self.assertRaises(SystemExit) as raised:
                    call_command(name, *args, stdout=output, **kwargs)
                self.assertEqual(raised.exception.code, exit_code)
            else:
                call_command(name, *args, stdout=output, **kwargs)
        self.assertEqual(before, fingerprint())
        for query in traced:
            self.assertTrue(query["sql"].lstrip().upper().startswith("SELECT"), query["sql"])
            self.assertNotIn("pg_advisory", query["sql"])
        return json.loads(output.getvalue())

    def test_batch_is_deterministic_multiple_cutoffs_and_tables_unchanged(self):
        selections = [
            f"EUR_USD@{CUTOFF.isoformat()}",
            f"EUR_USD@{(CUTOFF - timedelta(hours=1)).isoformat()}",
        ]
        first = self.run_readonly("preview_market_state_batch", *selections, granularities=["H1"])
        second = self.run_readonly(
            "preview_market_state_batch", *reversed(selections), granularities=["H1"]
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first["results"]), 2)
        self.assertEqual(
            first["results"][0]["output_payload"]["event_state"]["state"], "unavailable"
        )

    def test_all_malformed_commands_fail_before_sql_without_echo(self):
        cases = [
            ("preview_market_state_batch", ["secret\x1b" * 1000], {}),
            ("preview_market_state_batch", [f"EUR_USD@{CUTOFF.isoformat()}"] * 9, {}),
            ("preview_market_state_batch", ["EUR_USD@2026-01-01"], {}),
            (
                "preview_market_state_batch",
                [f"EUR_USD@{CUTOFF.isoformat()}"],
                {"granularities": ["H1"] * 6},
            ),
            ("market_state_integrity", [], {"after_id": -1}),
            ("market_state_integrity", [], {"instrument": "secret\x1b"}),
            (
                "market_state_coverage",
                [],
                {"since": CUTOFF.isoformat(), "cutoff": (CUTOFF + timedelta(days=8)).isoformat()},
            ),
        ]
        for name, args, kwargs in cases:
            with (
                self.subTest(name=name, kwargs=kwargs),
                CaptureQueriesContext(connection) as traced,
            ):
                with self.assertRaises(CommandError) as caught:
                    call_command(name, *args, **kwargs)
                self.assertNotIn("secret", str(caught.exception))
                self.assertEqual(len(traced), 0)

    def test_coverage_is_separate_unknown_and_explicit_exit_policy(self):
        kwargs = dict(
            instrument=["EUR_USD"],
            since=(CUTOFF - timedelta(hours=2)).isoformat(),
            cutoff=CUTOFF.isoformat(),
            granularities=["H1"],
        )
        report = self.run_readonly("market_state_coverage", **kwargs)
        self.assertEqual(report["axis"], "coverage")
        self.assertEqual(report["rows"][0]["expected_intervals"], 2)
        self.assertEqual(report["rows"][0]["missing_intervals"], 2)
        self.assertFalse(report["rows"][0]["snapshot_available"])
        strict = self.run_readonly(
            "market_state_coverage", require_complete=True, exit_code=1, **kwargs
        )
        self.assertEqual(strict, report)
        integrity = self.run_readonly("market_state_integrity")
        self.assertEqual(integrity["violation_count"], 0)

    def test_definition_envelope_and_malformed_contracts_never_write(self):
        envelope = {
            "key": DESCRIPTOR_KEY,
            "version": DESCRIPTOR_VERSION,
            "definition": DESCRIPTOR_DEFINITION,
            "definition_sha256": identity_digest(DESCRIPTOR_DEFINITION),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "definition.json"
            path.write_text(json.dumps(envelope))
            self.assertTrue(
                self.run_readonly("validate_market_state_definition", str(path))["valid"]
            )
            invalid = [b"{" * 65537, b'{"x":1,"x":2}', b"NaN", b"[]", b"\xff"]
            for key in (
                "algorithms",
                "thresholds",
                "terminology",
                "session_policy",
                "missing_data_policy",
                "event_risk_policy",
                "liquidity_lifecycle",
            ):
                changed = copy.deepcopy(envelope)
                changed["definition"][key] = {}
                changed["definition_sha256"] = identity_digest(changed["definition"])
                invalid.append(json.dumps(changed).encode())
            changed = copy.deepcopy(envelope)
            changed["version"] = "0.11.0"
            invalid.append(json.dumps(changed).encode())
            changed["version"] = DESCRIPTOR_VERSION
            changed["definition_sha256"] = "0" * 64
            invalid.append(json.dumps(changed).encode())
            changed = copy.deepcopy(envelope)
            changed["definition"]["event_risk_policy"]["inclusive"] = 1
            changed["definition_sha256"] = identity_digest(changed["definition"])
            invalid.append(json.dumps(changed).encode())
            for data in invalid:
                path.write_bytes(data)
                with CaptureQueriesContext(connection) as traced, self.assertRaises(CommandError):
                    call_command("validate_market_state_definition", str(path))
                self.assertEqual(len(traced), 0)

    def test_drift_m15_and_static_consumers_safe_and_readonly(self):
        ScheduledJob.objects.create(
            name="secret",
            task_name="market.compute_market_state",
            parameters={"instrument": "EUR_USD", "cutoff": "secret\x1b"},
            interval_seconds=60,
            next_run_at=CUTOFF,
        )
        ScheduledJob.objects.create(
            name="m15",
            task_name="market.ingest_oanda",
            parameters={"instrument": "EUR_USD", "granularity": "M15"},
            interval_seconds=60,
            next_run_at=CUTOFF,
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "forecasts"
            target.mkdir()
            (target / "consumer.py").write_text("from market.models import MarketStateSnapshot\n")
            with override_settings(BASE_DIR=directory):
                report = self.run_readonly("market_state_integrity", exit_code=1)
        codes = {v["code"] for v in report["operational_violations"]}
        self.assertEqual(
            codes,
            {
                "unexpected_phase4_schedule",
                "phase4_task_parameter_drift",
                "unexpected_m15_activation",
                "unexpected_phase4_consumer",
            },
        )
        self.assertNotIn("secret", json.dumps(report))


class EventWindowTests(TestCase):
    def setUp(self):
        self.inst = instrument()
        self.policy = policy("US", "USD")

    def test_before_equality_inside_after_microsecond_boundaries(self):
        event(self.policy, "US", CUTOFF, CUTOFF - timedelta(days=1))
        for offset, expected in [
            (-1800000001, "upcoming"),
            (-1800000000, "active"),
            (0, "active"),
            (1800000000, "active"),
            (1800000001, "expired"),
        ]:
            block = event_state(self.inst, CUTOFF + timedelta(microseconds=offset))
            window = block["events"][0]["intraday_risk_window"]
            self.assertEqual(window["status"], expected)
            self.assertEqual(
                window["starts_at"],
                (CUTOFF - timedelta(minutes=30)).isoformat(timespec="microseconds"),
            )
            self.assertEqual(
                block["aggregate_risk"], "present" if expected == "active" else "unknown"
            )

    def test_policy_values_consumed_overlap_and_no_severity(self):
        event(self.policy, "US", CUTOFF, CUTOFF - timedelta(days=1), key="one")
        event(
            self.policy, "US", CUTOFF + timedelta(minutes=20), CUTOFF - timedelta(days=1), key="two"
        )
        block = event_state(self.inst, CUTOFF)
        self.assertEqual(len(block["active_window_vintages"]), 2)
        for item in block["events"]:
            self.assertEqual(item["severity"]["state"], "unavailable")
        custom = copy.deepcopy(DESCRIPTOR_DEFINITION["event_risk_policy"])
        custom["pre_seconds"] = 60
        custom["post_seconds"] = 120
        block = event_state(self.inst, CUTOFF, policy=custom)
        self.assertEqual(len(block["active_window_vintages"]), 1)
        self.assertEqual(
            block["events"][0]["intraday_risk_window"]["ends_at"],
            (CUTOFF + timedelta(seconds=120)).isoformat(timespec="microseconds"),
        )

    def test_cancelled_postponed_unknown_status_and_date_only_never_active(self):
        for index, status in enumerate(("cancelled", "postponed", "secret-status")):
            e = event(self.policy, "US", CUTOFF, CUTOFF - timedelta(days=1), key=str(index))
            # Use frozen records to test source statuses without violating ledger immutability.
            e.status = status
            block = event_state(self.inst, CUTOFF, frozen={"events": [e]})
            self.assertEqual(
                block["events"][0]["intraday_risk_window"]["reason_code"], "event_status_ineligible"
            )
            self.assertEqual(block["aggregate_risk"], "unknown")
        e.time_precision = "date"
        e.status = "scheduled"
        block = event_state(self.inst, CUTOFF, frozen={"events": [e]})
        self.assertEqual(
            block["events"][0]["intraday_risk_window"]["reason_code"], "event_time_date_only"
        )

    def test_revision_cutoff_and_dst_absolute_duration(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        for month, day in ((3, 8), (11, 1)):
            at = datetime(2026, month, day, 1, 45, tzinfo=ZoneInfo("America/New_York"))
            e = event(self.policy, "US", at, at - timedelta(days=2), key=str(month))
            window = event_state(self.inst, at, frozen={"events": [e]})["events"][0][
                "intraday_risk_window"
            ]
            self.assertEqual(
                datetime.fromisoformat(window["ends_at"])
                - datetime.fromisoformat(window["starts_at"]),
                timedelta(hours=1),
            )
        first = event(self.policy, "US", CUTOFF, CUTOFF - timedelta(days=1), key="rev")
        old = event_state(self.inst, CUTOFF, frozen={"events": [first]})
        revised = event(
            self.policy,
            "US",
            CUTOFF + timedelta(days=10),
            CUTOFF + timedelta(microseconds=1),
            key="rev",
        )
        self.assertEqual(event_state(self.inst, CUTOFF, frozen={"events": [first, revised]}), old)
        self.assertEqual(
            event_state(
                self.inst, CUTOFF + timedelta(microseconds=1), frozen={"events": [first, revised]}
            )["state"],
            "unavailable",
        )


class LiquidityLifecycleTests(SimpleTestCase):
    def bars(self, closes):
        return [
            ohlc(i, c, c, c, c)._replace(end=ohlc(i + 1, c, c, c, c).timestamp)
            for i, c in enumerate(closes)
        ]

    def test_acceptance_normalization_confirmation_and_terminal_invalidation(self):
        for side, closes in (
            ("above", [12, 10, 10, 10, 9, 10]),
            ("below", [8, 10, 10, 10, 11, 10]),
        ):
            bars = self.bars(closes)
            self.assertIsNone(detect_acceptance(bars[:3], ATR1, LEVEL, side, level_id="level"))
            confirmed = detect_acceptance(bars[:4], ATR1, LEVEL, side, level_id="level")
            self.assertEqual(confirmed["status"], "confirmed")
            self.assertEqual(confirmed["acceptance_distance_atr"], "2.000000")
            self.assertEqual(
                confirmed["confirmation_at"], bars[3].end.isoformat(timespec="microseconds")
            )
            invalidated = detect_acceptance(bars, ATR1, LEVEL, side, level_id="level")
            self.assertEqual(invalidated["status"], "invalidated")
            self.assertEqual(
                invalidated["invalidated_at"], bars[4].end.isoformat(timespec="microseconds")
            )
            self.assertEqual(
                invalidated, detect_acceptance(bars[:5], ATR1, LEVEL, side, level_id="level")
            )

    def test_acceptance_gap_and_atr_at_breach_not_current(self):
        bars = self.bars([12, 10, 10, 10])
        history = {bars[0].timestamp: ATR1 * 4}
        result = detect_acceptance(
            bars, ATR1, LEVEL, "above", level_id="level", atr_history=history
        )
        self.assertEqual(result["acceptance_distance_atr"], "0.500000")
        self.assertIsNone(
            detect_acceptance(bars[:2] + bars[3:], ATR1, LEVEL, "above", level_id="level")
        )
        self.assertIsNone(detect_acceptance(bars, None, LEVEL, "above", level_id="level"))

    def test_expiry_equality_and_normalized_sweep_boundary(self):
        bars = self.bars([12] + [10] * 54)
        equal = detect_acceptance(bars[:54], ATR1, LEVEL, "above", level_id="level")
        expired = detect_acceptance(bars, ATR1, LEVEL, "above", level_id="level")
        self.assertEqual(equal["status"], "confirmed")
        self.assertEqual(expired["status"], "expired")
        self.assertEqual(expired["expired_at"], bars[54].end.isoformat(timespec="microseconds"))
        for high, qualifies in (("10.099999", False), ("10.1", True)):
            sweep = detect_sweep([ohlc(0, 9, high, 9, 9)], ATR1, LEVEL, "above", level_id="level")
            self.assertEqual(sweep is not None, qualifies)
            if sweep:
                self.assertEqual(sweep["status"], "confirmed")
                self.assertEqual(len(sweep["dependencies"]), 1)

    def test_descriptor_sql_hash_pinned(self):
        migration = import_module("market.migrations.0037_market_state_lifecycle")
        self.assertEqual(migration.DESCRIPTOR_0120_SHA256, identity_digest(DESCRIPTOR_DEFINITION))

    def test_sweep_equality_gap_invalidation_and_expiry_both_sides(self):
        for side, wick, reclaim, invalid in (("above", "10.1", 9, 11), ("below", "9.9", 11, 9)):
            bars = self.bars([10, reclaim, 10, invalid, 10])
            bars[0] = bars[0]._replace(**{"high" if side == "above" else "low": type(LEVEL)(wick)})
            self.assertIsNone(detect_sweep(bars[:1], ATR1, LEVEL, side, level_id="level"))
            result = detect_sweep(bars, ATR1, LEVEL, side, level_id="level")
            self.assertEqual(result["status"], "invalidated")
            self.assertEqual(
                result["confirmation_at"], bars[1].end.isoformat(timespec="microseconds")
            )
            self.assertEqual(
                result["invalidated_at"], bars[3].end.isoformat(timespec="microseconds")
            )
            gap = [bars[0], bars[1]._replace(timestamp=bars[2].timestamp)]
            self.assertIsNone(detect_sweep(gap, ATR1, LEVEL, side, level_id="level"))
            tail = self.bars([10] * 54)
            tail[:2] = bars[:2]
            self.assertEqual(
                detect_sweep(tail[:52], ATR1, LEVEL, side, level_id="level")["status"], "confirmed"
            )
            self.assertEqual(
                detect_sweep(tail, ATR1, LEVEL, side, level_id="level")["status"], "expired"
            )


class PersistedOmissionTests(TestCase):
    from market.tests.test_phase4_semantic_boundary import SemanticBoundaryTests as _fixture

    setUp = _fixture.setUp
    insert = _fixture.insert

    def test_persisted_liquidity_provenance_and_old_cutoff_suffix_invariance(self):
        from decimal import Decimal

        from market.state.compute import compute_market_state
        from market.state.integrity import verify_snapshots
        from market.tests.factories import candle
        from market.tests.legacy_state_evidence import store_ingestion
        from market.tests.test_live_observations import make_market

        inst, source = make_market()
        start = self.cutoff.replace(hour=0)
        prices = [5] * 20 + [10, 7] + [6] * 19 + [11] * 4
        candles = []
        for i, price in enumerate(prices):
            mid = Decimal(price)
            values = {
                f"{side}_{field}": mid + offset
                for side, offset in (("bid", Decimal("-0.0001")), ("ask", Decimal("0.0001")))
                for field in ("open", "high", "low", "close")
            }
            candles.append(candle(start + timedelta(hours=i), **values))
        cutoff = start + timedelta(hours=len(prices))
        with patch("market.services.timezone.now", return_value=cutoff):
            store_ingestion(source, inst, "H1", start, cutoff, candles, {"batch": "liquidity"})
        first, created = compute_market_state(inst, self.definition, cutoff, ["H1"])
        self.assertTrue(created)
        e = first.output_payload["granularities"]["H1"]["liquidity"]["acceptance_above"]
        self.assertEqual(e["status"], "confirmed")
        self.assertEqual(len(e["level_dependencies"]), 5)
        self.assertEqual(len(e["atr_dependencies"]), 15)
        for key in ("dependencies", "level_dependencies", "atr_dependencies"):
            self.assertTrue(all(d in first.input_manifest for d in e[key]))
        end = cutoff + timedelta(hours=1)
        with patch("market.services.timezone.now", return_value=end):
            store_ingestion(source, inst, "H1", cutoff, end, [candle(cutoff)], {"batch": "suffix"})
        again, created = compute_market_state(inst, self.definition, cutoff, ["H1"])
        self.assertFalse(created)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(again.output_payload, first.output_payload)
        self.assertEqual(verify_snapshots([first])["violation_count"], 0)

    def test_raw_event_forged_windows_fail_and_integrity_replays(self):
        from django.db import IntegrityError, transaction

        from market.models import MarketStateSnapshot
        from market.state.compute import build_market_state
        from market.state.integrity import verify_snapshots

        pol = policy("US", "USD")
        event(pol, "US", self.cutoff, self.cutoff - timedelta(days=1))
        (
            self.payload,
            self.scope,
            self.manifest,
            self.manifest_hash,
            self.evidence,
            self.evidence_hash,
            _,
        ) = build_market_state(self.instrument, self.definition, self.cutoff, ["H1"])
        self.insert(self.payload)
        original = MarketStateSnapshot.objects.latest("pk")
        self.assertEqual(verify_snapshots([original])["violation_count"], 0)
        for field, value in (
            ("starts_at", self.cutoff.isoformat()),
            ("inclusive", False),
            ("status", "expired"),
            ("available_at", "secret"),
        ):
            payload = copy.deepcopy(self.payload)
            payload["event_state"]["events"][0]["intraday_risk_window"][field] = value
            with (
                self.assertRaisesMessage(IntegrityError, "market_state_invalid_event_window"),
                transaction.atomic(),
            ):
                self.insert(payload)
            forged = copy.copy(original)
            forged.output_payload = payload
            forged.output_sha256 = identity_digest(payload)
            codes = {v["code"] for v in verify_snapshots([forged])["violations"]}
            self.assertIn("feature_semantics_mismatch", codes)

    def test_raw_liquidity_chronology_is_rejected_before_hash_consistent_forgery(self):
        from django.db import IntegrityError, transaction

        from market.models import MarketStateSnapshot
        from market.state.integrity import verify_snapshots

        bars = [
            ohlc(i, 12 if i == 0 else 10, 12 if i == 0 else 10, 10, 12 if i == 0 else 10)
            for i in range(4)
        ]
        base = detect_acceptance(bars, ATR1, LEVEL, "above", level_id="level")
        base["level_dependencies"] = base["atr_dependencies"] = base["dependencies"]
        for field, value in (
            ("confirmation_at", "2020-01-01T00:00:00+00:00"),
            ("expired_at", "2020-01-01T00:00:00+00:00"),
            ("breach_at", "secret"),
            ("dependencies", {}),
        ):
            payload = copy.deepcopy(self.payload)
            changed = copy.deepcopy(base)
            changed[field] = value
            payload["granularities"]["H1"]["liquidity"] = {"acceptance_above": changed}
            with self.assertRaises(IntegrityError) as caught, transaction.atomic():
                self.insert(payload)
            self.assertIn("market_state_", str(caught.exception))
            self.assertNotIn("secret", str(caught.exception))
            snapshot = MarketStateSnapshot(
                instrument=self.instrument,
                definition=self.definition,
                information_cutoff=self.cutoff,
                output_payload=payload,
                output_sha256=identity_digest(payload),
                input_manifest=self.manifest,
                input_manifest_sha256=self.manifest_hash,
                evidence_manifest=self.evidence,
                idempotency_key="0" * 64,
            )
            self.assertTrue(verify_snapshots([snapshot])["violation_count"])

    def test_populated_commands_no_write_and_coverage_success_then_stale(self):
        from market.tests.test_live_observations import make_market
        from market.tests.test_market_state_ops import MON_0800, IntegrityAndTaskTests

        self.instrument, self.source = make_market()
        with patch.object(self, "store", IntegrityAndTaskTests.store.__get__(self), create=True):
            snapshot = IntegrityAndTaskTests._seed_snapshot(self)
        run = OperationalSurfaceTests.run_readonly.__get__(self)
        code = self.instrument.code
        run(
            "preview_market_state",
            code,
            cutoff=snapshot.information_cutoff.isoformat(),
            granularities=["H1"],
        )
        run(
            "preview_market_state_batch",
            f"{code}@{snapshot.information_cutoff.isoformat()}",
            granularities=["H1"],
        )
        run("market_state_integrity")
        kwargs = dict(
            instrument=[code],
            since=MON_0800.isoformat(),
            cutoff=snapshot.information_cutoff.isoformat(),
            granularities=["H1"],
            require_complete=True,
        )
        report = run("market_state_coverage", **kwargs)
        self.assertTrue(report["complete"])
        self.assertEqual(report["rows"][0]["missing_intervals"], 0)
        self.assertEqual(
            report["rows"][0]["feature_families"]["higher_timeframe"]["state"], "partial"
        )
        kwargs["cutoff"] = (snapshot.information_cutoff + timedelta(hours=1)).isoformat()
        report = run("market_state_coverage", exit_code=1, **kwargs)
        self.assertFalse(report["rows"][0]["snapshot_fresh"])
        self.assertEqual(report["rows"][0]["missing_intervals"], 1)
