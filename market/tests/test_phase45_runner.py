"""The explicitly requested evidence partition cannot grow its waiver silently."""

import hashlib
import unittest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test.runner import DiscoverRunner, iter_test_cases

from market.tests import phase45_runner as runner
from research.tests import test_failed_break_detector_v2_queries as fixture


class AvailableEvidenceRunnerTests(SimpleTestCase):
    label = "research.tests.test_failed_break_detector_v2_queries"

    def test_exact_reviewed_id_and_source_pins(self):
        self.assertEqual(len(runner.RESTORE_REQUIRED), 6)
        self.assertEqual(
            hashlib.sha256("\n".join(sorted(runner.RESTORE_REQUIRED)).encode()).hexdigest(),
            "bf0b6468bc644c40e5a5ef5fe077960c0ed01fe46fd7be840dc92cceafb01ffd",
        )
        self.assertEqual(
            hashlib.sha256(runner.RESTORE_REQUIRED_SOURCE.read_bytes()).hexdigest(),
            "43dbd64834689ed592152769332246989d0b78c192af27546bea986f00ca99eb",
        )
        default = DiscoverRunner(verbosity=0).load_tests_for_label(self.label, {})
        self.assertEqual({test.id() for test in iter_test_cases(default)}, runner.RESTORE_REQUIRED)
        explicit = runner.AvailableEvidenceRunner(verbosity=0).load_tests_for_label(self.label, {})
        self.assertEqual(list(iter_test_cases(explicit)), [])

    def test_identity_drift_fails_closed(self):
        with patch.object(runner, "RESTORE_REQUIRED", runner.RESTORE_REQUIRED | {"new.test"}):
            with self.assertRaisesMessage(RuntimeError, "identities/source drifted"):
                runner.AvailableEvidenceRunner().load_tests_for_label(self.label, {})

    def test_source_drift_fails_closed(self):
        with patch.object(runner, "RESTORE_REQUIRED_SOURCE") as source:
            source.read_bytes.return_value = b"changed source"
            with self.assertRaisesMessage(RuntimeError, "identities/source drifted"):
                runner.AvailableEvidenceRunner().load_tests_for_label(self.label, {})

    def test_missing_identity_fails_closed(self):
        with patch.object(runner.defaultTestLoader, "getTestCaseNames", return_value=[]):
            with self.assertRaisesMessage(RuntimeError, "identities missing"):
                runner.AvailableEvidenceRunner().load_tests_for_label(self.label, {})

    def test_unlisted_regression_is_retained_and_executed(self):
        executed = []

        def unrelated(test):
            executed.append(test.id())
            test.fail("injected unlisted regression executed")

        case = fixture.DetectorV2QueryBudgetTests
        name = "test_new_unrelated_regression"
        with patch.object(case, name, unrelated, create=True):
            suite = runner.AvailableEvidenceRunner(verbosity=0).load_tests_for_label(self.label, {})
            tests = list(iter_test_cases(suite))
            expected = f"{self.label}.DetectorV2QueryBudgetTests.{name}"
            self.assertEqual([test.id() for test in tests], [expected])
            # Bypass only this injected test's unrelated accepted-data setup;
            # execute its real unittest body and verify the failure is visible.
            result = unittest.TestResult()
            unittest.TestCase.run(tests[0], result)
        self.assertEqual(executed, [expected])
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("injected unlisted regression executed", result.failures[0][1])
