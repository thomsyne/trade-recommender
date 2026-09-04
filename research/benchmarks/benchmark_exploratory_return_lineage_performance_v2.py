"""Bounded synthetic proof for the v2 lineage-performance correction.

Invocation:
    .venv/bin/python research/benchmarks/benchmark_exploratory_return_lineage_performance_v2.py

The 82-event workload mirrors the observed production H1-path cardinality but
uses deterministic synthetic timestamps and prices.  It never imports Django,
opens a database, or contacts a provider.  The separate lookup workload uses
the measured production inventory/call cardinalities and no price values.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from bisect import bisect_left
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.benchmarks.benchmark_exploratory_returns_v2 import synthetic_event  # noqa: E402
from research.exploratory_return_memory_v2 import (  # noqa: E402
    MEMORY_CEILING_BYTES,
    resident_bytes,
    run_isolated_worker,
)
from research.exploratory_return_runner_v2 import (  # noqa: E402
    SyntheticAtomicStore,
    SyntheticEvidenceAdapter,
    run_authorized,
    synthetic_authorization,
    synthetic_lineage,
)

EVENT_COUNT = 82
H1_MEMBERS_PER_EVENT = 241
MEASURED_PRIOR_LOOKUP_CALLS = 19_878
MEASURED_LEGACY_ELEMENTS_SCANNED = 1_141_664_450
MEASURED_NEEDED_CANDLES = 27_969
MEASURED_INVENTORY_MEMBERS = 362_229


def production_shaped_event(index: int) -> dict:
    """Return a synthetic event with a ten-day, hourly sealed path."""

    event = synthetic_event(index)
    entry = datetime.fromisoformat(event["entry_at"])
    starts = [entry + timedelta(hours=hour) for hour in range(H1_MEMBERS_PER_EVENT)]
    template = event["h1"][0]
    event["expected_h1_starts"] = [value.isoformat() for value in starts]
    event["h1"] = [{**template, "start": value.isoformat()} for value in starts]
    event["horizon_at"] = starts[-1].isoformat()
    event["d_completions"] = [(entry + timedelta(days=day)).isoformat() for day in range(1, 11)]
    event["daily"] = [
        {
            "complete": True,
            "completed_at": completed,
            "conflict": False,
            "mid_close": "1.0200",
            "sealed": True,
        }
        for completed in event["d_completions"]
    ]
    return event


def _worker(_channel) -> dict:
    events = [production_shaped_event(index) for index in range(EVENT_COUNT)]
    keys = tuple(row["physical_event_key"] for row in events)
    adapter = SyntheticEvidenceAdapter(events, synthetic_lineage())
    store = SyntheticAtomicStore()
    timings: dict[str, float] = {}
    started = perf_counter()
    payload = run_authorized(
        authorization=synthetic_authorization(),
        expected_keys=keys,
        adapter=adapter,
        store=store,
        bootstrap=True,
        timings=timings,
    )
    return {
        "duration_seconds": round(perf_counter() - started, 6),
        "evidence_sha256": payload["evidence_sha256"],
        "event_count": EVENT_COUNT,
        "h1_rows": sum(len(row["h1"]) for row in events),
        "query_counts": {**adapter.query_counts, **store.query_counts},
        "result_rows": len(store.rows),
        "timings": {key: round(value, 6) for key, value in sorted(timings.items())},
    }


def _run_worker() -> dict:
    parent_rss_before = resident_bytes(os.getpid())
    started = perf_counter()
    outcome = run_isolated_worker(
        _worker,
        (),
        memory_ceiling_bytes=MEMORY_CEILING_BYTES,
        timeout_seconds=900,
    )
    parent_rss_after = resident_bytes(os.getpid())
    parent_peak = max(parent_rss_before, parent_rss_after)
    return {
        **outcome.value,
        "watchdog_duration_seconds": round(perf_counter() - started, 6),
        "worker_peak_rss_bytes": outcome.peak_rss_bytes,
        "parent_observed_rss_bytes": parent_peak,
        "process_tree_conservative_bound_bytes": parent_peak + outcome.peak_rss_bytes,
    }


def lookup_benchmark() -> dict:
    """Measure the cached O(log n) lookup at production call cardinality."""

    starts = tuple(
        datetime(2010, 1, 1, tzinfo=UTC) + timedelta(hours=index) for index in range(57_500)
    )
    completions = tuple(value + timedelta(hours=1) for value in starts)
    queries = tuple(
        completions[(index * 7919) % (len(completions) - 1) + 1]
        for index in range(MEASURED_PRIOR_LOOKUP_CALLS)
    )
    started = perf_counter()
    selected = [starts[bisect_left(completions, when) - 1] for when in queries]
    elapsed = perf_counter() - started
    assert len(selected) == MEASURED_PRIOR_LOOKUP_CALLS
    return {
        "cached_lookup_seconds": round(elapsed, 6),
        "calls": MEASURED_PRIOR_LOOKUP_CALLS,
        "legacy_elements_scanned_measured": MEASURED_LEGACY_ELEMENTS_SCANNED,
        "synthetic_inventory_members": len(starts),
    }


def main() -> None:
    first = _run_worker()
    second = _run_worker()
    assert first["evidence_sha256"] == second["evidence_sha256"]
    report = {
        "authority": {
            "database_access": False,
            "provider_access": False,
            "real_outcome_access": False,
            "return_execution_authorization": False,
            "synthetic_only": True,
        },
        "environment": {
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "invocation": (
            ".venv/bin/python "
            "research/benchmarks/benchmark_exploratory_return_lineage_performance_v2.py"
        ),
        "measured_production_cardinality": {
            "inventory_members": MEASURED_INVENTORY_MEMBERS,
            "needed_candles": MEASURED_NEEDED_CANDLES,
            "physical_events": EVENT_COUNT,
            "prior_lookup_calls": MEASURED_PRIOR_LOOKUP_CALLS,
        },
        "lookup": lookup_benchmark(),
        "repeat": second,
        "run": first,
        "scope": (
            "PRODUCTION_SHAPED_SYNTHETIC_82_EVENT_19762_H1_ROW_FULL_RUNNER_"
            "CALCULATOR_BOOTSTRAP_ATOMIC_STORE"
        ),
        "exclusions": [
            "REAL_CANDLE_PRICES",
            "POSTGRESQL_CANDLE_LOADING",
            "POSTGRESQL_JSONB_WRITE_AND_COMMIT",
            "PROVIDER_NETWORK",
        ],
    }
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
