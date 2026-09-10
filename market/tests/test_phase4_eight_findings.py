"""Independent-review regressions; first executed on exact 0188ee5."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TestCase

from market.state import compute, context, features, orb, sessions, structure
from market.state.canonical import identity_digest
from market.tests import test_phase4_semantic_boundary as sql_fixture
from market.tests.test_market_state_context import (
    CUTOFF,
    event,
    instrument,
    observation,
    policy,
    series,
)
from market.tests.test_phase4_corrections import bar


class ResearchReviewTests(TestCase):
    def test_future_candidate_cannot_change_old_identity(self):
        inst = instrument()
        pol = policy("US", "USD")
        event(pol, "US", CUTOFF + timedelta(days=30), CUTOFF - timedelta(days=2))
        before = context.freeze_research(inst, CUTOFF, CUTOFF)
        event(pol, "US", CUTOFF + timedelta(days=1), CUTOFF + timedelta(seconds=1))
        after = context.freeze_research(inst, CUTOFF, CUTOFF)
        self.assertEqual(len(before["events"]), len(after["events"]))
        self.assertEqual(context.event_state(inst, CUTOFF, frozen=after)["state"], "unavailable")
        event(pol, "US", CUTOFF + timedelta(days=1), CUTOFF - timedelta(hours=2), key="suppressed")
        event(pol, "US", CUTOFF + timedelta(days=45), CUTOFF, key="suppressed")
        frozen = context.freeze_research(inst, CUTOFF, CUTOFF)
        self.assertEqual(context.event_state(inst, CUTOFF, frozen=frozen)["events"], [])
        self.assertEqual(len(frozen["events"]), 2)

    def test_pair_uses_canonical_code(self):
        inst = instrument()
        before = context.macro_regime(inst, CUTOFF, frozen={"events": (), "rates": ()})
        inst.base_currency = "GBP"
        self.assertEqual(
            before, context.macro_regime(inst, CUTOFF, frozen={"events": (), "rates": ()})
        )

    def test_unused_macro_history_does_not_change_identity(self):
        inst = instrument()
        pol = policy("US", "USD")
        ser = series(pol, "rate")
        for month, value in ((12, 4), (1, 5)):
            observation(
                ser,
                pol,
                date(2025 if month == 12 else 2026, month, 1),
                value,
                CUTOFF - timedelta(days=1),
                CUTOFF - timedelta(days=1),
            )
        definition = compute.ensure_descriptor_definition()
        before = compute.build_market_state(inst, definition, CUTOFF, ["H1"])
        observation(
            ser, pol, date(2025, 11, 1), 9, CUTOFF - timedelta(days=1), CUTOFF - timedelta(days=1)
        )
        after = compute.build_market_state(inst, definition, CUTOFF, ["H1"])
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[4], after[4])

    def test_quality_note_is_irrelevant_and_facts_are_immutable(self):
        inst = instrument()
        pol = policy("US", "USD")
        ser = series(pol, "rate")
        observation(
            ser, pol, date(2026, 1, 1), 5, CUTOFF - timedelta(days=1), CUTOFF - timedelta(days=1)
        )
        frozen = context.freeze_research(inst, CUTOFF, CUTOFF)
        before = context.macro_regime(inst, CUTOFF, frozen=frozen)
        definition = compute.ensure_descriptor_definition()
        snapshot, _ = compute.compute_market_state(inst, definition, CUTOFF, ["H1"])
        pol.quality_note = "unrelated editorial note"
        pol.save(update_fields=["quality_note"])
        after = context.macro_regime(inst, CUTOFF)
        self.assertEqual(before, after)
        with self.assertRaises((AttributeError, TypeError)):
            frozen["rates"][0].value = Decimal(99)
        with self.assertNumQueries(0):
            self.assertEqual(before, context.macro_regime(inst, CUTOFF, frozen=frozen))
            compute.build_market_state(
                inst,
                definition,
                CUTOFF,
                ["H1"],
                frozen_inputs=({g: () for g in compute.LOOKBACKS}, frozen),
            )
        from market.state.integrity import verify_snapshots

        self.assertEqual(verify_snapshots([snapshot])["violation_count"], 0)
        for obj, field, value in ((pol, "jurisdiction", "CA"), (ser, "unit", "points")):
            setattr(obj, field, value)
            with self.assertRaises(IntegrityError), transaction.atomic():
                obj.save(update_fields=[field])


class CausalReviewTests(SimpleTestCase):
    def test_orb_downstream_availability_in_both_sessions(self):
        for name in sessions.SESSIONS:
            start, local, tz = sessions.session_open_utc(date(2026, 1, 5), name)
            opening = bar(0, 9)._replace(
                timestamp=start, end=start + timedelta(minutes=15), high=Decimal(10), low=Decimal(9)
            )
            breakout = opening._replace(
                timestamp=opening.end,
                end=start + timedelta(minutes=30),
                close=Decimal(11),
                high=Decimal(11),
            )
            failure = breakout._replace(
                timestamp=breakout.end,
                end=start + timedelta(minutes=45),
                close=Decimal(8),
                low=Decimal(8),
            )
            for delay in (timedelta(minutes=20), timedelta(minutes=45), timedelta(hours=4)):
                with self.subTest(name=name, delay=delay):
                    late = opening._replace(observed_at=start + delay)
                    result = orb.opening_range(
                        late,
                        [breakout, failure],
                        Decimal(1),
                        Decimal(1),
                        session_name=name,
                        local_open=local,
                        tzinfo=tz,
                    )
                    self.assertGreaterEqual(result["failed_at"], result["available_at"])
                    self.assertEqual(
                        result["failed_at"], orb._iso(max(late.available_at, failure.available_at))
                    )
                    retest = failure._replace(close=Decimal(11), high=Decimal(12), low=Decimal(10))
                    held = orb.opening_range(
                        late,
                        [breakout, retest],
                        Decimal(1),
                        Decimal(1),
                        session_name=name,
                        local_open=local,
                        tzinfo=tz,
                    )
                    self.assertEqual(
                        held["retest_at"], orb._iso(max(late.available_at, retest.available_at))
                    )
                    from market.state.manifest import FrozenObservation

                    rows = [
                        FrozenObservation(
                            "M15",
                            b.timestamp,
                            b.end,
                            b.available_at,
                            1,
                            "a" * 64,
                            b.open,
                            b.high,
                            b.low,
                            b.close,
                            b.open,
                            b.high,
                            b.low,
                            b.close,
                        )
                        for b in (late, breakout, failure)
                    ]
                    production = compute._orb_block(
                        None, max(r.observed_at for r in rows) + timedelta(seconds=1), rows
                    )[name]
                    self.assertGreaterEqual(production["failed_at"], production["available_at"])
        from types import SimpleNamespace

        from market.models import Instrument
        from market.state.integrity import _verify_payload

        bad = deepcopy(result)
        self.assertIn("failed_formed_at", bad)
        self.assertEqual(bad["failed_formed_at"], orb._iso(failure.end))
        bad["failed_at"] = orb._iso(failure.end)
        sample = SimpleNamespace(
            pk=1,
            instrument=Instrument(code="EUR_USD", base_currency="EUR", quote_currency="USD"),
            information_cutoff=CUTOFF,
            output_payload={"opening_range": {"new_york": bad}},
        )
        codes = []
        _verify_payload(
            sample, SimpleNamespace(key="k", version="v"), lambda _, code, *args: codes.append(code)
        )
        self.assertIn("orb_availability_chronology", codes)
        bad["failed_at"] = []
        codes.clear()
        _verify_payload(
            sample, SimpleNamespace(key="k", version="v"), lambda _, code, *args: codes.append(code)
        )
        self.assertIn("malformed_orb_chronology", codes)

    def test_unrelated_early_observation_does_not_delay_zone(self):
        bars = [bar(i, 5) for i in range(20)]
        bars += [bar(i, price) for i, price in enumerate((10, 7, 6, 10), 20)]
        before = structure.support_resistance_zones(bars, None, "EUR_USD", "H1")
        bars[0] = bars[0]._replace(observed_at=bars[-1].end + timedelta(days=2))
        self.assertEqual(before, structure.support_resistance_zones(bars, None, "EUR_USD", "H1"))
        self.assertEqual(before["zones"][0]["distinct_tests"], 1)
        bars[22] = bars[22]._replace(observed_at=bars[-1].end + timedelta(days=1))
        delayed = structure.support_resistance_zones(bars, None, "EUR_USD", "H1")["zones"][0]
        self.assertGreater(delayed["available_at"], before["zones"][0]["available_at"])
        self.assertEqual(delayed["distinct_tests"], 0)

    def test_missing_exact_prior_day_is_unavailable(self):
        from types import SimpleNamespace

        start = CUTOFF.replace(day=28, month=1, hour=22)
        row = SimpleNamespace(
            timestamp=start,
            interval_end=start + timedelta(days=1),
            observed_at=start + timedelta(days=1),
            granularity="D",
            revision=1,
            content_sha256="a" * 64,
            **{
                f"{side}_{field}": Decimal(1)
                for side in ("bid", "ask")
                for field in ("open", "high", "low", "close")
            },
        )
        # Production caller must pass the cutoff, not choose the last available row.
        frozen = {g: () for g in compute.LOOKBACKS}
        frozen["D"] = (row,)
        from types import SimpleNamespace

        definition = SimpleNamespace(
            key=compute.DESCRIPTOR_KEY,
            version=compute.DESCRIPTOR_VERSION,
            definition=compute.DESCRIPTOR_DEFINITION,
            definition_sha256=identity_digest(compute.DESCRIPTOR_DEFINITION),
        )
        inst = SimpleNamespace(code="EUR_USD", base_currency="EUR", quote_currency="USD")
        payload = compute.build_market_state(
            inst, definition, CUTOFF, ["H1"], frozen_inputs=(frozen, {"events": (), "rates": ()})
        )[0]
        self.assertEqual(payload["prior_extremes"]["prior_day"]["state"], "unavailable")
        self.assertEqual(
            payload["prior_extremes"]["prior_day"]["utc_start"], "2026-01-29T22:00:00.000000+00:00"
        )
        self.assertEqual(
            payload["prior_extremes"]["prior_week"]["utc_start"], "2026-01-23T22:00:00.000000+00:00"
        )
        from market.services import live_candle_completion
        from market.state.manifest import FrozenObservation

        expected = row.timestamp + timedelta(days=1)
        exact = FrozenObservation.from_row(row)._replace(
            timestamp=expected,
            interval_end=live_candle_completion(expected, "D"),
            observed_at=CUTOFF,
        )
        available = compute._prior_extreme([exact], CUTOFF, "D")
        self.assertEqual(available["state"], "available")
        self.assertEqual(available["available_at"], context._iso(CUTOFF))
        stale_month = features.Bar(row.timestamp, Decimal(1), Decimal(2), Decimal(0), Decimal(1))
        with patch.object(compute, "_completed_months", return_value=[("2025-12", stale_month)]):
            missing = compute._prior_completed_month(inst, CUTOFF, [])
        self.assertEqual(missing["state"], "unavailable")
        self.assertEqual(missing["month"], "2026-01")

    def test_compression_expansion_relationship_is_emitted(self):
        bars = [bar(i)._replace(high=Decimal(12), low=Decimal(10)) for i in range(35)]
        bars += [
            bar(i)._replace(high=Decimal("11.05"), low=Decimal("10.95")) for i in range(35, 55)
        ]
        bars += [bar(55, 60)._replace(open=Decimal(11), high=Decimal(100), low=Decimal(0))]
        result = features.higher_timeframe_context(bars)
        self.assertIn("compression_before_expansion", result)
        self.assertEqual(result["compression_before_expansion"]["state"], "available")
        transition = result["compression_before_expansion"]["transitions"][0]
        self.assertEqual(transition["direction"], "up")
        self.assertEqual(transition["successor_count"], 1)
        self.assertEqual(transition["body_atr"], "490.000000")
        self.assertEqual(features.compression_before_expansion(bars[:-1])["state"], "pending")
        appended = bars + [bar(56), bar(57)]
        self.assertEqual(
            features.compression_before_expansion(appended)["transitions"][0], transition
        )
        self.assertEqual(
            features.compression_before_expansion(bars[:40] + bars[41:])["transitions"], []
        )
        # Boundary body normalized by the independently known preceding ATR=0.1.
        for body, qualifies in (("0.149999", False), ("0.15", True), ("0.150001", True)):
            final = bars[-1]._replace(close=Decimal(11) + Decimal(body))
            self.assertEqual(
                bool(features.compression_before_expansion(bars[:-1] + [final])["transitions"]),
                qualifies,
            )
        reverse = [bars[-1]._replace(timestamp=bars[0].timestamp, end=bars[0].end)] + bars[1:-1]
        self.assertEqual(features.compression_before_expansion(reverse)["transitions"], [])
        for distance, qualifies in ((19, True), (20, True), (21, False)):
            values = (
                [Decimal(1)] * 34 + [Decimal("0.1")] + [Decimal(2)] * (distance - 1) + [Decimal(3)]
            )
            between = [bar(i) for i in range(34 + distance)]
            final = bars[-1]._replace(
                timestamp=bar(34 + distance).timestamp, end=bar(34 + distance).end
            )
            with patch.object(features, "atr_at_index", side_effect=lambda _, i: values[i]):
                actual = features.compression_before_expansion(between + [final])
            self.assertEqual(bool(actual["transitions"]), qualifies)
        downward = bars[-1]._replace(close=Decimal(-38), low=Decimal(-100))
        self.assertEqual(
            features.compression_before_expansion(bars[:-1] + [downward])["transitions"][0][
                "direction"
            ],
            "down",
        )
        # Isolate strict percentile classification from the independently tested ATR.
        values = [Decimal(1)] * 40
        values[29:34] = [Decimal(5)] * 5
        values[34] = Decimal("0.1")
        boundary_bars = bars[:39] + [
            bars[-1]._replace(timestamp=bar(39).timestamp, end=bar(39).end)
        ]
        for value, qualifies in (("5", False), ("5.000001", True)):
            values[39] = Decimal(value)  # 20/25 strictly smaller = exactly 80 at 5
            with patch.object(features, "atr_at_index", side_effect=lambda _, i: values[i]):
                self.assertEqual(
                    bool(features.compression_before_expansion(boundary_bars)["transitions"]),
                    qualifies,
                )
        values = [Decimal(1)] * 36
        values[14:18] = [Decimal("0.1")] * 4
        values[35] = Decimal(10)
        boundary_bars = bars[:35] + [
            bars[-1]._replace(timestamp=bar(35).timestamp, end=bar(35).end)
        ]
        with patch.object(features, "atr_at_index", side_effect=lambda _, i: values[i]):
            self.assertEqual(
                features.compression_before_expansion(boundary_bars)["transitions"], []
            )


class SqlReviewTests(TestCase):
    insert = sql_fixture.SemanticBoundaryTests.insert

    def setUp(self):
        from uuid import uuid4

        sql_fixture.SemanticBoundaryTests.setUp(self)
        role = "p4_eight_" + uuid4().hex
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOLOGIN')
            cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            cursor.execute(
                f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"'
            )
            cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
            cursor.execute(f'SET LOCAL ROLE "{role}"')
            cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            self.assertFalse(cursor.fetchone()[0])

    def test_forged_macro_digest_rejected(self):
        pol = policy("US", "USD")
        ser = series(pol, "rate")
        observation(
            ser,
            pol,
            date(2026, 1, 1),
            5,
            self.cutoff - timedelta(days=1),
            self.cutoff - timedelta(days=1),
        )
        built = compute.build_market_state(self.instrument, self.definition, self.cutoff, ["H1"])
        self.evidence = deepcopy(built[4])
        next(iter(self.evidence["macro"].values()))[0]["content_sha256"] = "0" * 64
        self.evidence_hash = identity_digest(self.evidence)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.insert(built[0])
        from market.tests.test_market_state_context import retrieval

        unrelated = retrieval(pol, self.cutoff - timedelta(hours=1))
        self.evidence = deepcopy(built[4])
        next(iter(self.evidence["macro"].values()))[1] = context.record_identity(unrelated)
        self.evidence_hash = identity_digest(self.evidence)
        with (
            self.assertRaisesMessage(IntegrityError, "market_state_research_lineage_mismatch"),
            transaction.atomic(),
        ):
            self.insert(built[0])
        self.evidence = built[4]
        self.evidence_hash = built[5]
        self.insert(built[0])

    def test_earlier_latest_candle_rejected(self):
        from market.tests.factories import candle
        from market.tests.legacy_state_evidence import ingest
        from market.tests.test_live_observations import make_market

        _, source = make_market()
        with patch("market.services.timezone.now", return_value=self.cutoff):
            ingest(
                source,
                self.instrument,
                [candle(self.cutoff - timedelta(hours=i)) for i in (3, 2)],
                "latest",
            )
        built = compute.build_market_state(self.instrument, self.definition, self.cutoff, ["H1"])
        self.manifest = built[2]
        payload = deepcopy(built[0])
        latest = payload["granularities"]["H1"]["latest_eligible_candle"]
        latest["timestamp"] = self.manifest[0]["timestamp"]
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.insert(payload)
        payload = deepcopy(built[0])
        payload["granularities"]["H1"]["eligible_candle_count"] = 1
        payload["granularities"]["H1"]["latest_eligible_candle"]["timestamp"] = self.manifest[0][
            "timestamp"
        ]
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.insert(payload, manifest=self.manifest[:1])
        # SQL elapsed-time horizons must match Python even under a caller's DST zone.
        from datetime import UTC, datetime

        from market.tests.legacy_state_evidence import store_ingestion

        start = datetime(2023, 1, 5, 22, tzinfo=UTC)
        with patch("market.services.timezone.now", return_value=start + timedelta(days=1)):
            store_ingestion(
                source,
                self.instrument,
                "D",
                start,
                start + timedelta(days=1),
                [candle(start)],
                {"batch": "horizon", "requests": []},
            )
        self.cutoff = start + timedelta(days=1214, minutes=-30)
        empty = compute.build_market_state(
            self.instrument,
            self.definition,
            self.cutoff,
            ["H1"],
            frozen_inputs=({g: () for g in compute.LOOKBACKS}, {"events": (), "rates": ()}),
        )
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL TIME ZONE 'America/New_York'")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.insert(empty[0], manifest=[])
