"""Gate 8D3': successor registration authority.

The successor branch admits exactly one outcome — 132 chunks, 132 attempt-1
chains, 365,055 observations and the accepted aggregates — so a bounded fixture
can never satisfy it. That is the point: these tests drive the branch with
fixtures that are wrong in one specific way and prove it refuses, and prove the
predecessor branch is untouched. The positive admission is rehearsed at full
scale on a disposable restore of the real evidence, which no synthetic fixture
could faithfully reproduce without 365,055 rows.
"""

import importlib

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

from market.historical_discovery import (
    DISCOVERY_COMPLETION_SUMMARY_SHA256,
    DISCOVERY_V2_MANIFEST_SHA256,
    DISCOVERY_V2_PLAN_SHA256,
    approve_and_register_discovery,
    build_replacement_discovery_plan,
    create_discovery_plan,
    successor_registration_plan_sha256,
)
from market.models import (
    HistoricalDiscoveryApproval,
    HistoricalDiscoveryPlan,
    HistoricalDiscoveryRegistration,
    IngestionRun,
)
from market.provider_observed_outcome import (
    OUTCOME_ARTIFACT_SHA256,
    accepted_successor_registration,
)
from market.provider_observed_successor import build_successor_discovery_plan
from market.services import DatasetQualityError
from market.tests.test_gate8b_prime_successor_activation import (
    record_attempt,
    successor_first_h1,
)
from market.tests.test_replacement_canary_activation import migrate_to, seed_governed_market

MIGRATION_0023 = [("market", "0023_gate8b_prime_successor_discovery_activation")]
MIGRATION_0024 = [("market", "0024_gate8d3_prime_successor_registration_authority")]

MODULE = importlib.import_module(
    "market.migrations.0024_gate8d3_prime_successor_registration_authority"
)
PRIOR_0023 = importlib.import_module(
    "market.migrations.0023_gate8b_prime_successor_discovery_activation"
)


