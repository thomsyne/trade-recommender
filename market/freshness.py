"""Live candle freshness that separates the facts the operations page needs.

For every live series this reports, as distinct values: the latest stored
interval start, that candle's completion instant, when it was retrieved, the
next candle the provider is expected to complete, when the collection job
next polls, and a fresh/stale determination that respects the FX weekend,
the 17:00 America/New_York daily close, the Friday weekly close and the
polling interval. Holiday closures are deliberately not modelled: no
calendar is invented, so a stale flag around a market holiday must be read
as unverified rather than as a defect.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from market.models import Candle, Instrument
from market.quality import _market_is_open, registered_successor
from market.services import live_candle_completion
from operations.models import ScheduledJob

NEW_YORK = ZoneInfo("America/New_York")
H4_LOCAL_HOURS = (1, 5, 9, 13, 17, 21)
POLL_GRACE = timedelta(minutes=15)
DEFAULT_POLL_INTERVAL = {
    "H1": timedelta(hours=1),
    "H4": timedelta(hours=4),
    "D": timedelta(days=1),
    "W": timedelta(weeks=1),
}


def latest_expected_completion(now, granularity):
    """Completion instant of the most recent candle the provider must have completed."""
    local = now.astimezone(NEW_YORK)
    if granularity == "W":
        candidate = datetime.combine(local.date(), time(17), NEW_YORK)
        candidate -= timedelta(days=(candidate.weekday() - 4) % 7)
        if candidate > local:
            candidate -= timedelta(weeks=1)
        return candidate.astimezone(UTC)
    if granularity == "D":
        candidate = datetime.combine(local.date(), time(17), NEW_YORK)
        if candidate > local:
            candidate -= timedelta(days=1)
        while candidate.weekday() in {5, 6}:
            candidate -= timedelta(days=1)
        return candidate.astimezone(UTC)
    if granularity == "H4":
        candidate = local.replace(minute=0, second=0, microsecond=0)
        while candidate.hour not in H4_LOCAL_HOURS or not _market_is_open(
            candidate - timedelta(hours=4)
        ):
            candidate -= timedelta(hours=1)
        return candidate.astimezone(UTC)
    candidate = local.replace(minute=0, second=0, microsecond=0)
    while not _market_is_open(candidate - timedelta(hours=1)):
        candidate -= timedelta(hours=1)
    return candidate.astimezone(UTC)


def next_expected_completion(latest_start, granularity):
    successor = registered_successor(latest_start, granularity)
    return successor, live_candle_completion(successor, granularity)


@dataclass(frozen=True)
class SeriesFreshness:
    instrument: Instrument
    granularity: str
    latest_interval_start: datetime | None
    latest_completion: datetime | None
    retrieved_at: datetime | None
    expected_latest_completion: datetime
    next_interval_start: datetime | None
    next_completion: datetime | None
    job: ScheduledJob | None
    next_poll_at: datetime | None
    poll_interval: timedelta
    fresh: bool
    reason: str

    @property
    def state(self):
        if self.latest_interval_start is None:
            return "missing"
        return "fresh" if self.fresh else "stale"

    @property
    def label(self):
        return {"missing": "NO DATA", "fresh": "FRESH", "stale": "STALE"}[self.state]

    @property
    def tone(self):
        return {"missing": "disabled", "fresh": "healthy", "stale": "warning"}[self.state]


def series_freshness(instrument, granularity, *, now=None, job=None):
    now = now or timezone.now()
    if job is None:
        job = ScheduledJob.objects.filter(
            task_name="market.ingest_oanda",
            parameters__instrument=instrument.code,
            parameters__granularity=granularity,
        ).first()
    poll_interval = (
        timedelta(seconds=job.interval_seconds)
        if job is not None and job.interval_seconds
        else DEFAULT_POLL_INTERVAL[granularity]
    )
    latest = (
        Candle.objects.filter(instrument=instrument, granularity=granularity, dataset_version=None)
        .select_related("ingestion_run")
        .order_by("-timestamp")
        .first()
    )
    expected = latest_expected_completion(now, granularity)
    if latest is None:
        return SeriesFreshness(
            instrument,
            granularity,
            None,
            None,
            None,
            expected,
            None,
            None,
            job,
            job.next_run_at if job else None,
            poll_interval,
            False,
            "No live candle stored.",
        )
    completion = live_candle_completion(latest.timestamp, granularity)
    next_start, next_completion = next_expected_completion(latest.timestamp, granularity)
    retrieved_at = latest.observed_at or latest.ingestion_run.finished_at
    if completion >= expected:
        fresh, reason = True, "Latest completed candle is stored."
    elif now <= next_completion + poll_interval + POLL_GRACE:
        fresh, reason = (
            True,
            "A newer candle completed but the collection interval has not elapsed.",
        )
    else:
        fresh, reason = (
            False,
            f"Candle completing {next_completion:%b %d %H:%M} UTC is not stored after one "
            "polling interval plus grace.",
        )
    if job is not None and not job.enabled:
        reason += " Collection job is disabled."
    return SeriesFreshness(
        instrument,
        granularity,
        latest.timestamp,
        completion,
        retrieved_at,
        expected,
        next_start,
        next_completion,
        job,
        job.next_run_at if job else None,
        poll_interval,
        fresh,
        reason,
    )


def all_series_freshness(now=None, granularities=("H1", "H4", "D", "W")):
    now = now or timezone.now()
    jobs = {
        (job.parameters.get("instrument"), job.parameters.get("granularity")): job
        for job in ScheduledJob.objects.filter(task_name="market.ingest_oanda")
    }
    rows = []
    for instrument in Instrument.objects.filter(active=True):
        for granularity in granularities:
            rows.append(
                series_freshness(
                    instrument,
                    granularity,
                    now=now,
                    job=jobs.get((instrument.code, granularity)),
                )
            )
    return rows
