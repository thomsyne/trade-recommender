"""Durable market-state calculation task (one instrument per call).

Deterministic and idempotent: recomputing the same (definition, instrument,
cutoff, manifest) resolves to the existing snapshot. Bounded to a single
instrument so one failure cannot corrupt or block the others, and it spends no
model or provider budget and registers no schedule.
"""

from datetime import UTC, datetime

from django.utils import timezone

from market.models import Instrument
from market.state.compute import compute_market_state, ensure_descriptor_definition

DEFAULT_GRANULARITIES = ("M15", "H1", "H4", "D", "W")


def _cutoff(value):
    if value is None:
        return timezone.now()
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    return parsed.astimezone(UTC)


def run_compute_market_state(parameters):
    instrument = Instrument.objects.get(code=parameters["instrument"])
    cutoff = _cutoff(parameters.get("cutoff"))
    granularities = tuple(parameters.get("granularities") or DEFAULT_GRANULARITIES)
    definition = ensure_descriptor_definition()
    snapshot, _created = compute_market_state(instrument, definition, cutoff, granularities)
    return snapshot
