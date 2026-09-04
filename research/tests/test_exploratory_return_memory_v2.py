from __future__ import annotations

import resource
import signal
import time
import unittest
from unittest import mock

from research import exploratory_return_memory_v2 as memory
from research import exploratory_return_runner_v2 as runner


def _successful_worker(channel, value):
    channel.send(("PROGRESS", "synthetic", 1, 1))
    return value


def _sleeping_worker(_channel, seconds):
    time.sleep(seconds)
    return "late"


def _memory_error_worker(_channel):
    raise MemoryError


def _partial_then_error_worker(channel):
    channel.send(("PROGRESS", "synthetic", 0, 1))
    raise RuntimeError("injected failure")


class EffectiveCeilingTests(unittest.TestCase):
    def test_limit_tuple_matrix(self):
        infinity = resource.RLIM_INFINITY
        cap = 1_073_741_824
        cases = (
            ((infinity, infinity), cap),
            ((512_000_000, infinity), 512_000_000),
            ((2_000_000_000, infinity), cap),
            ((infinity, 700_000_000), None),
            ((600_000_000, 700_000_000), 600_000_000),
            ((700_000_000, 700_000_000), 700_000_000),
        )
        for limits, expected in cases:
            with self.subTest(limits=limits):
                if expected is None:
                    with self.assertRaisesRegex(memory.MemoryBoundaryFailure, "invalid"):
                        memory.effective_memory_ceiling(limits, cap)
                else:
                    self.assertEqual(memory.effective_memory_ceiling(limits, cap), expected)

    def test_exact_failed_host_tuple_is_handled_without_setrlimit(self):
        failed = (9_223_372_036_854_775_807, 9_223_372_036_854_775_807)
        with mock.patch.object(memory.resource, "RLIM_INFINITY", failed[0]):
            self.assertEqual(
                memory.effective_memory_ceiling(failed, infinity=failed[0]),
                memory.MEMORY_CEILING_BYTES,
            )

    def test_invalid_and_unsupported_behaviour_fails_closed(self):
        with self.assertRaises(memory.MemoryBoundaryFailure):
            memory.effective_memory_ceiling((10, 5), 100, infinity=-1)
        with (
            mock.patch.object(memory.sys, "platform", "unsupported"),
            self.assertRaisesRegex(memory.MemoryBoundaryFailure, "unsupported"),
        ):
            memory.resident_bytes(1)


class RuntimeBoundaryTests(unittest.TestCase):
    def test_actual_host_smoke_preserves_resource_and_timer_state(self):
        before = memory._runtime_state()
        with runner._operational_limits() as ceiling:
            self.assertGreaterEqual(ceiling, 1)
            self.assertGreater(memory.resident_bytes(__import__("os").getpid()), 0)
        self.assertEqual(memory._runtime_state(), before)

    def test_restoration_after_injected_exception(self):
        before = memory._runtime_state()
        with self.assertRaisesRegex(RuntimeError, "injected"):
            with runner._operational_limits():
                raise RuntimeError("injected")
        self.assertEqual(memory._runtime_state(), before)

    def test_restoration_failure_is_governed(self):
        original = ((resource.RLIM_INFINITY, resource.RLIM_INFINITY), signal.SIG_DFL, (0.0, 0.0))
        with (
            mock.patch.object(memory, "_runtime_state", return_value=original),
            mock.patch.object(memory, "resident_bytes", return_value=1),
            mock.patch.object(
                memory,
                "_restore_runtime_state",
                side_effect=memory.MemoryBoundaryFailure("runtime-state restoration failed"),
            ),
            self.assertRaisesRegex(runner.RunnerRefusal, "restoration"),
        ):
            with runner._operational_limits():
                pass

    def test_timeout_restores_state_and_terminates_worker(self):
        before = memory._runtime_state()
        with runner._operational_limits() as ceiling:
            with self.assertRaisesRegex(memory.MemoryBoundaryFailure, "15-minute"):
                memory.run_isolated_worker(
                    _sleeping_worker,
                    (1.0,),
                    memory_ceiling_bytes=ceiling,
                    timeout_seconds=0.1,
                    poll_interval_seconds=0.01,
                )
        self.assertEqual(memory._runtime_state(), before)

    def test_memory_error_and_partial_result_fail_closed(self):
        with runner._operational_limits() as ceiling:
            with self.assertRaisesRegex(memory.MemoryBoundaryFailure, "MemoryError"):
                memory.run_isolated_worker(
                    _memory_error_worker,
                    (),
                    memory_ceiling_bytes=ceiling,
                    timeout_seconds=5,
                )
            messages = []
            with self.assertRaisesRegex(memory.MemoryBoundaryFailure, "injected failure"):
                memory.run_isolated_worker(
                    _partial_then_error_worker,
                    (),
                    memory_ceiling_bytes=ceiling,
                    timeout_seconds=5,
                    progress=lambda *message: messages.append(message),
                )
        self.assertEqual(messages, [("synthetic", 0, 1)])
        self.assertNotIn("result", repr(messages).lower())

    def test_corrected_boundary_permits_isolated_success(self):
        messages = []
        with runner._operational_limits() as ceiling:
            outcome = memory.run_isolated_worker(
                _successful_worker,
                ({"complete": True},),
                memory_ceiling_bytes=ceiling,
                timeout_seconds=5,
                progress=lambda *message: messages.append(message),
            )
        self.assertEqual(outcome.value, {"complete": True})
        self.assertGreater(outcome.peak_rss_bytes, 0)
        self.assertEqual(messages, [("synthetic", 1, 1)])


if __name__ == "__main__":
    unittest.main()
