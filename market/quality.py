from dataclasses import dataclass
from datetime import UTC, timedelta


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    index: int
    detail: str


def validate_candles(candles, granularity):
    issues = []
    seen = set()
    previous = None
    expected_step = {"H4": timedelta(hours=4), "D": timedelta(days=1)}[granularity]

    for index, candle in enumerate(candles):
        timestamp = candle.timestamp
        if timestamp.tzinfo is None or timestamp.utcoffset() != UTC.utcoffset(timestamp):
            issues.append(ValidationIssue("timestamp_not_utc", index, str(timestamp)))
        if timestamp in seen:
            issues.append(ValidationIssue("duplicate_timestamp", index, str(timestamp)))
        seen.add(timestamp)
        if previous and timestamp <= previous.timestamp:
            issues.append(ValidationIssue("non_monotonic_timestamp", index, str(timestamp)))
        if previous and timestamp - previous.timestamp > expected_step * 2:
            if not _is_fx_weekend_gap(previous.timestamp, timestamp, granularity):
                issues.append(
                    ValidationIssue("unexpected_gap", index, f"{previous.timestamp} to {timestamp}")
                )
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


def _is_fx_weekend_gap(start, end, granularity):
    start_weekday = 3 if granularity == "D" else 4
    return (
        start.weekday() == start_weekday
        and end.weekday() in {6, 0}
        and end - start <= timedelta(days=4)
    )
