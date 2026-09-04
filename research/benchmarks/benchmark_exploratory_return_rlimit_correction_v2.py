"""Synthetic PostgreSQL rehearsal for the forward-only memory correction."""

from __future__ import annotations

import json
import os
import resource
import sys
import threading
import time
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research import exploratory_return_memory_v2 as memory  # noqa: E402
from research import exploratory_return_runner_v2_governance as governance  # noqa: E402

DATABASE_PREFIX = "exploratory_return_rlimit_synthetic_"
SYNTHETIC_KEY = "synthetic-successor-authorization-once"


def _database_name(dsn):
    with psycopg.connect(dsn) as connection:
        return connection.execute("SELECT current_database()").fetchone()[0]


def _rows(dsn):
    with psycopg.connect(dsn) as connection:
        return connection.execute("SELECT count(*) FROM research_jobrun").fetchone()[0]


def _worker(channel, dsn, mode, delay_seconds=0.0):
    queries = {"duplicate_check": 0, "result_insert": 0, "readback_verify": 0}
    with psycopg.connect(dsn) as connection:
        with connection.transaction():
            queries["duplicate_check"] += 1
            existing = connection.execute(
                "SELECT 1 FROM research_jobrun WHERE idempotency_key=%s", (SYNTHETIC_KEY,)
            ).fetchone()
            if existing is not None:
                raise RuntimeError("synthetic successor result already exists")
            if delay_seconds:
                time.sleep(delay_seconds)
            queries["result_insert"] += 1
            connection.execute(
                "INSERT INTO research_jobrun(idempotency_key,evidence) VALUES (%s,%s)",
                (SYNTHETIC_KEY, Jsonb({"promotion_eligible": False, "synthetic": True})),
            )
            channel.send(("PROGRESS", "transaction_entered", 0, 1))
            if mode == "failure":
                raise RuntimeError("injected failure after transaction entry")
            if mode == "timeout":
                time.sleep(5)
            if mode == "memory":
                allocations = []
                while True:
                    allocations.append(bytearray(16 * 1024 * 1024))
            queries["readback_verify"] += 1
            evidence = connection.execute(
                "SELECT evidence FROM research_jobrun WHERE idempotency_key=%s", (SYNTHETIC_KEY,)
            ).fetchone()[0]
            if evidence != {"promotion_eligible": False, "synthetic": True}:
                raise RuntimeError("synthetic readback changed")
    return {"query_counts": queries, "row_committed": True}


def _invoke(dsn, mode="success", *, timeout=10, memory_ceiling=1_073_741_824, delay=0.0):
    started = perf_counter()
    progress = []
    with memory.operational_boundary(memory_ceiling) as ceiling:
        outcome = memory.run_isolated_worker(
            _worker,
            (dsn, mode, delay),
            memory_ceiling_bytes=ceiling,
            timeout_seconds=timeout,
            poll_interval_seconds=0.01,
            progress=lambda *message: progress.append(message),
        )
    return {
        "duration_seconds": round(perf_counter() - started, 6),
        "peak_rss_bytes": outcome.peak_rss_bytes,
        "progress": progress,
        **outcome.value,
    }


def _expect_rollback(dsn, mode, **kwargs):
    refusal = None
    try:
        _invoke(dsn, mode, **kwargs)
    except memory.MemoryBoundaryFailure as error:
        refusal = str(error)
    if refusal is None or _rows(dsn) != 0:
        raise RuntimeError(f"{mode} did not fail closed and roll back")
    return {"refusal": refusal, "rows_after": 0}


def _concurrency(dsn):
    outcomes = []

    def invoke():
        try:
            _invoke(dsn, delay=0.2)
            outcomes.append("COMMITTED")
        except memory.MemoryBoundaryFailure as error:
            if "UniqueViolation" not in str(error):
                raise
            outcomes.append("UNIQUE_CONSTRAINT_REFUSAL")

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    if any(thread.is_alive() for thread in threads):
        raise RuntimeError("concurrency rehearsal did not terminate")
    return sorted(outcomes)


def main():
    dsn = os.environ.get("EXPLORATORY_RETURN_SYNTHETIC_DSN", "")
    if not dsn or not _database_name(dsn).startswith(DATABASE_PREFIX):
        raise RuntimeError("explicit synthetic disposable database is required")
    predecessor = governance.inspect_predecessor_authorization_history()
    failure = governance.inspect_failed_execution()
    successor = governance.inspect_execution_authorization()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP TABLE IF EXISTS research_jobrun")
        connection.execute(
            "CREATE TABLE research_jobrun ("
            "id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
            "idempotency_key text NOT NULL UNIQUE,evidence jsonb NOT NULL)"
        )
        success = _invoke(dsn)
        rows_after_success = _rows(dsn)
        repeat = None
        try:
            _invoke(dsn)
        except memory.MemoryBoundaryFailure as error:
            repeat = str(error)
        connection.execute("TRUNCATE research_jobrun")
        injected = _expect_rollback(dsn, "failure")
        timeout = _expect_rollback(dsn, "timeout", timeout=0.1)
        memory_breach = _expect_rollback(dsn, "memory", memory_ceiling=128 * 1024 * 1024)
        concurrency = _concurrency(dsn)
        rows_after_concurrency = _rows(dsn)
    result = {
        "authority": {
            "favourable_synthetic_result_can_promote": False,
            "original_authorization_status": predecessor["status"],
            "successor_authorization_sha256": successor["artifact_sha256"],
            "verified_failure_sha256": failure["artifact_sha256"],
        },
        "concurrency": {
            "outcomes": concurrency,
            "rows_after": rows_after_concurrency,
            "unique_constraint_is_authority": True,
        },
        "database": "SYNTHETIC_DISPOSABLE_POSTGRESQL_NO_REAL_RESTORE",
        "injected_failure": injected,
        "invocation": (
            "EXPLORATORY_RETURN_SYNTHETIC_DSN=<disposable> .venv/bin/python "
            "research/benchmarks/benchmark_exploratory_return_rlimit_correction_v2.py"
        ),
        "memory_breach": memory_breach,
        "parent_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "repeat_refusal": repeat,
        "rows_after_success": rows_after_success,
        "rows_written_by_table": {"every_other_application_table": 0, "research_jobrun": 1},
        "success": success,
        "timeout": timeout,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
