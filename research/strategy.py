"""Pure point-in-time functions for the frozen failed-break strategy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Context:
    as_of: datetime
    strategy_version: str
    dataset_version: str


@dataclass(frozen=True)
class Candle:
    opened_at: datetime
    completed_at: datetime
    bid_open: Decimal
    bid_high: Decimal
    bid_low: Decimal
    bid_close: Decimal
    ask_open: Decimal
    ask_high: Decimal
    ask_low: Decimal
    ask_close: Decimal
    complete: bool = True

    @property
    def open(self):
        return (self.bid_open + self.ask_open) / 2

    @property
    def high(self):
        return (self.bid_high + self.ask_high) / 2

    @property
    def low(self):
        return (self.bid_low + self.ask_low) / 2

    @property
    def close(self):
        return (self.bid_close + self.ask_close) / 2


@dataclass(frozen=True)
class Point:
    at: datetime
    value: Decimal


@dataclass(frozen=True)
class Pivot:
    at: datetime
    available_at: datetime
    price: Decimal
    kind: str


class Bias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"


class Role(StrEnum):
    SUPPORT = "support"
    RESISTANCE = "resistance"


class Lifecycle(StrEnum):
    ACTIVE = "active"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    SUPERSEDED_BY_FLIP = "superseded_by_flip"


FAMILY_PRIORITY = {
    "PREVIOUS_WEEKLY_EXTREME": 0,
    "CONFIRMED_DAILY_SWING": 1,
    "TWENTY_SESSION_BREAKOUT_FLIP": 2,
}


@dataclass(frozen=True)
class LevelSpec:
    key: str
    family: str
    role: Role
    central_price: Decimal
    zone_lower: Decimal
    zone_upper: Decimal
    atr_at_activation: Decimal
    activated_at: datetime
    source_at: datetime
    expires_at: datetime | None = None
    expires_after_sessions: int | None = None


@dataclass(frozen=True)
class LevelState:
    state: Lifecycle
    effective_at: datetime | None = None
    flipped: LevelSpec | None = None


@dataclass(frozen=True)
class SweepEvent:
    at: datetime
    side: Side
    level_keys: tuple[str, ...]
    confirmation_threshold: Decimal
    sweep_extreme: Decimal
    frozen_bias: Bias
    provisional_swing: Decimal


@dataclass(frozen=True)
class Confirmation:
    state: str
    at: datetime | None = None
    supporting_swing: Decimal | None = None


@dataclass(frozen=True)
class EntryOpen:
    timestamp: datetime
    bid_open: Decimal
    ask_open: Decimal


@dataclass(frozen=True)
class EntryResult:
    decision: str
    reason: str
    entry: Decimal | None = None
    stop: Decimal | None = None
    target: Decimal | None = None
    reward_risk: Decimal | None = None
    target_key: str | None = None
    risk_per_unit_quote: Decimal | None = None
    conversion_rate_to_cad: Decimal | None = None
    conversion_effective_at: datetime | None = None
    conversion_identity: str = ""
    risk_per_unit_cad: Decimal | None = None


def completed_candles(candles: Iterable[Candle], context: Context) -> tuple[Candle, ...]:
    return tuple(
        sorted(
            (c for c in candles if c.complete and c.completed_at <= context.as_of),
            key=lambda c: c.opened_at,
        )
    )


def ema(candles: Iterable[Candle], period: int, context: Context) -> tuple[Point, ...]:
    data = completed_candles(candles, context)
    if period < 1 or len(data) < period:
        return ()
    value = sum((c.close for c in data[:period]), Decimal()) / period
    points = [Point(data[period - 1].completed_at, value)]
    multiplier = Decimal(2) / (period + 1)
    for candle in data[period:]:
        value = value + multiplier * (candle.close - value)
        points.append(Point(candle.completed_at, value))
    return tuple(points)


def ema50(candles: Iterable[Candle], context: Context) -> tuple[Point, ...]:
    return ema(candles, 50, context)


def ema200(candles: Iterable[Candle], context: Context) -> tuple[Point, ...]:
    return ema(candles, 200, context)


def atr14(candles: Iterable[Candle], context: Context) -> tuple[Point, ...]:
    data = completed_candles(candles, context)
    if len(data) < 14:
        return ()
    ranges: list[Decimal] = []
    for index, candle in enumerate(data):
        previous_close = data[index - 1].close if index else candle.close
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    value = sum(ranges[:14], Decimal()) / 14
    points = [Point(data[13].completed_at, value)]
    for candle, true_range in zip(data[14:], ranges[14:], strict=True):
        value = (value * 13 + true_range) / 14
        points.append(Point(candle.completed_at, value))
    return tuple(points)


def daily_pivots(candles: Iterable[Candle], context: Context) -> tuple[Pivot, ...]:
    data = completed_candles(candles, context)
    pivots: list[Pivot] = []
    for index in range(2, len(data) - 2):
        center = data[index]
        peers = data[index - 2 : index] + data[index + 1 : index + 3]
        available_at = data[index + 2].completed_at
        if all(center.high > peer.high for peer in peers):
            pivots.append(Pivot(center.opened_at, available_at, center.high, "high"))
        if all(center.low < peer.low for peer in peers):
            pivots.append(Pivot(center.opened_at, available_at, center.low, "low"))
    return tuple(pivots)


def market_structure(
    pivots: Iterable[Pivot], latest_daily_close: Decimal, context: Context
) -> Bias:
    visible = [pivot for pivot in pivots if pivot.available_at <= context.as_of]
    highs = [pivot for pivot in visible if pivot.kind == "high"]
    lows = [pivot for pivot in visible if pivot.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return Bias.NEUTRAL
    if (
        highs[-1].price > highs[-2].price
        and lows[-1].price > lows[-2].price
        and latest_daily_close > lows[-1].price
    ):
        return Bias.BULLISH
    if (
        highs[-1].price < highs[-2].price
        and lows[-1].price < lows[-2].price
        and latest_daily_close < highs[-1].price
    ):
        return Bias.BEARISH
    return Bias.NEUTRAL


def daily_bias(candles: Iterable[Candle], pivots: Iterable[Pivot], context: Context) -> Bias:
    data = completed_candles(candles, context)
    fast = ema50(data, context)
    slow = ema200(data, context)
    if not data or len(fast) < 21 or not slow:
        return Bias.NEUTRAL
    structure = market_structure(pivots, data[-1].close, context)
    if (
        structure == Bias.BULLISH
        and fast[-1].value > slow[-1].value
        and fast[-1].value > fast[-21].value
    ):
        return Bias.BULLISH
    if (
        structure == Bias.BEARISH
        and fast[-1].value < slow[-1].value
        and fast[-1].value < fast[-21].value
    ):
        return Bias.BEARISH
    return Bias.NEUTRAL


def supporting_swing(pivots: Iterable[Pivot], bias: Bias, context: Context) -> Pivot | None:
    kind = "low" if bias == Bias.BULLISH else "high" if bias == Bias.BEARISH else None
    candidates = [
        pivot for pivot in pivots if pivot.kind == kind and pivot.available_at <= context.as_of
    ]
    return max(candidates, key=lambda pivot: pivot.available_at, default=None)


def make_level(
    key: str,
    family: str,
    role: Role,
    price: Decimal,
    atr: Decimal,
    activated_at,
    source_at,
    precision: Decimal,
    context: Context,
    *,
    expires_at=None,
    expires_after_sessions=None,
) -> LevelSpec:
    if activated_at > context.as_of or atr <= 0 or precision <= 0:
        raise ValueError("level is unavailable or has invalid ATR/precision")
    half_width = atr * Decimal("0.15") / 2
    return LevelSpec(
        key=key,
        family=family,
        role=role,
        central_price=price,
        zone_lower=(price - half_width).quantize(precision, rounding=ROUND_FLOOR),
        zone_upper=(price + half_width).quantize(precision, rounding=ROUND_CEILING),
        atr_at_activation=atr,
        activated_at=activated_at,
        source_at=source_at,
        expires_at=expires_at,
        expires_after_sessions=expires_after_sessions,
    )


def previous_weekly_levels(
    weeks: Iterable[Candle], atr: Decimal, precision: Decimal, context: Context, *, expires_at
) -> tuple[LevelSpec, ...]:
    done = completed_candles(weeks, context)
    if not done:
        return ()
    week = done[-1]
    return (
        make_level(
            f"weekly-low:{week.opened_at.isoformat()}",
            "PREVIOUS_WEEKLY_EXTREME",
            Role.SUPPORT,
            week.low,
            atr,
            week.completed_at,
            week.opened_at,
            precision,
            context,
            expires_at=expires_at,
        ),
        make_level(
            f"weekly-high:{week.opened_at.isoformat()}",
            "PREVIOUS_WEEKLY_EXTREME",
            Role.RESISTANCE,
            week.high,
            atr,
            week.completed_at,
            week.opened_at,
            precision,
            context,
            expires_at=expires_at,
        ),
    )


def confirmed_swing_levels(
    pivots: Iterable[Pivot],
    atr_by_time: Mapping[datetime, Decimal],
    precision: Decimal,
    context: Context,
) -> tuple[LevelSpec, ...]:
    return tuple(
        make_level(
            f"daily-swing:{pivot.kind}:{pivot.at.isoformat()}",
            "CONFIRMED_DAILY_SWING",
            Role.RESISTANCE if pivot.kind == "high" else Role.SUPPORT,
            pivot.price,
            atr_by_time[pivot.available_at],
            pivot.available_at,
            pivot.at,
            precision,
            context,
        )
        for pivot in pivots
        if pivot.available_at <= context.as_of and pivot.available_at in atr_by_time
    )


def breakout_flip_levels(
    daily: Iterable[Candle],
    atr_by_time: Mapping[datetime, Decimal],
    precision: Decimal,
    context: Context,
) -> tuple[LevelSpec, ...]:
    done = completed_candles(daily, context)
    levels: list[LevelSpec] = []
    for index in range(20, len(done)):
        candle = done[index]
        prior = done[index - 20 : index]
        prior_high = max(item.high for item in prior)
        prior_low = min(item.low for item in prior)
        atr = atr_by_time.get(candle.completed_at)
        if atr is None:
            continue
        if candle.close > prior_high:
            levels.append(
                make_level(
                    f"breakout-high:{candle.opened_at.isoformat()}",
                    "TWENTY_SESSION_BREAKOUT_FLIP",
                    Role.SUPPORT,
                    prior_high,
                    atr,
                    candle.completed_at,
                    candle.opened_at,
                    precision,
                    context,
                    expires_after_sessions=20,
                )
            )
        if candle.close < prior_low:
            levels.append(
                make_level(
                    f"breakout-low:{candle.opened_at.isoformat()}",
                    "TWENTY_SESSION_BREAKOUT_FLIP",
                    Role.RESISTANCE,
                    prior_low,
                    atr,
                    candle.completed_at,
                    candle.opened_at,
                    precision,
                    context,
                    expires_after_sessions=20,
                )
            )
    return tuple(levels)


def evaluate_level(
    level: LevelSpec,
    daily: Iterable[Candle],
    context: Context,
    *,
    superseded_at=None,
) -> LevelState:
    if superseded_at is not None and superseded_at <= context.as_of:
        return LevelState(Lifecycle.SUPERSEDED, superseded_at)
    done = [
        candle
        for candle in completed_candles(daily, context)
        if candle.completed_at >= level.activated_at
    ]
    for index, candle in enumerate(done):
        if level.expires_at is not None and level.expires_at <= candle.completed_at:
            return LevelState(Lifecycle.EXPIRED, level.expires_at)
        if level.expires_after_sessions is not None and index >= level.expires_after_sessions:
            return LevelState(Lifecycle.EXPIRED, candle.completed_at)
        can_flip = level.family in {"PREVIOUS_WEEKLY_EXTREME", "CONFIRMED_DAILY_SWING"}
        crossed_central = (
            candle.close < level.central_price
            if level.role == Role.SUPPORT
            else candle.close > level.central_price
        )
        if can_flip and crossed_central:
            return LevelState(Lifecycle.SUPERSEDED_BY_FLIP, candle.completed_at)
        invalidated = (
            candle.close < level.zone_lower
            if level.role == Role.SUPPORT
            else candle.close > level.zone_upper
        )
        if invalidated:
            return LevelState(Lifecycle.INVALIDATED, candle.completed_at)
    if level.expires_at is not None and level.expires_at <= context.as_of:
        return LevelState(Lifecycle.EXPIRED, level.expires_at)
    return LevelState(Lifecycle.ACTIVE)


def flip_level(
    source: LevelSpec,
    activating_candle: Candle,
    atr: Decimal,
    precision: Decimal,
    context: Context,
) -> LevelSpec:
    if not activating_candle.complete or activating_candle.completed_at > context.as_of:
        raise ValueError("flip activation candle is unavailable")
    crossed = (
        activating_candle.close < source.central_price
        if source.role == Role.SUPPORT
        else activating_candle.close > source.central_price
    )
    if not crossed:
        raise ValueError("daily close did not cross the source central price")
    activated_at = activating_candle.completed_at
    return make_level(
        f"{source.key}:flip:{activated_at.isoformat()}",
        source.family,
        Role.RESISTANCE if source.role == Role.SUPPORT else Role.SUPPORT,
        source.central_price,
        atr,
        activated_at,
        source.source_at,
        precision,
        context,
        expires_at=source.expires_at,
    )


def nearest_opposing_target(
    price: Decimal,
    side: Side,
    levels: Iterable[LevelSpec],
    context: Context,
    *,
    level_states: Mapping[str, LevelState],
) -> LevelSpec | None:
    levels = tuple(levels)
    if set(level_states) != {level.key for level in levels}:
        raise ValueError("target inventory requires lifecycle state for every level")
    active = [
        level
        for level in levels
        if level_states[level.key].state == Lifecycle.ACTIVE
        and level.activated_at <= context.as_of
        and (level.expires_at is None or level.expires_at > context.as_of)
    ]
    if side == Side.LONG:
        choices = [
            level for level in active if level.role == Role.RESISTANCE and level.zone_lower > price
        ]
        return min(
            choices,
            key=lambda level: (
                level.zone_lower,
                FAMILY_PRIORITY[level.family],
                level.activated_at,
                level.key,
            ),
            default=None,
        )
    choices = [level for level in active if level.role == Role.SUPPORT and level.zone_upper < price]
    return min(
        choices,
        key=lambda level: (
            price - level.zone_upper,
            FAMILY_PRIORITY[level.family],
            level.activated_at,
            level.key,
        ),
        default=None,
    )


def detect_failed_sweep(
    previous_h1: Candle,
    sweep_h1: Candle,
    levels: Iterable[LevelSpec],
    bias: Bias,
    provisional_swing: Decimal,
    context: Context,
) -> SweepEvent | None:
    if (
        not previous_h1.complete
        or previous_h1.completed_at > sweep_h1.opened_at
        or not sweep_h1.complete
        or sweep_h1.completed_at > context.as_of
    ):
        return None
    eligible = [level for level in levels if level.activated_at <= sweep_h1.opened_at]
    if bias == Bias.BULLISH:
        keys = sorted(
            level.key
            for level in eligible
            if level.role == Role.SUPPORT
            and previous_h1.close >= level.zone_lower
            and sweep_h1.low < level.zone_lower
            and sweep_h1.close >= level.zone_lower
        )
        if keys:
            return SweepEvent(
                sweep_h1.completed_at,
                Side.LONG,
                tuple(keys),
                sweep_h1.high,
                sweep_h1.low,
                bias,
                provisional_swing,
            )
    if bias == Bias.BEARISH:
        keys = sorted(
            level.key
            for level in eligible
            if level.role == Role.RESISTANCE
            and previous_h1.close <= level.zone_upper
            and sweep_h1.high > level.zone_upper
            and sweep_h1.close <= level.zone_upper
        )
        if keys:
            return SweepEvent(
                sweep_h1.completed_at,
                Side.SHORT,
                tuple(keys),
                sweep_h1.low,
                sweep_h1.high,
                bias,
                provisional_swing,
            )
    return None


def confirm_sweep(
    event: SweepEvent,
    h1: Iterable[Candle],
    daily: Iterable[Candle],
    context: Context,
    *,
    attributed_level_inactive_at: Mapping[str, datetime | None],
    supporting_swings: Iterable[Pivot] = (),
) -> Confirmation:
    if set(attributed_level_inactive_at) != set(event.level_keys):
        return Confirmation("CANCELLED_DATA_QUALITY", context.as_of)
    following = [
        candle for candle in completed_candles(h1, context) if candle.completed_at > event.at
    ][:3]
    previous_completion = event.at
    for candle in following:
        if not _is_registered_h1_successor(previous_completion, candle):
            return Confirmation("CANCELLED_DATA_QUALITY", candle.opened_at)
        previous_completion = candle.completed_at
    daily_after_sweep = [
        candle for candle in completed_candles(daily, context) if candle.completed_at > event.at
    ]
    inactive_times = tuple(attributed_level_inactive_at.values())

    def latest_valid_support(at: datetime) -> Decimal:
        kind = "low" if event.side == Side.LONG else "high"
        candidates = sorted(
            (
                pivot
                for pivot in supporting_swings
                if pivot.kind == kind and pivot.available_at <= at
            ),
            key=lambda pivot: pivot.available_at,
            reverse=True,
        )
        for pivot in candidates:
            breached = any(
                daily_candle.completed_at <= at
                and daily_candle.completed_at > pivot.available_at
                and (
                    daily_candle.close < pivot.price
                    if event.side == Side.LONG
                    else daily_candle.close > pivot.price
                )
                for daily_candle in daily_after_sweep
            )
            if not breached:
                return pivot.price
        return event.provisional_swing

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
            return Confirmation(
                "CONFIRMED", candle.completed_at, latest_valid_support(candle.completed_at)
            )
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


def _is_registered_h1_successor(previous_completion: datetime, candle: Candle) -> bool:
    if candle.completed_at - candle.opened_at != timedelta(hours=1):
        return False
    if candle.opened_at == previous_completion:
        return True
    previous_local = previous_completion.astimezone(ZoneInfo("America/New_York"))
    opened_local = candle.opened_at.astimezone(ZoneInfo("America/New_York"))
    return (
        previous_local.weekday() == 4
        and previous_local.time() == time(17)
        and opened_local.weekday() == 6
        and opened_local.time() == time(17)
        and candle.opened_at - previous_completion <= timedelta(days=3)
    )


def in_entry_session(timestamp) -> bool:
    for timezone_name in ("Europe/London", "America/New_York"):
        local_time = timestamp.astimezone(ZoneInfo(timezone_name)).time()
        if time(8) <= local_time < time(17):
            return True
    return False


def entry_eligibility(
    event: SweepEvent,
    opening: EntryOpen | None,
    h1_atr: Decimal | None,
    levels: Iterable[LevelSpec],
    context: Context,
    *,
    expected_entry_timestamp: datetime,
    precision: Decimal,
    absolute_spread_ceiling: Decimal,
    level_states: Mapping[str, LevelState],
    cad_conversion_rate: Decimal | None,
    conversion_effective_at: datetime | None,
    conversion_identity: str,
    relative_spread_ceiling: Decimal = Decimal("0.10"),
    data_complete: bool = True,
    market_open: bool = True,
    session_eligible: bool | None = None,
) -> EntryResult:
    if (
        not data_complete
        or h1_atr is None
        or h1_atr <= 0
        or precision <= 0
        or cad_conversion_rate is None
        or cad_conversion_rate <= 0
        or conversion_effective_at is None
        or conversion_effective_at > expected_entry_timestamp
        or conversion_effective_at > context.as_of
        or not conversion_identity
    ):
        return EntryResult("CANCELLED_DATA_QUALITY", "DATA_INCOMPLETE")
    levels = tuple(levels)
    if set(level_states) != {level.key for level in levels}:
        return EntryResult("CANCELLED_DATA_QUALITY", "INCOMPLETE_TARGET_INVENTORY")
    if opening is not None:
        if opening.timestamp != expected_entry_timestamp:
            return EntryResult("CANCELLED_DATA_QUALITY", "NOT_NEXT_H1_OPEN")
        if opening.timestamp > context.as_of:
            return EntryResult("CANCELLED_DATA_QUALITY", "ENTRY_OPEN_AFTER_AS_OF")
        if opening.ask_open < opening.bid_open:
            return EntryResult("CANCELLED_DATA_QUALITY", "NEGATIVE_SPREAD")
    if session_eligible is None:
        session_eligible = in_entry_session(expected_entry_timestamp)
    if session_eligible is False:
        return EntryResult("BLOCKED_SESSION", "OUTSIDE_SESSION")
    if opening is None or not market_open:
        return EntryResult("MISSED_FILL", "NO_DEFENSIBLE_H1_OPEN")
    spread = opening.ask_open - opening.bid_open
    if spread > absolute_spread_ceiling or spread / h1_atr > relative_spread_ceiling:
        return EntryResult("BLOCKED_SPREAD", "SPREAD_CEILING")
    entry = opening.ask_open if event.side == Side.LONG else opening.bid_open
    buffer = max(spread, h1_atr * Decimal("0.10"))
    if event.side == Side.LONG:
        stop = (event.sweep_extreme - buffer).quantize(precision, rounding=ROUND_FLOOR)
        if opening.bid_open <= stop:
            return EntryResult("MISSED_FILL", "OPEN_AT_OR_BEYOND_STOP")
    else:
        stop = (event.sweep_extreme + buffer).quantize(precision, rounding=ROUND_CEILING)
        if opening.ask_open >= stop:
            return EntryResult("MISSED_FILL", "OPEN_AT_OR_BEYOND_STOP")
    target_level = nearest_opposing_target(
        entry, event.side, levels, context, level_states=level_states
    )
    if target_level is None:
        return EntryResult("NO_TARGET", "NO_ACTIVE_OPPOSING_LEVEL")
    target = target_level.zone_lower if event.side == Side.LONG else target_level.zone_upper
    risk = entry - stop if event.side == Side.LONG else stop - entry
    reward = target - entry if event.side == Side.LONG else entry - target
    reward_risk = reward / risk if risk > 0 else Decimal("-Infinity")
    if reward_risk < Decimal("1.5"):
        return EntryResult("INSUFFICIENT_REWARD", "BELOW_1_5R")
    risk_per_unit_quote = risk
    risk_per_unit_cad = risk_per_unit_quote * cad_conversion_rate
    return EntryResult(
        "ENTRY_PENDING",
        "",
        entry,
        stop,
        target,
        reward_risk,
        target_level.key,
        risk_per_unit_quote,
        cad_conversion_rate,
        conversion_effective_at,
        conversion_identity,
        risk_per_unit_cad,
    )
