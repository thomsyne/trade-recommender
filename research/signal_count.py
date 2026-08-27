"""Return-blind Phase 2A signal-count boundaries.

This module deliberately does not import the strategy or execution code.  It is the
only market-data projection intended for S0/S1 entry-open use.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from market.models import Candle, IngestionRun

SIGNAL_COUNT_IDENTITY = "failed-break-signal-count-v1"
ENTRY_FIELDS = frozenset({"timestamp", "bid_open", "ask_open"})
FORBIDDEN_FIELD_PARTS = frozenset(
    {
        "high",
        "low",
        "close",
        "volume",
        "m1",
        "later",
        "exit",
        "pnl",
        "profit",
        "loss",
        "return",
        "outcome",
        "win_rate",
        "payoff",
        "drawdown",
        "excursion",
    }
)


class ReturnBlindViolation(ValueError):
    """Raised before a forbidden price or outcome can be accessed."""


@dataclass(frozen=True, slots=True)
class EntryProjection:
    timestamp: datetime
    bid_open: Decimal
    ask_open: Decimal


def read_entry_projection(
    *, dataset_id: int, instrument_id: int, theoretical_entry_timestamp, as_of, fields=ENTRY_FIELDS
) -> EntryProjection:
    """Project only an admitted, completed H1 entry open from one dataset."""
    requested = frozenset(fields)
    if requested != ENTRY_FIELDS:
        raise ReturnBlindViolation(
            "entry projection must request exactly timestamp, bid_open, ask_open"
        )
    if as_of < theoretical_entry_timestamp + timedelta(hours=1):
        raise ReturnBlindViolation("entry H1 candle has not completed as of the requested time")

    row = (
        Candle.objects.filter(
            dataset_version_id=dataset_id,
            instrument_id=instrument_id,
            granularity="H1",
            timestamp=theoretical_entry_timestamp,
            complete=True,
            ingestion_run__dataset_version_id=dataset_id,
            ingestion_run__status=IngestionRun.Status.SUCCEEDED,
        )
        .values(*sorted(ENTRY_FIELDS))
        .get()
    )
    return EntryProjection(row["timestamp"], row["bid_open"], row["ask_open"])


def enforce_price_cutoff(*, row_timestamp, theoretical_entry_timestamp, granularity="H1") -> None:
    """Fail closed before any non-H1 or post-entry row is considered."""
    if granularity != "H1":
        raise ReturnBlindViolation("signal count permits no non-H1 price data")
    if row_timestamp > theoretical_entry_timestamp:
        raise ReturnBlindViolation("price rows after theoretical entry are forbidden")


def _assert_return_blind(value, path="output") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_").replace(" ", "_")
            if any(part in normalized for part in FORBIDDEN_FIELD_PARTS):
                raise ReturnBlindViolation(f"forbidden signal-count output field: {path}.{key}")
            _assert_return_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_return_blind(child, f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class SignalCountOutput:
    identity: str
    stage: str
    counts: Mapping[str, int]
    coverage: Mapping[str, object]
    configuration_sha256: str

    def __post_init__(self):
        if self.identity != SIGNAL_COUNT_IDENTITY or self.stage not in {"S0", "S1"}:
            raise ValueError("unregistered signal-count identity or stage")
        _assert_return_blind(asdict(self))

    def as_dict(self):
        return asdict(self)


def stable_hash(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def generate_spread_ceilings(
    spreads: Mapping[str, Iterable[Decimal]], pipettes: Mapping[str, Decimal]
) -> dict[str, Decimal]:
    """Return deterministic absolute nearest-rank p99 ceilings from opening spreads."""
    ceilings = {}
    for group, observations in sorted(spreads.items()):
        ordered = sorted(Decimal(value) for value in observations)
        pipette = Decimal(pipettes.get(group, 0))
        if not ordered or ordered[0] < 0 or pipette <= 0:
            raise ValueError(f"{group} requires non-negative spread observations")
        percentile = ordered[math.ceil(Decimal("0.99") * len(ordered)) - 1]
        ceilings[group] = (percentile / pipette).to_integral_value(rounding=ROUND_CEILING) * pipette
    return ceilings
