"""Explicit Phase4.5 verification partition; never the application's default runner.

The excluded fixture fabricates an accepted registration and is rejected by the
real governance triggers. Its six checks require an authorized genuine restore,
not a disabled trigger or weakened assertion. Always print their exact IDs.
"""

import hashlib
from importlib import import_module
from pathlib import Path
from unittest import defaultTestLoader

from django.test.runner import DiscoverRunner, ParallelTestSuite, iter_test_cases

RESTORE_REQUIRED = frozenset(
    {
        "research.tests.test_failed_break_detector_v2_queries.DetectorV2QueryBudgetTests.test_contract_identity_as_dataset_name_is_refused",
        "research.tests.test_failed_break_detector_v2_queries.DetectorV2QueryBudgetTests.test_dataset_name_as_contract_identity_is_refused",
        "research.tests.test_failed_break_detector_v2_queries.DetectorV2QueryBudgetTests.test_every_other_pinned_identity_mismatch_remains_fail_closed",
        "research.tests.test_failed_break_detector_v2_queries.DetectorV2QueryBudgetTests.test_every_registration_identity_mismatch_remains_fail_closed",
        "research.tests.test_failed_break_detector_v2_queries.DetectorV2QueryBudgetTests.test_exact_accepted_dataset3_identity_uses_one_registration_query",
        "research.tests.test_failed_break_detector_v2_queries.DetectorV2QueryBudgetTests.test_preload_query_budget_is_three_independent_of_row_count",
    }
)
RESTORE_REQUIRED_IDS_SHA256 = "bf0b6468bc644c40e5a5ef5fe077960c0ed01fe46fd7be840dc92cceafb01ffd"
RESTORE_REQUIRED_SOURCE_SHA256 = "43dbd64834689ed592152769332246989d0b78c192af27546bea986f00ca99eb"
RESTORE_REQUIRED_SOURCE = (
    Path(__file__).resolve().parents[2] / "research/tests/test_failed_break_detector_v2_queries.py"
)


class ChildProcessSafeSuite(ParallelTestSuite):
    def run(self, result):
        # Django's workers are daemons and cannot launch the real isolated
        # research worker. Run those tests in this parent, never skip them.
        serial = []
        parallel = []
        for suite in self.subsuites:
            target = (
                serial
                if any(
                    test.id().startswith(
                        "research.tests.test_exploratory_return_memory_v2.RuntimeBoundaryTests."
                    )
                    for test in iter_test_cases(suite)
                )
                else parallel
            )
            target.append(suite)
        self.subsuites = parallel
        super().run(result)
        for suite in serial:
            if not result.shouldStop:
                suite.run(result)
        return result


class AvailableEvidenceRunner(DiscoverRunner):
    parallel_test_suite = ChildProcessSafeSuite

    def load_tests_for_label(self, *args, **kwargs):
        if (
            hashlib.sha256("\n".join(sorted(RESTORE_REQUIRED)).encode()).hexdigest()
            != RESTORE_REQUIRED_IDS_SHA256
            or hashlib.sha256(RESTORE_REQUIRED_SOURCE.read_bytes()).hexdigest()
            != RESTORE_REQUIRED_SOURCE_SHA256
        ):
            raise RuntimeError("Phase4.5 waiver identities/source drifted; review required")
        fixture = import_module("research.tests.test_failed_break_detector_v2_queries")
        case = fixture.DetectorV2QueryBudgetTests
        actual_ids = {case(name).id() for name in defaultTestLoader.getTestCaseNames(case)}
        if not RESTORE_REQUIRED.issubset(actual_ids):
            raise RuntimeError("Phase4.5 waived test identities missing; review required")
        # Filter before Django partitions the suite; preserve --parallel and
        # its process-local database ownership rather than flattening it later.
        suite = super().load_tests_for_label(*args, **kwargs)
        available = []
        for test in iter_test_cases(suite):
            if test.id() in RESTORE_REQUIRED:
                self.log(f"RESTORE REQUIRED (not executed): {test.id()}")
            else:
                available.append(test)
        return self.test_suite(available)
