"""Portable, fail-closed memory boundary for exploratory-return execution.

Darwin exposes ``RLIMIT_AS`` but rejects finite limits with ``EINVAL`` for the
native universal2/arm64 runtime used by this project.  The governed boundary
therefore runs the database transaction in an isolated child and monitors its
resident set from the parent.  Terminating the child closes its PostgreSQL
connection, so an in-flight transaction rolls back.
"""

from __future__ import annotations

import ctypes
import multiprocessing
import os
import resource
import signal
import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Any

MEMORY_CEILING_BYTES = 1_073_741_824
OPERATIONAL_CEILING_SECONDS = 900
POLL_INTERVAL_SECONDS = 0.05


class MemoryBoundaryFailure(RuntimeError):
    """The memory/timeout boundary could not be established or was exceeded."""


@dataclass(frozen=True)
class WorkerOutcome:
    value: Any
    peak_rss_bytes: int


def _is_infinite(value: int, infinity: int) -> bool:
    return value == infinity


def effective_memory_ceiling(
    limits: tuple[int, int],
    authorized_cap: int = MEMORY_CEILING_BYTES,
    *,
    infinity: int = resource.RLIM_INFINITY,
) -> int:
    """Return the strictest valid finite ceiling without changing rlimits."""

    soft, hard = limits
    if authorized_cap <= 0:
        raise MemoryBoundaryFailure("memory ceiling must be positive")
    if not _is_infinite(soft, infinity) and soft < 0:
        raise MemoryBoundaryFailure("invalid negative soft memory limit")
    if not _is_infinite(hard, infinity) and hard < 0:
        raise MemoryBoundaryFailure("invalid negative hard memory limit")
    if not _is_infinite(hard, infinity) and (_is_infinite(soft, infinity) or soft > hard):
        raise MemoryBoundaryFailure("invalid process memory-limit tuple")
    candidates = [authorized_cap]
    if not _is_infinite(soft, infinity):
        candidates.append(soft)
    if not _is_infinite(hard, infinity):
        candidates.append(hard)
    ceiling = min(candidates)
    if ceiling <= 0:
        raise MemoryBoundaryFailure("effective memory ceiling is not usable")
    return ceiling


class _DarwinRusageInfoV2(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64)
        for name in (
            "user_time",
            "system_time",
            "pkg_idle_wkups",
            "interrupt_wkups",
            "pageins",
            "wired_size",
            "resident_size",
            "phys_footprint",
            "proc_start_abstime",
            "proc_exit_abstime",
            "child_user_time",
            "child_system_time",
            "child_pkg_idle_wkups",
            "child_interrupt_wkups",
            "child_pageins",
            "child_elapsed_abstime",
            "diskio_bytesread",
            "diskio_byteswritten",
        )
    ]


def _darwin_resident_bytes(pid: int) -> int:
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        function = libproc.proc_pid_rusage
        function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        function.restype = ctypes.c_int
        usage = _DarwinRusageInfoV2()
        ctypes.set_errno(0)
        if function(pid, 2, ctypes.byref(usage)) != 0:
            raise OSError(ctypes.get_errno(), "proc_pid_rusage failed")
        return int(usage.resident_size)
    except (AttributeError, OSError) as error:
        raise MemoryBoundaryFailure("Darwin RSS monitoring is unavailable") from error


def _linux_resident_bytes(pid: int) -> int:
    try:
        fields = (Path("/proc") / str(pid) / "statm").read_text().split()
        return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")
    except (IndexError, OSError, TypeError, ValueError) as error:
        raise MemoryBoundaryFailure("Linux RSS monitoring is unavailable") from error


def resident_bytes(pid: int) -> int:
    if sys.platform == "darwin":
        return _darwin_resident_bytes(pid)
    if sys.platform.startswith("linux"):
        return _linux_resident_bytes(pid)
    raise MemoryBoundaryFailure("unsupported platform for RSS enforcement")


def _runtime_state():
    limit = resource.getrlimit(resource.RLIMIT_AS)
    handler = signal.getsignal(signal.SIGALRM) if hasattr(signal, "SIGALRM") else None
    timer = signal.getitimer(signal.ITIMER_REAL) if hasattr(signal, "getitimer") else None
    return limit, handler, timer


