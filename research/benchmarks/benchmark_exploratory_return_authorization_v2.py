"""Disposable-PostgreSQL rehearsal for the v2 return execution authorization.

The database must be explicitly named with the governed synthetic prefix.  The
harness creates only a minimal synthetic ``research_jobrun`` table and never
loads, restores, or queries real research evidence.
"""

from __future__ import annotations

import json
import os
import resource
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research import exploratory_return_runner_v2 as runner  # noqa: E402
from research import exploratory_return_runner_v2_governance as governance  # noqa: E402
from research.benchmarks.benchmark_exploratory_returns_v2 import synthetic_event  # noqa: E402

DATABASE_PREFIX = "exploratory_return_auth_synthetic_"


class PostgresSyntheticStore:
    def __init__(self, dsn, barrier=None):
        self.connection = psycopg.connect(dsn)
        self.barrier = barrier
        self.query_counts = {}

    @contextmanager
    def atomic(self):
        with self.connection.transaction():
            yield

    def ensure_absent(self, idempotency_key):
        self.query_counts["duplicate_check"] = self.query_counts.get("duplicate_check", 0) + 1
        row = self.connection.execute(
            "SELECT 1 FROM research_jobrun WHERE idempotency_key=%s", (idempotency_key,)
        ).fetchone()
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        runner.require(row is None, "exploratory result already exists")

    def persist(self, payload, *, inject_failure_after=None):
        self.query_counts["result_insert"] = self.query_counts.get("result_insert", 0) + 1
        self.connection.execute(
            "INSERT INTO research_jobrun(idempotency_key,evidence) VALUES (%s,%s)",
            (runner.IDEMPOTENCY_KEY, Jsonb(payload)),
        )
        if inject_failure_after == "insert":
            raise runner.RunnerRefusal("injected failure after insert")
        self.query_counts["readback_verify"] = self.query_counts.get("readback_verify", 0) + 1
        stored = self.connection.execute(
            "SELECT evidence FROM research_jobrun WHERE idempotency_key=%s",
            (runner.IDEMPOTENCY_KEY,),
        ).fetchone()[0]
        runner.require(stored == payload, "persistent readback changed")
        if inject_failure_after == "readback":
            raise runner.RunnerRefusal("injected failure after readback")

    def close(self):
        self.connection.close()


def _database_name(dsn):
    with psycopg.connect(dsn) as connection:
        return connection.execute("SELECT current_database()").fetchone()[0]


def _reset(connection):
    connection.execute("TRUNCATE research_jobrun")


def _count(connection):
    return connection.execute("SELECT count(*) FROM research_jobrun").fetchone()[0]


def _run(dsn, *, bootstrap, inject_failure_after=None):
    events = [synthetic_event(index) for index in range(82)]
    keys = tuple(sorted(row["physical_event_key"] for row in events))
    adapter = runner.SyntheticEvidenceAdapter(events, runner.synthetic_lineage())
    store = PostgresSyntheticStore(dsn)
    started = perf_counter()
    try:
        payload = runner.run_authorized(
            authorization=runner.synthetic_authorization(
                artifact_sha256=governance.AUTHORIZATION_ARTIFACT_SHA256,
                policy_sha256=governance.S2_POLICY_SHA256,
            ),
            expected_keys=keys,
            adapter=adapter,
            store=store,
            bootstrap=bootstrap,
            inject_failure_after=inject_failure_after,
        )
    except runner.RunnerRefusal:
        if inject_failure_after is None:
            raise
        payload = None
    finally:
        store.close()
    return {
        "duration_seconds": round(perf_counter() - started, 6),
        "evidence_sha256": payload["evidence_sha256"] if payload else None,
        "output_hashes": payload["output_hashes"] if payload else None,
        "query_counts": {**adapter.query_counts, **store.query_counts},
    }


def _concurrency(dsn):
    events = [synthetic_event(index) for index in range(82)]
    keys = tuple(sorted(row["physical_event_key"] for row in events))
    barrier = threading.Barrier(2)
    outcomes = []

    def invoke():
        store = PostgresSyntheticStore(dsn, barrier)
        adapter = runner.SyntheticEvidenceAdapter(events, runner.synthetic_lineage())
        try:
            runner.run_authorized(
                authorization=runner.synthetic_authorization(
                    artifact_sha256=governance.AUTHORIZATION_ARTIFACT_SHA256,
                    policy_sha256=governance.S2_POLICY_SHA256,
                ),
                expected_keys=keys,
                adapter=adapter,
                store=store,
                bootstrap=False,
            )
            outcomes.append("COMMITTED")
        except psycopg.errors.UniqueViolation:
            outcomes.append("UNIQUE_CONSTRAINT_REFUSAL")
        finally:
            store.close()

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
    governance.inspect_execution_authorization()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP TABLE IF EXISTS research_jobrun")
        connection.execute(
            "CREATE TABLE research_jobrun ("
            "id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
            "idempotency_key text NOT NULL UNIQUE,evidence jsonb NOT NULL)"
        )
        run = _run(dsn, bootstrap=True)
        rows_after_success = _count(connection)
        repeat_refusal = None
        try:
            _run(dsn, bootstrap=False)
        except runner.RunnerRefusal as error:
            repeat_refusal = str(error)
        _reset(connection)
        rollbacks = {}
        for stage in ("insert", "readback"):
            rollbacks[stage] = _run(dsn, bootstrap=False, inject_failure_after=stage)
            rollbacks[stage]["rows_after"] = _count(connection)
        _reset(connection)
        concurrency = _concurrency(dsn)
        rows_after_concurrency = _count(connection)
    result = {
        "authorization_artifact_sha256": governance.AUTHORIZATION_ARTIFACT_SHA256,
        "concurrency": {
            "outcomes": concurrency,
            "rows_after": rows_after_concurrency,
            "unique_constraint_is_authority": True,
        },
        "database": "SYNTHETIC_DISPOSABLE_POSTGRESQL_NO_REAL_RESTORE",
        "event_count": 82,
        "invocation": (
            "EXPLORATORY_RETURN_SYNTHETIC_DSN=<disposable> .venv/bin/python "
            "research/benchmarks/benchmark_exploratory_return_authorization_v2.py"
        ),
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "repeat_refusal": repeat_refusal,
        "rollback": rollbacks,
        "rows_after_success": rows_after_success,
        "rows_written_by_table": {"research_jobrun": 1, "every_other_application_table": 0},
        "run": run,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
