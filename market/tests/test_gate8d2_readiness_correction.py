"""Successor readiness must report what may actually be executed now.

The database gate admits an attempt only when the governed stage is open *and*
the chunk has no attempt of its own. Before this correction the read-only
interface consulted the first condition alone, so once all 132 chunks had been
attempted it still named the remainder stage and listed all 126 completed keys
as permitted — an operator following it would have issued 126 commands that
PostgreSQL was certain to refuse.

Fixtures stay minimal: readiness never reads observation content beyond the
six-per-first-H1 warm-up threshold, so nothing here needs a real inventory.
"""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.historical_discovery import (
    build_replacement_discovery_plan,
    create_discovery_plan,
    parse_timestamp,
)
from market.models import (
    HistoricalDiscoveryAttempt,
    HistoricalTimestampInventory,
    HistoricalTimestampObservation,
    IngestionRun,
)
from market.provider_observed_successor import (
    EXPECTED_CHUNK_COUNT,
    PREDECESSOR_H1_REQUESTED_FROM,
    STAGE_CANARY,
    STAGE_CROSS_INSTRUMENT,
    STAGE_REMAINDER,
    STATUS_ATTEMPT_IN_PROGRESS,
    STATUS_BLOCKED,
    STATUS_COMPLETE,
    STATUS_INCOMPLETE_EVIDENCE,
    STATUS_NO_ELIGIBLE_CHUNK,
    STATUS_NOT_MATERIALIZED,
    STATUS_OPEN,
    build_successor_discovery_plan,
    staged_discovery_membership,
    successor_readiness,
)
from market.tests.test_gate8b_prime_successor_activation import (
    MIGRATION_0023,
    record_attempt,
    successor_first_h1,
)
from market.tests.test_replacement_canary_activation import migrate_to, seed_governed_market


def counts():
    return (
        HistoricalDiscoveryAttempt.objects.count(),
        IngestionRun.objects.count(),
        HistoricalTimestampInventory.objects.count(),
        HistoricalTimestampObservation.objects.count(),
    )


def record_bare_attempt(chunk, number):
    """A further attempt row with no inventory of its own, written with the
    governed triggers suspended. A chunk keeps one inventory however many
    attempts exist, so this is the shape a prohibited attempt 2 would take."""
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE market_historicaldiscoveryattempt DISABLE TRIGGER USER")
        cursor.execute("ALTER TABLE market_ingestionrun DISABLE TRIGGER USER")
    try:
        run = IngestionRun.objects.create(
            source=chunk.plan.source,
            instrument=chunk.instrument,
            granularity=chunk.granularity,
            requested_from=chunk.requested_from,
            requested_to=chunk.requested_to,
            parameters={},
            request_manifest_hash=f"{chunk.ordinal:058d}bare{number:02d}",
            status=IngestionRun.Status.SUCCEEDED,
        )
        return HistoricalDiscoveryAttempt.objects.create(
            chunk=chunk,
            ingestion_run=run,
            attempt_number=number,
            idempotency_key=f"historical-discovery-attempt:{chunk.logical_key}:{number}",
        )
    finally:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_historicaldiscoveryattempt ENABLE TRIGGER USER")
            cursor.execute("ALTER TABLE market_ingestionrun ENABLE TRIGGER USER")


def attach_inventory(chunk, attempt, *, salt=0):
    """A sealed inventory bound to an explicit attempt, so a test can bind one
    to the wrong attempt on purpose. Written with the governed triggers
    suspended, like every other fixture here."""
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE market_historicaltimestampinventory DISABLE TRIGGER USER")
        cursor.execute("ALTER TABLE market_historicaltimestampobservation DISABLE TRIGGER USER")
    try:
        inventory = HistoricalTimestampInventory.objects.create(
            chunk=chunk,
            accepted_attempt=attempt,
            observation_count=1,
            timestamp_set_sha256=f"{chunk.ordinal:062d}{salt:02d}",
            structural_observation_sha256=f"{chunk.ordinal:062d}{salt:02d}",
            semantic_inventory_sha256=f"{chunk.ordinal:062x}{salt:02x}",
        )
        HistoricalTimestampObservation.objects.create(
            inventory=inventory,
            timestamp=parse_timestamp(PREDECESSOR_H1_REQUESTED_FROM),
            complete=True,
            volume=1,
            bid_present=True,
            ask_present=True,
        )
        return inventory
    finally:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_historicaltimestampinventory ENABLE TRIGGER USER")
            cursor.execute("ALTER TABLE market_historicaltimestampobservation ENABLE TRIGGER USER")


