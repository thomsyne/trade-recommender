"""Return-blind, forward-only admission primitives for failed-break detector v2.

This module deliberately does not expose a persistent S1 command.  It provides
the deterministic admission, incremental-indicator, supporting-swing, and
horizon primitives that a separately authorised v2 S1 runner may use after its
own S0 acceptance.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from bisect import bisect_left, bisect_right
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Q

from market.models import (
    Candle as MarketCandle,
)
from market.models import (
    CandleConflict,
    DatasetRegistration,
    DatasetVersion,
    HistoricalDataContract,
    HistoricalTimestampObservation,
    IngestionRun,
    Instrument,
)
from market.services import candle_completion as governed_candle_completion
from research.strategy import (
    Candle,
    Confirmation,
    Context,
    Pivot,
    Side,
    SweepEvent,
    completed_candles,
)

V2_STRATEGY_SLUG = "failed-break-phase-1-admission-correction-v2"
V2_DETECTOR_IDENTITY = "failed-break-detector-v2-admission-correction"
V2_ADMISSION_IDENTITY = "sealed-multitimeframe-completion-stream-v2"
V2_SUPPORTING_SWING_IDENTITY = "supporting-swing-pivot-lifetime-v2"
V2_HORIZON_IDENTITY = "sealed-provider-d-ten-session-horizon-v1"
SUCCESSOR_DATA_IDENTITY = "oanda-ba-ny17-friday-provider-observed-v2"
SUCCESSOR_DATASET_NAME = "failed-break-provider-observed-historical"
SUCCESSOR_DATASET_VERSION = "phase-2b1r-v2"
SUCCESSOR_MANIFEST_SHA256 = "11da094fc7ca6a30e946be33523757d7ab559a9ad1951c9142e8969539930014"
SUCCESSOR_CONTRACT_SHA256 = "d630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c"
SUCCESSOR_INVENTORY_SHA256 = "f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427"
SUCCESSOR_REGISTRATION_CONFIGURATION_SHA256 = (
    "dc12d05ba149b01ec2f5ed4228d64622bc675b58c7d790fe676d2b46370d18e2"
)
SUCCESSOR_REGISTRATION_REPORT_SHA256 = (
    "871ba55669da47577c6eb65c46bf8fb86ba6aef73fe7dd322ff37c67b3f280c2"
)

GRANULARITY_ORDER = ("H1", "W", "D")
GRANULARITY_PRIORITY = {granularity: index for index, granularity in enumerate(GRANULARITY_ORDER)}
PHASE_ORDER = (
    "H1_ENTRY_OPEN_USING_PRE_COMPLETION_STATE",
    "ADMIT_H1",
    "ADMIT_W",
    "ADMIT_D",
    "UPDATE_DW_LIFECYCLE_BIAS_AND_STRUCTURE",
    "RESOLVE_PENDING_H1_CONFIRMATION",
    "EVALUATE_H1_SWEEP_AND_CREATE_ANALYSIS",
)
DETECTION_CANDLE_FIELDS = (
    "timestamp",
    "granularity",
    "complete",
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
)
PRELOAD_ONLY_FIELDS = DETECTION_CANDLE_FIELDS + (
    "id",
    "instrument_id",
    "dataset_version_id",
    "ingestion_run_id",
    "ingestion_run__dataset_version_id",
    "ingestion_run__status",
    "ingestion_run__ingestion_manifest__id",
    "ingestion_run__historical_attempt__attempt_number",
    "ingestion_run__historical_attempt__chunk__dataset_version_id",
    "ingestion_run__historical_attempt__chunk__instrument_id",
    "ingestion_run__historical_attempt__chunk__granularity",
    "ingestion_run__historical_attempt__chunk__discovery_inventory_id",
)


class DetectorV2EvidenceError(RuntimeError):
    """Raised when registered sealed evidence cannot be admitted exactly."""


def validate_registered_successor(
    dataset: DatasetVersion,
    contract: HistoricalDataContract,
) -> dict[str, str]:
    """Validate stable dataset/registration invariants once before preloading."""

    if (
        dataset.name != SUCCESSOR_DATASET_NAME
        or dataset.version != SUCCESSOR_DATASET_VERSION
        or dataset.manifest_sha256 != SUCCESSOR_MANIFEST_SHA256
        or dataset.data_contract_sha256 != SUCCESSOR_CONTRACT_SHA256
        or contract.identity != SUCCESSOR_DATA_IDENTITY
        or contract.sha256 != SUCCESSOR_CONTRACT_SHA256
        or contract.global_semantic_inventory_sha256 != SUCCESSOR_INVENTORY_SHA256
    ):
        raise DetectorV2EvidenceError("successor dataset or contract identity mismatch")
    try:
        registration = (
            DatasetRegistration.objects.filter(
                dataset_version=dataset,
                data_contract=contract,
            )
            .values(
                "configuration_sha256",
                "report_sha256",
                "global_semantic_inventory_sha256",
                "conflict_count",
                "incident_count",
            )
            .get()
        )
    except DatasetRegistration.DoesNotExist as error:
        raise DetectorV2EvidenceError("successor dataset is not registered") from error
    if registration != {
        "configuration_sha256": SUCCESSOR_REGISTRATION_CONFIGURATION_SHA256,
        "report_sha256": SUCCESSOR_REGISTRATION_REPORT_SHA256,
        "global_semantic_inventory_sha256": SUCCESSOR_INVENTORY_SHA256,
        "conflict_count": 0,
        "incident_count": 0,
    }:
        raise DetectorV2EvidenceError("successor registration identity or quality changed")
    return {
        "dataset": f"{dataset.name}:{dataset.version}",
        "manifest_sha256": dataset.manifest_sha256,
        "contract_sha256": contract.sha256,
        "registration_configuration_sha256": registration["configuration_sha256"],
        "registration_report_sha256": registration["report_sha256"],
        "global_semantic_inventory_sha256": registration["global_semantic_inventory_sha256"],
    }


@dataclass(frozen=True, order=True)
class CompletionEvent:
    completed_at: datetime
    priority: int
    granularity: str
    opened_at: datetime

    @classmethod
    def create(
        cls, *, granularity: str, opened_at: datetime, completed_at: datetime
    ) -> CompletionEvent:
        try:
            priority = GRANULARITY_PRIORITY[granularity]
        except KeyError as exc:
            raise DetectorV2EvidenceError(f"unsupported granularity: {granularity}") from exc
        return cls(
            completed_at=completed_at,
            priority=priority,
            granularity=granularity,
            opened_at=opened_at,
        )


@dataclass(frozen=True)
class CompletionBatch:
    completed_at: datetime
    events: tuple[CompletionEvent, ...]

    @property
    def granularities(self) -> tuple[str, ...]:
        return tuple(event.granularity for event in self.events)


@dataclass(frozen=True)
class AdmissionProjection:
    batches: tuple[CompletionBatch, ...]
    admitted_members: Mapping[str, tuple[datetime, ...]]
    analysis_timestamps: tuple[datetime, ...]
    phase_trace: tuple[tuple[datetime, tuple[str, ...]], ...]

    @property
    def counters(self) -> dict[str, int]:
        return {
            "completion_batches": len(self.batches),
            "h1_members_admitted": len(self.admitted_members["H1"]),
            "weekly_members_admitted": len(self.admitted_members["W"]),
            "daily_members_admitted": len(self.admitted_members["D"]),
            "analysis_runs_projected": len(self.analysis_timestamps),
        }

    @property
    def membership_sha256(self) -> dict[str, str]:
        return {
            granularity: hashlib.sha256(
                json.dumps(
                    [timestamp.isoformat() for timestamp in self.admitted_members[granularity]],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            for granularity in GRANULARITY_ORDER
        }


def _validate_inventory(inventory: Mapping[str, Sequence[datetime]]) -> None:
    if set(inventory) != set(GRANULARITY_ORDER):
        raise DetectorV2EvidenceError("sealed inventory must contain exactly H1, W, and D")
    for granularity in GRANULARITY_ORDER:
        members = tuple(inventory[granularity])
        if members != tuple(sorted(members)) or len(members) != len(set(members)):
            raise DetectorV2EvidenceError(f"{granularity} inventory is not unique and ordered")


def _events_for_granularity(
    granularity: str,
    members: Sequence[datetime],
    completion_resolver: Callable[[str, datetime], datetime],
) -> tuple[CompletionEvent, ...]:
    events = tuple(
        CompletionEvent.create(
            granularity=granularity,
            opened_at=opened_at,
            completed_at=completion_resolver(granularity, opened_at),
        )
        for opened_at in members
    )
    if events != tuple(sorted(events)):
        raise DetectorV2EvidenceError(f"{granularity} completion order is not monotonic")
    return events


def reference_completion_stream(
    inventory: Mapping[str, Sequence[datetime]],
    completion_resolver: Callable[[str, datetime], datetime],
) -> tuple[CompletionEvent, ...]:
    """Simple golden implementation used to prove the optimised merge."""

    _validate_inventory(inventory)
    events = [
        event
        for granularity in GRANULARITY_ORDER
        for event in _events_for_granularity(
            granularity, inventory[granularity], completion_resolver
        )
    ]
    return tuple(sorted(events))


def completion_stream(
    inventory: Mapping[str, Sequence[datetime]],
    completion_resolver: Callable[[str, datetime], datetime],
) -> tuple[CompletionEvent, ...]:
    """Merge ordered sealed inventories without theoretical calendar members."""

    _validate_inventory(inventory)
    streams = (
        _events_for_granularity(granularity, inventory[granularity], completion_resolver)
        for granularity in GRANULARITY_ORDER
    )
    return tuple(heapq.merge(*streams))


def provider_observed_completion_stream(
    inventory: Mapping[str, Sequence[datetime]],
    contract: HistoricalDataContract,
) -> tuple[CompletionEvent, ...]:
    """Resolve completions only through the registered provider-observed contract."""

    return completion_stream(
        inventory,
        lambda granularity, opened_at: governed_candle_completion(
            opened_at,
            granularity,
            contract,
        ),
    )


def project_admission(events: Sequence[CompletionEvent]) -> AdmissionProjection:
    """Project exact admissions and the v1-compatible same-completion phases."""

    admitted: dict[str, list[datetime]] = {key: [] for key in GRANULARITY_ORDER}
    batches: list[CompletionBatch] = []
    analyses: list[datetime] = []
    phase_trace: list[tuple[datetime, tuple[str, ...]]] = []
    index = 0
    while index < len(events):
        completed_at = events[index].completed_at
        end = index + 1
        while end < len(events) and events[end].completed_at == completed_at:
            end += 1
        batch_events = tuple(events[index:end])
        expected = tuple(sorted(batch_events, key=lambda event: event.priority))
        if batch_events != expected or len({event.granularity for event in batch_events}) != len(
            batch_events
        ):
            raise DetectorV2EvidenceError(
                "same-completion events are ambiguous or out of canonical order"
            )
        granularities = {event.granularity for event in batch_events}
        phases: list[str] = []
        if "H1" in granularities:
            phases.append(PHASE_ORDER[0])
        for granularity, phase in (
            ("H1", PHASE_ORDER[1]),
            ("W", PHASE_ORDER[2]),
            ("D", PHASE_ORDER[3]),
        ):
            matching = [event for event in batch_events if event.granularity == granularity]
            if matching:
                admitted[granularity].append(matching[0].opened_at)
                phases.append(phase)
        if granularities.intersection({"W", "D"}):
            phases.append(PHASE_ORDER[4])
        if "H1" in granularities:
            phases.extend(PHASE_ORDER[5:])
            h1_event = next(event for event in batch_events if event.granularity == "H1")
            analyses.append(h1_event.opened_at)
        batches.append(CompletionBatch(completed_at=completed_at, events=batch_events))
        phase_trace.append((completed_at, tuple(phases)))
        index = end
    return AdmissionProjection(
        batches=tuple(batches),
        admitted_members={key: tuple(value) for key, value in admitted.items()},
        analysis_timestamps=tuple(analyses),
        phase_trace=tuple(phase_trace),
    )


def assert_complete_projection(
    projection: AdmissionProjection,
    inventory: Mapping[str, Sequence[datetime]],
) -> None:
    """Fail closed on a missing, duplicate, substituted, or extra admission."""

    _validate_inventory(inventory)
    for granularity in GRANULARITY_ORDER:
        if projection.admitted_members[granularity] != tuple(inventory[granularity]):
            raise DetectorV2EvidenceError(
                f"{granularity} projection does not equal sealed inventory"
            )
    if projection.analysis_timestamps != tuple(inventory["H1"]):
        raise DetectorV2EvidenceError("AnalysisRun projection does not equal sealed H1 inventory")


def drive_admission(
    events: Sequence[CompletionEvent],
    handlers: Mapping[
        str,
        Callable[[CompletionBatch, CompletionEvent | None], None],
    ],
) -> AdmissionProjection:
    """Drive v2 state callbacks in the frozen phase order.

    Requiring every phase handler prevents a future runner from silently
    omitting D/W lifecycle work or moving entry decisions after admission.
    """

    if set(handlers) != set(PHASE_ORDER):
        raise DetectorV2EvidenceError("admission handlers must cover every canonical phase")
    projection = project_admission(events)
    for batch, (_, phases) in zip(projection.batches, projection.phase_trace, strict=True):
        by_granularity = {event.granularity: event for event in batch.events}
        for phase in phases:
            event = None
            if phase in {PHASE_ORDER[0], PHASE_ORDER[1], PHASE_ORDER[5], PHASE_ORDER[6]}:
                event = by_granularity["H1"]
            elif phase == PHASE_ORDER[2]:
                event = by_granularity["W"]
            elif phase == PHASE_ORDER[3]:
                event = by_granularity["D"]
            handlers[phase](batch, event)
    return projection


class IncrementalEma:
    def __init__(self, period: int) -> None:
        self.period = period
        self._seed: list[Decimal] = []
        self.value: Decimal | None = None
        self._alpha = Decimal(2) / Decimal(period + 1)

    def update(self, value: Decimal) -> Decimal | None:
        if self.value is None:
            self._seed.append(value)
            if len(self._seed) == self.period:
                self.value = sum(self._seed, Decimal("0")) / Decimal(self.period)
            return self.value
        self.value = self.value + self._alpha * (value - self.value)
        return self.value


class IncrementalAtr:
    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._ranges: list[Decimal] = []
        self._previous_close: Decimal | None = None
        self.value: Decimal | None = None

    def update(self, *, high: Decimal, low: Decimal, close: Decimal) -> Decimal | None:
        true_range = high - low
        if self._previous_close is not None:
            true_range = max(
                true_range, abs(high - self._previous_close), abs(low - self._previous_close)
            )
        self._previous_close = close
        if self.value is None:
            self._ranges.append(true_range)
            if len(self._ranges) == self.period:
                self.value = sum(self._ranges, Decimal("0")) / Decimal(self.period)
            return self.value
        self.value = ((self.value * Decimal(self.period - 1)) + true_range) / Decimal(self.period)
        return self.value


@dataclass(frozen=True)
class IncrementalDailyUpdate:
    ema50: Decimal | None
    ema200: Decimal | None
    atr14: Decimal | None
    new_pivots: tuple[Pivot, ...]
    prior_20_high: Decimal | None
    prior_20_low: Decimal | None


class IncrementalDailyState:
    """O(1)-per-member EMA/ATR/pivot and breakout-window state."""

    def __init__(self) -> None:
        self._ema50 = IncrementalEma(50)
        self._ema200 = IncrementalEma(200)
        self._atr14 = IncrementalAtr(14)
        self._pivot_window: deque[Candle] = deque(maxlen=5)
        self._breakout_window: deque[Candle] = deque(maxlen=20)

    def update(self, candle: Candle) -> IncrementalDailyUpdate:
        breakout_ready = len(self._breakout_window) == 20
        prior_high = max((row.high for row in self._breakout_window), default=None)
        prior_low = min((row.low for row in self._breakout_window), default=None)
        ema50 = self._ema50.update(candle.close)
        ema200 = self._ema200.update(candle.close)
        atr14 = self._atr14.update(high=candle.high, low=candle.low, close=candle.close)
        self._pivot_window.append(candle)
        pivots: list[Pivot] = []
        if len(self._pivot_window) == 5:
            rows = tuple(self._pivot_window)
            center = rows[2]
            if all(center.high > row.high for index, row in enumerate(rows) if index != 2):
                pivots.append(Pivot(center.opened_at, rows[-1].completed_at, center.high, "high"))
            if all(center.low < row.low for index, row in enumerate(rows) if index != 2):
                pivots.append(Pivot(center.opened_at, rows[-1].completed_at, center.low, "low"))
        self._breakout_window.append(candle)
        return IncrementalDailyUpdate(
            ema50=ema50,
            ema200=ema200,
            atr14=atr14,
            new_pivots=tuple(pivots),
            prior_20_high=prior_high if breakout_ready else None,
            prior_20_low=prior_low if breakout_ready else None,
        )


def latest_valid_supporting_swing_v2(
    event: SweepEvent,
    daily_candles: Sequence[Candle],
    pivots: Sequence[Pivot],
    confirmation_at: datetime,
) -> Pivot | None:
    """Use the v2 pivot lifetime interval ``(available_at, confirmation_at]``."""

    required_kind = "low" if event.side == Side.LONG else "high"
    candidates = sorted(
        (
            pivot
            for pivot in pivots
            if pivot.kind == required_kind and pivot.available_at <= confirmation_at
        ),
        key=lambda pivot: (pivot.available_at, pivot.at),
        reverse=True,
    )
    for pivot in candidates:
        breached = False
        for candle in daily_candles:
            completed_at = candle.completed_at
            if not (pivot.available_at < completed_at <= confirmation_at):
                continue
            if event.side == Side.LONG and candle.close < pivot.price:
                breached = True
                break
            if event.side == Side.SHORT and candle.close > pivot.price:
                breached = True
                break
        if not breached:
            return pivot
    return None


def confirm_sweep_v2(
    event: SweepEvent,
    h1: Sequence[Candle],
    daily: Sequence[Candle],
    context: Context,
    *,
    attributed_level_inactive_at: Mapping[str, datetime | None],
    sealed_h1_inventory: Sequence[datetime],
    supporting_swings: Sequence[Pivot] = (),
) -> Confirmation:
    """V1 confirmation mechanics with the authorised v2 supporting interval."""

    if set(attributed_level_inactive_at) != set(event.level_keys):
        return Confirmation("CANCELLED_DATA_QUALITY", context.as_of)
    available_h1: dict[datetime, list[Candle]] = {}
    for candle in completed_candles(h1, context):
        if candle.completed_at > event.at:
            available_h1.setdefault(candle.opened_at, []).append(candle)
    following: list[Candle] = []
    missing_h1_at = None
    successor_opens = tuple(
        timestamp for timestamp in sorted(set(sealed_h1_inventory)) if timestamp >= event.at
    )[:3]
    for expected_open in successor_opens:
        expected_completion = expected_open + timedelta(hours=1)
        if expected_completion > context.as_of:
            break
        matches = available_h1.get(expected_open, [])
        if (
            len(matches) != 1
            or matches[0].opened_at != expected_open
            or matches[0].completed_at != expected_completion
        ):
            missing_h1_at = expected_completion
            break
        following.append(matches[0])
    available_daily = list(completed_candles(daily, context))
    daily_after_sweep = [candle for candle in available_daily if candle.completed_at > event.at]
    inactive_times = tuple(attributed_level_inactive_at.values())

    for candle in following:
        if inactive_times and all(
            inactive_at is not None and inactive_at <= candle.completed_at
            for inactive_at in inactive_times
        ):
            return Confirmation("INVALIDATED", max(inactive_times))
        invalidations = [
            daily_candle
            for daily_candle in daily_after_sweep
            if daily_candle.completed_at <= candle.completed_at
            and (
                daily_candle.close < event.provisional_swing
                if event.side == Side.LONG
                else daily_candle.close > event.provisional_swing
            )
        ]
        if invalidations:
            return Confirmation("INVALIDATED", invalidations[0].completed_at)
        confirmed = (
            candle.close > event.confirmation_threshold
            if event.side == Side.LONG
            else candle.close < event.confirmation_threshold
        )
        if confirmed:
            supporting = latest_valid_supporting_swing_v2(
                event,
                available_daily,
                supporting_swings,
                candle.completed_at,
            )
            return Confirmation(
                "CONFIRMED",
                candle.completed_at,
                supporting.price if supporting is not None else event.provisional_swing,
            )
    if missing_h1_at is not None:
        return Confirmation("CANCELLED_DATA_QUALITY", missing_h1_at)
    window_end = following[-1].completed_at if len(following) == 3 else context.as_of
    remaining_invalidations = [
        candle
        for candle in daily_after_sweep
        if candle.completed_at <= window_end
        if (
            candle.close < event.provisional_swing
            if event.side == Side.LONG
            else candle.close > event.provisional_swing
        )
    ]
    if remaining_invalidations:
        return Confirmation("INVALIDATED", remaining_invalidations[0].completed_at)
    if len(following) == 3:
        return Confirmation("EXPIRED", following[-1].completed_at)
    return Confirmation("TRIGGER_PENDING")


@dataclass(frozen=True)
class SealedHorizonIndex:
    daily_opened_at: tuple[datetime, ...]
    daily_completed_at: tuple[datetime, ...]
    hourly_opened_at: tuple[datetime, ...]

    @classmethod
    def from_projection(cls, projection: AdmissionProjection) -> SealedHorizonIndex:
        daily = tuple(
            event
            for batch in projection.batches
            for event in batch.events
            if event.granularity == "D"
        )
        return cls(
            daily_opened_at=tuple(event.opened_at for event in daily),
            daily_completed_at=tuple(event.completed_at for event in daily),
            hourly_opened_at=projection.admitted_members["H1"],
        )

    def maximum_exit_open(self, entry_at: datetime, sessions: int = 10) -> datetime | None:
        start = bisect_right(self.daily_completed_at, entry_at)
        target = start + sessions - 1
        if target >= len(self.daily_completed_at):
            return None
        completion = self.daily_completed_at[target]
        hourly_index = bisect_left(self.hourly_opened_at, completion)
        if hourly_index >= len(self.hourly_opened_at):
            return None
        return self.hourly_opened_at[hourly_index]

    def reference_maximum_exit_open(
        self, entry_at: datetime, sessions: int = 10
    ) -> datetime | None:
        completions = [completed for completed in self.daily_completed_at if completed > entry_at]
        if len(completions) < sessions:
            return None
        completion = completions[sessions - 1]
        return next((opened for opened in self.hourly_opened_at if opened >= completion), None)


@dataclass(frozen=True)
class V2InstrumentSnapshot:
    instrument_id: int
    inventory: Mapping[str, tuple[datetime, ...]]
    candles: Mapping[tuple[str, datetime], MarketCandle]


def _range_filter(
    ranges: Mapping[str, tuple[datetime, datetime]],
    *,
    granularity_field: str = "granularity",
    timestamp_field: str = "timestamp",
) -> Q:
    query = Q(pk__in=[])
    for granularity, (start, end) in ranges.items():
        if granularity not in GRANULARITY_ORDER or start > end:
            raise DetectorV2EvidenceError("invalid preload range")
        query |= Q(
            **{
                granularity_field: granularity,
                f"{timestamp_field}__gte": start,
                f"{timestamp_field}__lte": end,
            }
        )
    return query


def load_instrument_snapshot(
    *,
    dataset: DatasetVersion,
    contract: HistoricalDataContract,
    instrument: Instrument,
    ranges: Mapping[str, tuple[datetime, datetime]],
) -> V2InstrumentSnapshot:
    """Preload one instrument with exactly three range-size-independent queries."""

    inventory_filter = _range_filter(
        ranges,
        granularity_field="inventory__chunk__granularity",
    )
    inventory_rows = list(
        HistoricalTimestampObservation.objects.filter(
            inventory__chunk__plan__registration__id=contract.discovery_registration_id,
            inventory__chunk__instrument=instrument,
        )
        .filter(inventory_filter)
        .values_list(
            "inventory_id",
            "inventory__chunk__granularity",
            "timestamp",
            "complete",
            "bid_present",
            "ask_present",
            "inventory__accepted_attempt__ingestion_run__status",
            "inventory__chunk__plan__sealed_at",
        )
        .order_by("inventory__chunk__granularity", "timestamp")
    )
    inventory: dict[str, list[datetime]] = {key: [] for key in GRANULARITY_ORDER}
    expected_keys: set[tuple[str, datetime]] = set()
    inventory_ids: dict[tuple[str, datetime], int] = {}
    for (
        inventory_id,
        granularity,
        timestamp,
        is_complete,
        bid_present,
        ask_present,
        discovery_status,
        plan_sealed_at,
    ) in inventory_rows:
        key = (granularity, timestamp)
        if (
            key in expected_keys
            or not (is_complete and bid_present and ask_present)
            or discovery_status != IngestionRun.Status.SUCCEEDED
            or plan_sealed_at is None
        ):
            raise DetectorV2EvidenceError("inventory member is duplicate, incomplete, or one-sided")
        expected_keys.add(key)
        inventory_ids[key] = inventory_id
        inventory[granularity].append(timestamp)

    candle_rows = list(
        MarketCandle.objects.filter(dataset_version=dataset, instrument=instrument)
        .filter(_range_filter(ranges))
        .select_related(
            "ingestion_run__historical_attempt__chunk", "ingestion_run__ingestion_manifest"
        )
        .only(*PRELOAD_ONLY_FIELDS)
        .order_by("granularity", "timestamp")
    )
    candles: dict[tuple[str, datetime], MarketCandle] = {}
    for candle in candle_rows:
        key = (candle.granularity, candle.timestamp)
        try:
            attempt = candle.ingestion_run.historical_attempt
            candle.ingestion_run.ingestion_manifest
            chunk = attempt.chunk
        except AttributeError as error:
            raise DetectorV2EvidenceError("candle lacks governed acquisition lineage") from error
        if key in candles:
            raise DetectorV2EvidenceError("duplicate registered candle")
        if (
            not candle.complete
            or candle.ingestion_run.dataset_version_id != dataset.id
            or candle.ingestion_run.status != IngestionRun.Status.SUCCEEDED
            or attempt.attempt_number != 1
            or chunk.dataset_version_id != dataset.id
            or chunk.instrument_id != instrument.id
            or chunk.granularity != candle.granularity
            or chunk.discovery_inventory_id != inventory_ids.get(key)
        ):
            raise DetectorV2EvidenceError(
                "candle is incomplete or lacks successful registered ingestion"
            )
        candles[key] = candle
    if set(candles) != expected_keys:
        raise DetectorV2EvidenceError("registered candle membership differs from sealed inventory")

    conflict_exists = (
        CandleConflict.objects.filter(
            dataset_version=dataset,
            existing_candle__instrument=instrument,
        )
        .filter(
            Q(existing_candle__granularity="H1", existing_candle__timestamp__range=ranges["H1"])
            | Q(existing_candle__granularity="D", existing_candle__timestamp__range=ranges["D"])
            | Q(existing_candle__granularity="W", existing_candle__timestamp__range=ranges["W"])
        )
        .exists()
    )
    if conflict_exists:
        raise DetectorV2EvidenceError("conflicting candle evidence exists in preload window")
    return V2InstrumentSnapshot(
        instrument_id=instrument.id,
        inventory={key: tuple(value) for key, value in inventory.items()},
        candles=candles,
    )
