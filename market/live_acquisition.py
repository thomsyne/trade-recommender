"""Live-only window policy, using the registered calendar without changing it."""

from datetime import UTC, timedelta

from django.utils import timezone

from market.availability import live_candle_completion
from market.quality import (
    LIVE_GRANULARITIES,
    REGISTERED_STEPS,
    SCHEDULED_LIVE_GRANULARITIES,
    _market_is_open,
    live_interval_is_aligned,
    registered_successor,
)

#: Interval seconds for the granularities that carry a canonical ingestion
#: schedule. Pinned to SCHEDULED_LIVE_GRANULARITIES (H1/H4/D/W) so the Phase 2
#: schedule inventory, seeding, freshness defaults and the ``ingest_oanda`` CLI
#: are byte-identical after M15 is added to the ledger. M15 is intentionally
#: absent here — it has no production schedule.
LIVE_INTERVALS = {
    g: int(REGISTERED_STEPS[g].total_seconds())
    for g in sorted(SCHEDULED_LIVE_GRANULARITIES, key=lambda g: REGISTERED_STEPS[g])
}
#: Interval seconds for every granularity the live ledger supports, including
#: M15. Used only by the ingest/calculation contracts (provider request
#: validation, dry-run tooling) — never by scheduling.
SUPPORTED_LIVE_INTERVALS = {
    g: int(REGISTERED_STEPS[g].total_seconds())
    for g in sorted(LIVE_GRANULARITIES, key=lambda g: REGISTERED_STEPS[g])
}
MAX_COVERAGE_INTERVALS = 100_000


def canonical_live_start(value, granularity):
    """Floor an aware start to the exact registered grid (including NY DST)."""
    if granularity not in LIVE_GRANULARITIES or not timezone.is_aware(value):
        raise ValueError("Live window requires an aware timestamp and a supported granularity")
    candidate = value.astimezone(UTC).replace(second=0, microsecond=0)
    if granularity == "M15":
        # The quarter-hour grid is identical in UTC and NY wall clock (whole-hour
        # offsets), so flooring UTC minutes to a multiple of 15 always lands on an
        # aligned M15 start without stepping.
        candidate -= timedelta(minutes=candidate.minute % 15)
        return candidate
    candidate = candidate.replace(minute=0)
    # At most a week plus the repeated DST hour; alignment itself has one owner.
    for _ in range(170):
        if live_interval_is_aligned(candidate, granularity):
            return candidate
        candidate -= timedelta(hours=1)
    raise ValueError("No canonical live interval found")


def complete_live_intervals(start, end, granularity):
    """Bounded expected complete keys in [start,end], omitting registered closures."""
    if (
        not timezone.is_aware(end)
        or start >= end
        or canonical_live_start(start, granularity) != start
    ):
        raise ValueError("Invalid canonical live window")
    current = start
    if granularity in {"M15", "H1", "H4"}:
        # A window may begin during a registered weekend closure.
        from market.quality import NEW_YORK

        while not _market_is_open(current.astimezone(NEW_YORK)):
            current += REGISTERED_STEPS[granularity]
            # Crossing DST while closed may shift the absolute intraday grid.
            if not live_interval_is_aligned(current, granularity):
                current = canonical_live_start(current, granularity) + REGISTERED_STEPS[granularity]
    expected = []
    while current < end and live_candle_completion(current, granularity) <= end:
        if len(expected) >= MAX_COVERAGE_INTERVALS:
            raise ValueError("Requested coverage exceeds bounded report limit")
        expected.append(current)
        current = registered_successor(current, granularity)
    return tuple(expected)
