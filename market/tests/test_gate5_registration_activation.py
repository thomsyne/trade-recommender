import hashlib
import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase

from market.historical_discovery import (
    ACCEPTED_OPERATIONAL_EVIDENCE_SET_SHA256,
    DISCOVERY_COMPLETION_SUMMARY_SHA256,
    DISCOVERY_V2_MANIFEST_SHA256,
    DISCOVERY_V2_PLAN_SHA256,
    GATE5_ACCEPTED_INVENTORY_COUNT,
    GATE5_APPROVAL_DECISION_SHA256,
    GATE5_STRUCTURAL_OBSERVATION_COUNT,
    GLOBAL_SEMANTIC_INVENTORY_SHA256,
    approve_and_register_discovery,
    build_gate5_approval_decision,
    build_initial_discovery_plan,
    canonical_hash,
    create_discovery_plan,
    logical_discovery_key,
    run_discovery_chunk,
)
from market.models import (
    HistoricalDiscoveryApproval,
    HistoricalDiscoveryPlan,
    HistoricalDiscoveryRegistration,
    HistoricalTimestampInventory,
)
from market.services import DatasetQualityError
from market.tests.test_gate4_full_discovery import Gate4FixtureTestCase, WaveSuccessClient
from market.tests.test_replacement_canary_activation import (
    MIGRATION_0019,
    migrate_to,
    state_hashes,
)

DECISION_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "strategy"
    / "failed-break"
    / "v1"
    / "phase-2b1r-gate5-approval-decision.json"
)
COMPLETION_SUMMARY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "strategy"
    / "failed-break"
    / "v1"
    / "phase-2b1r-gate4-discovery-completion-summary.md"
)
GATE5_SEAL_FUNCTION_MD5 = "5ef0117c6a32cca8a81322a7766d8f52"
GATE5_REJECT_FUNCTION_MD5 = "b48181153e3caa0a52496311b200fc15"


