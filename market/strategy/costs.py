"""Explicit evidence-bearing cost assumptions, never inferred from midpoint OHLC."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from market.strategy.contracts import iso


@dataclass(frozen=True)
class CostEvidence:
    component: str
    source: str
    version: str
    content_sha256: str
    quote_currency: str
    known_at: datetime
    valid_from: datetime
    valid_through: datetime
    spread: Decimal | None
    commission_per_side: Decimal | None
    slippage_per_side: Decimal | None
    financing_reserve: Decimal | None
    latency_seconds: int | None

    def __post_init__(self):
        for value in (self.known_at, self.valid_from, self.valid_through):
            iso(value)
        if self.valid_from > self.valid_through:
            raise ValueError("cost_period")
        for value in (
            self.spread,
            self.commission_per_side,
            self.slippage_per_side,
            self.financing_reserve,
        ):
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError("invalid_cost")
        if self.latency_seconds is not None and (
            type(self.latency_seconds) is not int or self.latency_seconds < 0
        ):
            raise ValueError("invalid_latency")

    def readiness(self, cutoff, *, component):
        if (
            not self.source
            or not self.version
            or len(self.content_sha256) != 64
            or not self.quote_currency
        ):
            return "cost_provenance_unavailable"
        if self.component != component:
            return "cost_component_mismatch"
        if self.known_at > cutoff or not self.valid_from <= cutoff <= self.valid_through:
            return "cost_not_available_at_cutoff"
        if any(
            v is None
            for v in (
                self.spread,
                self.commission_per_side,
                self.slippage_per_side,
                self.financing_reserve,
                self.latency_seconds,
            )
        ):
            return "incomplete_cost_evidence"
        return None

    @property
    def roundtrip(self):
        return (
            self.spread
            + 2 * (self.commission_per_side + self.slippage_per_side)
            + self.financing_reserve
        )