class Gate8d3PrimeMigrationShapeTests(SimpleTestCase):
    """What the migration is, before any database is involved."""

    def test_it_depends_only_on_0023_is_atomic_and_migrates_no_data(self):
        # 12
        self.assertEqual(
            MODULE.Migration.dependencies,
            [("market", "0023_gate8b_prime_successor_discovery_activation")],
        )
        self.assertTrue(MODULE.Migration.atomic)
        self.assertEqual(len(MODULE.Migration.operations), 1)
        operation = MODULE.Migration.operations[0]
        self.assertEqual(operation.code, MODULE.forward)
        self.assertEqual(operation.reverse_code, MODULE.reverse)
        source = MODULE.forward.__code__.co_names + MODULE.reverse.__code__.co_names
        for forbidden in ("objects", "bulk_create", "save", "delete"):
            self.assertNotIn(forbidden, source)

    def test_the_predecessor_branch_survives_byte_for_byte(self):
        # 2: the v2 statements after the plan lookup are one unchanged span
        anchor = (
            "          SELECT * INTO STRICT plan_row FROM market_historicaldiscoveryplan\n"
            "            WHERE id=plan_key;\n"
        )
        self.assertIn(anchor, MODULE.PRIOR_GATE5_PROSRC)
        v2_body = MODULE.PRIOR_GATE5_PROSRC.split(anchor, 1)[1]
        self.assertIn(v2_body, MODULE.SUCCESSOR_GATE5_PROSRC)
        self.assertEqual(MODULE.SUCCESSOR_GATE5_PROSRC.count(v2_body), 1)
        tail = (
            "          IF registration_row.cross_series_report_sha256<>"
            "'d267326c7d62e43fffaa610af118d52c7754af357a888a1c95cf3d24b16ae32d'\n"
        )
        self.assertIn(tail, MODULE.PRIOR_SEAL_PROSRC)
        self.assertIn(
            tail + MODULE.PRIOR_SEAL_PROSRC.split(tail, 1)[1], MODULE.SUCCESSOR_SEAL_PROSRC
        )
        # every predecessor literal is still present, unrelaxed
        for literal in (
            DISCOVERY_V2_PLAN_SHA256,
            DISCOVERY_V2_MANIFEST_SHA256,
            DISCOVERY_COMPLETION_SUMMARY_SHA256,
            "78f8559bc9b14e84f8c1b1002d30ddd77d1918e9c026812b5ce6e2b0ca8af02c",
            "a650dd977f0f2c79cbad2cb476fe36610a0fc0c2f372107b541882d0b342c878",
            "364953",
            "attempt_count<>133",
        ):
            self.assertIn(literal, MODULE.SUCCESSOR_GATE5_PROSRC + MODULE.SUCCESSOR_SEAL_PROSRC)

    def test_the_successor_branch_pins_the_exact_accepted_literals(self):
        # 1, 8, 9: authority is literals plus reconstruction, never row-supplied
        accepted = accepted_successor_registration()
        body = MODULE.SUCCESSOR_GATE5_PROSRC + MODULE.SUCCESSOR_SEAL_PROSRC
        for literal in (
            accepted["plan_sha256"],
            accepted["plan_identity"],
            accepted["plan_version"],
            accepted["request_manifest_sha256"],
            accepted["global_semantic_inventory_sha256"],
            accepted["accepted_operational_evidence_set_sha256"],
            accepted["restricted_overlap_sha256"],
            OUTCOME_ARTIFACT_SHA256,
            "365055",
            "17412",
            "344817",
            "2826",
        ):
            self.assertIn(literal, body)
        self.assertEqual(MODULE.SUCCESSOR_PLAN_SHA256, accepted["plan_sha256"])
        self.assertEqual(MODULE.SUCCESSOR_OBSERVATION_COUNT, 365055)
        self.assertEqual(MODULE.SUCCESSOR_ATTEMPT_COUNT, 132)
        self.assertEqual(
            MODULE.SUCCESSOR_WARMUP,
            {"earlier": 17, "predecessor": 8, "combined": 25, "required": 14},
        )

    def test_the_successor_branch_reads_no_value_from_the_approval_or_registration_row(self):
        # 10: the only row-supplied value is compared with an exact literal
        successor_block = MODULE.SUCCESSOR_GATE5_PROSRC.split(MODULE.SUCCESSOR_PLAN_SHA256, 1)[1]
        successor_block = successor_block.split("          END IF;\n", 1)[0]
        for forbidden in ("approval_row", "registration_row"):
            self.assertNotIn(forbidden, successor_block)
        self.assertIn(
            f"registration_row.cross_series_report_sha256<>\n"
            f"               '{OUTCOME_ARTIFACT_SHA256}'",
            MODULE.SUCCESSOR_SEAL_PROSRC,
        )

    def test_the_reversal_guard_is_successor_specific_and_fails_closed(self):
        # 14
        source = MODULE.reverse.__doc__ or ""
        self.assertIn("_successor_authority_evidence", MODULE.reverse.__code__.co_names)
        self.assertIn(
            "successor discovery approval, registration, sealing or supersession",
            MODULE.__dict__["reverse"].__code__.co_consts[1]
            if isinstance(MODULE.__dict__["reverse"].__code__.co_consts[1], str)
            else "".join(c for c in MODULE.reverse.__code__.co_consts if isinstance(c, str)),
        )
        del source


