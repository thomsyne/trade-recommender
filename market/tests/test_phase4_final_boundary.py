"""Recording-time races use real new evidence; historical feature fixtures are explicit."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from uuid import uuid4

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from market.models import CandleObservation, MarketStateSnapshot
from market.state import compute, liquidity, structure
from market.state.integrity import verify_snapshots
from market.state.manifest import eligible_observations
from market.tests import test_phase4_semantic_boundary as sql_fixture
from market.tests.factories import candle
from market.tests.test_live_observations import ingest, make_market
from market.tests.test_market_state_context import observation, policy, series
from market.tests.test_phase4_corrections import bar
from research.models import MacroSeries


def db_now():
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        return cursor.fetchone()[0]


def raw_observations(rows, **kwargs):
    """Insert real ingestion values using SQL, attempting to backdate recording."""
    fields = [f for f in CandleObservation._meta.local_fields if not f.primary_key]
    columns = ",".join(connection.ops.quote_name(f.column) for f in fields)
    with connection.cursor() as cursor:
        for row in rows:
            row.recorded_at = row.observed_at
            values = [f.get_db_prep_save(f.pre_save(row, True), connection) for f in fields]
            cursor.execute(
                f"INSERT INTO market_candleobservation ({columns}) VALUES "
                f"({','.join(['%s'] * len(fields))}) RETURNING id",
                values,
            )
            row.pk = cursor.fetchone()[0]
    return rows


class PrerequisiteTests(SimpleTestCase):
    def test_sweep_includes_atr_inputs_but_not_unrelated_prefix(self):
        bars = [bar(i, p) for i, p in enumerate([5] * 20 + [10, 7] + [6] * 19 + [9, 9])]
        bars[41] = bars[41]._replace(high=Decimal(11))
        # The breach candle itself closes back below resistance: no later
        # candle is needed for this same-bar reclaim.
        baseline = bars[41].end
        for index in (18, 27, 41):
            for delta in (-1, 0, 1):
                delayed = bars.copy()
                known = baseline + timedelta(seconds=delta)
                delayed[index] = delayed[index]._replace(observed_at=known)
                event = liquidity.liquidity_context(delayed, Decimal(1), "EUR_USD", "H1")[
                    "sweep_above"
                ]
                self.assertEqual(
                    datetime.fromisoformat(event["available_at"]), max(known, baseline)
                )
        bars[0] = bars[0]._replace(observed_at=baseline + timedelta(days=1))
        event = liquidity.liquidity_context(bars, Decimal(1), "EUR_USD", "H1")["sweep_above"]
        self.assertEqual(datetime.fromisoformat(event["available_at"]), baseline)

    def test_left_swing_confirmation_delays_acceptance_in_both_directions(self):
        for sign, name in ((1, "acceptance_above"), (-1, "acceptance_below")):
            bars = [
                bar(i, sign * p) for i, p in enumerate([5] * 20 + [10, 7] + [6] * 19 + [11] * 4)
            ]
            physical = bars[41].end
            baseline = bars[44].end
            for delta in (-1, 0, 1, 16 * 3600):
                known = baseline + timedelta(seconds=delta)
                delayed = bars.copy()
                delayed[18] = delayed[18]._replace(observed_at=known)
                event = liquidity.liquidity_context(delayed, Decimal(1), "EUR_USD", "H1")[name]
                self.assertEqual(datetime.fromisoformat(event["acceptance_close"]), physical)
                self.assertEqual(
                    datetime.fromisoformat(event["available_at"]), max(known, baseline)
                )

    def test_consolidation_range_breakout_failure_and_retest_dependencies(self):
        for direction in (1, -1):
            for retest in (False, True):
                prices = [10 if i % 2 else 9 for i in range(20)] + [11, 11 if retest else 8, 11, 11]
                bars = [bar(i, direction * p) for i, p in enumerate(prices)]
                if retest:
                    bars[21] = bars[21]._replace(
                        **{"low" if direction == 1 else "high": Decimal(10 * direction)}
                    )
                field = "retest_at" if retest else "failed_at"
                for index in (18, 20, 21):
                    for delta in (-1, 0, 1):
                        known = bars[21].end + timedelta(seconds=delta)
                        delayed = bars.copy()
                        delayed[index] = delayed[index]._replace(observed_at=known)
                        state = structure.structure_context(delayed, Decimal(1), "EUR_USD", "H1")[
                            "consolidation"
                        ]
                        self.assertEqual(
                            datetime.fromisoformat(state[field]), max(known, bars[21].end)
                        )
                delayed = bars.copy()
                delayed[23] = delayed[23]._replace(observed_at=bars[23].end + timedelta(days=3))
                state = structure.structure_context(delayed, Decimal(1), "EUR_USD", "H1")[
                    "consolidation"
                ]
                self.assertEqual(datetime.fromisoformat(state[field]), bars[21].end)


class RecordingBoundaryTests(TransactionTestCase):
    insert = sql_fixture.SemanticBoundaryTests.insert

    def setUp(self):
        self.instrument, self.source = make_market()
        self.definition = compute.ensure_descriptor_definition()
        now = db_now()
        self.start = (now - timedelta(days=now.weekday() + 7)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.source_at = self.start + timedelta(hours=2)
        self.role = "p4_final_" + uuid4().hex
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{self.role}" NOSUPERUSER NOLOGIN')
            cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{self.role}"')
            cursor.execute(
                f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{self.role}"'
            )
            cursor.execute(
                f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{self.role}"'
            )

    def tearDown(self):
        with connection.cursor() as cursor:
            cursor.execute(f'DROP OWNED BY "{self.role}"')
            cursor.execute(f'DROP ROLE "{self.role}"')
        super().tearDown()

    def restrict(self):
        with connection.cursor() as cursor:
            cursor.execute(f'SET LOCAL ROLE "{self.role}"')
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute("SET LOCAL statement_timeout='8s'")
            cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            self.assertFalse(cursor.fetchone()[0])

    def ingest(self, volume=100, raw=False):
        with patch("market.services.timezone.now", return_value=self.source_at):
            if raw:
                with patch.object(
                    CandleObservation.objects, "bulk_create", side_effect=raw_observations
                ):
                    return ingest(
                        self.source,
                        self.instrument,
                        [candle(self.start, volume=volume)],
                        str(volume),
                    )
            original = CandleObservation.objects.bulk_create

            def backdated(rows, **kwargs):
                for row in rows:
                    row.recorded_at = self.source_at
                return original(rows, **kwargs)

            with patch.object(CandleObservation.objects, "bulk_create", side_effect=backdated):
                return ingest(
                    self.source, self.instrument, [candle(self.start, volume=volume)], str(volume)
                )

    def build(self, cutoff):
        self.cutoff = cutoff
        (
            self.payload,
            self.scope,
            self.manifest,
            self.manifest_hash,
            self.evidence,
            self.evidence_hash,
            _,
        ) = compute.build_market_state(self.instrument, self.definition, cutoff, ["H1"])

    def test_new_orm_and_sql_evidence_cannot_backdate_recording(self):
        before = db_now()
        with transaction.atomic():
            self.restrict()
            self.ingest()
        first = CandleObservation.objects.get()
        self.assertEqual(first.observed_at, self.source_at)
        self.assertGreaterEqual(first.recorded_at, before)
        self.assertEqual(eligible_observations(self.instrument, "H1", before), [])
        self.assertEqual(
            [r.pk for r in eligible_observations(self.instrument, "H1", first.recorded_at)],
            [first.pk],
        )
        with transaction.atomic():
            self.restrict()
            self.ingest(101, raw=True)
        later = CandleObservation.objects.latest("revision")
        self.assertGreater(later.recorded_at, first.recorded_at)
        self.assertEqual(
            [r.pk for r in eligible_observations(self.instrument, "H1", first.recorded_at)],
            [first.pk],
        )

    def test_future_cutoff_rejected_by_orm_and_sql_and_db_now_allowed(self):
        self.build(db_now() + timedelta(days=1))
        with self.assertRaisesMessage(ValueError, "future_market_state_cutoff"):
            compute.compute_market_state(self.instrument, self.definition, self.cutoff, ["H1"])
        from market.state.tasks import run_compute_market_state

        with self.assertRaisesMessage(ValueError, "future_market_state_cutoff"):
            run_compute_market_state(
                {
                    "instrument": self.instrument.code,
                    "cutoff": self.cutoff.isoformat(),
                    "granularities": ["H1"],
                }
            )
        with (
            self.assertRaisesMessage(IntegrityError, "future_market_state_cutoff"),
            transaction.atomic(),
        ):
            self.restrict()
            self.insert(self.payload)
        self.build(db_now())
        with transaction.atomic():
            self.restrict()
            self.insert(self.payload)
        self.assertEqual(MarketStateSnapshot.objects.count(), 1)

    def test_repeatable_read_cannot_validate_a_stale_database_view(self):
        self.build(db_now())
        with (
            self.assertRaisesMessage(IntegrityError, "market_state_requires_read_committed"),
            transaction.atomic(),
        ):
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            self.restrict()
            self.insert(self.payload)
        self.assertEqual(MarketStateSnapshot.objects.count(), 0)

    def test_reverse_cannot_erase_new_system_recording_facts(self):
        from django.db import DatabaseError
        from django.db.migrations.executor import MigrationExecutor

        self.ingest()
        before = CandleObservation.objects.get().recorded_at
        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes()
        try:
            with self.assertRaisesMessage(
                DatabaseError, "cannot discard recorded evidence availability"
            ):
                executor.migrate([("market", "0035_market_state_evidence_guards")])
        finally:
            # A later reversible contract migration can precede the expected
            # 0036 refusal. Restore through migrations, never fixture SQL repair.
            MigrationExecutor(connection).migrate(leaves)
        self.assertEqual(CandleObservation.objects.get().recorded_at, before)

    def test_unconsumed_policy_semantics_are_immutable_but_editorial_fields_are_not(self):
        pol = policy("US", "USD")
        with (
            self.assertRaisesMessage(IntegrityError, "consumed_research_semantics_immutable"),
            transaction.atomic(),
        ):
            self.restrict()
            pol.currency = "CAD"
            pol.save(update_fields=["currency"])
        with transaction.atomic():
            self.restrict()
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE research_sourcepolicy SET quality_note='Editorial' WHERE id=%s",
                    [pol.pk],
                )
        pol.refresh_from_db()
        self.assertEqual(pol.currency, "USD")
        self.assertEqual(pol.quality_note, "Editorial")

    def race(self, first, second):
        acquired, release, started = Event(), Event(), Event()

        def holder():
            close_old_connections()
            try:
                with transaction.atomic():
                    self.restrict()
                    result = first()
                    acquired.set()
                    if not release.wait(8):
                        raise AssertionError("race release timed out")
                return result
            finally:
                connection.close()

        def waiter():
            close_old_connections()
            try:
                with transaction.atomic():
                    self.restrict()
                    started.set()
                    return second()
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(holder)
            try:
                self.assertTrue(acquired.wait(4))
                b = pool.submit(waiter)
                self.assertTrue(started.wait(2))
                deadline = monotonic() + 3
                blocked = False
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND NOT granted)"
                        )
                        blocked = cursor.fetchone()[0]
                    if blocked or b.done():
                        break
                    sleep(0.01)
                self.assertTrue(blocked, "second transaction did not wait on shared input lock")
            finally:
                release.set()
            a.result(timeout=4)
            return b.result(timeout=4)

    def test_ingestion_first_orm_reselects_under_lock(self):
        self.ingest()

        def first():
            self.ingest(101, raw=True)
            self.cutoff = db_now()

        snapshot, _ = self.race(
            first,
            lambda: compute.compute_market_state(
                self.instrument, self.definition, self.cutoff, ["H1"]
            ),
        )
        self.assertEqual(snapshot.input_manifest[0]["revision"], 2)
        self.assertEqual(verify_snapshots([snapshot])["violation_count"], 0)

    def test_ingestion_first_raw_sql_rejects_stale_selection(self):
        self.ingest()

        def first():
            self.ingest(101, raw=True)
            self.cutoff = db_now()

        def second():
            # This read cannot see the uncommitted revision; INSERT must wait,
            # then validate with a fresh READ COMMITTED view after the lock.
            self.build(self.cutoff)
            self.insert(self.payload)

        with self.assertRaises(IntegrityError):
            self.race(first, second)

    def test_snapshot_first_retains_late_arrival_only_for_later_cutoff(self):
        self.build(db_now())
        self.race(lambda: self.insert(self.payload), lambda: self.ingest(raw=True))
        old = MarketStateSnapshot.objects.get()
        self.assertEqual(old.input_manifest, [])
        self.assertEqual(verify_snapshots([old])["violation_count"], 0)
        later, _ = compute.compute_market_state(self.instrument, self.definition, db_now(), ["H1"])
        self.assertEqual(len(later.input_manifest), 1)
        self.assertEqual(verify_snapshots([old, later])["violation_count"], 0)

    def test_research_first_consumption_and_semantic_update_both_orderings(self):
        pol = policy("US", "USD")
        ser = series(pol, "immutable-rate")
        self.cutoff = db_now()

        def reject_update(raw):
            with (
                self.assertRaisesMessage(IntegrityError, "consumed_research_semantics_immutable"),
                transaction.atomic(),
            ):
                self.restrict()
                if raw:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE research_macroseries SET unit='points' WHERE id=%s", [ser.pk]
                        )
                else:
                    MacroSeries.objects.filter(pk=ser.pk).update(unit="points")

        # Keep the update-first transaction open after its rejected savepoint
        # while another connection performs the first semantic consumption.
        updated, finish_update = Event(), Event()

        def update_first():
            close_old_connections()
            try:
                with transaction.atomic():
                    self.restrict()
                    reject_update(False)
                    updated.set()
                    if not finish_update.wait(5):
                        raise AssertionError("update-first race release timed out")
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            updater = pool.submit(update_first)
            try:
                self.assertTrue(updated.wait(4))
                with transaction.atomic():
                    self.restrict()
                    observation(ser, pol, self.cutoff.date(), 5, self.cutoff, self.cutoff)
                    first_snapshot, _ = compute.compute_market_state(
                        self.instrument, self.definition, self.cutoff, ["H1"]
                    )
            finally:
                finish_update.set()
            updater.result(timeout=4)
        self.assertTrue(first_snapshot.evidence_manifest["macro"])
        self.assertEqual(verify_snapshots([first_snapshot])["violation_count"], 0)
        ser = series(pol, "immutable-rate-consumption-first")
        self.cutoff = db_now()
        entered, release = Event(), Event()

        def consume():
            close_old_connections()
            try:
                with transaction.atomic():
                    self.restrict()
                    observation(ser, pol, self.cutoff.date(), 5, self.cutoff, self.cutoff)
                    snapshot, _ = compute.compute_market_state(
                        self.instrument, self.definition, self.cutoff, ["H1"]
                    )
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError("research race release timed out")
                return snapshot
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            worker = pool.submit(consume)
            try:
                self.assertTrue(entered.wait(4))
                reject_update(True)
                with transaction.atomic():
                    self.restrict()
                    MacroSeries.objects.filter(pk=ser.pk).update(label="Editorial label")
            finally:
                release.set()
            snapshot = worker.result(timeout=4)
        ser.refresh_from_db()
        self.assertEqual(ser.unit, "%")
        self.assertEqual(ser.label, "Editorial label")
        self.assertTrue(snapshot.evidence_manifest["macro"])
        self.assertEqual(verify_snapshots([snapshot])["violation_count"], 0)


class PersistedPrerequisiteTests(TestCase):
    def seed_prices(self, prices, known):
        from market.tests.legacy_state_evidence import store_ingestion

        inst, source = make_market()
        for i, price in enumerate(prices):
            point = Decimal(price)
            at = bar(i).timestamp
            item = candle(
                at,
                **{
                    f"{side}_{part}": point
                    for side in ("bid", "ask")
                    for part in ("open", "high", "low", "close")
                },
            )
            observed = known if i == 18 else bar(i).end
            with patch("market.services.timezone.now", return_value=observed):
                store_ingestion(
                    source, inst, "H1", at, bar(i).end, [item], {"batch": str(i), "requests": []}
                )
        return inst

    def test_late_left_confirmation_is_causal_in_persistence_and_integrity(self):
        from copy import deepcopy

        known = bar(61).timestamp
        inst = self.seed_prices([5] * 20 + [10, 7] + [6] * 19 + [11] * 4, known)
        definition = compute.ensure_descriptor_definition()
        for delta in (-1, 0, 1):
            snapshot, _ = compute.compute_market_state(
                inst, definition, known + timedelta(seconds=delta), ["H1"]
            )
            event = snapshot.output_payload["granularities"]["H1"]["liquidity"].get(
                "acceptance_above"
            )
            if delta < 0:
                self.assertIsNone(event)
            else:
                self.assertEqual(datetime.fromisoformat(event["available_at"]), known)
            self.assertEqual(verify_snapshots([snapshot])["violation_count"], 0)
        forged = deepcopy(snapshot)
        event = forged.output_payload["granularities"]["H1"]["liquidity"]["acceptance_above"]
        event["available_at"] = bar(41).timestamp.isoformat(timespec="microseconds")
        codes = {v["code"] for v in verify_snapshots([forged])["violations"]}
        self.assertIn("liquidity_availability_chronology", codes)
        self.assertIn("feature_semantics_mismatch", codes)

    def test_late_range_is_causal_in_persistence_and_integrity(self):
        from copy import deepcopy

        known = bar(41).timestamp
        inst = self.seed_prices([10 if i % 2 else 9 for i in range(20)] + [11, 8, 11, 11], known)
        definition = compute.ensure_descriptor_definition()
        for delta in (-1, 0, 1):
            snapshot, _ = compute.compute_market_state(
                inst, definition, known + timedelta(seconds=delta), ["H1"]
            )
            state = snapshot.output_payload["granularities"]["H1"]["structure"]["consolidation"]
            if delta < 0:
                self.assertEqual(state["state"], "unavailable")
            else:
                self.assertEqual(datetime.fromisoformat(state["failed_at"]), known)
                self.assertEqual(datetime.fromisoformat(state["failure_at"]), bar(21).end)
            self.assertEqual(verify_snapshots([snapshot])["violation_count"], 0)
        forged = deepcopy(snapshot)
        state = forged.output_payload["granularities"]["H1"]["structure"]["consolidation"]
        state["failed_at"] = (known - timedelta(seconds=1)).isoformat(timespec="microseconds")
        codes = {v["code"] for v in verify_snapshots([forged])["violations"]}
        self.assertIn("consolidation_availability_chronology", codes)
        self.assertIn("feature_semantics_mismatch", codes)
