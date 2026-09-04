"""Optimized, return-blind failed-break v2 S1 projection and persistence.

The public command remains fail-closed until a separately reviewed execution
authorization is committed.  The projection path is deliberately independent
of database primary keys so its canonical evidence is invariant across batch
sizes and disposable restores.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter

from django.db import connection, transaction

from market.models import IngestionManifest, Instrument
from market.services import candle_completion
from research.failed_break_detector import _serializable
from research.failed_break_detector_v2 import (
    IncrementalAtr,
    IncrementalDailyState,
    SealedHorizonIndex,
    V2InstrumentSnapshot,
    assert_complete_projection,
    completion_stream,
    confirm_sweep_v2,
    load_instrument_snapshot,
    project_admission,
    provider_observed_completion_stream,
)
from research.failed_break_services import (
    COMBINED_BOOK,
    DB_DECIMAL_QUANTUM,
    FAMILY_BOOKS,
    evidence_hash,
)
from research.failed_break_v2_s0 import V2_S0_AS_OF, validate_v2_s0_prerequisites
from research.failed_break_v2_s0_governance import (
    select_persistent_v2_s0_evidence,
    verify_v2_s0_acceptance,
)
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
from research.pre_s1_governance import (
    CAD_CONVERSION_POLICY_IDENTITY,
    CAD_CONVERSION_ROUTE_SHA256,
    CAD_CONVERSION_ROUTES,
)
from research.signal_count import DEVELOPMENT_END, DEVELOPMENT_START, FROZEN_INSTRUMENTS, PIPETTES
from research.strategy import (
    Bias,
    Candle,
    Context,
    EntryOpen,
    EntryResult,
    LevelSpec,
    LevelState,
    Lifecycle,
    Pivot,
    Role,
    SweepEvent,
    confirmed_swing_levels,
    detect_failed_sweep,
    entry_eligibility,
    flip_level,
    make_level,
    market_structure,
    previous_weekly_levels,
)

V2_S1_JOB_NAME = "failed-break-signal-count-s1-v2"
V2_S1_RUNNER_IDENTITY = "failed-break-optimized-s1-runner-v2"
EXPECTED_H1_MEMBERS = 344_817
DEFAULT_BATCH_SIZE = 5_000
PROGRESS_INTERVAL = 25_000
DISPOSABLE_DATABASE_PREFIX = "failed_break_v2_s1_benchmark_"


class V2S1Refusal(ValueError):
    """A v2 S1 identity, evidence, or execution boundary failed closed."""


def _stored_decimal(value):
    return value.quantize(DB_DECIMAL_QUANTUM) if value is not None else None


def _context(at, strategy, dataset) -> Context:
    return Context(at, strategy.content_hash, dataset.manifest_sha256)


def _strategy_candle(row, completed_at: datetime) -> Candle:
    return Candle(
        opened_at=row.timestamp,
        completed_at=completed_at,
        bid_open=row.bid_open,
        bid_high=row.bid_high,
        bid_low=row.bid_low,
        bid_close=row.bid_close,
        ask_open=row.ask_open,
        ask_high=row.ask_high,
        ask_low=row.ask_low,
        ask_close=row.ask_close,
        complete=row.complete,
    )


def _setup_evidence(event: SweepEvent) -> dict:
    return {
        "sweep": {
            "completed_at": event.at.isoformat(),
            "side": event.side.value,
            "extreme": str(event.sweep_extreme),
        },
        "bias": {"value": event.frozen_bias.value},
        "provisional_swing": {"price": str(event.provisional_swing)},
        "threshold": {"price": str(event.confirmation_threshold)},
    }


@dataclass
class ProjectedLevel:
    instrument_id: int
    instrument_code: str
    spec: LevelSpec
    stable_key: str
    state: LevelState = field(default_factory=lambda: LevelState(Lifecycle.ACTIVE))
    lifecycle: list[tuple[str, datetime, dict, str]] = field(default_factory=list)


@dataclass
class ProjectedEvaluation:
    book_identity: str
    result: EntryResult
    entry_timestamp: datetime
    target_stable_key: str | None
    evidence: dict
    evidence_hash: str


@dataclass
class ProjectedSetup:
    instrument_id: int
    instrument_code: str
    event: SweepEvent
    evidence: dict
    evidence_hash: str
    attribution_keys: tuple[str, ...]
    attribution_families: tuple[str, ...]
    confirmation: tuple[str, datetime, dict, str, str] | None = None
    evaluations: list[ProjectedEvaluation] = field(default_factory=list)
    censored: dict | None = None

    @property
    def logical_key(self) -> str:
        return self.evidence_hash


@dataclass(frozen=True)
class ProjectedAnalysis:
    instrument_id: int
    instrument_code: str
    completed_at: datetime
    result: str
    setup_keys: tuple[str, ...]
    evidence: dict
    evidence_hash: str


@dataclass(frozen=True)
class V2S1Projection:
    levels: tuple[ProjectedLevel, ...]
    setups: tuple[ProjectedSetup, ...]
    analyses: tuple[ProjectedAnalysis, ...]
    inventory_counts: Mapping[str, Mapping[str, int]]
    inventory_sha256: Mapping[str, Mapping[str, str]]
    report: dict

    def canonical_evidence(self) -> dict:
        return {
            "analyses": [
                {
                    "instrument": row.instrument_code,
                    "completed_at": row.completed_at.isoformat(),
                    "result": row.result,
                    "setup_keys": list(row.setup_keys),
                    "evidence_hash": row.evidence_hash,
                }
                for row in self.analyses
            ],
            "levels": [
                {
                    "instrument": row.instrument_code,
                    "stable_key": row.stable_key,
                    "state": row.state.state.value,
                    "lifecycle_hashes": [event[3] for event in row.lifecycle],
                }
                for row in self.levels
            ],
            "setups": [
                {
                    "instrument": row.instrument_code,
                    "logical_key": row.logical_key,
                    "attribution_keys": list(row.attribution_keys),
                    "confirmation_hash": row.confirmation[3] if row.confirmation else None,
                    "censored_sha256": row.censored.get("evidence_sha256")
                    if row.censored
                    else None,
                    "evaluations": [
                        {
                            "book": evaluation.book_identity,
                            "decision": evaluation.result.decision,
                            "evidence_hash": evaluation.evidence_hash,
                        }
                        for evaluation in row.evaluations
                    ],
                }
                for row in self.setups
            ],
        }


def _level_key(*, instrument, strategy, dataset, spec: LevelSpec) -> str:
    return evidence_hash(
        {
            "instrument": instrument.code,
            "strategy": strategy.content_hash,
            "dataset": dataset.manifest_sha256,
            "level": asdict(spec),
        }
    )


def _add_level(nodes, known_spec_keys, *, instrument, strategy, dataset, spec):
    if spec.key in known_spec_keys:
        return None
    known_spec_keys.add(spec.key)
    node = ProjectedLevel(
        instrument.pk,
        instrument.code,
        spec,
        _level_key(instrument=instrument, strategy=strategy, dataset=dataset, spec=spec),
    )
    nodes.append(node)
    return node


def _terminal(node: ProjectedLevel, state: Lifecycle, effective_at: datetime) -> None:
    evidence = {
        "source_level_key": node.stable_key,
        "state": state.value,
        "effective_at": effective_at.isoformat(),
    }
    node.lifecycle.append((state.value, effective_at, evidence, evidence_hash(evidence)))
    node.state = LevelState(state, effective_at)


def _update_lifecycle(
    nodes,
    known_spec_keys,
    *,
    instrument,
    strategy,
    dataset,
    at,
    daily_candle,
    daily_index,
    daily_index_by_completion,
    daily_atr,
):
    added = True
    while added:
        added = False
        specs = tuple(node.spec for node in nodes)
        for node in tuple(nodes):
            if node.state.state != Lifecycle.ACTIVE or node.spec.activated_at > at:
                continue
            superseded_at = None
            if node.spec.family == Level.Family.DAILY_SWING:
                original = node.spec.key.split(":flip:", 1)[0].split(":", 2)
                if len(original) != 3:
                    raise V2S1Refusal("daily-swing level lacks its governed original key")
                candidates = []
                for candidate in specs:
                    parts = candidate.key.split(":flip:", 1)[0].split(":", 2)
                    if (
                        candidate.family == Level.Family.DAILY_SWING
                        and len(parts) == 3
                        and parts[1] == original[1]
                        and candidate.source_at > node.spec.source_at
                    ):
                        candidates.append((candidate.activated_at, candidate.key))
                superseded_at = min(candidates)[0] if candidates else None
            if superseded_at is not None and superseded_at <= at:
                _terminal(node, Lifecycle.SUPERSEDED, superseded_at)
                continue
            if node.spec.expires_at is not None and node.spec.expires_at <= at:
                _terminal(node, Lifecycle.EXPIRED, node.spec.expires_at)
                continue
            if daily_candle is None or daily_candle.completed_at < node.spec.activated_at:
                continue
            if node.spec.expires_after_sessions is not None:
                activated_index = daily_index_by_completion.get(node.spec.activated_at)
                if activated_index is None:
                    raise V2S1Refusal("session-expiring level lacks a sealed D activation")
                if daily_index - activated_index >= node.spec.expires_after_sessions:
                    _terminal(node, Lifecycle.EXPIRED, daily_candle.completed_at)
                    continue
            crossed = (
                daily_candle.close < node.spec.central_price
                if node.spec.role == Role.SUPPORT
                else daily_candle.close > node.spec.central_price
            )
            if node.spec.family in {Level.Family.WEEKLY, Level.Family.DAILY_SWING} and crossed:
                _terminal(node, Lifecycle.SUPERSEDED_BY_FLIP, daily_candle.completed_at)
                if daily_atr is None:
                    raise V2S1Refusal("role flip lacks sealed D ATR evidence")
                flipped = flip_level(
                    node.spec,
                    daily_candle,
                    daily_atr,
                    PIPETTES[instrument.code],
                    _context(at, strategy, dataset),
                )
                if _add_level(
                    nodes,
                    known_spec_keys,
                    instrument=instrument,
                    strategy=strategy,
                    dataset=dataset,
                    spec=flipped,
                ):
                    added = True
                continue
            invalidated = (
                daily_candle.close < node.spec.zone_lower
                if node.spec.role == Role.SUPPORT
                else daily_candle.close > node.spec.zone_upper
            )
            if invalidated:
                _terminal(node, Lifecycle.INVALIDATED, daily_candle.completed_at)


def _bias(daily, pivots, update, ema50_history) -> Bias:
    if not daily or update.ema50 is None or update.ema200 is None or len(ema50_history) < 21:
        return Bias.NEUTRAL
    structure = market_structure(pivots, daily[-1].close, Context(daily[-1].completed_at, "", ""))
    if (
        structure == Bias.BULLISH
        and update.ema50 > update.ema200
        and update.ema50 > ema50_history[0]
    ):
        return Bias.BULLISH
    if (
        structure == Bias.BEARISH
        and update.ema50 < update.ema200
        and update.ema50 < ema50_history[0]
    ):
        return Bias.BEARISH
    return Bias.NEUTRAL


def _supporting(pivots: Sequence[Pivot], bias: Bias, at: datetime):
    kind = "low" if bias == Bias.BULLISH else "high" if bias == Bias.BEARISH else None
    return max(
        (pivot for pivot in pivots if pivot.kind == kind and pivot.available_at <= at),
        key=lambda pivot: (pivot.available_at, pivot.at),
        default=None,
    )


def _books(setup: ProjectedSetup) -> tuple[str, ...]:
    return tuple(
        sorted({COMBINED_BOOK, *(FAMILY_BOOKS[family] for family in setup.attribution_families)})
    )


def _conversion_leg(
    snapshots: Mapping[str, V2InstrumentSnapshot],
    manifest_by_run: Mapping[int, str],
    contract,
    dataset_manifest_sha256: str,
    instrument_code: str,
    entry_timestamp: datetime,
):
    snapshot = snapshots[instrument_code]
    eligible = []
    for opened_at in snapshot.inventory["H1"]:
        candle = snapshot.candles[("H1", opened_at)]
        completed_at = candle_completion(opened_at, "H1", contract)
        if completed_at < entry_timestamp:
            eligible.append((completed_at, candle))
    if not eligible:
        return None
    completed_at, candle = eligible[-1]
    manifest_sha = manifest_by_run.get(candle.ingestion_run_id)
    if not manifest_sha:
        return None
    body = {
        "instrument": instrument_code,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "granularity": "H1",
        "timestamp": candle.timestamp.isoformat(),
        "completed_at": completed_at.isoformat(),
        "midpoint_close": str(candle.midpoint_close),
        "ingestion_manifest_sha256": manifest_sha,
    }
    return candle.midpoint_close, completed_at, {**body, "evidence_sha256": evidence_hash(body)}


def _cad_conversion(
    snapshots,
    manifest_by_run,
    contract,
    dataset_manifest_sha256,
    instrument,
    entry_timestamp,
):
    route = CAD_CONVERSION_ROUTES.get(instrument.quote_currency)
    body = {
        "policy_identity": CAD_CONVERSION_POLICY_IDENTITY,
        "route_table_sha256": CAD_CONVERSION_ROUTE_SHA256,
        "account_currency": "CAD",
        "quote_currency": instrument.quote_currency,
        "entry_timestamp": entry_timestamp.isoformat(),
        "route": [],
    }
    if route is None:
        return None, None, "", {**body, "failure": "UNSUPPORTED_QUOTE_CURRENCY"}
    if not route:
        body["resulting_cad_conversion"] = "1"
        return (
            Decimal(1),
            entry_timestamp,
            f"{CAD_CONVERSION_POLICY_IDENTITY}:{evidence_hash(body)}",
            body,
        )
    result = Decimal(1)
    effective_at = None
    for code, direction in route:
        leg = _conversion_leg(
            snapshots,
            manifest_by_run,
            contract,
            dataset_manifest_sha256,
            code,
            entry_timestamp,
        )
        if not leg or leg[0] <= 0:
            body["failure"] = f"MISSING_OR_CONFLICTING_{code}"
            return None, None, "", body
        rate, completed_at, evidence = leg
        result = result * rate if direction == "multiply" else result / rate
        effective_at = max(effective_at, completed_at) if effective_at else completed_at
        body["route"].append({"direction": direction, **evidence})
    body["resulting_cad_conversion"] = str(result)
    return (
        result,
        effective_at,
        f"{CAD_CONVERSION_POLICY_IDENTITY}:{evidence_hash(body)}",
        body,
    )


def _censorship(setup: ProjectedSetup, inventory, contract) -> dict | None:
    successors = tuple(timestamp for timestamp in inventory if timestamp >= setup.event.at)[:4]
    latest = candle_completion(successors[2], "H1", contract) if len(successors) >= 3 else None
    entry_completion = (
        candle_completion(successors[3], "H1", contract) if len(successors) >= 4 else None
    )
    boundary = DEVELOPMENT_END.astimezone(UTC)
    if entry_completion is not None and entry_completion < boundary:
        return None
    body = {
        "setup_key": setup.logical_key,
        "sweep_timestamp": setup.event.at.isoformat(),
        "rule": "development-sweep-sealed-three-h1-plus-entry-v2",
        "partition_boundary": boundary.isoformat(),
        "latest_confirmation_completion": latest.isoformat() if latest else None,
        "entry_evidence_completion": entry_completion.isoformat() if entry_completion else None,
    }
    return {**body, "evidence_sha256": evidence_hash(body)}


def _evaluate_entry(
    setup,
    opening,
    h1_atr,
    nodes,
    snapshots,
    manifests,
    contract,
    instrument,
    strategy,
    dataset,
    ceiling,
):
    entry_at = opening.timestamp
    entry_event = setup.event
    if setup.confirmation is not None:
        confirmed_support = setup.confirmation[2].get("supporting_swing")
        if confirmed_support is not None:
            entry_event = replace(
                entry_event,
                provisional_swing=Decimal(str(confirmed_support)),
            )
    active_specs = []
    states = {}
    for node in nodes:
        if node.spec.activated_at > entry_at:
            continue
        stored = replace(node.spec, key=node.stable_key)
        active_specs.append(stored)
        states[stored.key] = node.state
    rate, conversion_at, identity, conversion_evidence = _cad_conversion(
        snapshots,
        manifests,
        contract,
        dataset.manifest_sha256,
        instrument,
        entry_at,
    )
    result = entry_eligibility(
        entry_event,
        opening,
        h1_atr,
        active_specs,
        _context(entry_at, strategy, dataset),
        expected_entry_timestamp=entry_at,
        precision=PIPETTES[instrument.code],
        absolute_spread_ceiling=ceiling,
        level_states=states,
        cad_conversion_rate=rate,
        conversion_effective_at=conversion_at,
        conversion_identity=identity,
    )
    evidence = {
        "expected_entry_timestamp": entry_at.isoformat(),
        "decision": result.decision,
        "reason": result.reason,
        "entry_open_present": True,
        "cad_conversion": conversion_evidence,
    }
    for book in _books(setup):
        setup.evaluations.append(
            ProjectedEvaluation(
                book,
                result,
                entry_at,
                result.target_key,
                evidence,
                evidence_hash(evidence),
            )
        )


def _project_instrument(
    *,
    snapshot,
    snapshots,
    manifests,
    contract,
    instrument,
    strategy,
    dataset,
    spread_ceiling,
    stream_builder,
    progress,
):
    events = (
        provider_observed_completion_stream(snapshot.inventory, contract)
        if stream_builder is completion_stream
        else stream_builder(
            snapshot.inventory,
            lambda granularity, opened_at: candle_completion(opened_at, granularity, contract),
        )
    )
    admission = project_admission(events)
    assert_complete_projection(admission, snapshot.inventory)
    horizon = SealedHorizonIndex.from_projection(admission)
    next_week_completion = {
        event.opened_at: (weekly[index + 1].completed_at if index + 1 < len(weekly) else None)
        for weekly in [[event for event in events if event.granularity == "W"]]
        for index, event in enumerate(weekly)
    }
    nodes: list[ProjectedLevel] = []
    setups: list[ProjectedSetup] = []
    analyses: list[ProjectedAnalysis] = []
    known_spec_keys: set[str] = set()
    consumed: set[str] = set()
    pending: list[ProjectedSetup] = []
    h1: list[Candle] = []
    daily: list[Candle] = []
    pivots: list[Pivot] = []
    daily_index_by_completion: dict[datetime, int] = {}
    daily_state = IncrementalDailyState()
    h1_atr_state = IncrementalAtr()
    ema50_history: deque[Decimal] = deque(maxlen=21)
    current_daily_atr = None
    bias = Bias.NEUTRAL
    supporting = None
    previous = None
    development_start = DEVELOPMENT_START.astimezone(UTC)
    development_end = DEVELOPMENT_END.astimezone(UTC)
    event_index = 0
    while event_index < len(events):
        completed_at = events[event_index].completed_at
        end = event_index + 1
        while end < len(events) and events[end].completed_at == completed_at:
            end += 1
        batch = events[event_index:end]
        by_granularity = {event.granularity: event for event in batch}
        h1_event = by_granularity.get("H1")
        current_h1 = None
        if h1_event is not None:
            current_h1 = _strategy_candle(
                snapshot.candles[("H1", h1_event.opened_at)], h1_event.completed_at
            )
            for setup in tuple(pending):
                if setup.confirmation and setup.confirmation[0] == SetupTransition.State.CONFIRMED:
                    expected_index = bisect_left(snapshot.inventory["H1"], setup.confirmation[1])
                    if expected_index >= len(snapshot.inventory["H1"]):
                        raise V2S1Refusal("confirmed setup lacks sealed H1 entry successor")
                    if snapshot.inventory["H1"][expected_index] == h1_event.opened_at:
                        _evaluate_entry(
                            setup,
                            EntryOpen(
                                current_h1.opened_at, current_h1.bid_open, current_h1.ask_open
                            ),
                            h1_atr_state.value,
                            nodes,
                            snapshots,
                            manifests,
                            contract,
                            instrument,
                            strategy,
                            dataset,
                            spread_ceiling,
                        )
                        pending.remove(setup)
            h1.append(current_h1)
            h1_atr_state.update(high=current_h1.high, low=current_h1.low, close=current_h1.close)

        new_week = None
        if "W" in by_granularity:
            event = by_granularity["W"]
            new_week = _strategy_candle(
                snapshot.candles[("W", event.opened_at)], event.completed_at
            )
        new_daily = None
        daily_update = None
        if "D" in by_granularity:
            event = by_granularity["D"]
            new_daily = _strategy_candle(
                snapshot.candles[("D", event.opened_at)], event.completed_at
            )
            daily.append(new_daily)
            daily_index_by_completion[new_daily.completed_at] = len(daily) - 1
            daily_update = daily_state.update(new_daily)
            current_daily_atr = daily_update.atr14
            if daily_update.ema50 is not None:
                ema50_history.append(daily_update.ema50)
            pivots.extend(daily_update.new_pivots)
            if daily_update.atr14 is not None:
                for spec in confirmed_swing_levels(
                    daily_update.new_pivots,
                    {new_daily.completed_at: daily_update.atr14},
                    PIPETTES[instrument.code],
                    _context(completed_at, strategy, dataset),
                ):
                    _add_level(
                        nodes,
                        known_spec_keys,
                        instrument=instrument,
                        strategy=strategy,
                        dataset=dataset,
                        spec=spec,
                    )
                if (
                    daily_update.prior_20_high is not None
                    and new_daily.close > daily_update.prior_20_high
                ):
                    spec = make_level(
                        f"breakout-high:{new_daily.opened_at.isoformat()}",
                        Level.Family.BREAKOUT,
                        Role.SUPPORT,
                        daily_update.prior_20_high,
                        daily_update.atr14,
                        new_daily.completed_at,
                        new_daily.opened_at,
                        PIPETTES[instrument.code],
                        _context(completed_at, strategy, dataset),
                        expires_after_sessions=20,
                    )
                    _add_level(
                        nodes,
                        known_spec_keys,
                        instrument=instrument,
                        strategy=strategy,
                        dataset=dataset,
                        spec=spec,
                    )
                if (
                    daily_update.prior_20_low is not None
                    and new_daily.close < daily_update.prior_20_low
                ):
                    spec = make_level(
                        f"breakout-low:{new_daily.opened_at.isoformat()}",
                        Level.Family.BREAKOUT,
                        Role.RESISTANCE,
                        daily_update.prior_20_low,
                        daily_update.atr14,
                        new_daily.completed_at,
                        new_daily.opened_at,
                        PIPETTES[instrument.code],
                        _context(completed_at, strategy, dataset),
                        expires_after_sessions=20,
                    )
                    _add_level(
                        nodes,
                        known_spec_keys,
                        instrument=instrument,
                        strategy=strategy,
                        dataset=dataset,
                        spec=spec,
                    )
        if new_week is not None and current_daily_atr is not None:
            expiry = next_week_completion[new_week.opened_at]
            for spec in previous_weekly_levels(
                (new_week,),
                current_daily_atr,
                PIPETTES[instrument.code],
                _context(completed_at, strategy, dataset),
                expires_at=expiry,
            ):
                _add_level(
                    nodes,
                    known_spec_keys,
                    instrument=instrument,
                    strategy=strategy,
                    dataset=dataset,
                    spec=spec,
                )
        if new_daily is not None or new_week is not None:
            _update_lifecycle(
                nodes,
                known_spec_keys,
                instrument=instrument,
                strategy=strategy,
                dataset=dataset,
                at=completed_at,
                daily_candle=new_daily,
                daily_index=len(daily) - 1,
                daily_index_by_completion=daily_index_by_completion,
                daily_atr=current_daily_atr,
            )
            if new_daily is not None:
                bias = _bias(daily, pivots, daily_update, ema50_history)
                supporting = _supporting(pivots, bias, completed_at)

        if h1_event is not None:
            for setup in tuple(pending):
                if setup.confirmation is not None:
                    continue
                inactive = {
                    key: next(
                        (node.state.effective_at for node in nodes if node.stable_key == key),
                        None,
                    )
                    for key in setup.attribution_keys
                }
                confirmation = confirm_sweep_v2(
                    setup.event,
                    h1,
                    daily,
                    _context(completed_at, strategy, dataset),
                    attributed_level_inactive_at=inactive,
                    sealed_h1_inventory=snapshot.inventory["H1"],
                    supporting_swings=pivots,
                )
                if confirmation.state != SetupTransition.State.TRIGGER_PENDING:
                    evidence = _serializable(asdict(confirmation))
                    setup.confirmation = (
                        confirmation.state,
                        confirmation.at,
                        evidence,
                        evidence_hash(evidence),
                        "CONFIRMATION_WINDOW"
                        if confirmation.state == SetupTransition.State.EXPIRED
                        else "",
                    )
                    if confirmation.state != SetupTransition.State.CONFIRMED:
                        pending.remove(setup)

            created: list[str] = []
            in_development = development_start <= completed_at < development_end
            if in_development and previous is not None and supporting and bias != Bias.NEUTRAL:
                active = [
                    node
                    for node in nodes
                    if node.state.state == Lifecycle.ACTIVE
                    and node.spec.activated_at <= current_h1.opened_at
                    and node.stable_key not in consumed
                ]
                event = detect_failed_sweep(
                    previous,
                    current_h1,
                    [replace(node.spec, key=node.stable_key) for node in active],
                    bias,
                    supporting.price,
                    _context(completed_at, strategy, dataset),
                )
                if event:
                    by_key = {node.stable_key: node for node in active}
                    evidence = _setup_evidence(event)
                    setup = ProjectedSetup(
                        instrument.pk,
                        instrument.code,
                        event,
                        evidence,
                        evidence_hash(evidence),
                        tuple(event.level_keys),
                        tuple(sorted({by_key[key].spec.family for key in event.level_keys})),
                    )
                    setup.censored = _censorship(setup, snapshot.inventory["H1"], contract)
                    setups.append(setup)
                    consumed.update(event.level_keys)
                    created.append(setup.logical_key)
                    if setup.censored is None:
                        pending.append(setup)
            result = (
                AnalysisRun.Result.NO_SETUP
                if not in_development
                else AnalysisRun.Result.CANDIDATE_CREATED
                if created
                else AnalysisRun.Result.LEVEL_ACTIVE
                if any(node.state.state == Lifecycle.ACTIVE for node in nodes)
                else AnalysisRun.Result.NO_SETUP
            )
            evidence = {
                "completed_h1_timestamp": completed_at.isoformat(),
                "result": result,
                "setup_keys": created,
                "phase": "DEVELOPMENT" if in_development else "WARMUP",
            }
            analyses.append(
                ProjectedAnalysis(
                    instrument.pk,
                    instrument.code,
                    completed_at,
                    result,
                    tuple(created),
                    evidence,
                    evidence_hash(evidence),
                )
            )
            previous = current_h1
            if progress and len(analyses) % PROGRESS_INTERVAL == 0:
                progress(instrument.code, len(analyses), len(snapshot.inventory["H1"]))
        event_index = end
    if pending:
        raise V2S1Refusal("v2 detector left unresolved non-censored setups")
    return nodes, setups, analyses, admission, horizon


def _projection_report(levels, setups, analyses, counts, hashes, horizons) -> dict:
    development_end = DEVELOPMENT_END.astimezone(UTC)
    confirmed = [
        setup
        for setup in setups
        if setup.confirmation and setup.confirmation[0] == SetupTransition.State.CONFIRMED
    ]
    included = []
    purged = 0
    for setup in confirmed:
        entry_at = setup.evaluations[0].entry_timestamp
        exit_at = horizons[setup.instrument_code].maximum_exit_open(entry_at)
        if exit_at is None or exit_at >= development_end:
            purged += 1
        else:
            included.append(setup)
    decisions = Counter(
        evaluation.result.decision for setup in setups for evaluation in setup.evaluations
    )
    row_counts = {
        "analysis_runs": len(analyses),
        "levels": len(levels),
        "lifecycle_events": sum(len(level.lifecycle) for level in levels),
        "setups": len(setups),
        "attributions": sum(len(setup.attribution_keys) for setup in setups),
        "transitions": sum(
            (1 if setup.confirmation else 0) + len(setup.evaluations) for setup in setups
        ),
        "entry_eligibility": sum(len(setup.evaluations) for setup in setups),
        "job_runs": 1,
    }
    body = {
        "identity": V2_S1_RUNNER_IDENTITY,
        "complete": True,
        "inventory_counts": counts,
        "inventory_sha256": hashes,
        "expected_h1_members": EXPECTED_H1_MEMBERS,
        "observed_h1_analyses": len(analyses),
        "row_counts": row_counts,
        "setup_counts": {
            "sweeps": len(setups),
            "confirmed": len(confirmed),
            "partition_boundary_censored": sum(setup.censored is not None for setup in setups),
            "partition_boundary_purged": purged,
            "included_confirmed": len(included),
            "eligibility_decisions": dict(sorted(decisions.items())),
        },
        "data_quality": {
            "analysis_data_incomplete": sum(
                row.result == AnalysisRun.Result.DATA_INCOMPLETE for row in analyses
            ),
            "cancelled": decisions[EntryEligibilityEvaluation.Decision.CANCELLED_DATA_QUALITY]
            + sum(
                setup.confirmation
                and setup.confirmation[0] == SetupTransition.State.CANCELLED_DATA_QUALITY
                for setup in setups
            ),
        },
        "post_entry_outcomes_read": False,
        "returns_read": False,
    }
    if len(analyses) != EXPECTED_H1_MEMBERS or body["data_quality"] != {
        "analysis_data_incomplete": 0,
        "cancelled": 0,
    }:
        raise V2S1Refusal("v2 S1 projection is incomplete or contains unresolved data quality")
    return {**body, "report_sha256": evidence_hash(body)}


def project_v2_s1(
    *,
    dataset,
    strategy,
    ranges_by_instrument,
    contract,
    s0_job,
    stream_builder=completion_stream,
    progress: Callable[[str, int, int], None] | None = None,
) -> V2S1Projection:
    instruments = {row.code: row for row in Instrument.objects.filter(code__in=FROZEN_INSTRUMENTS)}
    if set(instruments) != FROZEN_INSTRUMENTS:
        raise V2S1Refusal("v2 S1 requires the six frozen instruments")
    snapshots = {}
    for code in sorted(FROZEN_INSTRUMENTS):
        ranges = {
            required.granularity: (required.start, required.end)
            for required in ranges_by_instrument[code]
            if required.granularity in {"H1", "D", "W"}
        }
        snapshots[code] = load_instrument_snapshot(
            dataset=dataset,
            contract=contract,
            instrument=instruments[code],
            ranges=ranges,
        )
    manifests = dict(
        IngestionManifest.objects.filter(dataset_version=dataset).values_list(
            "ingestion_run_id", "sha256"
        )
    )
    expected_runs = {
        candle.ingestion_run_id
        for snapshot in snapshots.values()
        for candle in snapshot.candles.values()
    }
    if set(manifests) != expected_runs:
        raise V2S1Refusal("preloaded candles do not have one stable ingestion manifest each")
    all_levels = []
    all_setups = []
    all_analyses = []
    counts = {}
    hashes = {}
    horizons = {}
    spread_ceilings = s0_job.evidence["report"]["numerical_evidence"]["spread_ceilings"]
    for code in sorted(FROZEN_INSTRUMENTS):
        levels, setups, analyses, admission, horizon = _project_instrument(
            snapshot=snapshots[code],
            snapshots=snapshots,
            manifests=manifests,
            contract=contract,
            instrument=instruments[code],
            strategy=strategy,
            dataset=dataset,
            spread_ceiling=Decimal(spread_ceilings[code]),
            stream_builder=stream_builder,
            progress=progress,
        )
        all_levels.extend(levels)
        all_setups.extend(setups)
        all_analyses.extend(analyses)
        counts[code] = {key: len(value) for key, value in snapshots[code].inventory.items()}
        hashes[code] = admission.membership_sha256
        horizons[code] = horizon
    all_levels.sort(key=lambda row: (row.instrument_code, row.spec.activated_at, row.stable_key))
    all_setups.sort(key=lambda row: (row.event.at, row.instrument_code, row.logical_key))
    all_analyses.sort(key=lambda row: (row.completed_at, row.instrument_code))
    report = _projection_report(all_levels, all_setups, all_analyses, counts, hashes, horizons)
    projection = V2S1Projection(
        tuple(all_levels), tuple(all_setups), tuple(all_analyses), counts, hashes, report
    )
    body = projection.canonical_evidence()
    projection.report["canonical_evidence_sha256"] = evidence_hash(body)
    projection.report["report_sha256"] = evidence_hash(
        {key: value for key, value in projection.report.items() if key != "report_sha256"}
    )
    return projection


def _configuration(*, dataset, strategy, s0_job, governance) -> dict:
    return {
        "identity": V2_S1_RUNNER_IDENTITY,
        "stage": "S1",
        "governance_artifact_sha256": governance["artifact_sha256"],
        "dataset_id": dataset.pk,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "strategy_version_id": strategy.pk,
        "strategy_identity": strategy.version,
        "strategy_content_sha256": strategy.content_hash,
        "detector_identity": strategy.detector_version,
        "s0_job_id": s0_job.pk,
        "s0_configuration_sha256": s0_job.config_hash,
        "s0_report_sha256": s0_job.evidence["report"]["report_sha256"],
        "as_of": V2_S0_AS_OF.isoformat(),
        "expected_h1_members": EXPECTED_H1_MEMBERS,
    }


def _assert_pristine(dataset, strategy) -> None:
    checks = (
        JobRun.objects.filter(
            job_name=V2_S1_JOB_NAME, dataset_version=dataset, strategy_version=strategy
        ),
        AnalysisRun.objects.filter(
            dataset_version=dataset, detector_version=strategy.detector_version
        ),
        Level.objects.filter(dataset_version=dataset, strategy_version=strategy),
        SetupEvent.objects.filter(dataset_version=dataset, strategy_version=strategy),
    )
    if any(query.exists() for query in checks):
        raise V2S1Refusal("v2 S1 is not pristine; duplicate execution is prohibited")


def _bulk(model, rows, batch_size):
    if rows:
        model.objects.bulk_create(rows, batch_size=batch_size)


def persist_projection(
    *,
    projection,
    dataset,
    strategy,
    s0_job,
    governance,
    batch_size=DEFAULT_BATCH_SIZE,
    require_disposable=False,
    inject_failure_after=None,
    stage_observer: Callable[[str, float, int], None] | None = None,
):
    if batch_size < 1:
        raise V2S1Refusal("batch size must be positive")
    if require_disposable and not str(connection.settings_dict["NAME"]).startswith(
        DISPOSABLE_DATABASE_PREFIX
    ):
        raise V2S1Refusal("benchmark persistence requires an isolated disposable database")
    configuration = _configuration(
        dataset=dataset, strategy=strategy, s0_job=s0_job, governance=governance
    )

    def observe(name, started, rows):
        if stage_observer:
            stage_observer(name, perf_counter() - started, rows)

    transaction_started = perf_counter()
    with transaction.atomic():
        _assert_pristine(dataset, strategy)
        started = perf_counter()
        job = JobRun.objects.create(
            job_name=V2_S1_JOB_NAME,
            strategy_version=strategy,
            dataset_version=dataset,
            config_hash=evidence_hash(configuration),
            idempotency_key=f"s1-v2:{strategy.content_hash}:{dataset.manifest_sha256}:{evidence_hash(configuration)}",
            as_of=V2_S0_AS_OF,
            status=JobRun.Status.SUCCEEDED,
            evidence={"configuration": configuration, "report": projection.report},
        )
        observe("job_run", started, 1)
        level_rows = [
            Level(
                family=row.spec.family,
                role=row.spec.role.value,
                instrument_id=row.instrument_id,
                strategy_version=strategy,
                dataset_version=dataset,
                source_timeframe="W" if row.spec.family == Level.Family.WEEKLY else "D",
                source_candle_timestamp=row.spec.source_at,
                central_price=_stored_decimal(row.spec.central_price),
                zone_lower=_stored_decimal(row.spec.zone_lower),
                zone_upper=_stored_decimal(row.spec.zone_upper),
                atr_at_activation=_stored_decimal(row.spec.atr_at_activation),
                activated_at=row.spec.activated_at,
                expires_at=row.spec.expires_at,
                stable_key=row.stable_key,
            )
            for row in projection.levels
        ]
        started = perf_counter()
        _bulk(Level, level_rows, batch_size)
        observe("levels", started, len(level_rows))
        level_by_key = {row.stable_key: row for row in level_rows}
        lifecycle_rows = [
            LevelLifecycleEvent(
                level=level_by_key[level.stable_key],
                state=state,
                effective_at=effective_at,
                evidence=evidence,
                evidence_hash=sha,
            )
            for level in projection.levels
            for state, effective_at, evidence, sha in level.lifecycle
        ]
        started = perf_counter()
        _bulk(LevelLifecycleEvent, lifecycle_rows, batch_size)
        observe("lifecycle_events", started, len(lifecycle_rows))
        setup_rows = [
            SetupEvent(
                instrument_id=row.instrument_id,
                direction=row.event.side.value,
                sweep_h1_timestamp=row.event.at,
                detector_version=strategy.detector_version,
                dataset_version=dataset,
                strategy_version=strategy,
                sweep_evidence=row.evidence["sweep"],
                bias_evidence=row.evidence["bias"],
                provisional_swing_evidence=row.evidence["provisional_swing"],
                threshold_evidence=row.evidence["threshold"],
                attribution_keys=list(row.attribution_keys),
                evidence_hash=row.evidence_hash,
            )
            for row in projection.setups
        ]
        started = perf_counter()
        _bulk(SetupEvent, setup_rows, batch_size)
        observe("setups", started, len(setup_rows))
        setup_by_key = {
            projected.logical_key: stored
            for projected, stored in zip(projection.setups, setup_rows, strict=True)
        }
        attribution_rows = [
            SetupLevelAttribution(
                setup=setup_by_key[setup.logical_key], level=level_by_key[level_key]
            )
            for setup in projection.setups
            for level_key in setup.attribution_keys
        ]
        started = perf_counter()
        _bulk(
            SetupLevelAttribution,
            attribution_rows,
            batch_size,
        )
        observe("setup_attributions", started, len(attribution_rows))
        confirmation_rows = [
            SetupTransition(
                setup=setup_by_key[setup.logical_key],
                book_identity="",
                from_state=SetupTransition.State.TRIGGER_PENDING,
                to_state=setup.confirmation[0],
                effective_at=setup.confirmation[1],
                decision_at=setup.confirmation[1],
                evidence=setup.confirmation[2],
                evidence_hash=setup.confirmation[3],
                reason=setup.confirmation[4],
                strategy_version=strategy,
                dataset_version=dataset,
                execution_identity=strategy.execution_identity,
                job_run=job,
            )
            for setup in projection.setups
            if setup.confirmation is not None
        ]
        started = perf_counter()
        _bulk(SetupTransition, confirmation_rows, batch_size)
        observe("confirmation_transitions", started, len(confirmation_rows))
        evaluation_rows = []
        entry_transition_rows = []
        for setup in projection.setups:
            stored_setup = setup_by_key[setup.logical_key]
            for evaluation in setup.evaluations:
                result = evaluation.result
                permitted = result.decision == EntryEligibilityEvaluation.Decision.ENTRY_PENDING
                target = level_by_key.get(evaluation.target_stable_key)
                evaluation_rows.append(
                    EntryEligibilityEvaluation(
                        setup=stored_setup,
                        book_identity=evaluation.book_identity,
                        decision=result.decision,
                        terminal_reason=result.reason,
                        entry_timestamp=evaluation.entry_timestamp if permitted else None,
                        entry_price=_stored_decimal(result.entry) if permitted else None,
                        stop_price=_stored_decimal(result.stop) if permitted else None,
                        target_price=_stored_decimal(result.target) if permitted else None,
                        reward_risk=_stored_decimal(result.reward_risk) if permitted else None,
                        risk_per_unit_quote=_stored_decimal(result.risk_per_unit_quote)
                        if permitted
                        else None,
                        conversion_rate_to_cad=_stored_decimal(result.conversion_rate_to_cad)
                        if permitted
                        else None,
                        conversion_effective_at=result.conversion_effective_at
                        if permitted
                        else None,
                        conversion_identity=result.conversion_identity if permitted else "",
                        risk_per_unit_cad=_stored_decimal(result.risk_per_unit_cad)
                        if permitted
                        else None,
                        target_level=target if permitted else None,
                        target_stable_key=result.target_key if permitted else "",
                        evidence=evaluation.evidence,
                        evidence_hash=evaluation.evidence_hash,
                    )
                )
                entry_transition_rows.append(
                    SetupTransition(
                        setup=stored_setup,
                        book_identity=evaluation.book_identity,
                        from_state=SetupTransition.State.CONFIRMED,
                        to_state=result.decision,
                        effective_at=evaluation.entry_timestamp,
                        decision_at=evaluation.entry_timestamp,
                        evidence=evaluation.evidence,
                        evidence_hash=evaluation.evidence_hash,
                        reason=result.reason,
                        strategy_version=strategy,
                        dataset_version=dataset,
                        execution_identity=strategy.execution_identity,
                        job_run=job,
                    )
                )
        started = perf_counter()
        _bulk(EntryEligibilityEvaluation, evaluation_rows, batch_size)
        observe("entry_evaluations", started, len(evaluation_rows))
        started = perf_counter()
        _bulk(SetupTransition, entry_transition_rows, batch_size)
        observe("entry_transitions", started, len(entry_transition_rows))
        if inject_failure_after == "entry_evaluations":
            raise V2S1Refusal("injected disposable rollback verification")
        analysis_rows = [
            AnalysisRun(
                instrument_id=row.instrument_id,
                completed_h1_timestamp=row.completed_at,
                detector_version=strategy.detector_version,
                strategy_version=strategy,
                dataset_version=dataset,
                result=row.result,
                evidence_hash=row.evidence_hash,
            )
            for row in projection.analyses
        ]
        started = perf_counter()
        _bulk(
            AnalysisRun,
            analysis_rows,
            batch_size,
        )
        observe("analysis_runs", started, len(analysis_rows))
    observe(
        "atomic_transaction_total",
        transaction_started,
        sum(projection.report["row_counts"].values()),
    )
    return job


def readiness_v2_s1() -> dict:
    from research.failed_break_v2_s1_governance import load_v2_s1_policy

    policy = load_v2_s1_policy()
    job, dataset, strategy = select_persistent_v2_s0_evidence()
    acceptance = verify_v2_s0_acceptance(job=job, dataset=dataset, strategy=strategy)
    ranges, contract, _ = validate_v2_s0_prerequisites(
        dataset=dataset, strategy=strategy, as_of=V2_S0_AS_OF
    )
    _assert_pristine(dataset, strategy)
    return {
        "status": "READY_CODE_ONLY_EXECUTION_UNAUTHORIZED",
        "artifact_sha256": policy["artifact_sha256"],
        "dataset_id": dataset.pk,
        "strategy_version_id": strategy.pk,
        "s0_job_id": job.pk,
        "s0_acceptance_sha256": acceptance["acceptance_sha256"],
        "instrument_count": len(ranges),
        "contract_sha256": contract.sha256,
        "persistent_execution_authorized": False,
    }


def execute_v2_s1(progress=None):
    from research.failed_break_v2_s1_governance import (
        load_v2_s1_execution_authorization,
        load_v2_s1_policy,
    )

    policy = load_v2_s1_policy()
    authorization = load_v2_s1_execution_authorization()
    if policy["authorization"]["persistent_v2_s1_execution"] is not False or authorization is None:
        raise V2S1Refusal("persistent v2 S1 execution remains unauthorized")
    s0_job, dataset, strategy = select_persistent_v2_s0_evidence()
    verify_v2_s0_acceptance(job=s0_job, dataset=dataset, strategy=strategy)
    ranges, contract, _ = validate_v2_s0_prerequisites(
        dataset=dataset, strategy=strategy, as_of=V2_S0_AS_OF
    )
    _assert_pristine(dataset, strategy)
    projection = project_v2_s1(
        dataset=dataset,
        strategy=strategy,
        ranges_by_instrument=ranges,
        contract=contract,
        s0_job=s0_job,
        progress=progress,
    )
    job = persist_projection(
        projection=projection,
        dataset=dataset,
        strategy=strategy,
        s0_job=s0_job,
        governance=policy,
    )
    return {"job_run_id": job.pk, **projection.report}
