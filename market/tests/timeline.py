"""The canonical test-evidence timeline.

Every fixture that stores market evidence goes through this module, so that one
contract is stated once instead of being re-derived (and re-broken) per test:

* **Aligned intervals.** Candle starts sit on the New York session grid for
  their granularity: H1 on the hour, H4 on the 01/05/09/13/17/21 grid, D at the
  17:00 close from Sunday to Thursday, W at the Friday close. Succession follows
  the trading calendar, so a Thursday daily session is followed by Sunday's and
  the weekend is never invented away.
* **Completed before observed.** A provider cannot report a candle whose
  interval has not closed, so every observation instant is at or after the
  completion of the last interval it carries.
* **Coherent runs.** An ingestion run's request window contains exactly the
  intervals it stores, and its ``started_at``, ``finished_at`` and the
  ``observed_at`` of the rows it writes are the simulated instant at which the
  provider was polled. That instant is produced by freezing the application
  clock, because ``auto_now_add`` and ``timezone.now()`` are what the
  application itself records.
* **Nothing in the future.** The timeline refuses to build evidence dated after
  the real clock, which is what the database enforces in production.
* **Decisions follow their evidence.** ``after()`` returns an instant strictly
  after a run finished, so a forecast is only ever generated once the evidence
  it cites exists; evidence that must arrive later (the hourly candles a paper
  trade is resolved against) is ingested at a later simulated instant that is
  still in the past.

These are the same invariants migration 0029 enforces in PostgreSQL. The
timeline exists to satisfy them honestly, never to work around them: if a
scenario cannot be expressed here, the scenario is not one the production
system could have produced.

Fresh tests use the replacement ``0027_gate8i_empty_bootstrap`` through normal
Django migration execution. It installs the exact registration validator only
when the application tables are empty; it never fabricates accepted acquisition
evidence. Populated histories still use the published acceptance checks.
Historical tests use disposable databases via ``HistoricalDatabaseMixin``;
never fake 0027, repair SQL, or roll the shared current-state database backward.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest import mock

from django.apps import apps
from django.utils import timezone
from django.utils.timezone import now as _django_now

from market.quality import (
    NEW_YORK,
    SESSION_CLOSE,
    _market_is_open,
    live_interval_is_aligned,
    registered_successor,
)
from market.services import live_candle_completion, store_ingestion

#: Margin kept between the newest fixture evidence and the real clock.
CLOCK_MARGIN = timedelta(minutes=5)
#: Delay between an interval closing and the provider being polled for it.
POLL_DELAY = timedelta(minutes=1)


def _now_default_fields():
    """Model fields whose default is a direct reference to ``timezone.now``.

    ``DateTimeField(default=timezone.now)`` captures the function object at
    import time, so patching the module attribute never reaches it. Resolution
    and lifecycle timestamps are stamped that way, which is exactly what a
    historical scenario has to control, so they are rebound explicitly.
    """
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if getattr(field, "default", None) is _django_now:
                yield field


@contextmanager
def application_clock(instant):
    """Run a block with the application's clock frozen at ``instant``.

    Ingestion records ``started_at`` (``auto_now_add``), ``finished_at`` and
    every ``observed_at`` from ``timezone.now()``; adjudication stamps
    ``resolved_at`` and lifecycle events from field defaults. Freezing both is
    what lets a fixture describe work that happened in the past without
    back-dating rows afterwards, which the append-only triggers rightly forbid.
    """
    if instant > timezone.now():
        raise ValueError("the application clock cannot be moved into the future")
    fields = list(_now_default_fields())
    for field in fields:
        field.default = lambda instant=instant: instant
        # Django resolves a field's default once and caches it on the field
        # instance, so rebinding ``default`` alone is silently ignored after
        # anything has already instantiated that model.
        field.__dict__.pop("_get_default", None)
    try:
        with mock.patch("django.utils.timezone.now", return_value=instant):
            yield instant
    finally:
        for field in fields:
            field.default = _django_now
            field.__dict__.pop("_get_default", None)


def previous_aligned(instant, granularity):
    """The latest ``granularity`` interval start at or before ``instant``."""
    local = instant.astimezone(NEW_YORK)
    if granularity in {"D", "W"}:
        local = datetime.combine(local.date(), SESSION_CLOSE, NEW_YORK)
        if local.astimezone(UTC) > instant:
            local -= timedelta(days=1)
        step = timedelta(days=1)
    else:
        local = local.replace(minute=0, second=0, microsecond=0)
        step = timedelta(hours=1)
    while not live_interval_is_aligned(local.astimezone(UTC), granularity):
        local -= step
    return local.astimezone(UTC)


def completed_intervals(count, granularity, *, before):
    """``count`` consecutive interval starts whose intervals closed before ``before``.

    Oldest first. Succession uses the trading calendar, so weekends and the
    Friday close are respected rather than assumed away.
    """
    if count < 1:
        raise ValueError("count must be positive")
    latest = previous_aligned(before, granularity)
    while live_candle_completion(latest, granularity) > before:
        latest = previous_aligned(latest - timedelta(seconds=1), granularity)
    starts = [latest]
    while len(starts) < count:
        earlier = previous_aligned(starts[0] - timedelta(seconds=1), granularity)
        starts.insert(0, earlier)
    return tuple(starts)


def _is_tradeable(start, granularity):
    """Whether an interval starting at ``start`` is inside the trading week.

    ``_market_is_open`` is the repository's own definition of the FX week, and
    it is what the paper-trade resolver walks, so the hours a fixture stores
    have to agree with it or the two will disagree across every weekend.
    """
    if granularity in {"D", "W"}:
        return True
    return _market_is_open(start.astimezone(NEW_YORK))


def following_intervals(count, granularity, *, after):
    """``count`` interval starts that begin at or after ``after``, oldest first.

    Closed hours are skipped: the Friday close is followed by the Sunday open,
    never by a Friday evening that never traded.
    """
    current = previous_aligned(after, granularity)
    if current < after:
        current = registered_successor(current, granularity)
    starts = []
    while len(starts) < count:
        while not _is_tradeable(current, granularity):
            current = registered_successor(current, granularity)
        starts.append(current)
        current = registered_successor(current, granularity)
    return tuple(starts)


class EvidenceTimeline:
    """A coherent, entirely historical sequence of market evidence.

    ``trailing_hours`` reserves room after the daily sessions for the hourly
    evidence a paper trade needs, so that later evidence is still in the past.
    """

    def __init__(self, *, daily=0, trailing_hours=0, now=None):
        self.now = now or timezone.now()
        horizon = self.now - CLOCK_MARGIN - timedelta(hours=trailing_hours)
        if horizon >= self.now:
            raise ValueError("the timeline must end before the real clock")
        self.horizon = horizon
        self._daily = completed_intervals(daily, "D", before=horizon) if daily else ()

    @property
    def sessions(self):
        """The daily session starts this timeline was built with, oldest first."""
        return self._daily

    def session(self, index):
        return self._daily[index]

    def weeks(self, count):
        return completed_intervals(count, "W", before=self.horizon)

    def hours_after(self, instant, count):
        """``count`` hourly interval starts beginning after ``instant``."""
        return following_intervals(count, "H1", after=instant)

    def four_hours_after(self, instant, count):
        return following_intervals(count, "H4", after=instant)

    def poll_instant(self, starts, granularity):
        """The instant a provider could first have reported all of ``starts``."""
        latest_close = max(live_candle_completion(start, granularity) for start in starts)
        return latest_close + POLL_DELAY

    def ingest(
        self,
        source,
        instrument,
        granularity,
        candles,
        *,
        manifest=None,
        at=None,
        requested_from=None,
    ):
        """Store ``candles`` as one coherent, historical ingestion run.

        The request window contains exactly the intervals carried, and the run
        is recorded as having executed at the moment the provider could first
        have served them. ``requested_from`` may widen the window backwards --
        a real poll asks for everything since a known instant, such as the
        moment a decision was taken, and receives the intervals that closed
        inside it. Returns the ``IngestionRun``.
        """
        if not candles:
            raise ValueError("an ingestion run must carry at least one candle")
        starts = [item.timestamp for item in candles]
        for start in starts:
            if not live_interval_is_aligned(start, granularity):
                raise ValueError(
                    f"{start.isoformat()} does not open a {granularity} interval; "
                    "build fixture timestamps through this timeline"
                )
        observed_at = at or self.poll_instant(starts, granularity)
        latest_close = max(live_candle_completion(start, granularity) for start in starts)
        if observed_at < latest_close:
            raise ValueError("evidence cannot be observed before its interval closes")
        if observed_at > timezone.now():
            raise ValueError("the timeline refuses to date evidence in the future")
        window_start = requested_from or min(starts)
        if window_start > min(starts):
            raise ValueError("the request window must contain every interval it stores")
        with application_clock(observed_at):
            return store_ingestion(
                source,
                instrument,
                granularity,
                window_start,
                latest_close,
                candles,
                manifest or {"test": "timeline", "requests": []},
            )

    def at(self, instant):
        """Run a decision (generation, sizing, admission) at ``instant``.

        Policy activation and lifecycle events are stamped from the clock, so a
        decision taken at a historical instant has to be recorded there too --
        otherwise the recommendation predates its own policy and is never
        admitted.
        """
        return application_clock(instant)

    def after(self, run, *, seconds=1):
        """A decision instant strictly after ``run`` finished.

        Recommendation generation refuses evidence whose ingestion finished
        after the decision, so this is how a fixture states "and then we
        decided".
        """
        return run.finished_at + timedelta(seconds=seconds)
