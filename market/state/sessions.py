"""Versioned session definitions and UTC conversion for ORB.

London ORB opens 08:00 Europe/London; New York FX ORB opens 08:00
America/New_York; both use the first 15-minute (M15) candle. Boundaries convert
to UTC via IANA rules, so daylight saving is handled by the wall clock. Weekend
session dates are skipped (design §8).
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

SESSION_V = "session-v1"
ORB_MINUTES = 15

SESSIONS = {
    "london": {"timezone": "Europe/London", "open": time(8, 0)},
    "new_york": {"timezone": "America/New_York", "open": time(8, 0)},
}


def session_open_utc(session_date, session_name):
    """Return (utc_open, local_open, tzinfo) for a session date."""
    config = SESSIONS[session_name]
    tz = ZoneInfo(config["timezone"])
    local_open = datetime.combine(session_date, config["open"], tz)
    return local_open.astimezone(UTC), local_open, tz


def most_recent_completed_orb_open(information_cutoff, session_name):
    """The latest session whose opening M15 candle has completed by the cutoff.

    Returns (utc_open, local_open, tzinfo) or ``None`` if none in the last week.
    Weekend session dates are skipped."""
    local_cutoff = information_cutoff.astimezone(ZoneInfo(SESSIONS[session_name]["timezone"]))
    date = local_cutoff.date()
    for _ in range(8):
        utc_open, local_open, tz = session_open_utc(date, session_name)
        close = utc_open + timedelta(minutes=ORB_MINUTES)
        if local_open.weekday() < 5 and close <= information_cutoff:
            return utc_open, local_open, tz
        date -= timedelta(days=1)
    return None
