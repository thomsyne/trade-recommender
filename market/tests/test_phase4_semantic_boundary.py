"""Prospective SQL guards and safe diagnostics, without repairing installed SQL."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase

from market.models import MarketStateSnapshot
from market.state.canonical import canonical_json, identity_digest
from market.state.compute import build_market_state, ensure_descriptor_definition
from market.state.integrity import verify_snapshots
from market.state.snapshots import snapshot_idempotency_key
from market.tests.test_live_observations import make_market


class SemanticBoundaryTests(TestCase):
    def test_integrity_page_reports_its_unchecked_tail(self):
        snapshots = [
            MarketStateSnapshot(
                pk=i, definition=self.definition, information_cutoff=datetime(2026, 1, 5)
            )
            for i in range(1, 102)
        ]
        report = verify_snapshots(snapshots)
        self.assertEqual(report["checked"], 100)
        self.assertTrue(report["has_more"])
        self.assertEqual(report["next_after_id"], 100)
        self.assertEqual(len(report["violations"]), 100)

    def test_integrity_cli_cursor_does_not_recheck_previous_page(self):
        import json
        from io import StringIO

        from django.core.management import call_command

        self.insert(self.payload)
        pk = MarketStateSnapshot.objects.latest("pk").pk
        out = StringIO()
        with self.assertNumQueries(1):
            call_command("market_state_integrity", after_id=pk, stdout=out)
        self.assertEqual(json.loads(out.getvalue())["checked"], 0)

    def test_migration_pins_the_exact_supported_contract(self):
        from importlib import import_module

        from market.state.compute import DESCRIPTOR_DEFINITION

        migration = import_module("market.migrations.0036_market_state_recording_boundary")
        self.assertIn(identity_digest(DESCRIPTOR_DEFINITION), migration.NEW_FUNCTIONS)

    def setUp(self):
        self.instrument, _ = make_market()
        self.definition = ensure_descriptor_definition()
        self.cutoff = datetime(2026, 1, 5, 12, tzinfo=UTC)
        (
            self.payload,
            self.scope,
            self.manifest,
            self.manifest_hash,
            self.evidence,
            self.evidence_hash,
            _,
        ) = build_market_state(self.instrument, self.definition, self.cutoff, ["H1"])

    def insert(self, payload, *, manifest=None):
        manifest = self.manifest if manifest is None else manifest
        manifest_hash = identity_digest(manifest)
        key = snapshot_idempotency_key(
            self.definition.definition_sha256,
            self.instrument.code,
            self.cutoff,
            self.scope,
            manifest_hash,
            self.evidence_hash,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO market_marketstatesnapshot "
                "(instrument_id, definition_id, information_cutoff, created_at, input_manifest, "
                "input_manifest_sha256, evidence_manifest, output_payload, output_sha256, "
                "data_quality_status, idempotency_key) VALUES (%s,%s,%s,now(),%s,%s,%s,%s,%s,%s,%s)",
                [
                    self.instrument.pk,
                    self.definition.pk,
                    self.cutoff,
                    canonical_json(manifest),
                    manifest_hash,
                    canonical_json(self.evidence),
                    canonical_json(payload),
                    identity_digest(payload),
                    "partial",
                    key,
                ],
            )

    def test_self_consistent_hashes_do_not_authorize_false_instrument_or_scope(self):
        for field, value in (
            ("instrument", "GBP_USD"),
            ("requested_granularities", ["W"]),
            ("information_cutoff", "2026-01-06T12:00:00.000000+00:00"),
        ):
            with self.subTest(field=field):
                payload = deepcopy(self.payload)
                payload[field] = value
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.insert(payload)

    def test_non_superuser_cannot_forge_semantics_or_mutate_valid_snapshot(self):
        # CREATE ROLE and grants are transactional; TestCase rolls back only this
        # uniquely named role. No shared role or existing database is touched.
        role = "p4_probe_" + uuid4().hex
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOLOGIN')
            cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            cursor.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public TO "{role}"'
            )
            cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
            cursor.execute(f'SET LOCAL ROLE "{role}"')
            cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            self.assertFalse(cursor.fetchone()[0])
        bad = deepcopy(self.payload)
        bad["instrument"] = "GBP_USD"
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.insert(bad)
        self.insert(self.payload)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for sql, message in (
            ("UPDATE market_marketstatesnapshot SET output_sha256=repeat('0',64)", "immutable"),
            ("DELETE FROM market_marketstatesnapshot", "immutable"),
            ("TRUNCATE market_marketstatesnapshot", "must not be truncated"),
        ):
            with (
                self.subTest(sql=sql),
                self.assertRaisesMessage(DatabaseError, message),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(sql)

    def test_unknown_terminology_is_rejected_even_with_correct_payload_hash(self):
        bad = deepcopy(self.payload)
        bad["monthly_context"] = {
            "state": "available",
            "version": "trend-v1",
            "classification": "guaranteed profit",
        }
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.insert(bad)

    def test_missing_candle_with_valid_hash_is_rejected(self):
        manifest = [
            {
                "granularity": "H1",
                "timestamp": "2026-01-05T08:00:00.000000+00:00",
                "revision": 1,
                "content_sha256": "a" * 64,
            }
        ]
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.insert(self.payload, manifest=manifest)

    def test_integrity_rejects_self_consistent_omitted_candle_and_research(self):
        from datetime import timedelta
        from unittest.mock import patch

        from market.state.snapshots import persist_snapshot
        from market.tests.factories import candle
        from market.tests.legacy_state_evidence import ingest
        from market.tests.test_market_state_context import event, policy

        # Historical contradiction: valid at insertion, then backdated evidence
        # appended to the disposable ledger. New SQL inserts reject the omission.
        self.insert(self.payload)
        _, source = make_market()
        earlier = self.cutoff - timedelta(hours=2)
        with patch("market.services.timezone.now", return_value=earlier):
            ingest(source, self.instrument, [candle(earlier - timedelta(hours=1))], "omitted")
        event(policy("US", "USD"), "US", self.cutoff, earlier)
        codes = {
            v["code"] for v in verify_snapshots(MarketStateSnapshot.objects.all())["violations"]
        }
        self.assertIn("eligible_candle_set_mismatch", codes)
        self.assertIn("eligible_research_set_mismatch", codes)
        # A new application write cannot use that same omission under a new key.
        with self.assertRaisesMessage(ValueError, "invalid_snapshot_semantics"):
            persist_snapshot(
                self.instrument,
                self.definition,
                self.cutoff + timedelta(microseconds=1),
                self.manifest,
                self.manifest_hash,
                {
                    **self.payload,
                    "information_cutoff": (self.cutoff + timedelta(microseconds=1)).isoformat(
                        timespec="microseconds"
                    ),
                },
                scope=self.scope,
                evidence_manifest=self.evidence,
                evidence_sha256=self.evidence_hash,
                data_quality_status="partial",
            )

    def test_raw_insert_cannot_select_an_obsolete_eligible_revision(self):
        from datetime import timedelta
        from unittest.mock import patch

        from market.tests.factories import candle
        from market.tests.legacy_state_evidence import ingest

        _, source = make_market()
        start = self.cutoff - timedelta(hours=4)
        with patch("market.services.timezone.now", return_value=self.cutoff - timedelta(hours=2)):
            ingest(source, self.instrument, [candle(start)], "revision-one")
        result = build_market_state(self.instrument, self.definition, self.cutoff, ["H1"])
        with patch("market.services.timezone.now", return_value=self.cutoff - timedelta(hours=1)):
            ingest(source, self.instrument, [candle(start, volume=999)], "revision-two")
        with (
            self.assertRaisesMessage(IntegrityError, "market_state_obsolete_revision"),
            transaction.atomic(),
        ):
            self.insert(result[0], manifest=result[2])

    def test_available_bos_without_candle_prerequisites_is_rejected(self):
        payload = deepcopy(self.payload)
        payload["granularities"]["H1"] = {
            "state": "available",
            "eligible_candle_count": 0,
            "higher_timeframe": {"bos": {"state": "available", "direction": "up"}},
        }
        with (
            self.assertRaisesMessage(IntegrityError, "market_state_invalid_prerequisites"),
            transaction.atomic(),
        ):
            self.insert(payload)

    def test_future_research_lineage_is_rejected_with_consistent_hashes(self):
        from datetime import timedelta

        from market.state.context import research_lineage
        from market.tests.test_market_state_context import event, policy

        late = self.cutoff + timedelta(hours=1)
        release = event(policy("US", "USD"), "US", late, late)
        self.evidence = {"events": [research_lineage(release)], "macro": {}}
        self.evidence_hash = identity_digest(self.evidence)
        with (
            self.assertRaisesMessage(IntegrityError, "market_state_research_after_cutoff"),
            transaction.atomic(),
        ):
            self.insert(self.payload)

    def test_frozen_research_replays_trigger_vintages_without_queries(self):
        from datetime import date, timedelta

        from market.state import context
        from market.tests.test_market_state_context import event, observation, policy, series

        pol = policy("US", "USD")
        ser = series(pol, "USD-policy")
        earlier = self.cutoff - timedelta(hours=2)
        observation(ser, pol, date(2025, 12, 1), 3, earlier, earlier)
        observation(ser, pol, date(2026, 1, 1), 4, earlier, earlier)
        first = event(pol, "US", self.cutoff, earlier)
        observation(ser, pol, date(2026, 1, 1), 2, self.cutoff, self.cutoff, revision=1)
        event(pol, "US", self.cutoff + timedelta(days=30), self.cutoff)
        frozen = context.freeze_research(self.instrument, earlier, self.cutoff)
        with self.assertNumQueries(0):
            before = context.event_state(self.instrument, earlier, frozen=frozen)
            after = context.event_state(self.instrument, self.cutoff, frozen=frozen)
            rate_before = context.macro_regime(self.instrument, earlier, frozen=frozen)
            rate_after = context.macro_regime(self.instrument, self.cutoff, frozen=frozen)
        self.assertEqual(before["events"][0]["vintage_id"], first.payload_fingerprint)
        self.assertEqual(after["events"], [])  # reschedule out must suppress the old release
        self.assertEqual(rate_before["by_currency"]["USD"]["direction"], "tightening")
        self.assertEqual(rate_after["by_currency"]["USD"]["direction"], "easing")

        result = build_market_state(self.instrument, self.definition, self.cutoff, ["H1"])
        payload, scope, manifest, manifest_hash, evidence, evidence_hash, quality = result
        payload = deepcopy(payload)
        payload["macro_regime"]["by_currency"]["USD"]["direction"] = "tightening"
        snapshot = MarketStateSnapshot(
            instrument=self.instrument,
            definition=self.definition,
            information_cutoff=self.cutoff,
            input_manifest=manifest,
            input_manifest_sha256=manifest_hash,
            evidence_manifest=evidence,
            output_payload=payload,
            output_sha256=identity_digest(payload),
            data_quality_status=quality,
            idempotency_key=snapshot_idempotency_key(
                self.definition.definition_sha256,
                self.instrument.code,
                self.cutoff,
                scope,
                manifest_hash,
                evidence_hash,
            ),
        )
        self.assertIn(
            "feature_semantics_mismatch",
            [v["code"] for v in verify_snapshots([snapshot])["violations"]],
        )

    def test_historical_malformed_values_are_safe_reason_codes(self):
        for change in (
            {"output_payload": {"x": 1.5}},
            {"information_cutoff": datetime(2026, 1, 5)},
            {
                "input_manifest": [
                    {
                        "timestamp": "9999-12-31T23:00:00+00:00",
                        "granularity": "H1",
                        "revision": 1,
                        "content_sha256": "a" * 64,
                    }
                ]
            },
            {
                "input_manifest": [
                    {
                        "timestamp": "2026-01-05T08:00:00",
                        "granularity": "H1",
                        "revision": [],
                        "content_sha256": "a" * 64,
                    }
                ]
            },
        ):
            snapshot = MarketStateSnapshot(
                instrument=self.instrument,
                definition=self.definition,
                information_cutoff=self.cutoff,
                output_payload=self.payload,
                input_manifest=[],
                evidence_manifest=self.evidence,
                input_manifest_sha256=self.manifest_hash,
                output_sha256=identity_digest(self.payload),
                idempotency_key="a" * 64,
            )
            for key, value in change.items():
                setattr(snapshot, key, value)
            report = verify_snapshots([snapshot])
            self.assertGreater(report["violation_count"], 0)
            self.assertTrue(all(set(v) == {"snapshot_id", "code"} for v in report["violations"]))

    def test_impossible_historical_plan_leaves_normal_m15_installation_intact(self):
        from django.db.migrations.exceptions import IrreversibleError

        from market.tests.historical_database import PreservingMigrationExecutor

        def installed_state():
            with connection.cursor() as cursor:
                cursor.execute("SELECT app,name FROM django_migrations ORDER BY app,name")
                graph = cursor.fetchall()
                cursor.execute(
                    "SELECT pg_get_functiondef('market_candleobservation_live_completion(timestamptz,text)'::regprocedure)"
                )
                return graph, cursor.fetchone()[0]

        before = installed_state()
        with self.assertRaises(IrreversibleError):
            PreservingMigrationExecutor(connection).migrate(
                [("market", "0012_operation_aware_historical_dataset")]
            )
        self.assertEqual(installed_state(), before)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT market_candleobservation_live_completion(%s,'M15')",
                [datetime(2026, 3, 5, tzinfo=UTC)],
            )
            self.assertEqual(cursor.fetchone()[0], datetime(2026, 3, 5, 0, 15, tzinfo=UTC))
