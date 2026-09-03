"""Reproducible compute and disposable-persistence benchmarks for detector v2.

This is not an S1 runner.  Persistence mode refuses every database whose name
does not begin with ``detector_v2_benchmark_`` and writes only to an isolated
benchmark schema that it removes before returning.
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
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_EVENT_COUNT = 63_500
DEFAULT_DATASET_ID = 3
DEFAULT_INSTRUMENT = "AUD_USD"
DEFAULT_YEAR = 2018
MAX_STAGE_SECONDS = 120
MAX_TOTAL_SECONDS = 900
DISPOSABLE_DATABASE_PREFIX = "detector_v2_benchmark_"
BENCHMARK_SCHEMA = "detector_v2_benchmark"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _repository_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _environment() -> dict[str, str]:
    import django

    return {
        "django": django.get_version(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "repository_commit": _repository_commit(),
    }


class RuntimeBudget:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    def stage(self, name: str, started: float) -> float:
        duration = time.perf_counter() - started
        if duration > MAX_STAGE_SECONDS:
            raise RuntimeError(f"{name} exceeded {MAX_STAGE_SECONDS} seconds")
        if time.perf_counter() - self.started > MAX_TOTAL_SECONDS:
            raise RuntimeError(f"benchmark exceeded {MAX_TOTAL_SECONDS} seconds")
        print(f"{name}: {duration:.6f}s", flush=True)
        return duration


def _synthetic_inventory(event_count: int) -> dict[str, tuple[datetime, ...]]:
    if event_count != DEFAULT_EVENT_COUNT:
        raise ValueError(f"the governed synthetic workload is exactly {DEFAULT_EVENT_COUNT} events")
    start = datetime(2010, 1, 1, tzinfo=UTC)
    return {
        "H1": tuple(start + timedelta(hours=index) for index in range(60_000)),
        "D": tuple(start + timedelta(days=index) for index in range(3_000)),
        "W": tuple(start + timedelta(days=7 * index) for index in range(500)),
    }


def compute_benchmark(event_count: int) -> dict[str, object]:
    from research.failed_break_detector_v2 import (
        SealedHorizonIndex,
        assert_complete_projection,
        completion_stream,
        project_admission,
    )

    budget = RuntimeBudget()
    started = time.perf_counter()
    inventory = _synthetic_inventory(event_count)
    inventory_digest = _sha256(
        {key: [timestamp.isoformat() for timestamp in value] for key, value in inventory.items()}
    )
    load_seconds = budget.stage("synthetic_inventory_loading", started)

    duration = {"H1": timedelta(hours=1), "D": timedelta(days=1), "W": timedelta(days=7)}
    started = time.perf_counter()
    events = completion_stream(
        inventory,
        lambda granularity, opened_at: opened_at + duration[granularity],
    )
    projection = project_admission(events)
    assert_complete_projection(projection, inventory)
    horizon = SealedHorizonIndex.from_projection(projection)
    horizon.maximum_exit_open(inventory["H1"][0])
    compute_seconds = budget.stage("detector_admission_computation", started)

    return {
        "environment": _environment(),
        "invocation_workload": {
            "event_count": event_count,
            "granularity_counts": {key: len(value) for key, value in inventory.items()},
            "inventory_sha256": inventory_digest,
            "workload": "deterministic synthetic sealed completion inventory",
        },
        "scope": {
            "includes": [
                "sealed inventory construction and canonical hashing",
                "ordered completion-stream merge",
                "admission projection and exact membership assertion",
                "sealed ten-D-session horizon index construction",
            ],
            "excludes": [
                "persistent S1 evidence writes",
                "database registration validation",
                "ORM inventory preload",
                "return or outcome calculation",
            ],
        },
        "timings_seconds": {
            "inventory_loading": load_seconds,
            "detector_computation": compute_seconds,
            "total": time.perf_counter() - budget.started,
        },
        "projection": projection.counters,
    }


def _strategy_candle(market_candle, completed_at):
    from research.strategy import Candle

    return Candle(
        opened_at=market_candle.timestamp,
        completed_at=completed_at,
        bid_open=market_candle.bid_open,
        bid_high=market_candle.bid_high,
        bid_low=market_candle.bid_low,
        bid_close=market_candle.bid_close,
        ask_open=market_candle.ask_open,
        ask_high=market_candle.ask_high,
        ask_low=market_candle.ask_low,
        ask_close=market_candle.ask_close,
    )


def _source_workload_counts(dataset_id: int, strategy_id: int, instrument_id: int, year: int):
    from research.models import (
        AnalysisRun,
        EntryEligibilityEvaluation,
        Level,
        LevelLifecycleEvent,
        SetupEvent,
        SetupLevelAttribution,
        SetupTransition,
    )

    start = datetime(year, 1, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC)
    setup_scope = SetupEvent.objects.filter(
        dataset_version_id=dataset_id,
        strategy_version_id=strategy_id,
        instrument_id=instrument_id,
        sweep_h1_timestamp__gte=start,
        sweep_h1_timestamp__lt=end,
    )
    return {
        "analysis_runs": AnalysisRun.objects.filter(
            dataset_version_id=dataset_id,
            strategy_version_id=strategy_id,
            instrument_id=instrument_id,
            completed_h1_timestamp__gte=start,
            completed_h1_timestamp__lt=end,
        ).count(),
        "levels": Level.objects.filter(
            dataset_version_id=dataset_id,
            strategy_version_id=strategy_id,
            instrument_id=instrument_id,
            activated_at__gte=start,
            activated_at__lt=end,
        ).count(),
        "lifecycle_events": LevelLifecycleEvent.objects.filter(
            level__dataset_version_id=dataset_id,
            level__strategy_version_id=strategy_id,
            level__instrument_id=instrument_id,
            effective_at__gte=start,
            effective_at__lt=end,
        ).count(),
        "setups": setup_scope.count(),
        "attributions": SetupLevelAttribution.objects.filter(setup__in=setup_scope).count(),
        "transitions": SetupTransition.objects.filter(setup__in=setup_scope).count(),
        "entry_eligibility": EntryEligibilityEvaluation.objects.filter(
            setup__in=setup_scope
        ).count(),
    }


def _create_benchmark_schema(cursor) -> None:
    cursor.execute(f'DROP SCHEMA IF EXISTS "{BENCHMARK_SCHEMA}" CASCADE')
    cursor.execute(f'CREATE SCHEMA "{BENCHMARK_SCHEMA}"')
    cursor.execute(
        f"""
        CREATE FUNCTION "{BENCHMARK_SCHEMA}".validate_evidence_hash()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF length(NEW.evidence_hash) <> 64 THEN
                RAISE EXCEPTION 'invalid evidence hash';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    for table in ("analysis", "level", "setup"):
        cursor.execute(
            f"""
            CREATE TABLE "{BENCHMARK_SCHEMA}"."{table}" (
                id bigint PRIMARY KEY,
                occurred_at timestamptz NOT NULL,
                evidence_hash char(64) NOT NULL UNIQUE,
                payload jsonb NOT NULL,
                CHECK (length(evidence_hash) = 64)
            )
            """
        )
    for table, parent in (
        ("lifecycle", "level"),
        ("attribution", "setup"),
        ("transition", "setup"),
        ("entry_eligibility", "setup"),
    ):
        cursor.execute(
            f"""
            CREATE TABLE "{BENCHMARK_SCHEMA}"."{table}" (
                id bigint PRIMARY KEY,
                parent_id bigint NOT NULL REFERENCES "{BENCHMARK_SCHEMA}"."{parent}"(id),
                occurred_at timestamptz NOT NULL,
                evidence_hash char(64) NOT NULL UNIQUE,
                payload jsonb NOT NULL,
                CHECK (length(evidence_hash) = 64)
            )
            """
        )
    for table in (
        "analysis",
        "level",
        "lifecycle",
        "setup",
        "attribution",
        "transition",
        "entry_eligibility",
    ):
        cursor.execute(
            f"""
            CREATE TRIGGER validate_{table}_evidence
            BEFORE INSERT ON "{BENCHMARK_SCHEMA}"."{table}"
            FOR EACH ROW EXECUTE FUNCTION "{BENCHMARK_SCHEMA}".validate_evidence_hash()
            """
        )


