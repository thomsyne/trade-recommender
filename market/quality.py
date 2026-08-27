from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    index: int
    detail: str


NEW_YORK = ZoneInfo("America/New_York")
REGISTERED_STEPS = {
    "W": timedelta(weeks=1),
    "D": timedelta(days=1),
    "H4": timedelta(hours=4),
    "H1": timedelta(hours=1),
}


def final_registered_completion_before(boundary, granularity):
    """Return the last frozen-calendar completion strictly before ``boundary``."""
    if not timezone.is_aware(boundary) or granularity not in {"W", "D", "H1"}:
        raise ValueError("boundary must be aware and granularity must be W, D or H1")
    local_boundary = boundary.astimezone(NEW_YORK)
    if granularity == "H1":
        candidate = local_boundary - timedelta(hours=1)
        while not _market_is_open(candidate - timedelta(hours=1)):
            candidate -= timedelta(hours=1)
        return candidate.astimezone(UTC)
    if granularity == "D":
        candidate = datetime.combine(local_boundary.date(), time(17), NEW_YORK)
        if candidate >= local_boundary:
            candidate -= timedelta(days=1)
        while candidate.weekday() in {4, 5}:
            candidate -= timedelta(days=1)
        return candidate.astimezone(UTC)
    candidate = datetime.combine(local_boundary.date(), time(17), NEW_YORK)
    candidate -= timedelta(days=(candidate.weekday() - 4) % 7)
    if candidate >= local_boundary:
        candidate -= timedelta(weeks=1)
    return candidate.astimezone(UTC)


def registered_candle_completion(timestamp, granularity):
    """Return the registered close of one interval without crossing the FX weekend."""
    local = timestamp.astimezone(NEW_YORK)
    return (local + REGISTERED_STEPS[granularity]).astimezone(UTC)


def registered_successor(timestamp, granularity):
    """Return the next market-active interval start under the frozen FX calendar."""
    local = timestamp.astimezone(NEW_YORK)
    if granularity == "W":
        return (local + timedelta(weeks=1)).astimezone(UTC)
    if granularity == "D":
        days = 3 if local.weekday() == 3 else 1
        return (local + timedelta(days=days)).astimezone(UTC)

    candidate = local + REGISTERED_STEPS[granularity]
    if candidate.weekday() == 4 and candidate.time() == time(17):
        candidate += timedelta(days=2)
    return candidate.astimezone(UTC)


def expected_candle_timestamps(start, end, granularity):
    """Expand one closed-open registered range into every required candle key."""
    if granularity not in REGISTERED_STEPS:
        raise ValueError(f"unsupported candle granularity: {granularity}")
    if not timezone.is_aware(start) or not timezone.is_aware(end) or start >= end:
        raise ValueError("candle range requires aware increasing timestamps")
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    local = start.astimezone(NEW_YORK)
    aligned = local.minute == local.second == local.microsecond == 0
    if granularity == "W":
        aligned = aligned and local.weekday() == 4 and local.time() == time(17)
    elif granularity == "D":
        aligned = aligned and local.weekday() in {6, 0, 1, 2, 3} and local.time() == time(17)
    elif granularity == "H4":
        aligned = aligned and local.hour in {1, 5, 9, 13, 17, 21} and _market_is_open(local)
    else:
        aligned = aligned and _market_is_open(local)
    if not aligned:
        raise ValueError("candle range start is not a registered market interval")

    expected = []
    current = start
    while current < end:
        completion = registered_candle_completion(current, granularity)
        if completion > end:
            raise ValueError("candle range end cuts through a registered interval")
        expected.append(current)
        current = registered_successor(current, granularity)
    if not expected or registered_candle_completion(expected[-1], granularity) != end:
        raise ValueError("candle range end is not the final candle completion")
    return tuple(expected)


def _market_is_open(local):
    return (
        local.weekday() in {0, 1, 2, 3}
        or (local.weekday() == 4 and local.time() < time(17))
        or (local.weekday() == 6 and local.time() >= time(17))
    )


def validate_candles(candles, granularity, *, require_registered_alignment=False):
    issues = []
    seen = set()
    previous = None
    expected_step = REGISTERED_STEPS[granularity]

    for index, candle in enumerate(candles):
        timestamp = candle.timestamp
        if timestamp.tzinfo is None or timestamp.utcoffset() != UTC.utcoffset(timestamp):
            issues.append(ValidationIssue("timestamp_not_utc", index, str(timestamp)))
        if timestamp in seen:
            issues.append(ValidationIssue("duplicate_timestamp", index, str(timestamp)))
        seen.add(timestamp)
        if previous and timestamp <= previous.timestamp:
            issues.append(ValidationIssue("non_monotonic_timestamp", index, str(timestamp)))
        if previous and not _is_expected_successor(
            previous.timestamp,
            timestamp,
            granularity,
            expected_step,
            require_registered_alignment=require_registered_alignment,
        ):
            issues.append(
                ValidationIssue("unexpected_gap", index, f"{previous.timestamp} to {timestamp}")
            )
        if (
            require_registered_alignment
            and granularity in {"D", "W"}
            and not _has_registered_alignment(timestamp, granularity)
        ):
            issues.append(ValidationIssue("alignment_mismatch", index, str(timestamp)))
        if not candle.complete:
            issues.append(ValidationIssue("incomplete_candle", index, str(timestamp)))
        if candle.volume < 0:
            issues.append(ValidationIssue("negative_volume", index, str(timestamp)))
        for side in ("bid", "ask"):
            open_ = getattr(candle, f"{side}_open")
            high = getattr(candle, f"{side}_high")
            low = getattr(candle, f"{side}_low")
            close = getattr(candle, f"{side}_close")
            if low > min(open_, close) or high < max(open_, close) or low > high:
                issues.append(ValidationIssue("impossible_ohlc", index, f"{side} {timestamp}"))
        for component in ("open", "high", "low", "close"):
            if getattr(candle, f"bid_{component}") > getattr(candle, f"ask_{component}"):
                issues.append(ValidationIssue("crossed_bid_ask", index, f"{component} {timestamp}"))
        previous = candle
    return issues


def _is_fx_weekend_gap(start, end, granularity, *, registered=False):
    if granularity == "W":
        return False
    if registered:
        start_local = start.astimezone(NEW_YORK)
        end_local = end.astimezone(NEW_YORK)
        expected_start = {"H1": (4, time(16)), "H4": (4, time(13)), "D": (3, time(17))}
        start_weekday, start_time = expected_start[granularity]
        return (
            start_local.weekday() == start_weekday
            and start_local.time() == start_time
            and end_local.weekday() == 6
            and end_local.time() == time(17)
        )
    start_weekday = 3 if granularity == "D" else 4
    return (
        start.weekday() == start_weekday
        and end.weekday() in {6, 0}
        and end - start <= timedelta(days=4)
    )


def _is_expected_successor(
    start, end, granularity, expected_step, *, require_registered_alignment=False
):
    if end - start == expected_step:
        return True
    if _is_fx_weekend_gap(start, end, granularity, registered=require_registered_alignment):
        return True
    if granularity not in {"D", "W"}:
        return False
    start_local = start.astimezone(NEW_YORK)
    end_local = end.astimezone(NEW_YORK)
    local_delta = end_local.replace(tzinfo=None) - start_local.replace(tzinfo=None)
    return local_delta == expected_step


def _has_registered_alignment(timestamp, granularity):
    local = timestamp.astimezone(NEW_YORK)
    if local.time() != time(17):
        return False
    return granularity == "D" or local.weekday() == 4