class Gate8d2ReadinessCorrectionTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0023)
        self.source = seed_governed_market("gate8d2 readiness fixture")
        self.membership = staged_discovery_membership()

    def tearDown(self):
        MigrationExecutor(connection).migrate(MIGRATION_0023)
        super().tearDown()

    def materialize(self):
        self.plan = create_discovery_plan(build_successor_discovery_plan())
        self.first_h1 = successor_first_h1(self.plan)
        self.canary, self.cross = self.first_h1[0], self.first_h1[1:]
        by_key = {chunk.logical_key: chunk for chunk in self.plan.chunks.all()}
        self.remainder = [
            by_key[item["logical_discovery_key"]] for item in self.membership[STAGE_REMAINDER]
        ]
        return self.plan

    def keys(self, stage):
        return [item["logical_discovery_key"] for item in self.membership[stage]]

    def test_unmaterialized_successor_permits_nothing_and_is_not_complete(self):
        # 1
        readiness = successor_readiness()
        self.assertFalse(readiness["materialized"])
        self.assertEqual(readiness["execution_status"], STATUS_NOT_MATERIALIZED)
        self.assertFalse(readiness["complete"])
        self.assertEqual(readiness["permitted_logical_keys"], [])
        self.assertIsNone(readiness["permitted_stage"])

    def test_a_fresh_materialized_plan_exposes_only_the_canary(self):
        # 2
        self.materialize()
        readiness = successor_readiness()
        self.assertEqual(readiness["permitted_logical_keys"], self.keys(STAGE_CANARY))
        self.assertEqual(readiness["permitted_stage"], STAGE_CANARY)
        self.assertEqual(readiness["execution_status"], STATUS_OPEN)
        self.assertFalse(readiness["complete"])
        self.assertEqual(readiness["attempted_chunks"], 0)

    def test_canary_success_exposes_the_five_cross_instrument_keys(self):
        # 3, and the canary key must not reappear
        self.materialize()
        record_attempt(self.canary, status=IngestionRun.Status.SUCCEEDED)
        readiness = successor_readiness()
        self.assertEqual(readiness["permitted_logical_keys"], self.keys(STAGE_CROSS_INSTRUMENT))
        self.assertEqual(len(readiness["permitted_logical_keys"]), 5)
        self.assertEqual(readiness["permitted_stage"], STAGE_CROSS_INSTRUMENT)
        self.assertNotIn(self.canary.logical_key, readiness["permitted_logical_keys"])
        self.assertEqual(readiness["execution_status"], STATUS_OPEN)

    def test_partial_gate_8d1_exposes_only_the_unattempted_cross_instrument_keys(self):
        # 4
        self.materialize()
        record_attempt(self.canary, status=IngestionRun.Status.SUCCEEDED)
        for chunk in self.cross[:2]:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        readiness = successor_readiness()
        expected = [
            key
            for key in self.keys(STAGE_CROSS_INSTRUMENT)
            if key not in {chunk.logical_key for chunk in self.cross[:2]}
        ]
        self.assertEqual(readiness["permitted_logical_keys"], expected)
        self.assertEqual(len(readiness["permitted_logical_keys"]), 3)
        self.assertEqual(readiness["permitted_stage"], STAGE_CROSS_INSTRUMENT)
        self.assertFalse(readiness["complete"])

    def test_six_first_h1_successes_expose_exactly_the_126_remainder_keys(self):
        # 5
        self.materialize()
        for chunk in self.first_h1:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        readiness = successor_readiness()
        self.assertEqual(readiness["permitted_logical_keys"], self.keys(STAGE_REMAINDER))
        self.assertEqual(len(readiness["permitted_logical_keys"]), 126)
        self.assertEqual(readiness["permitted_stage"], STAGE_REMAINDER)
        self.assertEqual(readiness["attempted_chunks"], 6)
        self.assertFalse(readiness["complete"])

    def test_partial_gate_8d2_returns_the_remaining_keys_in_committed_order(self):
        # 6
        self.materialize()
        for chunk in self.first_h1:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        done = self.remainder[:4]
        for chunk in done:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED, earlier=1)
        readiness = successor_readiness()
        expected = [
            key
            for key in self.keys(STAGE_REMAINDER)
            if key not in {chunk.logical_key for chunk in done}
        ]
        self.assertEqual(readiness["permitted_logical_keys"], expected)
        self.assertEqual(len(readiness["permitted_logical_keys"]), 122)
        self.assertEqual(readiness["attempted_chunks"], 10)
        self.assertEqual(readiness["accepted_inventories"], 10)
        self.assertEqual(readiness["missing_inventories"], 0)
        self.assertEqual(readiness["execution_status"], STATUS_OPEN)

    def test_a_complete_plan_permits_nothing_and_reports_successful_completion(self):
        # 7
        self.materialize()
        for chunk in self.first_h1:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        for chunk in self.remainder:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED, earlier=1)
        readiness = successor_readiness()
        self.assertEqual(readiness["permitted_logical_keys"], [])
        self.assertIsNone(readiness["permitted_stage"])
        self.assertTrue(readiness["complete"])
        self.assertEqual(readiness["execution_status"], STATUS_COMPLETE)
        self.assertFalse(readiness["blocked_by_failed_attempt"])
        self.assertEqual(readiness["attempted_chunks"], EXPECTED_CHUNK_COUNT)
        self.assertEqual(readiness["chunks"], EXPECTED_CHUNK_COUNT)
        self.assertEqual(readiness["accepted_inventories"], EXPECTED_CHUNK_COUNT)
        self.assertEqual(readiness["missing_inventories"], 0)

    def attempt_everything(self, *, bare=()):
        """All 132 chunks attempted and succeeded; those in ``bare`` get a
        succeeded run with no inventory of their own."""
        skip = {chunk.pk for chunk in bare}
        for chunk in self.first_h1:
            if chunk.pk in skip:
                record_bare_attempt(chunk, 1)
            else:
                record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        for chunk in self.remainder:
            if chunk.pk in skip:
                record_bare_attempt(chunk, 1)
            else:
                record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED, earlier=1)

    def test_all_succeeded_but_one_inventory_missing_is_not_complete(self):
        # 2: 132 succeeded runs cannot stand in for 132 stored results
        self.materialize()
        self.attempt_everything(bare=[self.remainder[7]])
        readiness = successor_readiness()
        self.assertEqual(readiness["attempted_chunks"], EXPECTED_CHUNK_COUNT)
        self.assertEqual(readiness["accepted_inventories"], EXPECTED_CHUNK_COUNT - 1)
        self.assertEqual(readiness["missing_inventories"], 1)
        self.assertFalse(readiness["complete"])
        self.assertEqual(readiness["execution_status"], STATUS_INCOMPLETE_EVIDENCE)
        # attempt 2 is prohibited, so nothing becomes runnable again
        self.assertEqual(readiness["permitted_logical_keys"], [])
        self.assertIsNone(readiness["permitted_stage"])
        self.assertFalse(readiness["blocked_by_failed_attempt"])

    def test_several_missing_inventories_report_the_exact_bounded_count(self):
        # 3
        self.materialize()
        bare = [self.first_h1[2], self.remainder[0], self.remainder[40], self.remainder[125]]
        self.attempt_everything(bare=bare)
        readiness = successor_readiness()
        self.assertEqual(readiness["missing_inventories"], len(bare))
        self.assertEqual(readiness["accepted_inventories"], EXPECTED_CHUNK_COUNT - len(bare))
        self.assertFalse(readiness["complete"])
        self.assertEqual(readiness["execution_status"], STATUS_INCOMPLETE_EVIDENCE)

    def test_a_predecessor_inventory_does_not_satisfy_successor_completeness(self):
        # 4
        self.materialize()
        target = self.remainder[3]
        self.attempt_everything(bare=[target])
        legacy = create_discovery_plan(build_replacement_discovery_plan())
        legacy_chunk = legacy.chunks.order_by("ordinal").first()
        attach_inventory(legacy_chunk, record_bare_attempt(legacy_chunk, 1), salt=9)
        self.assertEqual(HistoricalTimestampInventory.objects.filter(chunk=legacy_chunk).count(), 1)
        readiness = successor_readiness()
        self.assertEqual(readiness["missing_inventories"], 1)
        self.assertEqual(readiness["accepted_inventories"], EXPECTED_CHUNK_COUNT - 1)
        self.assertFalse(readiness["complete"])
        self.assertEqual(readiness["execution_status"], STATUS_INCOMPLETE_EVIDENCE)

    def test_an_inventory_bound_to_another_attempt_does_not_satisfy_the_chunk(self):
        # 5
        self.materialize()
        starved, donor = self.remainder[5], self.remainder[6]
        self.attempt_everything(bare=[starved, donor])
        attach_inventory(starved, donor.attempts.get(), salt=1)
        self.assertEqual(HistoricalTimestampInventory.objects.filter(chunk=starved).count(), 1)
        readiness = successor_readiness()
        # the inventory exists on the right chunk but is bound to the wrong
        # attempt, so neither chunk is satisfied
        self.assertEqual(readiness["missing_inventories"], 2)
        self.assertEqual(readiness["accepted_inventories"], EXPECTED_CHUNK_COUNT - 2)
        self.assertFalse(readiness["complete"])
        self.assertEqual(readiness["execution_status"], STATUS_INCOMPLETE_EVIDENCE)

    def test_a_quarantined_attempt_is_blocked_and_not_complete(self):
        # 7
        self.materialize()
        record_attempt(self.canary, status=IngestionRun.Status.QUARANTINED)
        readiness = successor_readiness()
        self.assertEqual(readiness["permitted_logical_keys"], [])
        self.assertIsNone(readiness["permitted_stage"])
        self.assertTrue(readiness["blocked_by_failed_attempt"])
        self.assertEqual(readiness["execution_status"], STATUS_BLOCKED)
        self.assertFalse(readiness["complete"])

    def test_a_failed_attempt_permits_nothing_and_reports_the_block(self):
        # 8
        self.materialize()
        record_attempt(self.canary, status=IngestionRun.Status.FAILED)
        readiness = successor_readiness()
        self.assertEqual(readiness["permitted_logical_keys"], [])
        self.assertIsNone(readiness["permitted_stage"])
        self.assertTrue(readiness["blocked_by_failed_attempt"])
        self.assertEqual(readiness["execution_status"], STATUS_BLOCKED)
        self.assertFalse(readiness["complete"])

    def test_a_running_attempt_is_never_reported_as_available(self):
        # 9
        self.materialize()
        record_attempt(self.canary, status=IngestionRun.Status.RUNNING)
        readiness = successor_readiness()
        self.assertEqual(readiness["permitted_logical_keys"], [])
        self.assertIsNone(readiness["permitted_stage"])
        self.assertEqual(readiness["execution_status"], STATUS_ATTEMPT_IN_PROGRESS)
        self.assertFalse(readiness["complete"])
        self.assertFalse(readiness["blocked_by_failed_attempt"])

    def test_a_predecessor_failure_does_not_alter_successor_readiness(self):
        # 10: scope is relational — the successor plan's own chunks only
        self.materialize()
        legacy = create_discovery_plan(build_replacement_discovery_plan())
        record_attempt(legacy.chunks.order_by("ordinal").first(), status=IngestionRun.Status.FAILED)
        readiness = successor_readiness()
        self.assertFalse(readiness["blocked_by_failed_attempt"])
        self.assertEqual(readiness["permitted_logical_keys"], self.keys(STAGE_CANARY))
        self.assertEqual(readiness["execution_status"], STATUS_OPEN)
        self.assertEqual(readiness["attempted_chunks"], 0)

    def test_a_second_attempt_is_never_reported_as_eligible(self):
        # 11
        self.materialize()
        record_attempt(self.canary, status=IngestionRun.Status.SUCCEEDED)
        record_bare_attempt(self.canary, 2)
        self.assertEqual(self.canary.attempts.count(), 2)
        readiness = successor_readiness()
        self.assertNotIn(self.canary.logical_key, readiness["permitted_logical_keys"])
        # two attempt rows, one closed chunk: the count is of chunks, not attempts
        self.assertEqual(readiness["attempted_chunks"], 1)
        self.assertEqual(readiness["permitted_logical_keys"], self.keys(STAGE_CROSS_INSTRUMENT))

    def test_an_exhausted_stage_short_of_completion_permits_nothing(self):
        # a stage whose keys are all attempted but whose successor gate is shut
        self.materialize()
        record_attempt(self.canary, status=IngestionRun.Status.SUCCEEDED)
        for chunk in self.cross[:-1]:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        record_attempt(self.cross[-1], status=IngestionRun.Status.SUCCEEDED, earlier=1)
        readiness = successor_readiness()
        self.assertEqual(readiness["permitted_logical_keys"], [])
        self.assertIsNone(readiness["permitted_stage"])
        self.assertEqual(readiness["execution_status"], STATUS_NO_ELIGIBLE_CHUNK)
        self.assertFalse(readiness["complete"])
        self.assertFalse(readiness["blocked_by_failed_attempt"])

    def test_the_reporting_command_is_read_only_and_builds_no_provider_client(self):
        # 12
        import market.oanda as oanda

        self.materialize()
        for chunk in self.first_h1:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        for chunk in self.remainder:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED, earlier=1)
        before = counts()
        buffer = StringIO()
        with patch.object(oanda, "OandaClient", side_effect=AssertionError("client built")):
            call_command("report_gate8b_prime_readiness", stdout=buffer)
        import json

        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["permitted_logical_keys"], [])
        self.assertEqual(payload["execution_status"], STATUS_COMPLETE)
        self.assertTrue(payload["complete"])
        self.assertIsNone(payload["permitted_stage"])
        self.assertEqual(before, counts())

    def test_the_earlier_stage_outputs_keep_their_established_fields(self):
        # 13
        self.materialize()
        fresh = successor_readiness()
        self.assertEqual(fresh["permitted_stage"], STAGE_CANARY)
        self.assertFalse(fresh["canary_prerequisite_met"])
        self.assertFalse(fresh["cross_instrument_prerequisite_met"])
        record_attempt(self.canary, status=IngestionRun.Status.SUCCEEDED)
        after_canary = successor_readiness()
        self.assertEqual(after_canary["permitted_stage"], STAGE_CROSS_INSTRUMENT)
        self.assertTrue(after_canary["canary_prerequisite_met"])
        self.assertFalse(after_canary["cross_instrument_prerequisite_met"])
        for chunk in self.cross:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        after_first_h1 = successor_readiness()
        self.assertEqual(after_first_h1["permitted_stage"], STAGE_REMAINDER)
        self.assertTrue(after_first_h1["cross_instrument_prerequisite_met"])
        for readiness in (fresh, after_canary, after_first_h1):
            self.assertEqual(
                readiness["successor_plan_sha256"],
                build_successor_discovery_plan()["plan_sha256"],
            )
            self.assertTrue(readiness["materialized"])
            self.assertEqual(readiness["chunks"], EXPECTED_CHUNK_COUNT)
            self.assertFalse(readiness["blocked_by_failed_attempt"])
            self.assertFalse(readiness["complete"])
            self.assertEqual(readiness["execution_status"], STATUS_OPEN)
