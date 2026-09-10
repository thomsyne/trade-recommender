"""Shared bounded, read-only operational input and preview contract."""

from datetime import UTC, datetime

from django.core.management.base import CommandError

from market.models import Instrument, MarketStateDefinition
from market.state.canonical import identity_digest
from market.state.compute import (
    DESCRIPTOR_DEFINITION,
    DESCRIPTOR_KEY,
    DESCRIPTOR_VERSION,
    LOOKBACKS,
    build_market_state,
)

MAX_BATCH = 8


def cutoff_value(value):
    try:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or not 2000 <= parsed.year <= 2100:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        raise CommandError("invalid_cutoff") from None


def scope_value(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= len(LOOKBACKS):
        raise CommandError("invalid_granularities")
    if any(not isinstance(g, str) or g not in LOOKBACKS for g in values) or len(set(values)) != len(
        values
    ):
        raise CommandError("invalid_granularities")
    return sorted(values)


def selections(values):
    if not 1 <= len(values) <= MAX_BATCH:
        raise CommandError("batch_limit_exceeded")
    result = []
    for value in values:
        if not isinstance(value, str) or len(value) > 64 or value.count("@") != 1:
            raise CommandError("invalid_selection")
        code, at = value.split("@")
        if code not in Instrument.Code.values:
            raise CommandError("invalid_instrument")
        result.append((code, cutoff_value(at)))
    if len(set(result)) != len(result):
        raise CommandError("duplicate_selection")
    return sorted(result)


def preview(instrument, cutoff, scope):
    definition = MarketStateDefinition(
        key=DESCRIPTOR_KEY,
        version=DESCRIPTOR_VERSION,
        definition=DESCRIPTOR_DEFINITION,
        definition_sha256=identity_digest(DESCRIPTOR_DEFINITION),
    )
    return build_market_state(instrument, definition, cutoff, scope)
