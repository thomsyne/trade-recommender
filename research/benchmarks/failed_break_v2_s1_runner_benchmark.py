"""Bounded real-model benchmark for the code-only v2 S1 runner.

This harness refuses ordinary database names.  It reads an accepted restored
dataset, writes only v2 evidence to that disposable restore, and never imports
an outcome or return model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from django.db import connection

PRIMARY_INSTRUMENT = "AUD_USD"
CONVERSION_INSTRUMENT = "USD_CAD"
DISPOSABLE_DATABASE_PREFIX = "failed_break_v2_s1_benchmark_"
WARMUP_START = datetime(2017, 1, 1, tzinfo=UTC)
MEASUREMENT_START = datetime(2018, 1, 1, tzinfo=UTC)
MEASUREMENT_END = datetime(2019, 1, 1, tzinfo=UTC)
MAX_SECONDS = 15 * 60


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _environment() -> dict:
    import django

    return {
        "django": django.get_version(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "repository_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip(),
    }


def _v1_counts() -> dict[str, int]:
    from research.models import (
        AnalysisRun,
        EntryEligibilityEvaluation,
        JobRun,
        Level,
        LevelLifecycleEvent,
        SetupEvent,
        SetupLevelAttribution,
        SetupTransition,
    )

    return {
        "analysis_runs": AnalysisRun.objects.filter(strategy_version_id=1).count(),
        "entry_eligibility": EntryEligibilityEvaluation.objects.filter(
            setup__strategy_version_id=1
        ).count(),
        "job_runs": JobRun.objects.filter(strategy_version_id=1).count(),
        "levels": Level.objects.filter(strategy_version_id=1).count(),
        "lifecycle_events": LevelLifecycleEvent.objects.filter(
            level__strategy_version_id=1
        ).count(),
        "setups": SetupEvent.objects.filter(strategy_version_id=1).count(),
        "attributions": SetupLevelAttribution.objects.filter(setup__strategy_version_id=1).count(),
        "transitions": SetupTransition.objects.filter(strategy_version_id=1).count(),
    }


def run(batch_size: int) -> dict:
    from market.models import IngestionManifest, Instrument
    from research.failed_break_detector_v2 import (
        load_instrument_snapshot,
        reference_completion_stream,
        validate_registered_successor,
    )
    from research.failed_break_v2_s0 import V2_S0_AS_OF, validate_v2_s0_prerequisites
    from research.failed_break_v2_s0_governance import (
        select_persistent_v2_s0_evidence,
        verify_v2_s0_acceptance,
    )
    from research.failed_break_v2_s1 import (
        V2S1Projection,
        V2S1Refusal,
        _project_instrument,
        persist_projection,
    )
    from research.failed_break_v2_s1_governance import load_v2_s1_policy
    from research.models import AnalysisRun, JobRun, Level, SetupEvent

    database_name = str(connection.settings_dict["NAME"])
    if not database_name.startswith(DISPOSABLE_DATABASE_PREFIX):
        raise V2S1Refusal("benchmark requires an explicitly named disposable database")
    started_total = time.perf_counter()
    timings = {}

    started = time.perf_counter()
    s0_job, dataset, strategy = select_persistent_v2_s0_evidence()
    acceptance = verify_v2_s0_acceptance(job=s0_job, dataset=dataset, strategy=strategy)
    timings["s0_acceptance_verification"] = time.perf_counter() - started

    started = time.perf_counter()
    ranges, contract, _ = validate_v2_s0_prerequisites(
        dataset=dataset, strategy=strategy, as_of=V2_S0_AS_OF
    )
    registration = validate_registered_successor(dataset, contract)
    timings["registration_and_lineage_validation"] = time.perf_counter() - started

    instruments = {
        row.code: row
        for row in Instrument.objects.filter(code__in={PRIMARY_INSTRUMENT, CONVERSION_INSTRUMENT})
    }
    ranges = {
        "H1": (WARMUP_START, MEASUREMENT_END),
        "D": (WARMUP_START, MEASUREMENT_END),
        "W": (WARMUP_START, MEASUREMENT_END),
    }
    started = time.perf_counter()
    snapshots = {
        code: load_instrument_snapshot(
            dataset=dataset, contract=contract, instrument=instrument, ranges=ranges
        )
        for code, instrument in sorted(instruments.items())
    }
    manifests = dict(
        IngestionManifest.objects.filter(dataset_version=dataset).values_list(
            "ingestion_run_id", "sha256"
        )
    )
    timings["h1_d_w_and_conversion_preload"] = time.perf_counter() - started

    started = time.perf_counter()
    levels, setups, analyses, admission, _ = _project_instrument(
        snapshot=snapshots[PRIMARY_INSTRUMENT],
        snapshots=snapshots,
        manifests=manifests,
        contract=contract,
        instrument=instruments[PRIMARY_INSTRUMENT],
        strategy=strategy,
        dataset=dataset,
        spread_ceiling=__import__("decimal").Decimal(
            s0_job.evidence["report"]["numerical_evidence"]["spread_ceilings"][PRIMARY_INSTRUMENT]
        ),
        stream_builder=__import__(
            "research.failed_break_detector_v2", fromlist=["completion_stream"]
        ).completion_stream,
        progress=None,
    )
    timings["detector_computation"] = time.perf_counter() - started

    started = time.perf_counter()
    year_setups = tuple(
        setup for setup in setups if MEASUREMENT_START <= setup.event.at < MEASUREMENT_END
    )
    year_analyses = tuple(
        row for row in analyses if MEASUREMENT_START <= row.completed_at < MEASUREMENT_END
    )
    row_counts = {
        "analysis_runs": len(year_analyses),
        "levels": len(levels),
        "lifecycle_events": sum(len(row.lifecycle) for row in levels),
        "setups": len(year_setups),
        "attributions": sum(len(row.attribution_keys) for row in year_setups),
        "transitions": sum(
            (1 if row.confirmation else 0) + len(row.evaluations) for row in year_setups
        ),
        "entry_eligibility": sum(len(row.evaluations) for row in year_setups),
        "job_runs": 1,
    }
    canonical = {
        "analysis": [row.evidence_hash for row in year_analyses],
        "levels": [row.stable_key for row in levels],
        "setups": [row.logical_key for row in year_setups],
        "evaluations": [
            evaluation.evidence_hash for setup in year_setups for evaluation in setup.evaluations
        ],
    }
    timings["canonical_evidence_construction"] = time.perf_counter() - started
    started_reference = time.perf_counter()
    reference_levels, reference_setups, reference_analyses, _, _ = _project_instrument(
        snapshot=snapshots[PRIMARY_INSTRUMENT],
        snapshots=snapshots,
        manifests=manifests,
        contract=contract,
        instrument=instruments[PRIMARY_INSTRUMENT],
        strategy=strategy,
        dataset=dataset,
        spread_ceiling=__import__("decimal").Decimal(
            s0_job.evidence["report"]["numerical_evidence"]["spread_ceilings"][PRIMARY_INSTRUMENT]
        ),
        stream_builder=reference_completion_stream,
        progress=None,
    )
    reference_year_setups = tuple(
        setup for setup in reference_setups if MEASUREMENT_START <= setup.event.at < MEASUREMENT_END
    )
    reference_canonical = {
        "analysis": [
            row.evidence_hash
            for row in reference_analyses
            if MEASUREMENT_START <= row.completed_at < MEASUREMENT_END
        ],
        "levels": [row.stable_key for row in reference_levels],
        "setups": [row.logical_key for row in reference_year_setups],
        "evaluations": [
            evaluation.evidence_hash
            for setup in reference_year_setups
            for evaluation in setup.evaluations
        ],
    }
    timings["reference_equivalence_verification"] = time.perf_counter() - started_reference
    if canonical != reference_canonical:
        raise RuntimeError("optimized projection differs from the golden reference projection")
    report_body = {
        "identity": "failed-break-v2-s1-disposable-one-instrument-year-v1",
        "instrument": PRIMARY_INSTRUMENT,
        "year": 2018,
        "row_counts": row_counts,
        "canonical_evidence_sha256": _hash(canonical),
        "inventory_sha256": admission.membership_sha256,
        "post_entry_outcomes_read": False,
        "returns_read": False,
    }
    projection = V2S1Projection(
        tuple(levels),
        year_setups,
        year_analyses,
        {
            PRIMARY_INSTRUMENT: {
                key: len(value) for key, value in admission.admitted_members.items()
            }
        },
        {PRIMARY_INSTRUMENT: admission.membership_sha256},
        {**report_body, "report_sha256": _hash(report_body)},
    )
    policy = load_v2_s1_policy()
    v1_before = _v1_counts()
    v2_before = {
        "jobs": JobRun.objects.filter(strategy_version=strategy, job_name__contains="s1").count(),
        "analyses": AnalysisRun.objects.filter(strategy_version=strategy).count(),
        "levels": Level.objects.filter(strategy_version=strategy).count(),
        "setups": SetupEvent.objects.filter(strategy_version=strategy).count(),
    }
    try:
        persist_projection(
            projection=projection,
            dataset=dataset,
            strategy=strategy,
            s0_job=s0_job,
            governance=policy,
            batch_size=batch_size,
            require_disposable=True,
            inject_failure_after="entry_evaluations",
        )
    except V2S1Refusal as error:
        rollback_refusal = str(error)
    else:
        raise RuntimeError("injected failure did not roll back")
    v2_after_rollback = {
        "jobs": JobRun.objects.filter(strategy_version=strategy, job_name__contains="s1").count(),
        "analyses": AnalysisRun.objects.filter(strategy_version=strategy).count(),
        "levels": Level.objects.filter(strategy_version=strategy).count(),
        "setups": SetupEvent.objects.filter(strategy_version=strategy).count(),
    }
    if v2_after_rollback != v2_before:
        raise RuntimeError("injected failure left partial v2 evidence")

    write_timings = {}

    def observe(name, seconds, rows):
        write_timings[name] = {"rows": rows, "seconds": seconds}

    started = time.perf_counter()
    job = persist_projection(
        projection=projection,
        dataset=dataset,
        strategy=strategy,
        s0_job=s0_job,
        governance=policy,
        batch_size=batch_size,
        require_disposable=True,
        stage_observer=observe,
    )
    timings["actual_model_persistence_and_commit"] = time.perf_counter() - started
    try:
        persist_projection(
            projection=projection,
            dataset=dataset,
            strategy=strategy,
            s0_job=s0_job,
            governance=policy,
            batch_size=batch_size,
            require_disposable=True,
        )
    except V2S1Refusal as error:
        duplicate_refusal = str(error)
    else:
        raise RuntimeError("duplicate v2 S1 benchmark execution was accepted")
    if _v1_counts() != v1_before:
        raise RuntimeError("v1 S1 evidence changed during v2 benchmark")
    total = time.perf_counter() - started_total
    if total > MAX_SECONDS:
        raise RuntimeError("bounded v2 S1 benchmark exceeded 15 minutes")
    write_stage_sum = sum(
        value["seconds"]
        for key, value in write_timings.items()
        if key != "atomic_transaction_total"
    )
    write_timings["transaction_commit_estimate"] = {
        "rows": 0,
        "seconds": max(
            0,
            write_timings["atomic_transaction_total"]["seconds"] - write_stage_sum,
        ),
    }
    return {
        "authorization": {
            "persistent_v2_s1_execution": False,
            "benchmark_disposable_write_only": True,
            "returns_or_backtesting": False,
        },
        "batch_size": batch_size,
        "database": {
            "name": database_name,
            "required_prefix": DISPOSABLE_DATABASE_PREFIX,
        },
        "environment": _environment(),
        "identity": {
            "acceptance_sha256": acceptance["acceptance_sha256"],
            "dataset": registration,
            "job_config_hash": job.config_hash,
            "job_report_hash": job.evidence["report"]["report_sha256"],
            "projection_sha256": _hash(projection.canonical_evidence()),
        },
        "inventory_counts": {
            code: {key: len(value) for key, value in snapshot.inventory.items()}
            for code, snapshot in snapshots.items()
        },
        "row_counts": row_counts,
        "safety": {
            "duplicate_refusal": duplicate_refusal,
            "injected_rollback_refusal": rollback_refusal,
            "rollback_exact": v2_after_rollback == v2_before,
            "reference_equivalence": canonical == reference_canonical,
            "v1_counts_before": v1_before,
            "v1_counts_after": _v1_counts(),
            "v1_unchanged": _v1_counts() == v1_before,
        },
        "scope": {
            "measurement_year": 2018,
            "warmup_start": WARMUP_START.isoformat(),
            "post_entry_outcomes_read": False,
            "returns_read": False,
            "persistent_evidence_writes_covered": True,
        },
        "timings_seconds": {**timings, "total": total},
        "write_stages": write_timings,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    result = run(args.batch_size)
    encoded = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
