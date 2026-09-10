"""Causal input-manifest construction.

The input manifest is the ordered set of frozen candle identities that were
genuinely available at an information cutoff. Every downstream feature reads
only these candles, which is what makes a snapshot causal and reproducible:

* a candle is eligible only when it is ``complete``, its registered interval has
  ended (``interval_end <= cutoff``) and its recorded availability is at or
  before the cutoff (``observed_at <= cutoff``);
* for each candle identity the manifest records the *latest revision known by
  the cutoff* — a provider revision observed after the cutoff is excluded, so a
  later revision creates a later snapshot without rewriting an earlier one;
* entries are ordered deterministically by ``(granularity, timestamp)`` and
  carry the frozen ``content_sha256``, so the manifest hash is independent of
  query or insertion order.
"""

from datetime import UTC
from typing import NamedTuple

from django.utils import timezone

from market.models import CandleObservation
from market.quality import REGISTERED_STEPS
from market.state.canonical import identity_digest

SEARCH_INTERVAL_MULTIPLIER = 3
SEARCH_PADDING_INTERVALS = 14


class FrozenObservation(NamedTuple):
    """Scalar evidence only: no lazy ORM relationships or mutable model state."""

    granularity: str
    timestamp: object
    interval_end: object
    observed_at: object
    revision: int
    content_sha256: str
    bid_open: object
    bid_high: object
    bid_low: object
    bid_close: object
    ask_open: object
    ask_high: object
    ask_low: object
    ask_close: object

    @classmethod
    def from_row(cls, row):
        return cls(*(getattr(row, field) for field in cls._fields))


def _iso(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def eligible_observations(instrument, granularity, information_cutoff, *, lookback=None):
    """Return the causally-eligible observation per candle, oldest first.

    One row per candle identity: the highest revision whose ``observed_at`` is at
    or before the cutoff. ``lookback`` (when given) keeps only the most recent N.
    """
    if not timezone.is_aware(information_cutoff):
        raise ValueError("information_cutoff must be timezone-aware")
    eligible = CandleObservation.objects.filter(
        instrument=instrument,
        granularity=granularity,
        timestamp__lt=information_cutoff,
        complete=True,
        interval_end__lte=information_cutoff,
        observed_at__lte=information_cutoff,
    ).exclude(content_sha256="")
    if lookback is not None:
        # A finite elapsed-time search horizon is distinct from a row LIMIT.
        # Three nominal intervals per wanted bar accommodates FX weekends/DST;
        # absent older data remains unavailable rather than scanning all history.
        eligible = eligible.filter(
            timestamp__gte=information_cutoff
            - REGISTERED_STEPS[granularity]
            * (SEARCH_INTERVAL_MULTIPLIER * lookback + SEARCH_PADDING_INTERVALS)
        )
    # DISTINCT ON (timestamp) over eligible revisions ordered by (timestamp desc,
    # revision desc) yields exactly one row per candle — its highest *eligible*
    # revision — newest first. A ``lookback`` then LIMITs the distinct candles in
    # SQL (not just in Python), so the database scan itself is bounded and uses
    # the (instrument, granularity, -timestamp, -revision) index (design §14).
    distinct = eligible.order_by("-timestamp", "-revision").distinct("timestamp")
    if lookback is not None:
        distinct = distinct[:lookback]
    rows = list(distinct)
    rows.sort(key=lambda row: row.timestamp)
    return rows


def build_input_manifest(instrument, granularities, information_cutoff, *, lookbacks=None):
    """Return ``(manifest, manifest_sha256)`` for the eligible candles at cutoff.

    ``manifest`` is a deterministic ordered list of
    ``{granularity, timestamp, revision, content_sha256}`` entries.
    """
    lookbacks = lookbacks or {}
    rows = {
        granularity: eligible_observations(
            instrument, granularity, information_cutoff, lookback=lookbacks.get(granularity)
        )
        for granularity in sorted(granularities)
    }
    return manifest_from_rows(rows)


def manifest_from_rows(rows):
    """Serialize already selected evidence; never perform a second database read."""
    entries = []
    for granularity in sorted(rows):
        for row in rows[granularity]:
            entries.append(
                {
                    "granularity": granularity,
                    "timestamp": _iso(row.timestamp),
                    "revision": row.revision,
                    "content_sha256": row.content_sha256,
                }
            )
    return entries, identity_digest(entries)
