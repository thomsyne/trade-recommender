"""Offline exceptional-session readiness; never changes the frozen FX calendar.

An explicit, reviewed attestation is required for the selected provider profile
and interval. Absence of an exception is not proof that trading was available.
This policy is not connected to ingestion, scheduling, signals or Phase4 output.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CalendarAttestation:
    version: str
    source_url: str
    profile: str
    known_at: datetime
    open_intervals: tuple[tuple[datetime, datetime], ...]
    closed_intervals: tuple[tuple[datetime, datetime], ...]


def interval_readiness(start, end, *, profile, as_of, attestation=None):
    """A whole [start,end) interval must be explicitly attested, not inferred.

    Half-open boundaries permit an interval ending exactly at closure or
    beginning exactly at reopening. Partial overlap is an irregular session,
    not a normal full candle. A source learned later cannot authorize a past
    information cutoff. The caller must supply a reviewed immutable attestation.
    """
    if any(value.tzinfo is None for value in (start, end, as_of)) or start >= end:
        raise ValueError("calendar_requires_aware_increasing_interval")
    if (
        attestation is None
        or attestation.profile != profile
        or not attestation.version
        or not attestation.source_url.startswith("https://")
        or attestation.known_at > as_of
    ):
        return "unavailable"
    for closed_start, closed_end in attestation.closed_intervals:
        if closed_start < end and start < closed_end:
            if closed_start <= start and end <= closed_end:
                return "closed"
            return "irregular"
    if any(a <= start and end <= b for a, b in attestation.open_intervals):
        return "attested_open"
    return "unavailable"
