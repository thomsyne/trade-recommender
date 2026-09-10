"""Immutable scalar boundaries; no persistence, scheduling or promotion."""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, localcontext

from market.state.canonical import canonical_json, format_decimal, identity_digest
from market.state.features import Bar, contiguous

PHASE4_DIGEST = "9213b548d3e6c6656805d2cf230c242926f08a42112373d7518d685384b9f7d3"


def iso(value):
    if value.tzinfo is None:
        raise ValueError("naive_time")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def decimal(value):
    if not isinstance(value, (str, Decimal, int)) or isinstance(value, bool):
        raise ValueError("non_decimal")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("nonfinite")
    return result


def encoded(value, *, exact=False):
    """Quantize outputs, but preserve decimal input evidence losslessly for replay."""

    def convert(item):
        if isinstance(item, Decimal):
            with localcontext() as ctx:
                ctx.prec = 34
                return format(item, "f") if exact else format_decimal(item)
        if isinstance(item, datetime):
            return iso(item)
        if isinstance(item, dict):
            return {k: convert(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [convert(v) for v in item]
        return item

    return canonical_json(convert(asdict(value)))


@dataclass(frozen=True)
class Unavailable:
    strategy: str
    reason: str
    schema: str = field(default="phase5/unavailable-v1", init=False)


@dataclass(frozen=True)
class Component:
    name: str
    raw: Decimal | None
    capped: Decimal | None
    exclusion: str | None


@dataclass(frozen=True)
class ContinuousForecast:
    strategy: str
    value: Decimal | None
    buffered: Decimal | None
    components: tuple[Component, ...]
    reason: str | None = None
    schema: str = field(default="phase5/continuous-v1", init=False)

    def __post_init__(self):
        if any(
            v is not None and (not v.is_finite() or abs(v) > 20)
            for v in (self.value, self.buffered)
        ):
            raise ValueError("forecast_bounds")
        if (self.value is None) != (self.reason is not None) or (self.value is None) != (
            self.buffered is None
        ):
            raise ValueError("forecast_missingness")


@dataclass(frozen=True)
class SetupCandidate:
    strategy: str
    direction: int
    available_at: datetime
    signal_start: datetime
    granularity: str
    reference: Decimal
    stop: Decimal
    target: Decimal
    entry_at: datetime
    expires_at: datetime
    exit_at: datetime
    evidence: tuple[str, ...]
    schema: str = field(default="phase5/setup-v1", init=False)

    def __post_init__(self):
        if (
            type(self.direction) is not int
            or self.direction not in (-1, 1)
            or self.granularity not in ("M15", "H1")
        ):
            raise ValueError("setup_direction_or_interval")
        for time in (
            self.available_at,
            self.signal_start,
            self.entry_at,
            self.expires_at,
            self.exit_at,
        ):
            iso(time)
        if not (
            self.signal_start < self.available_at <= self.entry_at <= self.expires_at < self.exit_at
        ):
            raise ValueError("setup_chronology")
        if not all(v.is_finite() and v > 0 for v in (self.reference, self.stop, self.target)):
            raise ValueError("setup_price")
        if (
            self.direction * (self.reference - self.stop) <= 0
            or self.direction * (self.target - self.reference) <= 0
        ):
            raise ValueError("setup_geometry")


@dataclass(frozen=True)
class ExecutionIntent:
    candidate_sha256: str
    simulator_sha256: str
    cost_sha256: str
    calendar_sha256: str
    schema: str = field(default="phase5/intent-v1", init=False)


@dataclass(frozen=True)
class ExecutionResult:
    intent_sha256: str
    entered_at: datetime
    exited_at: datetime
    entry: Decimal
    exit: Decimal
    gross_quote: Decimal
    costs_quote: Decimal
    net_quote: Decimal
    net_account: Decimal
    outcome_evidence: tuple[str, ...]
    reason: str
    schema: str = field(default="phase5/execution-v1", init=False)


@dataclass(frozen=True)
class RiskOverlay:
    strategy: str
    multiplier: Decimal | None
    reason: str
    evidence: tuple[str, ...] = ()
    schema: str = field(default="phase5/risk-v1", init=False)

    def __post_init__(self):
        if self.multiplier is not None and (
            not self.multiplier.is_finite() or not 0 <= self.multiplier <= 1
        ):
            raise ValueError("risk_cannot_increase_baseline")


@dataclass(frozen=True)
class SnapshotInput:
    """Loaded only from a verified immutable snapshot, with exact cited bars."""

    snapshot_id: int
    envelope_json: str
    bars: tuple[Bar, ...]

    def __post_init__(self):
        envelope = json.loads(self.envelope_json)
        if canonical_json(envelope) != self.envelope_json:
            raise ValueError("noncanonical_envelope")
        if envelope["definition_sha256"] != PHASE4_DIGEST:
            raise ValueError("unsupported_phase4")
        payload = envelope["output_payload"]
        if payload["schema"] != "market-state/descriptor-v0" or payload["definition"] != [
            "market-state-descriptor",
            "0.12.0",
        ]:
            raise ValueError("unsupported_phase4")
        for key, digest in (
            ("input_manifest", "input_manifest_sha256"),
            ("evidence_manifest", "evidence_sha256"),
            ("output_payload", "output_sha256"),
        ):
            if identity_digest(envelope[key]) != envelope[digest]:
                raise ValueError("snapshot_hash_mismatch")
        from market.state.snapshots import snapshot_idempotency_key

        if (
            snapshot_idempotency_key(
                PHASE4_DIGEST,
                payload["instrument"],
                self.cutoff,
                payload["requested_granularities"],
                envelope["input_manifest_sha256"],
                envelope["evidence_sha256"],
            )
            != envelope["idempotency_key"]
        ):
            raise ValueError("snapshot_identity_mismatch")
        cited = {
            (r["granularity"], r["timestamp"], r["revision"], r["content_sha256"])
            for r in envelope["input_manifest"]
        }
        actual = {
            (b.granularity, iso(b.timestamp), b.revision, b.content_sha256) for b in self.bars
        }
        if cited != actual or len(actual) != len(self.bars):
            raise ValueError("uncited_or_missing_observation")
        for b in self.bars:
            if b.end is None or b.observed_at is None or b.available_at > self.cutoff:
                raise ValueError("unavailable_observation")
            if (
                not all(v.is_finite() and v > 0 for v in (b.open, b.high, b.low, b.close))
                or not b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
            ):
                raise ValueError("invalid_ohlc")

    @property
    def cutoff(self):
        return datetime.fromisoformat(
            json.loads(self.envelope_json)["output_payload"]["information_cutoff"]
        )

    @property
    def payload(self):
        return json.loads(self.envelope_json)["output_payload"]

    def series(self, granularity, *, before=None):
        values = tuple(
            sorted(
                (
                    b
                    for b in self.bars
                    if b.granularity == granularity and (before is None or b.available_at <= before)
                ),
                key=lambda b: b.timestamp,
            )
        )
        if not contiguous(values):
            return ()
        return values
