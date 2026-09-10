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

from django.utils import timezone

from market.models import CandleObservation
from market.state.canonical import identity_digest


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
        complete=True,
        interval_end__lte=information_cutoff,
        observed_at__lte=information_cutoff,
    ).exclude(content_sha256="")
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
    entries = []
    for granularity in sorted(granularities):
        for row in eligible_observations(
            instrument, granularity, information_cutoff, lookback=lookbacks.get(granularity)
        ):
            entries.append(
                {
                    "granularity": granularity,
                    "timestamp": _iso(row.timestamp),
                    "revision": row.revision,
                    "content_sha256": row.content_sha256,
                }
            )
    return entries, identity_digest(entries)