class Gate8d3PrimeCatalogTests(TransactionTestCase):
    """Applying and reversing the migration against a real catalog."""

    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0024)

    def tearDown(self):
        MigrationExecutor(connection).migrate(MIGRATION_0024)
        super().tearDown()

    def catalog(self):
        with connection.cursor() as cursor:
            cursor.execute(
                r"SELECT p.proname, md5(p.prosrc) FROM pg_proc p"
                r" JOIN pg_namespace n ON n.oid=p.pronamespace"
                r" WHERE n.nspname=current_schema() AND p.proname LIKE 'market\_%'"
                r" ORDER BY p.proname"
            )
            functions = cursor.fetchall()
            cursor.execute(
                r"SELECT c.relname, t.tgname, md5(pg_get_triggerdef(t.oid))"
                r" FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid"
                r" JOIN pg_namespace n ON n.oid=c.relnamespace"
                r" WHERE NOT t.tgisinternal AND n.nspname=current_schema()"
                r" AND t.tgname LIKE 'market\_%' ORDER BY 1,2"
            )
            return functions, cursor.fetchall()

    def test_application_adds_no_object_and_changes_only_the_two_bodies(self):
        # 12, 15
        functions, triggers = self.catalog()
        self.assertEqual(len(functions), MODULE.REQUIRED_FUNCTION_COUNT)
        self.assertEqual(len(triggers), MODULE.REQUIRED_TRIGGER_COUNT)
        MigrationExecutor(connection).migrate(MIGRATION_0023)
        prior_functions, prior_triggers = self.catalog()
        self.assertEqual(len(prior_functions), MODULE.REQUIRED_FUNCTION_COUNT)
        self.assertEqual(len(prior_triggers), MODULE.REQUIRED_TRIGGER_COUNT)
        self.assertEqual(prior_triggers, triggers)
        changed = [
            name
            for (name, digest), (_, prior) in zip(functions, prior_functions)
            if digest != prior
        ]
        self.assertEqual(sorted(changed), sorted(MODULE.REPLACED_FUNCTIONS))

    def test_empty_reverse_restores_the_0023_catalog_byte_for_byte(self):
        # 13
        MigrationExecutor(connection).migrate(MIGRATION_0023)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace"
                " WHERE n.nspname=current_schema() AND p.proname='market_validate_gate5_registration'"
            )
            self.assertEqual(cursor.fetchone()[0], MODULE.PRIOR_GATE5_PROSRC)
            cursor.execute(
                "SELECT prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace"
                " WHERE n.nspname=current_schema()"
                " AND p.proname='market_validate_discovery_seal_deferred'"
            )
            self.assertEqual(cursor.fetchone()[0], MODULE.PRIOR_SEAL_PROSRC)

    def test_reapplication_is_deterministic(self):
        first = self.catalog()
        MigrationExecutor(connection).migrate(MIGRATION_0023)
        MigrationExecutor(connection).migrate(MIGRATION_0024)
        self.assertEqual(self.catalog(), first)


