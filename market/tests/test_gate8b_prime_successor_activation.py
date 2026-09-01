"""Gate 8B': pre-discovery execution authority for the successor plan.

The successor plan may be materialized and executed in its governed order, and
nothing more. Sealing, approval and registration stay closed, so the tests that
matter most here are the ones proving a *complete* successor still cannot reach
them.

Fixtures stay small on purpose: six earlier observations per first-H1 inventory
is exactly the governed threshold, so nothing needs 364,953 rows to prove a
staged transition.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from market.historical_discovery import (
    DISCOVERY_V2_PLAN_SHA256,
    begin_discovery_attempt,
    build_replacement_discovery_plan,
    canonical_hash,
    create_discovery_plan,
    parse_timestamp,
)
from market.models import (
    HistoricalDiscoveryAttempt,
    HistoricalDiscoveryPlan,
    HistoricalTimestampInventory,
    HistoricalTimestampObservation,
    IngestionRun,
)
from market.provider_observed_successor import (
    CANARY_INSTRUMENT,
    EXPECTED_CHUNK_COUNT,
    MINIMUM_EARLIER_OBSERVATIONS,
    PREDECESSOR_H1_REQUESTED_FROM,
    STAGE_CANARY,
    STAGE_CROSS_INSTRUMENT,
    STAGE_REMAINDER,
    SUCCESSOR_H1_REQUESTED_FROM,
    build_successor_discovery_plan,
    staged_discovery_membership,
    successor_readiness,
    successor_stage,
)
from market.services import DatasetQualityError
from market.tests.test_replacement_canary_activation import migrate_to, seed_governed_market

MIGRATION_0022 = [("market", "0022_provider_observed_registration_validator_correction")]
MIGRATION_0023 = [("market", "0023_gate8b_prime_successor_discovery_activation")]


def successor_first_h1(plan):
    """The six governed extended first-H1 chunks, canary first."""
    chunks = [
        chunk
        for chunk in plan.chunks.select_related("instrument").order_by("ordinal")
        if chunk.granularity == "H1"
        and chunk.canonical_request.get("from") == SUCCESSOR_H1_REQUESTED_FROM
    ]
    return sorted(chunks, key=lambda c: c.instrument.code != CANARY_INSTRUMENT)


def record_attempt(chunk, *, status, earlier=MINIMUM_EARLIER_OBSERVATIONS, number=1, salt=0):
    """A terminal attempt with a sealed inventory, written with the governed
    triggers suspended: these fixtures exist to exercise the *next* transition,
    not to re-prove the ingestion path."""
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE market_historicaldiscoveryattempt DISABLE TRIGGER USER")
        cursor.execute("ALTER TABLE market_historicaltimestampinventory DISABLE TRIGGER USER")
        cursor.execute("ALTER TABLE market_historicaltimestampobservation DISABLE TRIGGER USER")
        cursor.execute("ALTER TABLE market_ingestionrun DISABLE TRIGGER USER")
    try:
        run = IngestionRun.objects.create(
            source=chunk.plan.source,
            instrument=chunk.instrument,
            granularity=chunk.granularity,
            requested_from=chunk.requested_from,
            requested_to=chunk.requested_to,
            parameters={},
            request_manifest_hash=f"{chunk.ordinal:060d}{number:02d}{salt:02d}",
            status=status,
        )
        attempt = HistoricalDiscoveryAttempt.objects.create(
            chunk=chunk,
            ingestion_run=run,
            attempt_number=number,
            idempotency_key=f"historical-discovery-attempt:{chunk.logical_key}:{number}",
        )
        if status == IngestionRun.Status.SUCCEEDED:
            inventory = HistoricalTimestampInventory.objects.create(
                chunk=chunk,
                accepted_attempt=attempt,
                observation_count=earlier,
                timestamp_set_sha256=f"{chunk.ordinal:064d}",
                structural_observation_sha256=f"{chunk.ordinal:064d}",
                semantic_inventory_sha256=f"{chunk.ordinal:064x}",
            )
            boundary = parse_timestamp(PREDECESSOR_H1_REQUESTED_FROM)
            for offset in range(earlier):
                HistoricalTimestampObservation.objects.create(
                    inventory=inventory,
                    timestamp=boundary - timedelta(hours=offset + 1),
                    complete=True,
                    volume=1,
                    bid_present=True,
                    ask_present=True,
                )
        return attempt
    finally:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_historicaldiscoveryattempt ENABLE TRIGGER USER")
            cursor.execute("ALTER TABLE market_historicaltimestampinventory ENABLE TRIGGER USER")
            cursor.execute("ALTER TABLE market_historicaltimestampobservation ENABLE TRIGGER USER")
            cursor.execute("ALTER TABLE market_ingestionrun ENABLE TRIGGER USER")


def materialize_partial(payload, source, limit):
    """The governed successor plan with only its first ``limit`` chunks.

    Each chunk still matches its manifest entry exactly, so the only thing
    wrong is that the plan is incomplete — which is precisely what the deferred
    completeness trigger exists to catch.
    """
    from market.models import HistoricalDiscoveryChunk, Instrument

    supplied = {key: value for key, value in payload.items() if key != "plan_sha256"}
    plan = HistoricalDiscoveryPlan.objects.create(
        identity=supplied["identity"],
        version=supplied["discovery_version"],
        source=source,
        purpose=supplied["purpose"],
        environment=supplied["environment"],
        phase1_spec_hash=supplied["phase1_spec_hash"],
        phase1_manifest_hash=supplied["phase1_manifest_hash"],
        superseded_data_identity=supplied["superseded_data_identity"],
        declared_chunk_count=supplied["declared_chunk_count"],
        canonical_request_manifest=supplied["requests"],
        canonical_request_manifest_sha256=supplied["canonical_request_manifest_sha256"],
        payload=supplied,
        sha256=payload["plan_sha256"],
    )
    instruments = {item.code: item for item in Instrument.objects.all()}
    for item in supplied["requests"][:limit]:
        request = item["canonical_request"]
        HistoricalDiscoveryChunk.objects.create(
            plan=plan,
            ordinal=item["ordinal"],
            instrument=instruments[request["instrument"]],
            granularity=request["granularity"],
            requested_from=parse_timestamp(request["from"]),
            requested_to=parse_timestamp(request["to"]),
            canonical_request=request,
            canonical_request_sha256=item["canonical_request_sha256"],
            logical_key=item["logical_discovery_key"],
        )
    return plan


class Gate8bPrimeMigrationTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(MIGRATION_0023)

    def tearDown(self):
        MigrationExecutor(connection).migrate(MIGRATION_0023)
        super().tearDown()

    def module(self):
        from importlib import import_module

        return import_module("market.migrations.0023_gate8b_prime_successor_discovery_activation")

    def test_dependency_atomicity_and_no_data_migration(self):
        # 1, 4
        migration = self.module()
        self.assertEqual(
            migration.Migration.dependencies,
            [("market", "0022_provider_observed_registration_validator_correction")],
        )
        self.assertTrue(migration.Migration.atomic)
        self.assertEqual(
            [type(op).__name__ for op in migration.Migration.operations], ["RunPython"]
        )
        self.assertEqual(len(migration.REQUIRED_0022_FUNCTIONS), 55)
        self.assertEqual(len(migration.REQUIRED_0022_TRIGGERS), 72)
        for table in ("market_historicaldiscoveryplan", "market_historicaldiscoverychunk"):
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT count(*) FROM {table}")
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_preflight_passes_and_installs_the_successor_objects(self):
        # 2
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace"
                " WHERE n.nspname=current_schema()"
                " AND p.proname='market_validate_successor_plan_complete'"
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid"
                " WHERE NOT t.tgisinternal AND t.tgdeferrable AND t.tginitdeferred"
                " AND t.tgname IN ('market_successor_plan_complete',"
                " 'market_successor_chunk_complete')"
            )
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_altered_governance_is_rejected_by_preflight(self):
        # 3: the stub must be restored, or every later test inherits a corrupt
        # catalog and 0023's preflight refuses it for the wrong reason.
        MigrationExecutor(connection).migrate(MIGRATION_0022)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_functiondef('market_acquisition_reject_truncate()'::regprocedure)"
            )
            original = cursor.fetchone()[0]
            cursor.execute(
                "CREATE OR REPLACE FUNCTION market_acquisition_reject_truncate()"
                " RETURNS trigger AS $$BEGIN RETURN NULL; END$$ LANGUAGE plpgsql"
            )
        try:
            with self.assertRaisesMessage(RuntimeError, "does not match its 0022 definition"):
                MigrationExecutor(connection).migrate(MIGRATION_0023)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(original)
        MigrationExecutor(connection).migrate(MIGRATION_0023)

    def test_partial_prior_installation_is_rejected(self):
        # 3
        MigrationExecutor(connection).migrate(MIGRATION_0022)
        migration = self.module()
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE OR REPLACE FUNCTION market_validate_successor_plan_complete()"
                " RETURNS trigger AS $governed$"
                + migration.SUCCESSOR_PLAN_COMPLETE_PROSRC.replace("%", "%%")
                + "$governed$ LANGUAGE plpgsql"
            )
        try:
            with self.assertRaisesMessage(RuntimeError, "already installed"):
                MigrationExecutor(connection).migrate(MIGRATION_0023)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP FUNCTION IF EXISTS market_validate_successor_plan_complete()")
        MigrationExecutor(connection).migrate(MIGRATION_0023)

    def test_empty_reverse_restores_the_exact_0022_definitions(self):
        # 23
        migration = self.module()
        MigrationExecutor(connection).migrate(MIGRATION_0022)
        with connection.cursor() as cursor:
            for name, expected in (
                ("market_validate_discovery_plan", migration.PRIOR_DISCOVERY_PLAN_PROSRC),
                ("market_validate_discovery_attempt", migration.PRIOR_DISCOVERY_ATTEMPT_PROSRC),
            ):
                cursor.execute("SELECT prosrc FROM pg_proc WHERE proname=%s", [name])
                self.assertEqual(cursor.fetchall()[0][0], expected, name)
            cursor.execute(
                "SELECT count(*) FROM pg_proc"
                " WHERE proname='market_validate_successor_plan_complete'"
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_sealing_and_registration_governance_is_untouched(self):
        # 21 (catalog half): the two protected functions keep their 0022 bodies
        migration = self.module()
        from importlib import import_module

        governance = import_module("market.migrations.0014_historical_discovery_supersession")
        with connection.cursor() as cursor:
            cursor.execute(
                governance.FUNCTION_FINGERPRINT_SQL, [list(migration.PROTECTED_FUNCTIONS)]
            )
            live = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        for name in migration.PROTECTED_FUNCTIONS:
            self.assertEqual(live[name], tuple(migration.REQUIRED_0022_FUNCTIONS[name]), name)


class Gate8bPrimePlanTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0023)
        self.source = seed_governed_market("gate8b-prime fixture")

    def tearDown(self):
        MigrationExecutor(connection).migrate(MIGRATION_0023)
        super().tearDown()

    def test_the_exact_successor_plan_and_its_132_chunks_commit(self):
        # 5
        plan = create_discovery_plan(build_successor_discovery_plan())
        self.assertEqual(plan.sha256, build_successor_discovery_plan()["plan_sha256"])
        self.assertEqual(plan.chunks.count(), EXPECTED_CHUNK_COUNT)
        counts = {}
        for chunk in plan.chunks.all():
            counts[chunk.granularity] = counts.get(chunk.granularity, 0) + 1
        self.assertEqual(counts, {"D": 6, "H1": 120, "W": 6})
        self.assertEqual(len(successor_first_h1(plan)), 6)

    def test_a_missing_chunk_fails_at_commit(self):
        # 6: 131 individually valid chunks still cannot commit
        payload = build_successor_discovery_plan()
        with self.assertRaisesMessage(Exception, "132 authorized chunks"):
            with transaction.atomic():
                materialize_partial(payload, self.source, EXPECTED_CHUNK_COUNT - 1)
        self.assertEqual(
            HistoricalDiscoveryPlan.objects.filter(sha256=payload["plan_sha256"]).count(), 0
        )

    def test_a_partial_successor_marker_is_refused(self):
        """A row may not wear the successor identity without earning it, and it
        must not quietly degrade into the generic path either."""
        payload = build_replacement_discovery_plan()
        for field, value in (
            ("identity", "failed-break-phase-2b1r-discovery-plan-v3"),
            ("discovery_version", "phase-2b1r-discovery-v3"),
        ):
            forged = {key: item for key, item in payload.items() if key != "plan_sha256"}
            forged[field] = value
            if field == "discovery_version":
                forged["identity"] = payload["identity"]
            forged["plan_sha256"] = canonical_hash(forged)
            with self.assertRaisesMessage(
                Exception, "successor discovery plan markers must reconstruct"
            ):
                with transaction.atomic():
                    create_discovery_plan(forged)

    def test_a_successor_plan_short_of_its_declared_count_is_refused(self):
        # 6
        payload = build_successor_discovery_plan()
        forged = {key: item for key, item in payload.items() if key != "plan_sha256"}
        forged["requests"] = forged["requests"][:-1]
        forged["declared_chunk_count"] = EXPECTED_CHUNK_COUNT - 1
        forged["canonical_request_manifest_sha256"] = canonical_hash(forged["requests"])
        forged["plan_sha256"] = canonical_hash(forged)
        with self.assertRaises(Exception), transaction.atomic():
            create_discovery_plan(forged)

    def test_raw_sql_cannot_insert_a_successor_plan_without_its_chunks(self):
        # 7
        payload = build_successor_discovery_plan()
        with self.assertRaisesMessage(Exception, "132 authorized chunks"):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO market_historicaldiscoveryplan
                      (identity,version,source_id,purpose,environment,phase1_spec_hash,
                       phase1_manifest_hash,superseded_data_identity,declared_chunk_count,
                       canonical_request_manifest,canonical_request_manifest_sha256,
                       payload,sha256,created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,now())
                    """,
                    [
                        payload["identity"],
                        payload["discovery_version"],
                        self.source.pk,
                        payload["purpose"],
                        payload["environment"],
                        payload["phase1_spec_hash"],
                        payload["phase1_manifest_hash"],
                        payload["superseded_data_identity"],
                        payload["declared_chunk_count"],
                        __import__("json").dumps(payload["requests"]),
                        payload["canonical_request_manifest_sha256"],
                        __import__("json").dumps(
                            {k: v for k, v in payload.items() if k != "plan_sha256"}
                        ),
                        payload["plan_sha256"],
                    ],
                )

    def test_the_accepted_v2_plan_is_unaffected(self):
        # 20
        plan = create_discovery_plan(build_replacement_discovery_plan())
        self.assertEqual(plan.sha256, DISCOVERY_V2_PLAN_SHA256)
        self.assertEqual(plan.chunks.count(), 132)


class Gate8bPrimeStagedExecutionTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0023)
        self.source = seed_governed_market("gate8b-prime staged fixture")
        self.plan = create_discovery_plan(build_successor_discovery_plan())
        self.first_h1 = successor_first_h1(self.plan)
        self.canary = self.first_h1[0]
        self.cross = self.first_h1[1:]
        self.remaining = self.plan.chunks.exclude(
            pk__in=[chunk.pk for chunk in self.first_h1]
        ).order_by("ordinal")

    def tearDown(self):
        MigrationExecutor(connection).migrate(MIGRATION_0023)
        super().tearDown()

    def test_stage_classification_matches_the_committed_membership(self):
        membership = staged_discovery_membership()
        self.assertEqual(successor_stage(self.canary), STAGE_CANARY)
        self.assertEqual(self.canary.instrument.code, CANARY_INSTRUMENT)
        self.assertEqual(
            membership[STAGE_CANARY][0]["logical_discovery_key"], self.canary.logical_key
        )
        for chunk in self.cross:
            self.assertEqual(successor_stage(chunk), STAGE_CROSS_INSTRUMENT)
        self.assertEqual(successor_stage(self.remaining.first()), STAGE_REMAINDER)
        self.assertEqual(len(membership[STAGE_REMAINDER]), 126)

    def test_only_the_canary_is_permitted_before_any_success(self):
        # 9, 10
        for chunk in self.cross:
            with self.assertRaisesMessage(DatasetQualityError, "gate 8D1 requires"):
                begin_discovery_attempt(chunk.logical_key)
        with self.assertRaisesMessage(DatasetQualityError, "gate 8D2 requires"):
            begin_discovery_attempt(self.remaining.first().logical_key)
        attempt = begin_discovery_attempt(self.canary.logical_key)
        self.assertEqual(attempt.attempt_number, 1)

    def test_a_failed_canary_blocks_all_progression(self):
        # 11, 18
        record_attempt(self.canary, status=IngestionRun.Status.FAILED)
        with self.assertRaises(DatasetQualityError):
            begin_discovery_attempt(self.cross[0].logical_key)
        # and the canary itself receives no automatic retry: attempt 2 is refused
        with self.assertRaisesMessage(DatasetQualityError, "only attempt 1"):
            begin_discovery_attempt(self.canary.logical_key)

    def test_a_canary_with_too_few_earlier_observations_blocks_progression(self):
        # 12
        record_attempt(
            self.canary,
            status=IngestionRun.Status.SUCCEEDED,
            earlier=MINIMUM_EARLIER_OBSERVATIONS - 1,
        )
        with self.assertRaisesMessage(DatasetQualityError, "gate 8D1 requires"):
            begin_discovery_attempt(self.cross[0].logical_key)

    def test_a_valid_canary_opens_exactly_the_five_cross_instrument_chunks(self):
        # 13, 14
        record_attempt(self.canary, status=IngestionRun.Status.SUCCEEDED)
        self.assertEqual(successor_readiness()["permitted_stage"], STAGE_CROSS_INSTRUMENT)
        # checked before anything is running, so the stage rule is what refuses
        with self.assertRaisesMessage(DatasetQualityError, "gate 8D2 requires"):
            begin_discovery_attempt(self.remaining.first().logical_key)
        attempt = begin_discovery_attempt(self.cross[0].logical_key)
        self.assertEqual(attempt.attempt_number, 1)

    def test_one_short_cross_instrument_inventory_keeps_gate_8d2_closed(self):
        # 15
        record_attempt(self.canary, status=IngestionRun.Status.SUCCEEDED)
        for chunk in self.cross[:-1]:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        record_attempt(
            self.cross[-1],
            status=IngestionRun.Status.SUCCEEDED,
            earlier=MINIMUM_EARLIER_OBSERVATIONS - 1,
        )
        with self.assertRaisesMessage(DatasetQualityError, "gate 8D2 requires"):
            begin_discovery_attempt(self.remaining.first().logical_key)

    def test_six_valid_first_h1_inventories_open_the_remaining_126(self):
        # 16
        for chunk in self.first_h1:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        readiness = successor_readiness()
        self.assertEqual(readiness["permitted_stage"], STAGE_REMAINDER)
        self.assertEqual(len(readiness["permitted_logical_keys"]), 126)
        attempt = begin_discovery_attempt(self.remaining.first().logical_key)
        self.assertEqual(attempt.attempt_number, 1)

    def test_attempt_two_is_refused_through_the_service_and_raw_sql(self):
        # 17
        record_attempt(self.canary, status=IngestionRun.Status.FAILED)
        with self.assertRaisesMessage(DatasetQualityError, "only attempt 1"):
            begin_discovery_attempt(self.canary.logical_key)
        run = IngestionRun.objects.create(
            source=self.plan.source,
            instrument=self.canary.instrument,
            granularity=self.canary.granularity,
            requested_from=self.canary.requested_from,
            requested_to=self.canary.requested_to,
            parameters={},
            request_manifest_hash="1" * 64,
            status=IngestionRun.Status.RUNNING,
        )
        with self.assertRaises(Exception), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO market_historicaldiscoveryattempt"
                " (chunk_id,ingestion_run_id,attempt_number,idempotency_key,created_at)"
                " VALUES (%s,%s,2,%s,now())",
                [
                    self.canary.pk,
                    run.pk,
                    f"historical-discovery-attempt:{self.canary.logical_key}:2",
                ],
            )

    def test_a_second_attempt_one_is_impossible(self):
        """18, 19: attempt 1 is unique per chunk at the database level.

        The attempt validators are suspended for the duplicate so the refusal
        can only come from the unique index itself — with them armed, the
        governed lineage rule refuses first and the constraint is never
        reached, which would prove something else.
        """
        record_attempt(self.canary, status=IngestionRun.Status.FAILED)
        run = IngestionRun.objects.create(
            source=self.plan.source,
            instrument=self.canary.instrument,
            granularity=self.canary.granularity,
            requested_from=self.canary.requested_from,
            requested_to=self.canary.requested_to,
            parameters={},
            request_manifest_hash=f"{self.canary.ordinal:062d}99",
            status=IngestionRun.Status.RUNNING,
        )
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_historicaldiscoveryattempt DISABLE TRIGGER USER")
        try:
            with (
                self.assertRaisesMessage(
                    IntegrityError, "market_historicaldiscoveryattempt_idempotency_key_key"
                ),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "INSERT INTO market_historicaldiscoveryattempt"
                    " (chunk_id,ingestion_run_id,attempt_number,idempotency_key,created_at)"
                    " VALUES (%s,%s,1,%s,now())",
                    [
                        self.canary.pk,
                        run.pk,
                        f"historical-discovery-attempt:{self.canary.logical_key}:1",
                    ],
                )
        finally:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE market_historicaldiscoveryattempt ENABLE TRIGGER USER")

    def test_no_attempt_before_the_complete_plan_exists(self):
        # 8: proven inside the transaction, since an incomplete successor plan
        # can never reach commit.
        payload = build_successor_discovery_plan()
        with self.assertRaises(Exception):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM market_historicaldiscoverychunk WHERE plan_id=%s",
                        [self.plan.pk],
                    )
                    cursor.execute(
                        "DELETE FROM market_historicaldiscoveryplan WHERE id=%s", [self.plan.pk]
                    )
                partial = materialize_partial(payload, self.source, EXPECTED_CHUNK_COUNT - 1)
                self.assertEqual(partial.chunks.count(), EXPECTED_CHUNK_COUNT - 1)
                chunk = partial.chunks.select_related("plan", "instrument").order_by("ordinal")[0]
                with self.assertRaisesMessage(DatasetQualityError, "complete authorized plan"):
                    begin_discovery_attempt(chunk.logical_key)
                raise RuntimeError("roll back the incomplete successor plan")

    def test_readiness_reporting_writes_nothing_and_builds_no_client(self):
        # 26
        import market.oanda as oanda

        before = (
            HistoricalDiscoveryAttempt.objects.count(),
            HistoricalTimestampInventory.objects.count(),
            HistoricalDiscoveryPlan.objects.count(),
        )
        with patch.object(oanda, "OandaClient", side_effect=AssertionError("client built")):
            readiness = successor_readiness()
        self.assertEqual(readiness["permitted_stage"], STAGE_CANARY)
        self.assertTrue(readiness["materialized"])
        self.assertEqual(readiness["chunks"], EXPECTED_CHUNK_COUNT)
        self.assertEqual(
            before,
            (
                HistoricalDiscoveryAttempt.objects.count(),
                HistoricalTimestampInventory.objects.count(),
                HistoricalDiscoveryPlan.objects.count(),
            ),
        )

    def test_reversal_is_refused_once_successor_evidence_exists(self):
        # 24
        with self.assertRaisesMessage(RuntimeError, "prohibits gate 8B-prime reversal"):
            MigrationExecutor(connection).migrate(MIGRATION_0022)

    def test_successor_sealing_approval_and_registration_remain_refused(self):
        # 21, 22: even with every first-H1 inventory in place
        from market.historical_discovery import approve_and_register_discovery

        for chunk in self.first_h1:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        approver = get_user_model().objects.create_user("gate8b-prime-approver")
        with self.assertRaisesMessage(
            DatasetQualityError, "only the approved replacement discovery plan may be approved"
        ):
            approve_and_register_discovery(self.plan.sha256, approver.pk, "0" * 64)
        self.assertIsNone(self.plan.__class__.objects.get(pk=self.plan.pk).sealed_at)
        with self.assertRaises(Exception), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE market_historicaldiscoveryplan SET sealed_at=now() WHERE id=%s",
                [self.plan.pk],
            )


