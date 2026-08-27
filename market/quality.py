from dataclasses import dataclass
from datetime import UTC, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    index: int
    detail: str


def validate_candles(candles, granularity, *, require_registered_alignment=False):
    issues = []
    seen = set()
    previous = None
    expected_step = {
        "W": timedelta(weeks=1),
        "H1": timedelta(hours=1),
        "H4": timedelta(hours=4),
        "D": timedelta(days=1),
    }[granularity]

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
        start_local = start.astimezone(ZoneInfo("America/New_York"))
        end_local = end.astimezone(ZoneInfo("America/New_York"))
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
    start_local = start.astimezone(ZoneInfo("America/New_York"))
    end_local = end.astimezone(ZoneInfo("America/New_York"))
    local_delta = end_local.replace(tzinfo=None) - start_local.replace(tzinfo=None)
    return local_delta == expected_step


def _has_registered_alignment(timestamp, granularity):
    local = timestamp.astimezone(ZoneInfo("America/New_York"))
    if local.time() != time(17):
        return False
    return granularity == "D" or local.weekday() == 4
