"""Governed orchestration for one future v2 exploratory-return execution.

The committed state is intentionally not executable: a separate fixed-path
authorization artifact must be added and verified before the Django adapter is
constructed or any outcome-bearing query can run.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Protocol

from research import exploratory_returns_v2 as calculator

JOB_IDENTITY = "failed-break-exploratory-returns-v2"
IDEMPOTENCY_KEY = "failed-break-exploratory-returns-v2|phase-2b1r-v2|development-2010-2018"
EXPECTED_EVENTS = 82
BOUNDARY_PURGED_EVENT_KEY = "cbecf84cceff3e391963280179633853ea8f74b2dafe3ba93910f71aac002e77"


class RunnerRefusal(ValueError):
    """The governed runner cannot proceed safely."""


def require(condition, message):
    if not condition:
        raise RunnerRefusal(message)


class EvidenceAdapter(Protocol):
    query_counts: dict[str, int]

    def verify_return_blind_lineage(self) -> dict: ...

    def load_normalized_events(self, expected_keys: tuple[str, ...]) -> list[dict]: ...


class ResultStore(Protocol):
    query_counts: dict[str, int]

    def ensure_absent(self, idempotency_key: str) -> None: ...

    @contextmanager
    def atomic(self): ...

    def persist(self, payload: dict, *, inject_failure_after: str | None = None) -> None: ...


def _validate_authorization(authorization: dict) -> None:
    require(
        authorization.get("authority")
        == {
            "exploratory_return_execution": True,
            "retry": False,
            "resume": False,
            "promotion": False,
            "live_trading": False,
        },
        "execution authorization does not grant exactly one exploratory run",
    )
    require(authorization.get("job_identity") == JOB_IDENTITY, "job identity substitution")
    require(authorization.get("physical_event_count") == EXPECTED_EVENTS, "event count changed")


def _validate_lineage(lineage: dict) -> None:
    require(lineage.get("dataset_version") == "phase-2b1r-v2", "dataset substitution")
    require(
        lineage.get("strategy_version") == "failed-break-phase-1-admission-correction-v2",
        "strategy substitution",
    )
    require(lineage.get("s1_outcome") == "ACCEPTED", "v2 S1 outcome is not accepted")
    require(lineage.get("s2_policy") == "EFFECTIVE_EXPLORATORY_ONLY", "S2 policy unavailable")
    require(lineage.get("promotion_permanently_prohibited") is True, "promotion boundary changed")


def build_persistent_payload(
    *,
    authorization: dict,
    lineage: dict,
    events: list[dict],
    report: dict,
) -> dict:
    """Build the sole immutable JobRun evidence payload."""
    keys = tuple(sorted(row["physical_event_key"] for row in events))
    require(len(keys) == EXPECTED_EVENTS and len(set(keys)) == EXPECTED_EVENTS, "event set changed")
    require(report["event_count"] == EXPECTED_EVENTS, "calculator event count changed")
    require(
        len(report["event_results"]) == EXPECTED_EVENTS
        and all(row["terminal"] != "UNRESOLVED_DATA" for row in report["event_results"]),
        "complete resolved terminal set required",
    )
    require(
        report["authorization"]
        == {"exploratory_only": True, "persistent_execution": False, "promotion": False},
        "calculator authority drift",
    )
    require(
        set(report["cost_scenarios"]) == {"25", "50", "100"}
        and all(
            len(events_by_key) == EXPECTED_EVENTS
            and all(len(cells) == 15 for cells in events_by_key.values())
            for events_by_key in report["cost_scenarios"].values()
        ),
        "complete 82-event 15-cell cost grids required",
    )
    configuration = {
        "authorization_sha256": authorization["artifact_sha256"],
        "calculator_artifact_sha256": authorization["calculator_artifact_sha256"],
        "dataset_version": lineage["dataset_version"],
        "geometry_event_set_sha256": authorization["geometry_event_set_sha256"],
        "identity": JOB_IDENTITY,
        "policy_sha256": authorization["policy_sha256"],
        "strategy_version": lineage["strategy_version"],
    }
    output_hashes = {
        **report["hashes"],
        "complete_report_sha256": report["report_sha256"],
        "equity_paths_sha256": calculator.digest(
            {risk: body["daily_equity"] for risk, body in sorted(report["fixed_capital"].items())}
        ),
        "event_keys_sha256": calculator.digest(keys),
        "metrics_sha256": calculator.digest(report["metrics"]),
        "terminal_counts_sha256": calculator.digest(report["terminal_counts"]),
    }
    body = {
        "authority": {
            "exploratory_only": True,
            "promotion_permanently_prohibited": True,
            "return_execution_authorization_consumed": authorization["artifact_sha256"],
        },
        "configuration": configuration,
        "configuration_sha256": calculator.digest(configuration),
        "input_manifest": {
            "event_count": EXPECTED_EVENTS,
            "event_keys": list(keys),
            "normalized_inputs_sha256": calculator.digest(
                sorted(events, key=lambda row: row["physical_event_key"])
            ),
        },
        "lineage": lineage,
        "output_hashes": output_hashes,
        "report": report,
        "schema": "failed-break-v2-exploratory-return-result-v1",
    }
    body["evidence_sha256"] = calculator.digest(body)
    return body


def run_authorized(
    *,
    authorization: dict,
    expected_keys: tuple[str, ...],
    adapter: EvidenceAdapter,
    store: ResultStore,
    bootstrap: bool = True,
    inject_failure_after: str | None = None,
    progress=None,
    timings: dict[str, float] | None = None,
) -> dict:
    """Execute adapter -> pure calculator -> one atomic immutable write."""
    _validate_authorization(authorization)
    require(
        len(expected_keys) == len(set(expected_keys)) == EXPECTED_EVENTS,
        "governed event set changed",
    )
    require(BOUNDARY_PURGED_EVENT_KEY not in expected_keys, "boundary-purged event reintroduced")
    with store.atomic():
        return _run_atomic_operation(
            authorization=authorization,
            expected_keys=expected_keys,
            adapter=adapter,
            store=store,
            bootstrap=bootstrap,
            inject_failure_after=inject_failure_after,
            progress=progress,
            timings=timings,
        )


def _run_atomic_operation(
    *,
    authorization,
    expected_keys,
    adapter,
    store,
    bootstrap,
    inject_failure_after,
    progress,
    timings,
):
    """Perform every read, calculation and write in the store transaction."""
    clock = perf_counter()
    lineage = adapter.verify_return_blind_lineage()
    if timings is not None:
        timings["return_blind_lineage_seconds"] = perf_counter() - clock
    _validate_lineage(lineage)
    store.ensure_absent(IDEMPOTENCY_KEY)
    if progress:
        progress("lineage", 0, EXPECTED_EVENTS)
    clock = perf_counter()
    events = adapter.load_normalized_events(expected_keys)
    if timings is not None:
        timings["sealed_evidence_loading_seconds"] = perf_counter() - clock
    actual_keys = tuple(sorted(row.get("physical_event_key") for row in events))
    require(actual_keys == tuple(sorted(expected_keys)), "missing or extra physical event")
    if progress:
        progress("normalized", len(events), EXPECTED_EVENTS)
    clock = perf_counter()
    try:
        report = calculator.calculate_synthetic_cohort(
            events,
            set(expected_keys),
            authorization["policy_sha256"],
            bootstrap=bootstrap,
        )
    except calculator.ReturnRefusal as error:
        raise RunnerRefusal(str(error)) from error
    if timings is not None:
        timings["pure_calculator_seconds"] = perf_counter() - clock
    require(
        all(row["terminal"] != "UNRESOLVED_DATA" for row in report["event_results"]),
        "unresolved outcome aborts the complete operation",
    )
    clock = perf_counter()
    payload = build_persistent_payload(
        authorization=authorization,
        lineage=lineage,
        events=events,
        report=report,
    )
    if timings is not None:
        timings["canonical_payload_seconds"] = perf_counter() - clock
    if inject_failure_after == "calculation":
        raise RunnerRefusal("injected failure after calculation")
    clock = perf_counter()
    store.persist(payload, inject_failure_after=inject_failure_after)
    if timings is not None:
        timings["atomic_persistence_seconds"] = perf_counter() - clock
    if progress:
        progress("committed", EXPECTED_EVENTS, EXPECTED_EVENTS)
    return payload


def readiness() -> dict:
    """Return fixed-path code readiness without constructing a DB adapter."""
    from research import exploratory_return_runner_v2_governance as governance

    artifact = governance.load_preregistration()
    authorization = governance.inspect_execution_authorization()
    return {
        "code_only_implementation": "READY",
        "execution_authorization": authorization["status"],
        "governed_physical_events": artifact["expected"]["physical_event_count"],
        "outcome_query_count": 0,
        "persistent_write_count": 0,
        "promotion_permanently_prohibited": True,
        "status": "IMPLEMENTED_NOT_AUTHORIZED",
    }


def execute_persistent(*, progress=None) -> dict:
    """Future entry point; authorization is checked before Django/ORM imports."""
    from research import exploratory_return_runner_v2_governance as governance

    governance.load_preregistration()
    authorization = governance.require_execution_authorization()
    # These imports are deliberately unreachable in the committed unauthorized state.
    from research.exploratory_return_adapter_v2 import (  # pragma: no cover
        DjangoResultStore,
        DjangoSealedEvidenceAdapter,
    )

    return run_authorized(
        authorization=authorization,
        expected_keys=governance.governed_event_keys(),
        adapter=DjangoSealedEvidenceAdapter(),
        store=DjangoResultStore(),
        progress=progress,
    )


@dataclass
class SyntheticEvidenceAdapter:
    """Bounded synthetic adapter used by focused tests and the benchmark."""

    events: list[dict]
    lineage: dict
    query_counts: dict[str, int] = field(default_factory=dict)

    def verify_return_blind_lineage(self) -> dict:
        self.query_counts["return_blind_lineage"] = 1
        return copy.deepcopy(self.lineage)

    def load_normalized_events(self, expected_keys: tuple[str, ...]) -> list[dict]:
        self.query_counts["sealed_outcome_preload"] = 1
        require(
            set(expected_keys) == {row.get("physical_event_key") for row in self.events},
            "synthetic event set drift",
        )
        return copy.deepcopy(self.events)


@dataclass
class SyntheticAtomicStore:
    """Transactional in-memory image of the single JobRun persistence contract."""

    rows: dict[str, dict] = field(default_factory=dict)
    query_counts: dict[str, int] = field(default_factory=dict)
    _snapshot: dict[str, dict] | None = None

    def ensure_absent(self, idempotency_key: str) -> None:
        self.query_counts["duplicate_check"] = self.query_counts.get("duplicate_check", 0) + 1
        require(idempotency_key not in self.rows, "exploratory result already exists")

    @contextmanager
    def atomic(self):
        self._snapshot = copy.deepcopy(self.rows)
        try:
            yield
        except Exception:
            self.rows = self._snapshot
            raise
        finally:
            self._snapshot = None

    def persist(self, payload: dict, *, inject_failure_after: str | None = None) -> None:
        self.query_counts["result_insert"] = self.query_counts.get("result_insert", 0) + 1
        require(IDEMPOTENCY_KEY not in self.rows, "duplicate write")
        self.rows[IDEMPOTENCY_KEY] = copy.deepcopy(payload)
        if inject_failure_after == "insert":
            raise RunnerRefusal("injected failure after insert")
        self.query_counts["readback_verify"] = self.query_counts.get("readback_verify", 0) + 1
        stored = self.rows[IDEMPOTENCY_KEY]
        claimed = stored["evidence_sha256"]
        body = dict(stored)
        body.pop("evidence_sha256")
        require(claimed == calculator.digest(body), "persisted result hash mismatch")
        if inject_failure_after == "readback":
            raise RunnerRefusal("injected failure after readback")


def synthetic_authorization(
    *, artifact_sha256: str = "a" * 64, policy_sha256: str = "b" * 64
) -> dict:
    """Test-only authorization value; never loaded by the management command."""
    return {
        "artifact_sha256": artifact_sha256,
        "authority": {
            "exploratory_return_execution": True,
            "retry": False,
            "resume": False,
            "promotion": False,
            "live_trading": False,
        },
        "calculator_artifact_sha256": (
            "92acc23cc194e530f525c92243466aa87adc1933b8e659b560ccf9dae3a3ec1a"
        ),
        "geometry_event_set_sha256": (
            "8abb97a0e658d7079b9cfffd66259609b00f7c57aba89209a01cb5673df9fbd8"
        ),
        "job_identity": JOB_IDENTITY,
        "physical_event_count": EXPECTED_EVENTS,
        "policy_sha256": policy_sha256,
    }


def synthetic_lineage() -> dict:
    return {
        "dataset_version": "phase-2b1r-v2",
        "strategy_version": "failed-break-phase-1-admission-correction-v2",
        "s1_outcome": "ACCEPTED",
        "s2_policy": "EFFECTIVE_EXPLORATORY_ONLY",
        "promotion_permanently_prohibited": True,
    }
