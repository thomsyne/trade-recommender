"""Gate 7C: the registration command reports creation status truthfully.

The provider-observed command has two distinct already-registered outcomes, and
this suite states each one exactly:

* Concurrently, two --execute processes can both clear readiness before either
  commits. The winner reports registered/1; the loser blocks on the dataset row
  lock and then reports already-registered/0. That path is reachable only under
  concurrency, and the authoritative positive evidence for it is the completed
  two-process rehearsal on the real post-Wave-6 state, not this suite.
* Sequentially, a later invocation reaches the real readiness gate after the
  registration exists, so it fails closed with a CommandError and emits no
  registration JSON. That is exercised here against the real gate.

Tests that drive the reporting branches directly stub only the readiness inputs;
where a test would otherwise depend on the readiness gate being bypassed, it
uses the real gate instead and asserts the real outcome.
"""

import json
from contextlib import ExitStack
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

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

    def run_command(self, *, execute, service, suspend_validators=False, stub_readiness=True):
        """Invoke the command. stub_readiness=False runs the real readiness
        gate, which is what a later sequential invocation actually meets."""
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
            with ExitStack() as stack:
                stack.enter_context(
                    patch(
                        f"{COMMAND}.replacement_registration_contract",
                        return_value=SimpleNamespace(sha256="a" * 64),
                    )
                )
                stack.enter_context(
                    patch(
                        f"{COMMAND}.load_committed_registration_authorization",
                        return_value=self.authorization,
                    )
                )
                stack.enter_context(
                    patch(f"{COMMAND}.register_historical_dataset", side_effect=service)
                )
                if stub_readiness:
                    stack.enter_context(
                        patch(
                            f"{COMMAND}.verify_registration_readiness",
                            return_value=self.readiness,
                        )
                    )
                call_command("register_failed_break_dataset", *args, stdout=stdout)
        finally:
            if suspend_validators:
                with connection.cursor() as cursor:
                    cursor.execute("ALTER TABLE market_datasetregistration ENABLE TRIGGER USER")
        return json.loads(stdout.getvalue()) if stdout.getvalue() else None

    def test_first_execute_reports_created(self):
        """1: the invocation that creates the row says registered/1."""
        report = self.run_command(
            execute=True, service=lambda *args: self.registration_row(), suspend_validators=True
        )
        self.assertEqual(report["checkpoint"], "registered")
        self.assertEqual(report["registrations_created"], 1)
        self.assertFalse(report["read_only"])
        self.assertEqual(DatasetRegistration.objects.count(), 1)

    def test_later_sequential_execute_fails_closed_through_the_real_readiness_gate(self):
        """2: a later invocation meets the real readiness gate, which refuses
        because the registration already exists. It emits no registration JSON,
        creates nothing and leaves the committed row and its hashes intact."""
        first = self.run_command(
            execute=True, service=lambda *args: self.registration_row(), suspend_validators=True
        )
        self.assertEqual(first["registrations_created"], 1)
        row = DatasetRegistration.objects.get()
        before = (row.pk, row.report_sha256, row.configuration_sha256)

        def refuse(*args, **kwargs):
            raise AssertionError("the registration service must not be reached")

        stdout = StringIO()
        with (
            self.assertRaisesMessage(CommandError, "replacement dataset is already registered"),
            patch(
                f"{COMMAND}.replacement_registration_contract",
                return_value=SimpleNamespace(sha256="a" * 64),
            ),
            patch(
                f"{COMMAND}.load_committed_registration_authorization",
                return_value=self.authorization,
            ),
            patch(f"{COMMAND}.register_historical_dataset", side_effect=refuse),
        ):
            call_command(
                "register_failed_break_dataset",
                "--dataset-id",
                str(self.dataset.pk),
                "--plan-sha256",
                self.plan_object.sha256,
                "--execute",
                stdout=stdout,
            )
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(DatasetRegistration.objects.count(), 1)
        row.refresh_from_db()
        self.assertEqual((row.pk, row.report_sha256, row.configuration_sha256), before)

    def test_already_registered_branch_reports_zero_when_the_locked_check_finds_a_row(self):
        """3: the reporting branch itself. In production this state is reached
        only when a concurrent invocation commits between this one's readiness
        check and its dataset lock; the two-process rehearsal on the real
        post-Wave-6 state is the authoritative evidence that it occurs. Here the
        branch is driven directly so its output cannot regress."""
        first = self.run_command(
            execute=True, service=lambda *args: self.registration_row(), suspend_validators=True
        )
        row = DatasetRegistration.objects.get()
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

    def test_for_update_precedes_the_existence_check_and_service_in_one_transaction(self):
        """The observable ordering: the command issues SELECT ... FOR UPDATE on
        the dataset before it queries the registration table, and both the
        existence check and the service call happen inside one open
        transaction. This asserts ordering and transaction scope only. It does
        not, and cannot, demonstrate row contention between two sessions; the
        real two-process rehearsal is the evidence for actual serialization."""
        observed = {}

        def service(dataset_id, plan_sha256):
            observed["in_atomic_block"] = connection.in_atomic_block
            return self.registration_row()

        with CaptureQueriesContext(connection) as captured:
            report = self.run_command(execute=True, service=service, suspend_validators=True)

        self.assertEqual(report["registrations_created"], 1)
        self.assertTrue(observed["in_atomic_block"])
        statements = [query["sql"] for query in captured.captured_queries]
        for_update = [
            index
            for index, sql in enumerate(statements)
            if "market_datasetversion" in sql and "FOR UPDATE" in sql.upper()
        ]
        registration_reads = [
            index
            for index, sql in enumerate(statements)
            if "market_datasetregistration" in sql and sql.lstrip().upper().startswith("SELECT")
        ]
        self.assertTrue(for_update, statements)
        self.assertTrue(registration_reads, statements)
        self.assertLess(min(for_update), min(registration_reads))

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
