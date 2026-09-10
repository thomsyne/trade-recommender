"""Phase 4 slice 10 — discriminating tests for the second independent review.

Each test targets a specific finding so its fix is provable and cannot silently
regress: snapshot identity binds scope and consumed inputs; registered-interval
consecutiveness; contemporaneous ATR; prior-month completeness; definition
governance; terminology fail-closed; integrity semantic detection; and the
database-boundary rejection of malformed inserts.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from market.models import MarketStateSnapshot
from market.services import store_ingestion
from market.state import compute, terminology
from market.state.canonical import identity_digest
from market.state.compute import (
    compute_market_state,
    ensure_descriptor_definition,
)
from market.state.definitions import DefinitionError, register_definition
from market.state.features import Bar
from market.state.fvg import find_fvgs
from market.state.integrity import verify_snapshots
from market.state.manifest import eligible_observations
from market.tests.factories import candle
from market.tests.test_live_observations import make_market

MON = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
PIP = Decimal("0.0001")


def _valid_other_body():
    return {
        "algorithms": {"x": "v1"},
        "features": ["a"],
        "price_basis": "midpoint",
        "rounding": {"quantum": "0.000001", "mode": "ROUND_HALF_EVEN"},
        "calendar_policy": "ny-fx-week-v1",
        "missing_data_policy": "explicit-unavailable-v1",
        "lookbacks": {},
        "thresholds": {},
    }


def h1_bar(i, high, low, close, open_=None, *, gap=False):
    ts = MON + timedelta(hours=i)
    end = ts + timedelta(hours=1)
    return Bar(
        timestamp=ts,
        open=Decimal(str(close if open_ is None else open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        end=(ts if gap else end),  # gap=True breaks end==next.timestamp
        spread=Decimal("0.0002"),
    )


class IdentityBindsScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def _store_h1(self, starts, observed_at, batch):
        candles = [candle(s) for s in starts]
        with patch("market.services.timezone.now", return_value=observed_at):
            store_ingestion(
                self.source,
                self.instrument,
                "H1",
                starts[0],
                starts[-1] + timedelta(hours=1),
                candles,
                {"batch": batch, "requests": []},
            )

    def test_empty_scopes_do_not_collide(self):
        defn = ensure_descriptor_definition()
        s_m15, c1 = compute_market_state(self.instrument, defn, MON, ["M15"])
        s_h4, c2 = compute_market_state(self.instrument, defn, MON, ["H4"])
        self.assertTrue(c1 and c2)
        self.assertNotEqual(s_m15.idempotency_key, s_h4.idempotency_key)

    def test_adding_a_consumed_m15_candle_changes_an_h1_snapshot_identity(self):
        defn = ensure_descriptor_definition()
        self._store_h1([MON, MON + timedelta(hours=1)], MON + timedelta(hours=2), "h1")
        cutoff = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)  # after both H1 and the M15 close
        before, _ = compute_market_state(self.instrument, defn, cutoff, ["H1"])
        # An M15 candle the ORB reads is now in the manifest, so recomputing at the
        # same cutoff yields a NEW identity, not a determinism collision.
        m15_open = datetime(2026, 1, 5, 13, 0, tzinfo=UTC)  # NY 08:00, ends 13:15 <= cutoff
        with patch("market.services.timezone.now", return_value=m15_open + timedelta(minutes=15)):
            store_ingestion(
                self.source,
                self.instrument,
                "M15",
                m15_open,
                m15_open + timedelta(minutes=15),
                [candle(m15_open)],
                {"batch": "m15", "requests": []},
            )
        after, created = compute_market_state(self.instrument, defn, cutoff, ["H1"])
        self.assertTrue(created)
        self.assertNotEqual(before.idempotency_key, after.idempotency_key)


class ConsecutivenessTests(TestCase):
    def test_gap_between_candles_is_not_an_fvg(self):
        # A clean bullish gap over three consecutive bars is found (middle candle
        # displaces up: open 10 -> close 13, body 3 >= 1*ATR)...
        consecutive = [h1_bar(0, 10, 9, 9.5), h1_bar(1, 13, 10, 13, 10), h1_bar(2, 14, 11, 13)]
        self.assertEqual(len(find_fvgs(consecutive, PIP, atr_override=Decimal("1"))["fvgs"]), 1)
        # ...but the same prices with a gap (candle 1 does not end where 2 starts)
        # are not, because a missing registered interval is not a gap.
        gapped = [h1_bar(0, 10, 9, 9.5, gap=True), h1_bar(1, 13, 10, 13, 10), h1_bar(2, 14, 11, 13)]
        self.assertEqual(find_fvgs(gapped, PIP, atr_override=Decimal("1"))["fvgs"], [])


class ContemporaneousAtrTests(TestCase):
    def test_appending_volatile_bars_does_not_requalify_a_past_gap(self):
        # 18 flat bars (ATR settles) then a bullish gap whose middle candle
        # displaces up (open 10 -> close 13); the gap is qualified against the ATR
        # contemporaneous with candle 3.
        bars = [h1_bar(i, 10.5, 9.5, 10) for i in range(18)]
        bars += [h1_bar(18, 10.5, 9.5, 10), h1_bar(19, 13, 10, 13, 10), h1_bar(20, 14, 11, 13)]
        before = find_fvgs(bars, PIP)["fvgs"]
        self.assertEqual(len(before), 1)
        gap_atr = before[0]["gap_atr"]
        # Append 14 very high-range bars (after the gap); the past gap's
        # ATR-normalization is fixed because it used candle 3's contemporaneous ATR.
        bars += [h1_bar(21 + j, 200, 0, 100) for j in range(14)]
        after = [
            g for g in find_fvgs(bars, PIP)["fvgs"] if g["created_at"] == before[0]["created_at"]
        ]
        self.assertEqual(after[0]["gap_atr"], gap_atr)


class PriorMonthCompletenessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def test_single_day_is_not_a_completed_month(self):
        from market.tests.factories import daily_sessions

        # One daily candle in January, evaluated in February: not a completed month.
        sessions = daily_sessions(1, before=datetime(2026, 1, 20, tzinfo=UTC))
        observed = sessions[-1] + timedelta(days=1)
        with patch("market.services.timezone.now", return_value=observed):
            store_ingestion(
                self.source,
                self.instrument,
                "D",
                sessions[0],
                sessions[-1] + timedelta(days=1),
                [candle(sessions[0])],
                {"batch": "d", "requests": []},
            )
        result = compute._prior_completed_month(self.instrument, datetime(2026, 2, 2, tzinfo=UTC))
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["reason_code"], "incomplete_period")


class DefinitionGovernanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def test_computing_under_a_nonmatching_definition_fails_closed(self):
        with self.assertRaises(DefinitionError):
            register_definition("undefined", "0.0.0", _valid_other_body())


class TerminologyTests(TestCase):
    def test_banned_vocabulary_and_unknown_version_are_flagged(self):
        self.assertEqual(
            terminology.terminology_violations({"note": "A+ setup"}), ["banned_vocabulary"]
        )
        self.assertEqual(
            terminology.terminology_violations({"x": {"version": "made-up-v9"}}),
            ["noncanonical_terminology"],
        )
        self.assertEqual(terminology.terminology_violations({"x": {"version": "swing-v1"}}), [])


class IntegritySemanticTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def test_self_consistent_but_contradictory_snapshot_is_detected(self):
        definition = ensure_descriptor_definition()
        payload = {
            "schema": "market-state/descriptor-v0",
            "definition": [definition.key, definition.version],
            "instrument": "WRONG_PAIR",  # not the snapshot's instrument
            "granularities": {"M1": {"note": "A+ setup"}},  # unsupported + banned
        }
        manifest = []
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO market_marketstatesnapshot "
                "(instrument_id, definition_id, information_cutoff, created_at, input_manifest, "
                "input_manifest_sha256, evidence_manifest, output_payload, output_sha256, "
                "data_quality_status, idempotency_key) VALUES (%s,%s,%s, now(), %s,%s,%s,%s,%s,%s,%s)",
                [
                    self.instrument.pk,
                    definition.pk,
                    MON,
                    json.dumps(manifest),
                    identity_digest(manifest),
                    json.dumps({}),
                    json.dumps(payload),
                    identity_digest(payload),
                    "complete",
                    "a" * 64,
                ],
            )
        codes = {
            v["code"]
            for v in verify_snapshots(
                [
                    MarketStateSnapshot(
                        pk=1,
                        instrument=self.instrument,
                        definition=definition,
                        information_cutoff=MON,
                        input_manifest=manifest,
                        input_manifest_sha256=identity_digest(manifest),
                        evidence_manifest={},
                        output_payload=payload,
                        output_sha256=identity_digest(payload),
                        data_quality_status="complete",
                        idempotency_key="a" * 64,
                    )
                ]
            )["violations"]
        }
        self.assertIn("payload_instrument_mismatch", codes)
        self.assertIn("unsupported_granularity", codes)
        self.assertIn("banned_vocabulary", codes)


class DatabaseBoundaryTests(TestCase):
    def _insert_definition(self, body, sha):
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO market_marketstatedefinition (key, version, definition, "
                "definition_sha256, created_at) VALUES (%s,%s,%s,%s, now())",
                ["raw", "1.0.0", json.dumps(body), sha],
            )

    def test_malformed_hash_is_rejected_at_insert(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._insert_definition({"a": 1}, "bogus")

    def test_non_object_definition_body_is_rejected_at_insert(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._insert_definition([], "0" * 64)


class BoundedScanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, cls.source = make_market()

    def test_lookback_bounds_the_result(self):
        starts = [MON + timedelta(hours=i) for i in range(8)]
        with patch("market.services.timezone.now", return_value=MON + timedelta(hours=9)):
            store_ingestion(
                self.source,
                self.instrument,
                "H1",
                starts[0],
                starts[-1] + timedelta(hours=1),
                [candle(s) for s in starts],
                {"batch": "h1", "requests": []},
            )
        cutoff = MON + timedelta(hours=9)
        self.assertEqual(len(eligible_observations(self.instrument, "H1", cutoff)), 8)
        bounded = eligible_observations(self.instrument, "H1", cutoff, lookback=3)
        self.assertEqual(len(bounded), 3)
        self.assertEqual([b.timestamp for b in bounded], starts[-3:])  # newest three, ascending
