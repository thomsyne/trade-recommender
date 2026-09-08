"""Live-only window policy, using the registered calendar without changing it."""

from datetime import UTC, timedelta

from django.utils import timezone

from market.quality import (
    LIVE_GRANULARITIES,
    REGISTERED_STEPS,
    _market_is_open,
    live_interval_is_aligned,
    registered_successor,
)

LIVE_INTERVALS = {
    g: int(REGISTERED_STEPS[g].total_seconds())
    for g in sorted(LIVE_GRANULARITIES, key=lambda g: REGISTERED_STEPS[g])
}
MAX_COVERAGE_INTERVALS = 100_000


def canonical_live_start(value, granularity):
    """Floor an aware start to the exact registered grid (including NY DST)."""
    if granularity not in LIVE_GRANULARITIES or not timezone.is_aware(value):
        raise ValueError("Live window requires an aware timestamp and H1/H4/D/W")
    candidate = value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    # At most a week plus the repeated DST hour; alignment itself has one owner.
    for _ in range(170):
        if live_interval_is_aligned(candidate, granularity):
            return candidate
        candidate -= timedelta(hours=1)
    raise ValueError("No canonical live interval found")


def complete_live_intervals(start, end, granularity):
    """Bounded expected complete keys in [start,end], omitting registered closures."""
    from market.services import live_candle_completion

    if (
        not timezone.is_aware(end)
        or start >= end
        or canonical_live_start(start, granularity) != start
    ):
        raise ValueError("Invalid canonical live window")
    current = start
    if granularity in {"H1", "H4"}:
        # A window may begin during a registered weekend closure.
        from market.quality import NEW_YORK

        while not _market_is_open(current.astimezone(NEW_YORK)):
            current += REGISTERED_STEPS[granularity]
            # Crossing DST while closed may shift the absolute H4 grid.
            if not live_interval_is_aligned(current, granularity):
                current = canonical_live_start(current, granularity) + REGISTERED_STEPS[granularity]
    expected = []
    while current < end and live_candle_completion(current, granularity) <= end:
        if len(expected) >= MAX_COVERAGE_INTERVALS:
            raise ValueError("Requested coverage exceeds bounded report limit")
        expected.append(current)
        current = registered_successor(current, granularity)
    return tuple(expected)
