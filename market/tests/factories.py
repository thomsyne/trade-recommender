from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from market.oanda import CandleData
from market.quality import NEW_YORK, SESSION_CLOSE, live_interval_is_aligned
from market.services import live_candle_completion


def next_daily_session(timestamp):
    """The canonical daily session start that follows ``timestamp``.

    Daily candles open at the 17:00 America/New_York close from Sunday through
    Thursday, so the successor of a Thursday session is Sunday's, not Friday's.
    """
    local = timestamp.astimezone(NEW_YORK) + timedelta(days=1)
    while not live_interval_is_aligned(local.astimezone(UTC), "D"):
        local += timedelta(days=1)
    return local.astimezone(UTC)


def daily_sessions(count, *, before=None):
    """``count`` consecutive daily session starts, oldest first, all completed.

    Fixtures cannot invent daily candles at an arbitrary wall-clock instant:
    migration 0029 refuses an observation whose interval start is not a New York
    session boundary, or whose interval has not closed yet. This walks the real
    session calendar backwards from ``before`` (default: now) so a test gets
    sessions a provider could actually have published.
    """
    before = before or timezone.now()
    local = datetime.combine(before.astimezone(NEW_YORK).date(), SESSION_CLOSE, NEW_YORK)
    while True:
        candidate = local.astimezone(UTC)
        if live_interval_is_aligned(candidate, "D") and (
            live_candle_completion(candidate, "D") <= before
        ):
            break
        local -= timedelta(days=1)
    sessions = [candidate]
    while len(sessions) < count:
        local = sessions[0].astimezone(NEW_YORK) - timedelta(days=1)
        while not live_interval_is_aligned(local.astimezone(UTC), "D"):
            local -= timedelta(days=1)
        sessions.insert(0, local.astimezone(UTC))
    return sessions


def candle(timestamp=None, **changes):
    values = {
        "timestamp": timestamp or datetime(2026, 1, 5, tzinfo=UTC),
        "complete": True,
        "volume": 100,
        "bid_open": Decimal("1.1000"),
        "bid_high": Decimal("1.1020"),
        "bid_low": Decimal("1.0990"),
        "bid_close": Decimal("1.1010"),
        "ask_open": Decimal("1.1002"),
        "ask_high": Decimal("1.1022"),
        "ask_low": Decimal("1.0992"),
        "ask_close": Decimal("1.1012"),
    }
    values.update(changes)
    return CandleData(**values)
