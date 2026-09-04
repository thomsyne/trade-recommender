"""Deterministic synthetic full-path benchmark for the v2 return runner.

Invocation:
    .venv/bin/python research/benchmarks/benchmark_exploratory_return_runner_v2.py

No Django setup, database, provider, network or real candle evidence is used.
"""

from __future__ import annotations

import json
import platform
import resource
import sys
import tracemalloc
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.benchmarks.benchmark_exploratory_returns_v2 import synthetic_event  # noqa: E402
from research.exploratory_return_runner_v2 import (  # noqa: E402
    SyntheticAtomicStore,
    SyntheticEvidenceAdapter,
    run_authorized,
    synthetic_authorization,
    synthetic_lineage,
)


def one_run(*, inject_failure_after=None):
    events = [synthetic_event(index) for index in range(82)]
    keys = tuple(row["physical_event_key"] for row in events)
    adapter = SyntheticEvidenceAdapter(events, synthetic_lineage())
    store = SyntheticAtomicStore()
    timings = {}
    tracemalloc.start()
    started = perf_counter()
    rolled_back = False
    try:
        payload = run_authorized(
            authorization=synthetic_authorization(),
            expected_keys=keys,
            adapter=adapter,
            store=store,
            bootstrap=True,
            inject_failure_after=inject_failure_after,
            timings=timings,
        )
    except ValueError:
        payload = None
        rolled_back = not store.rows
    duration = perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "duration_seconds": round(duration, 6),
        "evidence_sha256": payload["evidence_sha256"] if payload else None,
        "event_count": 82,
        "output_hashes": payload["output_hashes"] if payload else None,
        "peak_bytes": peak,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "query_counts": {**adapter.query_counts, **store.query_counts},
        "result_rows": len(store.rows),
        "rows_written_by_table": {"research_jobrun": len(store.rows)},
        "rolled_back": rolled_back,
        "timings": {key: round(value, 6) for key, value in sorted(timings.items())},
    }


def main():
    first = one_run()
    second = one_run()
    rollback = {stage: one_run(inject_failure_after=stage) for stage in ("insert", "readback")}
    assert first["evidence_sha256"] == second["evidence_sha256"]
    assert all(row["rolled_back"] for row in rollback.values())
    report = {
        "coverage": "SYNTHETIC_82_EVENT_ADAPTER_CALCULATOR_10000_BOOTSTRAP_ATOMIC_STORE",
        "database_disclosure": "NO_DATABASE; QUERY_COUNTS_ARE_SYNTHETIC_REPOSITORY_PORT_CALLS",
        "environment": {
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "exclusions": [
            "POSTGRESQL_LATENCY",
            "JSONB_WRITE_AND_COMMIT",
            "DATABASE_CONSTRAINT_OR_TRIGGER_TIME",
            "REAL_SEALED_EVIDENCE_LOADING",
        ],
        "invocation": ".venv/bin/python research/benchmarks/benchmark_exploratory_return_runner_v2.py",
        "repeat": second,
        "rollback": rollback,
        "run": first,
    }
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