class Gate8bPrimeFailedPlanTests(TransactionTestCase):
    """A failed successor attempt ends the plan, not merely its own chunk.

    Attempt 2 is prohibited, so once any chunk fails the 132-chunk plan can
    never complete; every further request would be spent on a plan that can
    never be sealed or registered.
    """

    FAILED_PLAN = "a failed successor discovery attempt permanently stops this plan"

    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0023)
        self.source = seed_governed_market("gate8b-prime failed-plan fixture")
        self.plan = create_discovery_plan(build_successor_discovery_plan())
        self.first_h1 = successor_first_h1(self.plan)
        self.canary, self.cross = self.first_h1[0], self.first_h1[1:]
        self.remaining = list(
            self.plan.chunks.exclude(pk__in=[c.pk for c in self.first_h1]).order_by("ordinal")[:3]
        )

    def tearDown(self):
        MigrationExecutor(connection).migrate(MIGRATION_0023)
        super().tearDown()

    def open_cross_instrument(self):
        record_attempt(self.canary, status=IngestionRun.Status.SUCCEEDED)

    def open_remainder(self):
        for chunk in self.first_h1:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)

    def test_a_failed_canary_blocks_every_other_successor_chunk(self):
        # 1
        record_attempt(self.canary, status=IngestionRun.Status.FAILED)
        for chunk in (self.cross[0], self.remaining[0]):
            with self.assertRaisesMessage(DatasetQualityError, self.FAILED_PLAN):
                begin_discovery_attempt(chunk.logical_key)

    def test_a_failed_cross_instrument_attempt_blocks_the_rest(self):
        # 2
        self.open_cross_instrument()
        record_attempt(self.cross[0], status=IngestionRun.Status.FAILED)
        for chunk in (self.cross[1], self.remaining[0]):
            with self.assertRaisesMessage(DatasetQualityError, self.FAILED_PLAN):
                begin_discovery_attempt(chunk.logical_key)

    def test_a_failed_remainder_attempt_blocks_a_different_remainder_chunk(self):
        # 3: the finding this correction exists for
        self.open_remainder()
        record_attempt(self.remaining[0], status=IngestionRun.Status.FAILED)
        with self.assertRaisesMessage(DatasetQualityError, self.FAILED_PLAN):
            begin_discovery_attempt(self.remaining[1].logical_key)

    def test_the_failed_chunk_still_cannot_take_attempt_two(self):
        # 4: the older rule survives, with its own distinct message
        self.open_remainder()
        record_attempt(self.remaining[0], status=IngestionRun.Status.FAILED)
        with self.assertRaisesMessage(DatasetQualityError, "only attempt 1"):
            begin_discovery_attempt(self.remaining[0].logical_key)

    def test_raw_sql_is_refused_by_postgresql_with_its_own_message(self):
        # 6: PostgreSQL is authoritative, so bypassing the service changes nothing
        self.open_remainder()
        record_attempt(self.remaining[0], status=IngestionRun.Status.FAILED)
        target = self.remaining[1]

        def make_run():
            return IngestionRun.objects.create(
                source=self.plan.source,
                instrument=target.instrument,
                granularity=target.granularity,
                requested_from=target.requested_from,
                requested_to=target.requested_to,
                parameters={
                    "purpose": "provider_timestamp_inventory_discovery",
                    "logical_discovery_key": target.logical_key,
                    "canonical_request_sha256": target.canonical_request_sha256,
                    **target.canonical_request,
                },
                request_manifest_hash=canonical_hash(
                    {
                        "purpose": "provider_timestamp_inventory_discovery",
                        "attempt_idempotency_key": (
                            f"historical-discovery-attempt:{target.logical_key}:1"
                        ),
                    }
                ),
                status=IngestionRun.Status.RUNNING,
            )

        with (
            self.assertRaisesMessage(DatabaseError, self.FAILED_PLAN),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            run = make_run()
            cursor.execute(
                "INSERT INTO market_historicaldiscoveryattempt"
                " (chunk_id,ingestion_run_id,attempt_number,idempotency_key,created_at)"
                " VALUES (%s,%s,1,%s,now())",
                [target.pk, run.pk, f"historical-discovery-attempt:{target.logical_key}:1"],
            )

    def test_readiness_reports_the_plan_blocked_with_no_eligible_chunk(self):
        # 7, 8
        import market.oanda as oanda

        self.open_remainder()
        record_attempt(self.remaining[0], status=IngestionRun.Status.FAILED)
        with patch.object(oanda, "OandaClient", side_effect=AssertionError("client built")):
            readiness = successor_readiness()
        self.assertTrue(readiness["blocked_by_failed_attempt"])
        self.assertIsNone(readiness["permitted_stage"])
        self.assertEqual(readiness["permitted_logical_keys"], [])

    def test_a_succeeded_attempt_does_not_trigger_the_failed_plan_rule(self):
        # 9
        self.open_remainder()
        readiness = successor_readiness()
        self.assertFalse(readiness["blocked_by_failed_attempt"])
        self.assertEqual(readiness["permitted_stage"], STAGE_REMAINDER)
        attempt = begin_discovery_attempt(self.remaining[0].logical_key)
        self.assertEqual(attempt.attempt_number, 1)

    def test_a_failed_attempt_on_another_plan_does_not_block_the_successor(self):
        # 10: scope is relational — successor plan, its chunks, their runs
        legacy = create_discovery_plan(build_replacement_discovery_plan())
        legacy_chunk = legacy.chunks.order_by("ordinal").first()
        record_attempt(legacy_chunk, status=IngestionRun.Status.FAILED)
        self.assertFalse(successor_readiness()["blocked_by_failed_attempt"])
        attempt = begin_discovery_attempt(self.canary.logical_key)
        self.assertEqual(attempt.attempt_number, 1)

    def test_the_running_and_failed_rules_stay_diagnostically_distinct(self):
        # the single-flight rule must not be absorbed into the failure rule
        self.open_remainder()
        begin_discovery_attempt(self.remaining[0].logical_key)
        with self.assertRaisesMessage(DatasetQualityError, "already running"):
            begin_discovery_attempt(self.remaining[1].logical_key)