def _insert_roots(cursor, table: str, count: int, occurred_at: datetime) -> None:
    cursor.execute(
        f"""
        INSERT INTO "{BENCHMARK_SCHEMA}"."{table}" (id, occurred_at, evidence_hash, payload)
        SELECT value, %s, encode(digest('{table}:' || value::text, 'sha256'), 'hex'),
               jsonb_build_object('ordinal', value)
        FROM generate_series(1, %s) AS value
        """,
        [occurred_at, count],
    )


def _insert_children(
    cursor, table: str, parent_count: int, count: int, occurred_at: datetime
) -> None:
    if count and not parent_count:
        raise RuntimeError(f"cannot benchmark {table} without parent rows")
    cursor.execute(
        f"""
        INSERT INTO "{BENCHMARK_SCHEMA}"."{table}"
            (id, parent_id, occurred_at, evidence_hash, payload)
        SELECT value, 1 + ((value - 1) %% %s), %s,
               encode(digest('{table}:' || value::text, 'sha256'), 'hex'),
               jsonb_build_object('ordinal', value)
        FROM generate_series(1, %s) AS value
        """,
        [max(parent_count, 1), occurred_at, count],
    )


def persistence_benchmark(dataset_id: int, instrument_code: str, year: int) -> dict[str, object]:
    from django.db import connection

    from market.models import DatasetVersion, HistoricalDataContract, Instrument
    from research.failed_break_detector_v2 import (
        SUCCESSOR_CONTRACT_SHA256,
        IncrementalAtr,
        IncrementalDailyState,
        assert_complete_projection,
        load_instrument_snapshot,
        project_admission,
        provider_observed_completion_stream,
    )
    from research.signal_count import _validate_dataset_contract

    database_name = connection.settings_dict["NAME"]
    if not isinstance(database_name, str) or not database_name.startswith(
        DISPOSABLE_DATABASE_PREFIX
    ):
        raise RuntimeError("persistence benchmark requires a disposable benchmark database name")
    budget = RuntimeBudget()
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = '120s'")
        cursor.execute("SET lock_timeout = '5s'")
        cursor.execute("SHOW server_version")
        postgres_version = cursor.fetchone()[0]

    dataset = DatasetVersion.objects.get(pk=dataset_id)
    contract = HistoricalDataContract.objects.get(sha256=SUCCESSOR_CONTRACT_SHA256)
    instrument = Instrument.objects.get(code=instrument_code)
    strategy_id = contract.strategy_version_id
    strategy = contract.strategy_version

    started = time.perf_counter()
    _validate_dataset_contract(
        dataset,
        strategy,
        datetime(2019, 1, 1, 4, tzinfo=UTC),
    )
    registration_seconds = budget.stage("registered_dataset_validation", started)
    registration = dataset.registration
    registration_identity = {
        "contract_sha256": contract.sha256,
        "dataset": f"{dataset.name}:{dataset.version}",
        "global_semantic_inventory_sha256": contract.global_semantic_inventory_sha256,
        "manifest_sha256": dataset.manifest_sha256,
        "registration_configuration_sha256": registration.configuration_sha256,
        "registration_report_sha256": registration.report_sha256,
    }

    start = datetime(year, 1, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC) - timedelta(microseconds=1)
    ranges = {granularity: (start, end) for granularity in ("H1", "D", "W")}
    started = time.perf_counter()
    snapshot = load_instrument_snapshot(
        dataset=dataset,
        contract=contract,
        instrument=instrument,
        ranges=ranges,
    )
    preload_seconds = budget.stage("h1_d_w_preload", started)

    started = time.perf_counter()
    events = provider_observed_completion_stream(snapshot.inventory, contract)
    projection = project_admission(events)
    assert_complete_projection(projection, snapshot.inventory)
    daily_state = IncrementalDailyState()
    hourly_atr = IncrementalAtr()
    for event in events:
        if event.granularity not in {"H1", "D"}:
            continue
        candle = _strategy_candle(
            snapshot.candles[(event.granularity, event.opened_at)], event.completed_at
        )
        if event.granularity == "D":
            daily_state.update(candle)
        else:
            hourly_atr.update(high=candle.high, low=candle.low, close=candle.close)
    detector_seconds = budget.stage("detector_computation", started)

    started = time.perf_counter()
    row_counts = _source_workload_counts(dataset_id, strategy_id, instrument.id, year)
    source_count_seconds = budget.stage("return_blind_source_row_counts", started)
    if row_counts["analysis_runs"] != len(snapshot.inventory["H1"]):
        raise RuntimeError("source AnalysisRun count does not match sealed H1 inventory")

    timings: dict[str, float] = {
        "registered_dataset_validation": registration_seconds,
        "h1_d_w_preload": preload_seconds,
        "detector_computation": detector_seconds,
        "source_row_count_queries": source_count_seconds,
    }
    connection.close_if_unusable_or_obsolete()
    connection.set_autocommit(False)
    try:
        with connection.cursor() as cursor:
            started = time.perf_counter()
            _create_benchmark_schema(cursor)
            timings["isolated_schema_setup"] = budget.stage("isolated_schema_setup", started)

            started = time.perf_counter()
            _insert_roots(cursor, "analysis", row_counts["analysis_runs"], start)
            timings["analysis_run_persistence"] = budget.stage("analysis_run_persistence", started)

            started = time.perf_counter()
            _insert_roots(cursor, "level", row_counts["levels"], start)
            _insert_children(
                cursor,
                "lifecycle",
                row_counts["levels"],
                row_counts["lifecycle_events"],
                start,
            )
            timings["levels_lifecycle_persistence"] = budget.stage(
                "levels_lifecycle_persistence", started
            )

            started = time.perf_counter()
            _insert_roots(cursor, "setup", row_counts["setups"], start)
            _insert_children(
                cursor,
                "transition",
                row_counts["setups"],
                row_counts["transitions"],
                start,
            )
            _insert_children(
                cursor,
                "attribution",
                row_counts["setups"],
                row_counts["attributions"],
                start,
            )
            timings["setups_transitions_attribution_persistence"] = budget.stage(
                "setups_transitions_attribution_persistence", started
            )

            started = time.perf_counter()
            _insert_children(
                cursor,
                "entry_eligibility",
                row_counts["setups"],
                row_counts["entry_eligibility"],
                start,
            )
            timings["entry_eligibility_persistence"] = budget.stage(
                "entry_eligibility_persistence", started
            )

            started = time.perf_counter()
            cursor.execute(
                f"""
                SELECT count(*)
                FROM "{BENCHMARK_SCHEMA}".analysis
                WHERE length(evidence_hash) = 64 AND payload ? 'ordinal'
                """
            )
            constraint_rows = cursor.fetchone()[0]
            if constraint_rows != row_counts["analysis_runs"]:
                raise RuntimeError("constraint/trigger verification count changed")
            timings["constraint_trigger_verification"] = budget.stage(
                "constraint_trigger_verification", started
            )

            started = time.perf_counter()
            report_payload = {
                "dataset_id": dataset_id,
                "instrument": instrument_code,
                "inventory_membership_sha256": projection.membership_sha256,
                "row_counts": row_counts,
                "year": year,
            }
            report_sha256 = _sha256(report_payload)
            timings["canonical_report_hash_generation"] = budget.stage(
                "canonical_report_hash_generation", started
            )

        started = time.perf_counter()
        connection.commit()
        timings["transaction_commit"] = budget.stage("transaction_commit", started)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.set_autocommit(True)

    with connection.cursor() as cursor:
        cursor.execute(f'DROP SCHEMA "{BENCHMARK_SCHEMA}" CASCADE')
    timings["total"] = time.perf_counter() - budget.started
    return {
        "database_guard": {
            "database_name": database_name,
            "required_prefix": DISPOSABLE_DATABASE_PREFIX,
            "schema_removed_after_measurement": True,
        },
        "environment": {**_environment(), "postgresql": postgres_version},
        "identity": registration_identity,
        "scope": {
            "includes": [
                "real successor registration validation",
                "real sealed H1/D/W ORM preload",
                "v2 admission projection and incremental H1 ATR/D EMA-ATR-pivot computation",
                "return-blind v1 S1 row counts for persistence workload sizing",
                "isolated-schema inserts with primary, unique, foreign-key, check and row-trigger work",
                "transaction commit and canonical report hashing",
            ],
            "excludes": [
                "persistent research-table writes",
                "a production v2 S1 runner",
                "full v2 level/setup/eligibility materialization",
                "post-entry outcome, return, P&L or backtest work",
            ],
        },
        "workload": {
            "dataset_id": dataset_id,
            "instrument": instrument_code,
            "inventory_counts": {key: len(value) for key, value in snapshot.inventory.items()},
            "representative_persistence_rows": row_counts,
            "year": year,
        },
        "report_sha256": report_sha256,
        "timings_seconds": timings,
    }


def _write_result(result: dict[str, object], output: Path | None) -> None:
    encoded = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if output is None:
        print(encoded, end="")
    else:
        output.write_text(encoded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    compute = subparsers.add_parser("compute")
    compute.add_argument("--events", type=int, default=DEFAULT_EVENT_COUNT)
    persistence = subparsers.add_parser("persistence")
    persistence.add_argument("--dataset-id", type=int, default=DEFAULT_DATASET_ID)
    persistence.add_argument("--instrument", default=DEFAULT_INSTRUMENT)
    persistence.add_argument("--year", type=int, default=DEFAULT_YEAR)
    args = parser.parse_args(argv)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    if args.mode == "compute":
        result = compute_benchmark(args.events)
    else:
        result = persistence_benchmark(args.dataset_id, args.instrument, args.year)
    _write_result(result, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