def _restore_runtime_state(original) -> None:
    original_limit, original_handler, original_timer = original
    failures = []
    try:
        if resource.getrlimit(resource.RLIMIT_AS) != original_limit:
            resource.setrlimit(resource.RLIMIT_AS, original_limit)
    except (OSError, ValueError) as error:
        failures.append(f"resource limit: {error}")
    try:
        if original_handler is not None and signal.getsignal(signal.SIGALRM) != original_handler:
            signal.signal(signal.SIGALRM, original_handler)
    except (OSError, RuntimeError, ValueError) as error:
        failures.append(f"signal handler: {error}")
    try:
        if original_timer is not None and signal.getitimer(signal.ITIMER_REAL) != original_timer:
            signal.setitimer(signal.ITIMER_REAL, *original_timer)
    except (OSError, ValueError) as error:
        failures.append(f"timer: {error}")
    if failures:
        raise MemoryBoundaryFailure("runtime-state restoration failed: " + "; ".join(failures))


@contextmanager
def operational_boundary(memory_ceiling_bytes: int = MEMORY_CEILING_BYTES):
    """Validate RSS enforcement and preserve timer/resource state exactly."""

    original = _runtime_state()
    primary_error = None
    try:
        ceiling = effective_memory_ceiling(original[0], memory_ceiling_bytes)
        if resident_bytes(os.getpid()) > ceiling:
            raise MemoryBoundaryFailure("parent already exceeds the governed memory ceiling")
        yield ceiling
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            _restore_runtime_state(original)
        except MemoryBoundaryFailure:
            if primary_error is None:
                raise
            raise MemoryBoundaryFailure("runtime-state restoration failed after execution error")


def _child_entry(target, child_connection, args):
    try:
        if child_connection.recv() != ("START",):
            raise MemoryBoundaryFailure("worker start handshake changed")
        value = target(child_connection, *args)
        child_connection.send(("RESULT", value))
    except MemoryError:
        child_connection.send(("ERROR", "MemoryError", "worker exceeded available memory"))
    except BaseException as error:
        child_connection.send(("ERROR", type(error).__name__, str(error)))
    finally:
        child_connection.close()


def _stop_process(process) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
    if process.is_alive():
        raise MemoryBoundaryFailure("isolated worker could not be terminated")


def run_isolated_worker(
    target: Callable[..., Any],
    args: tuple[Any, ...],
    *,
    memory_ceiling_bytes: int,
    timeout_seconds: float = OPERATIONAL_CEILING_SECONDS,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
    progress: Callable[[str, int, int], None] | None = None,
    multiprocessing_context=None,
) -> WorkerOutcome:
    """Run one worker while enforcing RSS and monotonic wall-clock ceilings."""

    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise MemoryBoundaryFailure("invalid watchdog timing")
    context = multiprocessing_context or multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=True)
    process = context.Process(target=_child_entry, args=(target, child_connection, args))
    started = monotonic()
    peak_rss = 0
    result = None
    try:
        process.start()
        child_connection.close()
        peak_rss = resident_bytes(process.pid)
        if peak_rss > memory_ceiling_bytes:
            raise MemoryBoundaryFailure("worker exceeded the governed memory ceiling")
        parent_connection.send(("START",))
        while True:
            if monotonic() - started > timeout_seconds:
                raise MemoryBoundaryFailure(
                    "exploratory return execution exceeded 15-minute ceiling"
                )
            if process.is_alive():
                peak_rss = max(peak_rss, resident_bytes(process.pid))
                if peak_rss > memory_ceiling_bytes:
                    raise MemoryBoundaryFailure("worker exceeded the governed memory ceiling")
            if parent_connection.poll(poll_interval_seconds):
                message = parent_connection.recv()
                if message[0] == "PROGRESS":
                    if progress is not None:
                        progress(message[1], message[2], message[3])
                elif message[0] == "RESULT":
                    result = message[1]
                elif message[0] == "ERROR":
                    raise MemoryBoundaryFailure(f"worker failed closed: {message[1]}: {message[2]}")
                else:
                    raise MemoryBoundaryFailure("worker emitted an unknown message")
            if result is not None:
                process.join(timeout=5)
                if process.is_alive() or process.exitcode != 0:
                    raise MemoryBoundaryFailure("worker did not exit cleanly after result")
                return WorkerOutcome(value=result, peak_rss_bytes=peak_rss)
            if not process.is_alive():
                process.join(timeout=1)
                if parent_connection.poll():
                    continue
                raise MemoryBoundaryFailure(
                    f"worker exited without a complete result (exit={process.exitcode})"
                )
            sleep(0)
    finally:
        _stop_process(process)
        parent_connection.close()
        child_connection.close()
