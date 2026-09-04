"""Deterministic synthetic benchmark for the pure v2 return engine.

Invocation:
    .venv/bin/python research/benchmarks/benchmark_exploratory_returns_v2.py

The workload contains no database or real market data and deliberately excludes
the 10,000-replicate bootstrap so that event-resolution scaling is measured
separately.
"""

from __future__ import annotations

import json
import platform
import sys
import tracemalloc
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.exploratory_returns_v2 import cost_grid, digest, resolve_event  # noqa: E402


def synthetic_event(index: int) -> dict:
    start = datetime(2014, 1, 6, 14, tzinfo=UTC) + timedelta(days=index)
    end = start + timedelta(hours=1)
    start_text, end_text = start.isoformat(), end.isoformat()
    d_completions = [(start + timedelta(days=day)).isoformat() for day in range(1, 11)]
    horizon = d_completions[-1]
    conversion = {
        "currency": "USD",
        "as_of": end_text,
        "legs": [
            {
                "complete": True,
                "completed_at": (start - timedelta(hours=1)).isoformat(),
                "conflict": False,
                "direction": "multiply",
                "midpoint_close": "1.25",
                "pair": "USD_CAD",
                "sealed": True,
            }
        ],
    }
    bar = {
        "ask_close": "1.0222",
        "ask_high": "1.0225",
        "ask_low": "1.0195",
        "ask_open": "1.0202",
        "bid_close": "1.0220",
        "bid_high": "1.0221",
        "bid_low": "1.0193",
        "bid_open": "1.0200",
        "complete": True,
        "conflict": False,
        "sealed": True,
        "start": start_text,
    }
    return {
        "books": ["failed-break-any-level-deduplicated-v1"],
        "conversion": {end_text: conversion},
        "daily": [
            {
                "complete": True,
                "completed_at": completed,
                "conflict": False,
                "mid_close": "1.0200",
                "sealed": True,
            }
            for completed in d_completions
        ],
        "direction": "long",
        "entry_ask": "1.0202",
        "entry_at": start_text,
        "entry_bid": "1.0200",
        "d_completions": d_completions,
        "expected_h1_starts": [start_text, horizon],
        "h1": [
            bar,
            {**bar, "start": horizon},
        ],
        "horizon_at": horizon,
        "instrument": "EUR_USD",
        "marks": [],
        "physical_event_key": f"synthetic-{index:06d}",
        "pip_size": "0.0001",
        "risk_per_unit_cad": "0.00125",
        "rollovers": [],
        "stop": "1.0192",
        "supporting_swing": "1.0100",
        "target": "1.0220",
    }


def run(size: int = 20_000) -> dict:
    events = [synthetic_event(index) for index in range(size)]
    outputs = []
    tracemalloc.start()
    started = perf_counter()
    for event in events:
        result = resolve_event(event)
        outputs.append((result, cost_grid(event, result, 25)))
    duration = perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "duration_seconds": round(duration, 6),
        "events": size,
        "h1_rows": size * 2,
        "output_sha256": digest(outputs),
        "peak_bytes": peak,
    }


def main() -> None:
    scaling = [run(size) for size in (5_000, 10_000, 20_000)]
    repeated = run(20_000)
    assert scaling[-1]["output_sha256"] == repeated["output_sha256"]
    report = {
        "coverage": "PURE_EVENT_RESOLUTION_AND_15_COST_CELLS; EXCLUDES_BOOTSTRAP_AND_PERSISTENCE",
        "environment": {
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "invocation": ".venv/bin/python research/benchmarks/benchmark_exploratory_returns_v2.py",
        "repeated_20000": repeated,
        "scaling": scaling,
    }
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
