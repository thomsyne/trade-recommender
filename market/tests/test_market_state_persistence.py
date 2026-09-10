"""Phase 4 slice 2 — immutable definition/snapshot persistence and causality.

Adversarial coverage of the persistence contract: canonical serialization
(float/Decimal/key guards), content-addressed definitions that fail closed,
causal input-manifest eligibility (interval-ended, availability, latest-revision-
by-cutoff, prefix/cutoff invariance), idempotent and determinism-checked
snapshot persistence, and dual-layer immutability (ORM ``ImmutableModel`` plus
database UPDATE/DELETE/TRUNCATE triggers). Expected values are derived by hand,
not from the code under test.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import Error, connection, transaction
from django.test import TestCase

from market.models import MarketStateDefinition, MarketStateSnapshot
from market.services import store_ingestion
from market.state.canonical import (
    NonCanonicalValue,
    canonical_json,
    format_decimal,
    identity_digest,
)
from market.state.compute import (
    DESCRIPTOR_KEY,
    DESCRIPTOR_VERSION,
    compute_market_state,
    ensure_descriptor_definition,
)
from market.state.definitions import (
    DefinitionError,
    load_definition,
    register_definition,
    validate_definition_body,
)
from market.state.manifest import build_input_manifest, eligible_observations
from market.state.snapshots import DeterminismViolation, persist_snapshot
from market.tests.factories import candle
from market.tests.test_live_observations import make_market

MON_0800 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)  # Monday, market open, H1-aligned


def _valid_definition_body(**overrides):
    body = {
        "algorithms": {"x": "v1"},
        "features": ["a"],
        "price_basis": "midpoint",
        "rounding": {"quantum": "0.000001", "mode": "ROUND_HALF_EVEN"},
        "calendar_policy": "ny-fx-week-v1",
        "missing_data_policy": "explicit-unavailable-v1",
        "lookbacks": {},
        "thresholds": {},
    }
    body.update(overrides)
    return body


class CanonicalSerializationTests(TestCase):
    def test_format_decimal_is_fixed_point_half_even(self):
        self.assertEqual(format_decimal(Decimal("1.1010")), "1.101000")
        self.assertEqual(format_decimal(Decimal("1.0000005")), "1.000000")  # half to even
        self.assertEqual(format_decimal(Decimal("1.0000015")), "1.000002")

    def test_key_order_does_not_change_digest(self):
        self.assertEqual(
            identity_digest({"b": 1, "a": 2}),
            identity_digest({"a": 2, "b": 1}),
        )

    def test_float_and_decimal_and_bad_keys_are_rejected(self):
        for bad in (1.5, float("nan"), float("inf"), {"x": 2.0}, [1, 2.5]):
            with self.assertRaises(NonCanonicalValue):
                canonical_json(bad)
        with self.assertRaises(NonCanonicalValue):
            canonical_json({"x": Decimal("1.0")})
        with self.assertRaises(NonCanonicalValue):
            canonical_json({1: "x"})

    def test_ints_bools_none_strings_are_canonical(self):
        self.assertEqual(
            canonical_json({"a": 1, "b": True, "c": None}), '{"a":1,"b":true,"c":null}'
        )


class DefinitionRegistryTests(TestCase):
    def test_content_addressed_registration_is_idempotent(self):
        a = register_definition("k", "1.0.0", _valid_definition_body())
        b = register_definition("k", "1.0.0", _valid_definition_body())
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(MarketStateDefinition.objects.count(), 1)

    def test_same_content_different_identity_fails_closed(self):
        register_definition("k", "1.0.0", _valid_definition_body())
        with self.assertRaises(DefinitionError):
            register_definition("other", "2.0.0", _valid_definition_body())

    def test_different_content_same_identity_fails_closed(self):
        register_definition("k", "1.0.0", _valid_definition_body())
        with self.assertRaises(DefinitionError):
            register_definition("k", "1.0.0", _valid_definition_body(features=["a", "b"]))

    def test_missing_required_keys_fail_closed(self):
        body = _valid_definition_body()
        del body["thresholds"]
        with self.assertRaises(DefinitionError):
            validate_definition_body(body)

    def test_load_unknown_definition_fails_closed(self):
        with self.assertRaises(DefinitionError):
            load_definition("nope", "9.9.9")

    def test_load_detects_hash_mismatch_from_raw_insert(self):
        # save() recompute and the UPDATE trigger make a mismatched row
        # unreachable except via a raw INSERT (which the triggers do not block);
        # load_definition must still fail closed on such a forgery.
        body = _valid_definition_body()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO market_marketstatedefinition "
                "(key, version, definition, definition_sha256, created_at) "
                "VALUES (%s, %s, %s, %s, now())",
                ["raw", "1.0.0", json.dumps(body), "0" * 64],
            )
        with self.assertRaises(DefinitionError):
            load_definition("raw", "1.0.0")

    def test_model_save_rejects_mismatched_sha(self):
        with self.assertRaises(ValidationError):
            MarketStateDefinition(
                key="k",
                version="1.0.0",
                definition=_valid_definition_body(),
                definition_sha256="0" * 64,
            ).save()


class ManifestCausalityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def store(self, starts, observed_at, batch, **close):
        candles = [candle(s, **close) for s in starts]
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

    def three_hours(self, observed_at, batch="a", **close):
        starts = [MON_0800 + timedelta(hours=i) for i in range(3)]  # 08,09,10 -> ends 09,10,11
        return self.store(starts, observed_at, batch, **close)

    def test_only_intervals_ended_and_available_by_cutoff_are_eligible(self):
        # Each candle can only be observed at its own close (the ledger enforces
        # observed_at >= interval_end). At a 10:00 cutoff the 10:00 candle, whose
        # interval ends at 11:00, is not yet available; the two earlier ended
        # intervals are.
        for i in range(3):
            start = MON_0800 + timedelta(hours=i)
            self.store([start], observed_at=start + timedelta(hours=1), batch=f"h{i}")
        rows = eligible_observations(self.instrument, "H1", MON_0800 + timedelta(hours=2))
        self.assertEqual([r.timestamp for r in rows], [MON_0800, MON_0800 + timedelta(hours=1)])

    def test_availability_after_cutoff_is_excluded(self):
        self.three_hours(observed_at=MON_0800 + timedelta(hours=5))  # observed 13:00
        # Cutoff at 12:00 < observed 13:00 -> nothing is yet available.
        rows = eligible_observations(self.instrument, "H1", MON_0800 + timedelta(hours=4))
        self.assertEqual(rows, [])

    def test_latest_revision_known_by_cutoff_is_used(self):
        # Revision 1 observed at 11:00; revision 2 (changed close) observed at 20:00.
        self.three_hours(observed_at=MON_0800 + timedelta(hours=3), batch="v1")
        self.store(
            [MON_0800],
            observed_at=MON_0800 + timedelta(hours=12),
            batch="v2",
            bid_close=Decimal("1.1015"),
            ask_close=Decimal("1.1017"),
        )
        # Cutoff 12:00 is before the revision-2 availability (20:00): revision 1 stands.
        rows = eligible_observations(self.instrument, "H1", MON_0800 + timedelta(hours=4))
        first = next(r for r in rows if r.timestamp == MON_0800)
        self.assertEqual(first.revision, 1)
        self.assertEqual(first.bid_close, Decimal("1.1010"))
        # Cutoff after 20:00 sees revision 2.
        later = eligible_observations(self.instrument, "H1", MON_0800 + timedelta(hours=13))
        first_later = next(r for r in later if r.timestamp == MON_0800)
        self.assertEqual(first_later.revision, 2)

    def test_manifest_is_order_independent_and_prefix_invariant(self):
        self.three_hours(observed_at=MON_0800 + timedelta(hours=3))
        cutoff = MON_0800 + timedelta(hours=3)
        _, sha_before = build_input_manifest(self.instrument, ["H1"], cutoff)
        # Append future candles (11:00, 12:00) observed later; they end after the cutoff.
        self.store(
            [MON_0800 + timedelta(hours=3), MON_0800 + timedelta(hours=4)],
            observed_at=MON_0800 + timedelta(hours=5),
            batch="future",
        )
        _, sha_after = build_input_manifest(self.instrument, ["H1"], cutoff)
        self.assertEqual(sha_before, sha_after)


class SnapshotPersistenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def setUp(self):
        self.definition = register_definition("k", "1.0.0", _valid_definition_body())

    def persist(self, output, cutoff=MON_0800, manifest=None, manifest_sha=None, scope=("H1",)):
        manifest = manifest if manifest is not None else []
        manifest_sha = manifest_sha or identity_digest(manifest)
        evidence = {"events": [], "macro": {}}
        return persist_snapshot(
            self.instrument,
            self.definition,
            cutoff,
            manifest,
            manifest_sha,
            output,
            scope=list(scope),
            evidence_manifest=evidence,
            evidence_sha256=identity_digest(evidence),
        )

    def test_persist_is_idempotent(self):
        snap1, created1 = self.persist({"v": 1})
        snap2, created2 = self.persist({"v": 1})
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(snap1.pk, snap2.pk)
        self.assertEqual(MarketStateSnapshot.objects.count(), 1)

    def test_same_identity_different_output_fails_closed(self):
        self.persist({"v": 1})
        with self.assertRaises(DeterminismViolation):
            self.persist({"v": 2})

    def test_orm_update_and_delete_are_blocked(self):
        snap, _ = self.persist({"v": 1})
        snap.data_quality_status = "degraded"
        with self.assertRaises(ValidationError):
            snap.save()
        with self.assertRaises(ValidationError):
            snap.delete()

    def test_raw_sql_update_delete_truncate_are_blocked(self):
        snap, _ = self.persist({"v": 1})
        for sql, params in (
            ("UPDATE market_marketstatesnapshot SET output_sha256='x' WHERE id=%s", [snap.pk]),
            ("DELETE FROM market_marketstatesnapshot WHERE id=%s", [snap.pk]),
            ("TRUNCATE market_marketstatesnapshot", None),
        ):
            with self.assertRaises(Error):
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(sql, params)
        self.assertTrue(MarketStateSnapshot.objects.filter(pk=snap.pk).exists())

    def test_definition_raw_update_is_blocked_by_trigger(self):
        with self.assertRaises(Error):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE market_marketstatedefinition SET version='9' WHERE id=%s",
                        [self.definition.pk],
                    )


class ComputeDescriptorTests(TestCase):
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

    def test_descriptor_definition_registers_idempotently(self):
        a = ensure_descriptor_definition()
        b = ensure_descriptor_definition()
        self.assertEqual(a.pk, b.pk)
        self.assertEqual((a.key, a.version), (DESCRIPTOR_KEY, DESCRIPTOR_VERSION))

    def test_output_is_byte_equivalent_and_idempotent(self):
        self.store([MON_0800, MON_0800 + timedelta(hours=1)], MON_0800 + timedelta(hours=2), "a")
        defn = ensure_descriptor_definition()
        cutoff = MON_0800 + timedelta(hours=2)
        snap1, created1 = compute_market_state(self.instrument, defn, cutoff, ["H1"])
        snap2, created2 = compute_market_state(self.instrument, defn, cutoff, ["H1"])
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(snap1.output_sha256, snap2.output_sha256)
        payload = snap1.output_payload
        self.assertEqual(payload["granularities"]["H1"]["eligible_candle_count"], 2)
        self.assertEqual(
            payload["granularities"]["H1"]["latest_eligible_candle"]["midpoint_close"],
            format_decimal((Decimal("1.1010") + Decimal("1.1012")) / 2),
        )
        self.assertEqual(snap1.data_quality_status, "complete")

    def test_unavailable_when_no_eligible_candles(self):
        defn = ensure_descriptor_definition()
        snap, _ = compute_market_state(self.instrument, defn, MON_0800, ["H1"])
        self.assertEqual(
            snap.output_payload["granularities"]["H1"],
            {"state": "unavailable", "reason_code": "insufficient_history"},
        )
        self.assertEqual(snap.data_quality_status, "partial")

    def test_future_candle_does_not_change_earlier_snapshot(self):
        self.store([MON_0800, MON_0800 + timedelta(hours=1)], MON_0800 + timedelta(hours=2), "a")
        defn = ensure_descriptor_definition()
        cutoff = MON_0800 + timedelta(hours=2)
        snap_before, _ = compute_market_state(self.instrument, defn, cutoff, ["H1"])
        self.store([MON_0800 + timedelta(hours=2)], MON_0800 + timedelta(hours=4), "future")
        snap_after, created = compute_market_state(self.instrument, defn, cutoff, ["H1"])
        self.assertFalse(created)
        self.assertEqual(snap_before.output_sha256, snap_after.output_sha256)
