"""Pure live-evidence time boundaries, independent of ingestion and persistence.

Source interval time, provider observation time and system recording time are
different clocks. Legacy observations with no recording timestamp retain their
published observed-time semantics; this is not a new backdating permission.
"""

from market.quality import REGISTERED_STEPS, registered_candle_completion


def live_candle_completion(timestamp, granularity):
    """Live intraday intervals use absolute duration; D/W use the NY close.

    Preserve the established live contract. Registered legacy historical H1
    remains wall-clock based and must use registered_candle_completion instead.
    """
    if granularity in {"M15", "H1", "H4"}:
        return timestamp + REGISTERED_STEPS[granularity]
    return registered_candle_completion(timestamp, granularity)


def first_known_at(observed_at, recorded_at=None):
    """Earliest knowledge instant, including system recording when available."""
    return max(observed_at, recorded_at) if recorded_at is not None else observed_at


def observation_available_at(interval_end, observed_at, recorded_at=None):
    """Earliest completed-and-known instant; equality with cutoff is eligible."""
    return max(interval_end, first_known_at(observed_at, recorded_at))