class Gate8d3PrimeAdmissionTests(TransactionTestCase):
    """The successor branch refuses everything that is not the accepted outcome."""

    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0024)
        self.source = seed_governed_market("gate8d3-prime fixture")
        self.plan = create_discovery_plan(build_successor_discovery_plan())
        self.first_h1 = successor_first_h1(self.plan)
        self.approver = get_user_model().objects.create_user(
            "gate8d3p", "gate8d3p@example.com", "x", is_active=True, is_superuser=True
        )

    def tearDown(self):
        MigrationExecutor(connection).migrate(MIGRATION_0024)
        super().tearDown()

    def register(self, sha256=None, report=None):
        return approve_and_register_discovery(
            sha256 or successor_registration_plan_sha256(),
            self.approver.pk,
            report or OUTCOME_ARTIFACT_SHA256,
        )

    def test_a_partial_successor_outcome_is_refused_before_the_aggregates(self):
        # 4: an incomplete plan cannot even reach the successor aggregate check
        for chunk in self.first_h1:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        with self.assertRaisesMessage(
            DatasetQualityError, "every discovery chunk requires an accepted inventory"
        ):
            self.register()

    def test_a_complete_but_wrong_successor_outcome_is_refused(self):
        # 4, 8: all 132 chunks attempted and inventoried, but the evidence is not
        # the accepted outcome. Layered governance refuses it — here at the
        # provider-evidence ledger, and at full scale the successor aggregate
        # branch itself, which the disposable rehearsal exercises.
        for chunk in self.plan.chunks.order_by("ordinal"):
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED, earlier=1)
        self.assertEqual(self.plan.chunks.count(), 132)
        with self.assertRaises(DatasetQualityError):
            self.register()
        self.plan.refresh_from_db()
        self.assertIsNone(self.plan.sealed_at)

    def test_attempt_two_and_failed_evidence_are_refused(self):
        # 5, 6: the same reconstruction check refuses both shapes
        for chunk in self.plan.chunks.order_by("ordinal"):
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED, earlier=1)
        record_attempt(self.first_h1[0], status=IngestionRun.Status.FAILED, number=2, salt=3)
        with self.assertRaises(DatasetQualityError):
            self.register()

    def test_the_wrong_cross_series_report_is_refused(self):
        # the accepted artifact digest is the successor's only admissible report
        with self.assertRaisesMessage(
            DatasetQualityError, "accepted successor outcome artifact hash"
        ):
            self.register(report=DISCOVERY_COMPLETION_SUMMARY_SHA256)

    def test_the_predecessor_plan_still_takes_the_predecessor_path(self):
        # 2, 3, 15: the v2 plan is routed to the v2 branch and fails on the v2
        # supersession rule, exactly as it did before this migration existed
        v2 = create_discovery_plan(build_replacement_discovery_plan())
        self.assertEqual(v2.sha256, DISCOVERY_V2_PLAN_SHA256)
        self.assertNotEqual(v2.sha256, successor_registration_plan_sha256())
        with self.assertRaisesMessage(
            DatasetQualityError, "gate5 supersession lineage does not reconstruct"
        ):
            approve_and_register_discovery(
                v2.sha256, self.approver.pk, DISCOVERY_COMPLETION_SUMMARY_SHA256
            )
        # and the predecessor still refuses the successor's report hash
        with self.assertRaisesMessage(
            DatasetQualityError, "gate5 supersession lineage does not reconstruct"
        ):
            approve_and_register_discovery(v2.sha256, self.approver.pk, OUTCOME_ARTIFACT_SHA256)

    def test_nothing_is_sealed_approved_or_registered_by_a_refusal(self):
        # 11: the transaction is atomic, so a refusal leaves no partial authority
        for chunk in self.first_h1:
            record_attempt(chunk, status=IngestionRun.Status.SUCCEEDED)
        with self.assertRaises(DatasetQualityError):
            self.register()
        self.plan.refresh_from_db()
        self.assertIsNone(self.plan.sealed_at)
        self.assertEqual(HistoricalDiscoveryApproval.objects.filter(plan=self.plan).count(), 0)
        self.assertEqual(HistoricalDiscoveryRegistration.objects.filter(plan=self.plan).count(), 0)

    def test_a_row_declared_approval_cannot_seal_without_the_reconstruction(self):
        # 10, 11: an approval row asserting the accepted hashes is still refused
        accepted = accepted_successor_registration()
        with (
            self.assertRaises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO market_historicaldiscoveryapproval"
                " (plan_id,approved_by_id,global_semantic_inventory_sha256,"
                " accepted_operational_evidence_set_sha256,payload,sha256,approved_at,created_at)"
                " VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now(),now())",
                [
                    self.plan.pk,
                    self.approver.pk,
                    accepted["global_semantic_inventory_sha256"],
                    accepted["accepted_operational_evidence_set_sha256"],
                    "f" * 64,
                ],
            )

    def test_the_successor_plan_remains_unsealed_throughout(self):
        # 16
        self.plan.refresh_from_db()
        self.assertIsNone(self.plan.sealed_at)
        self.assertEqual(HistoricalDiscoveryPlan.objects.filter(sealed_at__isnull=False).count(), 0)


class Gate8d3PrimeReadinessTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0024)

    def tearDown(self):
        MigrationExecutor(connection).migrate(MIGRATION_0024)
        super().tearDown()

    def test_the_accepted_profile_builds_no_provider_client_and_writes_nothing(self):
        # 16
        from unittest.mock import patch

        import market.oanda as oanda

        before = (
            HistoricalDiscoveryPlan.objects.count(),
            HistoricalDiscoveryApproval.objects.count(),
            HistoricalDiscoveryRegistration.objects.count(),
        )
        with patch.object(oanda, "OandaClient", side_effect=AssertionError("client built")):
            accepted = accepted_successor_registration()
            self.assertEqual(accepted["plan_sha256"], successor_registration_plan_sha256())
            self.assertEqual(accepted["observation_count"], 365055)
        self.assertEqual(
            before,
            (
                HistoricalDiscoveryPlan.objects.count(),
                HistoricalDiscoveryApproval.objects.count(),
                HistoricalDiscoveryRegistration.objects.count(),
            ),
        )
