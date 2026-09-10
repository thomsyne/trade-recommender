"""Explicit Phase4.5 verification partition; never the application's default runner.

The excluded fixture fabricates an accepted registration and is rejected by the
real governance triggers. Its six checks require an authorized genuine restore,
not a disabled trigger or weakened assertion. Always print their exact IDs.
"""

from django.test.runner import DiscoverRunner, ParallelTestSuite, iter_test_cases

RESTORE_REQUIRED = (
    "research.tests.test_failed_break_detector_v2_queries.DetectorV2QueryBudgetTests."
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
        # Filter before Django partitions the suite; preserve --parallel and
        # its process-local database ownership rather than flattening it later.
        suite = super().load_tests_for_label(*args, **kwargs)
        available = []
        for test in iter_test_cases(suite):
            if test.id().startswith(RESTORE_REQUIRED):
                self.log(f"RESTORE REQUIRED (not executed): {test.id()}")
            else:
                available.append(test)
        return self.test_suite(available)