def variant_plan_payload(version="phase-2b1r-discovery-v9"):
    from datetime import datetime

    payload = build_initial_discovery_plan()
    request = dict(payload["requests"][0])
    request["ordinal"] = 1
    request_body = request["canonical_request"]
    start = datetime.fromisoformat(request_body["from"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(request_body["to"].replace("Z", "+00:00"))
    request["logical_discovery_key"] = logical_discovery_key(
        request_sha256=request["canonical_request_sha256"],
        instrument=request_body["instrument"],
        granularity=request_body["granularity"],
        requested_from=start,
        requested_to=end,
        discovery_version=version,
    )
    body = {key: value for key, value in payload.items() if key not in {"requests", "plan_sha256"}}
    body.update(
        identity=f"test-{version}",
        discovery_version=version,
        declared_chunk_count=1,
        requests=[request],
        canonical_request_manifest_sha256=canonical_hash([request]),
    )
    return {**body, "plan_sha256": canonical_hash(body)}


def approver_user(username="gate5-approver"):
    user = get_user_model().objects.create_user(username)
    user.user_permissions.add(Permission.objects.get(codename="approve_historical_discovery"))
    return user


def registration_state():
    return (
        HistoricalDiscoveryApproval.objects.count(),
        HistoricalDiscoveryRegistration.objects.count(),
        HistoricalDiscoveryPlan.objects.filter(sealed_at__isnull=False).count(),
    )


class Gate5DecisionArtifactTests(TransactionTestCase):
    def test_committed_artifact_is_canonical_and_matches_the_pinned_hash(self):
        artifact_bytes = DECISION_ARTIFACT_PATH.read_bytes()
        payload = build_gate5_approval_decision()
        self.assertEqual(
            artifact_bytes,
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        )
        self.assertEqual(hashlib.sha256(artifact_bytes).hexdigest(), GATE5_APPROVAL_DECISION_SHA256)
        self.assertEqual(canonical_hash(payload), GATE5_APPROVAL_DECISION_SHA256)

    def test_artifact_freezes_the_gate5_identities_and_all_nine_decisions(self):
        payload = build_gate5_approval_decision()
        self.assertEqual(payload["schema_identity"], "phase-2b1r-gate5-approval-decision-v1")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["plan_sha256"], DISCOVERY_V2_PLAN_SHA256)
        self.assertEqual(payload["request_manifest_sha256"], DISCOVERY_V2_MANIFEST_SHA256)
        self.assertEqual(
            payload["global_semantic_inventory_sha256"], GLOBAL_SEMANTIC_INVENTORY_SHA256
        )
        self.assertEqual(
            payload["accepted_operational_evidence_set_sha256"],
            ACCEPTED_OPERATIONAL_EVIDENCE_SET_SHA256,
        )
        self.assertEqual(
            payload["discovery_completion_summary_sha256"],
            DISCOVERY_COMPLETION_SUMMARY_SHA256,
        )
        self.assertEqual(payload["successful_inventories"], GATE5_ACCEPTED_INVENTORY_COUNT)
        self.assertEqual(payload["structural_observations"], GATE5_STRUCTURAL_OBSERVATION_COUNT)
        self.assertEqual(
            [item["code"] for item in payload["decisions"]],
            [
                "preserve-provider-observed-membership",
                "retain-weekend-h1-evidence",
                "chronological-indicator-history",
                "frozen-entry-eligibility-rules",
                "instrument-specific-calendars",
                "preserve-sunday-ny17-daily-candles",
                "preserve-weekly-inventories-471",
                "failed-canary-operational-only",
                "provider-drift-fails-closed",
            ],
        )

    def test_artifact_contains_no_database_keys_credentials_or_request_ids(self):
        text = DECISION_ARTIFACT_PATH.read_text()
        payload = build_gate5_approval_decision()
        self.assertEqual(
            set(payload),
            {
                "schema_identity",
                "schema_version",
                "plan_sha256",
                "request_manifest_sha256",
                "global_semantic_inventory_sha256",
                "accepted_operational_evidence_set_sha256",
                "discovery_completion_summary_sha256",
                "successful_inventories",
                "structural_observations",
                "decisions",
            },
        )
        for marker in (
            "provider_request_id",
            "Authorization",
            "Bearer",
            "api-fxpractice",
            '_id"',
            '"pk"',
        ):
            self.assertNotIn(marker, text)


class Gate5InstalledGovernanceTests(TransactionTestCase):
    def tearDown(self):
        migrate_to(MIGRATION_0019)
        super().tearDown()

    def test_gate5_functions_are_installed_with_the_reviewed_bodies(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT proname, md5(prosrc) FROM pg_proc p
                   JOIN pg_namespace n ON n.oid=p.pronamespace
                   WHERE n.nspname=current_schema() AND proname IN
                     ('market_validate_discovery_seal_deferred',
                      'market_reject_superseded_discovery_write',
                      'market_validate_gate5_registration')
                   ORDER BY proname"""
            )
            rows = dict(cursor.fetchall())
        self.assertEqual(rows["market_validate_discovery_seal_deferred"], GATE5_SEAL_FUNCTION_MD5)
        self.assertEqual(
            rows["market_reject_superseded_discovery_write"], GATE5_REJECT_FUNCTION_MD5
        )
        self.assertIn("market_validate_gate5_registration", rows)

    def test_exactly_one_approval_and_registration_row_can_ever_exist_per_plan(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT count(*) FROM pg_indexes
                   WHERE tablename='market_historicaldiscoveryapproval'
                     AND indexdef LIKE 'CREATE UNIQUE INDEX%(plan_id)'"""
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                """SELECT count(*) FROM pg_indexes
                   WHERE tablename='market_historicaldiscoveryregistration'
                     AND indexdef LIKE 'CREATE UNIQUE INDEX%(plan_id)'"""
            )
            self.assertEqual(cursor.fetchone()[0], 1)


class Gate5ApprovalRejectionTests(Gate4FixtureTestCase):
    """The fixture provides the exact v2 plan, supersession and complete
    canary success lineage; only the 131 remaining inventories, the 364,953
    observation total and the pinned global hashes are absent."""

    retention_policy = "gate5 rejection fixture"

    def test_generic_plans_are_rejected_at_both_layers(self):
        other = create_discovery_plan(variant_plan_payload())
        user = approver_user("gate5-generic")
        with self.assertRaisesMessage(
            DatasetQualityError, "only the approved replacement discovery plan may be approved"
        ):
            approve_and_register_discovery(
                other.sha256, user.pk, DISCOVERY_COMPLETION_SUMMARY_SHA256
            )
        with (
            self.assertRaisesMessage(
                DatabaseError, "only the approved replacement discovery plan may be approved"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [other.pk, user.pk, "a" * 64, "b" * 64, "c" * 64],
            )
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_superseded_v1_plan_remains_rejected(self):
        user = approver_user("gate5-v1")
        with self.assertRaisesMessage(
            DatasetQualityError, "superseded discovery plans cannot be approved"
        ):
            approve_and_register_discovery(
                self.superseded.sha256, user.pk, DISCOVERY_COMPLETION_SUMMARY_SHA256
            )
        with (
            self.assertRaisesMessage(DatabaseError, "superseded discovery plans reject new writes"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [self.superseded.pk, user.pk, "a" * 64, "b" * 64, "c" * 64],
            )
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_wrong_cross_series_hash_is_rejected(self):
        user = approver_user("gate5-wrong-artifact")
        for wrong in ("a" * 64, GATE5_APPROVAL_DECISION_SHA256):
            with self.assertRaisesMessage(
                DatasetQualityError,
                "gate5 approval requires the committed cross-series completion-summary hash",
            ):
                approve_and_register_discovery(self.replacement.sha256, user.pk, wrong)
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_incomplete_registration_state_is_rejected_at_both_layers(self):
        user = approver_user("gate5-incomplete")
        with self.assertRaisesMessage(
            DatasetQualityError, "every discovery chunk requires an accepted inventory"
        ):
            approve_and_register_discovery(
                self.replacement.sha256, user.pk, DISCOVERY_COMPLETION_SUMMARY_SHA256
            )
        for statement, params in (
            (
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [self.replacement.pk, user.pk, "a" * 64, "b" * 64, "c" * 64],
            ),
            (
                "UPDATE market_historicaldiscoveryplan SET sealed_at=now() WHERE id=%s",
                [self.replacement.pk],
            ),
        ):
            with (
                self.assertRaisesMessage(
                    DatabaseError, "gate5 registration state does not reconstruct"
                ),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(statement, params)
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_orm_bulk_and_queryset_bypasses_fail_closed(self):
        user = approver_user("gate5-bypass")
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalDiscoveryApproval.objects.bulk_create(
                [
                    HistoricalDiscoveryApproval(
                        plan=self.replacement,
                        approved_by=user,
                        global_semantic_inventory_sha256="a" * 64,
                        accepted_operational_evidence_set_sha256="b" * 64,
                        payload={},
                        sha256="c" * 64,
                        approved_at=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                ]
            )
        with self.assertRaises(DatabaseError), transaction.atomic():
            HistoricalDiscoveryPlan.objects.filter(pk=self.replacement.pk).update(
                sealed_at=datetime(2026, 1, 1, tzinfo=UTC)
            )
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_forged_global_hashes_cannot_shortcut_the_reconstruction(self):
        user = approver_user("gate5-forger")
        with (
            self.assertRaisesMessage(
                DatabaseError, "gate5 registration state does not reconstruct"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [
                    self.replacement.pk,
                    user.pk,
                    GLOBAL_SEMANTIC_INVENTORY_SHA256,
                    ACCEPTED_OPERATIONAL_EVIDENCE_SET_SHA256,
                    GATE5_APPROVAL_DECISION_SHA256,
                ],
            )
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_tampered_observation_fails_inventory_replay_despite_stored_hashes(self):
        """Self-consistent forgery: the stored summary hashes are left intact
        while an underlying observation row is altered with triggers disabled.
        Gate 5 must replay the hashes from the rows and reject."""
        user = approver_user("gate5-observation-forger")
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE market_historicaltimestampobservation DISABLE TRIGGER USER")
            try:
                cursor.execute(
                    """UPDATE market_historicaltimestampobservation SET volume=volume+1
                       WHERE id=(SELECT min(o.id)
                                 FROM market_historicaltimestampobservation o
                                 JOIN market_historicaltimestampinventory i
                                   ON i.id=o.inventory_id
                                 JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
                                 WHERE c.plan_id=%s)""",
                    [self.replacement.pk],
                )
            finally:
                cursor.execute(
                    "ALTER TABLE market_historicaltimestampobservation ENABLE TRIGGER USER"
                )
        with (
            self.assertRaisesMessage(DatabaseError, "gate5 inventory replay does not reconstruct"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [self.replacement.pk, user.pk, "a" * 64, "b" * 64, "c" * 64],
            )
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_tampered_evidence_fails_operational_replay_despite_stored_hashes(self):
        user = approver_user("gate5-evidence-forger")
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE market_historicaldiscoveryproviderevidence DISABLE TRIGGER USER"
            )
            try:
                cursor.execute(
                    """UPDATE market_historicaldiscoveryproviderevidence
                       SET provider_request_id='forged-request-id'
                       WHERE attempt_id=(SELECT min(a.id)
                                 FROM market_historicaldiscoveryattempt a
                                 JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
                                 WHERE c.plan_id=%s)""",
                    [self.replacement.pk],
                )
            finally:
                cursor.execute(
                    "ALTER TABLE market_historicaldiscoveryproviderevidence ENABLE TRIGGER USER"
                )
        with (
            self.assertRaisesMessage(
                DatabaseError, "gate5 operational evidence replay does not reconstruct"
            ),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [self.replacement.pk, user.pk, "a" * 64, "b" * 64, "c" * 64],
            )
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_permission_and_active_user_still_required(self):
        no_permission = get_user_model().objects.create_user("gate5-no-permission")
        with self.assertRaises(PermissionDenied):
            approve_and_register_discovery(
                self.replacement.sha256, no_permission.pk, DISCOVERY_COMPLETION_SUMMARY_SHA256
            )
        inactive = approver_user("gate5-inactive")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            approve_and_register_discovery(
                self.replacement.sha256, inactive.pk, DISCOVERY_COMPLETION_SUMMARY_SHA256
            )
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_concurrent_approval_attempts_serialize_and_leave_nothing(self):
        user = approver_user("gate5-concurrent")
        before = state_hashes(self.superseded, self.replacement)
        barrier = threading.Barrier(2)
        outcomes = []

        def attempt():
            barrier.wait(timeout=10)
            try:
                approve_and_register_discovery(
                    self.replacement.sha256, user.pk, DISCOVERY_COMPLETION_SUMMARY_SHA256
                )
                outcomes.append("committed")
            except DatasetQualityError as error:
                outcomes.append(str(error))
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(outcomes, ["every discovery chunk requires an accepted inventory"] * 2)
        self.assertEqual(registration_state(), (0, 0, 0))
        self.assertEqual(state_hashes(self.superseded, self.replacement), before)

    def test_complete_but_nonmatching_state_is_rejected_at_both_layers(self):
        """All 132 inventories exist, but synthetic observations cannot match
        the pinned global hashes or the 364,953 observation total."""
        client = WaveSuccessClient(self.replacement)
        for chunk in self.remaining:
            run_discovery_chunk(chunk.logical_key, client)
        self.assertEqual(
            HistoricalTimestampInventory.objects.filter(chunk__plan=self.replacement).count(),
            GATE5_ACCEPTED_INVENTORY_COUNT,
        )
        user = approver_user("gate5-nonmatching")
        with self.assertRaisesMessage(
            DatasetQualityError, "gate5 registration state does not reconstruct"
        ):
            approve_and_register_discovery(
                self.replacement.sha256, user.pk, DISCOVERY_COMPLETION_SUMMARY_SHA256
            )
        for statement, params in (
            (
                """INSERT INTO market_historicaldiscoveryapproval
                   (plan_id,approved_by_id,global_semantic_inventory_sha256,
                    accepted_operational_evidence_set_sha256,payload,sha256,approved_at)
                   VALUES (%s,%s,%s,%s,'{}'::jsonb,%s,now())""",
                [
                    self.replacement.pk,
                    user.pk,
                    GLOBAL_SEMANTIC_INVENTORY_SHA256,
                    ACCEPTED_OPERATIONAL_EVIDENCE_SET_SHA256,
                    GATE5_APPROVAL_DECISION_SHA256,
                ],
            ),
            (
                "UPDATE market_historicaldiscoveryplan SET sealed_at=now() WHERE id=%s",
                [self.replacement.pk],
            ),
        ):
            with (
                self.assertRaisesMessage(
                    DatabaseError, "gate5 registration state does not reconstruct"
                ),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(statement, params)
        self.assertEqual(registration_state(), (0, 0, 0))


class Gate5CommandTests(Gate4FixtureTestCase):
    retention_policy = "gate5 command fixture"

    def call(
        self,
        *,
        plan_sha256=None,
        artifact=None,
        summary=None,
        approver="gate5-operator",
        execute=True,
    ):
        arguments = [
            "--plan-sha256",
            plan_sha256 or DISCOVERY_V2_PLAN_SHA256,
            "--decision-artifact",
            artifact or str(DECISION_ARTIFACT_PATH),
            "--completion-summary",
            summary or str(COMPLETION_SUMMARY_PATH),
            "--approver",
            approver,
        ]
        if execute:
            arguments.append("--execute")
        output = StringIO()
        call_command("approve_discovery_registration", *arguments, stdout=output)
        return output.getvalue()

    def write_artifact(self, content):
        directory = tempfile.TemporaryDirectory(
            prefix="gate5-artifact-", ignore_cleanup_errors=True
        )
        self.addCleanup(directory.cleanup)
        path = os.path.join(directory.name, "decision.json")
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def test_command_rejects_wrong_plan_sha(self):
        approver_user("gate5-operator")
        with self.assertRaisesMessage(
            CommandError, "--plan-sha256 does not match the approved v2 plan"
        ):
            self.call(plan_sha256="a" * 64)
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_command_verifies_the_artifact_byte_for_byte(self):
        approver_user("gate5-operator")
        artifact_bytes = DECISION_ARTIFACT_PATH.read_bytes()
        tampered = json.loads(artifact_bytes)
        tampered["decisions"][0]["decision"] = "Altered decision text."
        for content in (
            artifact_bytes + b"\n",
            json.dumps(json.loads(artifact_bytes), sort_keys=True, indent=2).encode(),
            json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode(),
        ):
            with self.assertRaisesMessage(
                CommandError,
                "approval-decision artifact does not match the committed gate5 decision",
            ):
                self.call(artifact=self.write_artifact(content))
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_command_verifies_the_completion_summary_byte_for_byte(self):
        approver_user("gate5-operator")
        summary_bytes = COMPLETION_SUMMARY_PATH.read_bytes()
        for content in (summary_bytes + b"\n", summary_bytes.replace(b"132", b"133", 1)):
            with self.assertRaisesMessage(
                CommandError,
                "completion summary does not match the committed cross-series report",
            ):
                self.call(summary=self.write_artifact(content))
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_command_requires_an_existing_django_approver(self):
        with self.assertRaisesMessage(CommandError, "approver must be an existing Django user"):
            self.call(approver="gate5-nonexistent")
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_dry_run_performs_complete_validation_and_reports_not_ready(self):
        """The dry run reconstructs every count and identity in a rolled-back
        transaction; on this incomplete fixture it must report the exact
        shortfalls, run PostgreSQL's Gate 5 validator, and write nothing."""
        approver_user("gate5-operator")
        with self.assertRaisesMessage(CommandError, "gate5 dry run is not ready"):
            self.call(execute=False)
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "approve_discovery_registration",
                "--plan-sha256",
                DISCOVERY_V2_PLAN_SHA256,
                "--decision-artifact",
                str(DECISION_ARTIFACT_PATH),
                "--completion-summary",
                str(COMPLETION_SUMMARY_PATH),
                "--approver",
                "gate5-operator",
                stdout=output,
            )
        report = json.loads(output.getvalue())
        self.assertEqual(report["event"], "gate5_dry_run")
        self.assertFalse(report["executed"])
        self.assertFalse(report["ready"])
        self.assertFalse(report["plan_sealed"])
        self.assertTrue(report["approver_active"])
        self.assertTrue(report["approver_has_permission"])
        self.assertEqual(report["supersession_lineage_count"], 1)
        self.assertEqual(report["canary_lineage"], "reconstructed")
        self.assertEqual(report["chunk_count"], GATE5_ACCEPTED_INVENTORY_COUNT)
        self.assertEqual(report["inventory_count"], 1)
        self.assertIn("inventory count does not match the pin", report["problems"])
        self.assertIn("observation count does not match the pin", report["problems"])
        self.assertIn("every discovery chunk requires an accepted inventory", report["problems"])
        self.assertTrue(
            any("gate5" in item for item in report["problems"]),
            report["problems"],
        )
        self.assertIn("postgresql_gate5_validator", report)
        self.assertEqual(registration_state(), (0, 0, 0))

    def test_command_execute_fails_closed_without_the_complete_state(self):
        approver_user("gate5-operator")
        with self.assertRaisesMessage(
            CommandError, "every discovery chunk requires an accepted inventory"
        ):
            self.call()
        self.assertEqual(registration_state(), (0, 0, 0))
