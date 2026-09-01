"""Gate 7C: the registration command reports creation status truthfully.

Registration is deliberately idempotent, so a second invocation receives the
existing immutable row and must say so rather than claiming a creation. The
decision is made under the same DatasetVersion lock the service takes, which is
what makes it correct under concurrency; the two-process race itself is proven
against the real provider-observed pins in the disposable post-Wave-6 rehearsal,
because the synthetic fixture cannot satisfy the database's sealed-inventory
hash check.
"""

import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection, transaction
from django.test import TransactionTestCase

from market.historical_acquisition import register_historical_dataset
from market.models import DatasetRegistration
from market.tests.test_historical_acquisition import HistoricalFixtureMixin

COMMAND = "market.management.commands.register_failed_break_dataset"


class Gate7CCommandReportingTests(HistoricalFixtureMixin, TransactionTestCase):
    """The v2 reporting branch, exercised on a real dataset row and a real
    DatasetRegistration table. Only the readiness inputs are stubbed: the
    creation-status decision, the lock and the registration row are real."""

    def setUp(self):
        super().setUp()
        self.plan_object, self.dataset = self.plan()
        self.readiness = {
            "observed": {
                field: value
                for field, value in (
                    ("data_contract_sha256", "a" * 64),
                    ("replacement_plan_sha256", self.plan_object.sha256),
                    ("replacement_dataset_manifest_sha256", self.dataset.manifest_sha256),
                    ("global_semantic_inventory_sha256", "b" * 64),
                    ("chunk_count", 132),
                    ("successful_attempt_count", 132),
                    ("ingestion_manifest_count", 132),
                    ("candle_count", 364953),
                    ("granularity_candle_totals", {"D": 17412, "H1": 344715, "W": 2826}),
                    ("logical_chunk_set_hash", "c" * 64),
                    ("successful_attempt_set_hash", "d" * 64),
                    ("ingestion_manifest_set_hash", "e" * 64),
                    ("candle_key_hash", "f" * 64),
                    ("candle_payload_hash", "0" * 64),
                )
            }
        }
        self.authorization = {
            "authorization_sha256": "1" * 64,
            "registration_identity": "failed-break-provider-observed-dataset-registration-v1",
        }

    def registration_row(self):
        """One registration row for this dataset. Its governed validators are
        suspended around the whole invocation by run_command(), because this
        suite exercises the command's creation-status reporting rather than
        registration eligibility, which the Gate 7C suite and the real-state
        rehearsal both cover."""
        return DatasetRegistration.objects.create(
            dataset_version=self.dataset,
            plan=self.plan_object,
            series_manifest=[],
            row_counts={"EUR_USD:D": 1},
            first_last_timestamps={},
            missingness={},
            conflict_count=0,
            incident_count=0,
            logical_chunk_set_hash="c" * 64,
            successful_attempt_set_hash="d" * 64,
            ingestion_manifest_set_hash="e" * 64,
            candle_key_hash="f" * 64,
            candle_payload_hash="0" * 64,
            configuration_sha256="",
            report_sha256="",
        )

    def run_command(self, *, execute, service, suspend_validators=False):
        stdout = StringIO()
        args = [
            "--dataset-id",
            str(self.dataset.pk),
            "--plan-sha256",
            self.plan_object.sha256,
        ]
        if execute:
            args.append("--execute")
        if suspend_validators:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE market_datasetregistration DISABLE TRIGGER USER")
        try:
            with (
                patch(
                    f"{COMMAND}.replacement_registration_contract",
                    return_value=SimpleNamespace(sha256="a" * 64),
                ),
                patch(
                    f"{COMMAND}.load_committed_registration_authorization",
                    return_value=self.authorization,
                ),
                patch(f"{COMMAND}.verify_registration_readiness", return_value=self.readiness),
                patch(f"{COMMAND}.register_historical_dataset", side_effect=service),
            ):
                call_command("register_failed_break_dataset", *args, stdout=stdout)
        finally:
            if suspend_validators:
                with connection.cursor() as cursor:
                    cursor.execute("ALTER TABLE market_datasetregistration ENABLE TRIGGER USER")
        return json.loads(stdout.getvalue())

    def test_first_execute_reports_created_and_repeat_reports_already_registered(self):
        # 1: the invocation that creates the row says so
        created = {}

        def create(dataset_id, plan_sha256):
            created["row"] = created.get("row") or self.registration_row()
            return created["row"]

        first = self.run_command(execute=True, service=create, suspend_validators=True)
        self.assertEqual(first["checkpoint"], "registered")
        self.assertEqual(first["registrations_created"], 1)
        self.assertEqual(DatasetRegistration.objects.count(), 1)
        row = DatasetRegistration.objects.get()

        # 2: a later idempotent invocation receives the same immutable row
        second = self.run_command(execute=True, service=lambda *args: row, suspend_validators=True)
        self.assertEqual(second["checkpoint"], "already-registered")
        self.assertEqual(second["registrations_created"], 0)
        self.assertEqual(second["report_sha256"], first["report_sha256"])
        self.assertEqual(second["configuration_sha256"], first["configuration_sha256"])
        self.assertEqual(DatasetRegistration.objects.count(), 1)
        self.assertEqual(DatasetRegistration.objects.get().pk, row.pk)

    def test_dry_run_stays_read_only_and_reports_zero(self):
        # 4
        def refuse(*args, **kwargs):
            raise AssertionError("a dry run must not call the registration service")

        report = self.run_command(execute=False, service=refuse)
        self.assertEqual(report["checkpoint"], "dry-run")
        self.assertTrue(report["read_only"])
        self.assertTrue(report["ready"])
        self.assertEqual(report["registrations_created"], 0)
        self.assertEqual(DatasetRegistration.objects.count(), 0)

    def test_creation_status_is_decided_under_the_dataset_row_lock(self):
        """The check is only authoritative if it runs while this transaction
        holds the DatasetVersion row, which is the same row the service locks."""
        locked = []

        def service(dataset_id, plan_sha256):
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT count(*) FROM pg_locks l
                       JOIN pg_class c ON c.oid=l.relation
                       WHERE c.relname='market_datasetversion' AND l.mode='RowShareLock'
                         AND l.pid=pg_backend_pid()"""
                )
                locked.append(cursor.fetchone()[0])
            return self.registration_row()

        report = self.run_command(execute=True, service=service, suspend_validators=True)
        self.assertEqual(report["registrations_created"], 1)
        self.assertTrue(locked and locked[0] >= 1, locked)

    def test_legacy_command_output_and_behaviour_are_unchanged(self):
        # 5: a legacy dataset registers on invocation with its historical keys
        stdout = StringIO()
        with patch(
            f"{COMMAND}.register_historical_dataset",
            return_value=SimpleNamespace(pk=7, report_sha256="a" * 64, row_counts={"EUR_USD:D": 1}),
        ) as service:
            call_command(
                "register_failed_break_dataset",
                "--dataset-id",
                str(self.dataset.pk),
                "--plan-sha256",
                self.plan_object.sha256,
                stdout=stdout,
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            sorted(payload), ["dataset_registration_id", "report_sha256", "row_counts"]
        )
        service.assert_called_once_with(self.dataset.pk, self.plan_object.sha256)

    def test_legacy_service_error_semantics_are_unchanged(self):
        from django.core.management.base import CommandError

        with (
            self.assertRaisesMessage(
                CommandError, "every historical chunk requires exactly one successful attempt"
            ),
            transaction.atomic(),
        ):
            call_command(
                "register_failed_break_dataset",
                "--dataset-id",
                str(self.dataset.pk),
                "--plan-sha256",
                self.plan_object.sha256,
            )
        self.assertEqual(DatasetRegistration.objects.count(), 0)
        self.assertIsNotNone(register_historical_dataset)
