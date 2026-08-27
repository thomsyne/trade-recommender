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

from market.models import Candle, DatasetVersion, IngestionRun
from market.services import assert_dataset_usable
from research.models import EntryEligibilityEvaluation, SetupEvent

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
S0_COUNT_FIELDS = frozenset({"observations"})
S0_COVERAGE_FIELDS = frozenset({"spread_ceilings"})
S1_COUNT_FIELDS = frozenset(
    {
        "physical_setups_processed",
        "eligibility_evaluations_processed",
        "entry_eligible",
        "missed_fill",
        "blocked_session",
        "blocked_spread",
        "no_target",
        "insufficient_reward",
        "cancelled_data_quality",
    }
)
S1_COVERAGE_FIELDS = frozenset(
    {"dataset_id", "bounded", "maximum_setups", "entry_projections_read"}
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
        expected_counts = S0_COUNT_FIELDS if self.stage == "S0" else S1_COUNT_FIELDS
        expected_coverage = S0_COVERAGE_FIELDS if self.stage == "S0" else S1_COVERAGE_FIELDS
        if set(self.counts) != expected_counts or set(self.coverage) != expected_coverage:
            raise ReturnBlindViolation("signal-count output does not match the registered schema")
        if any(type(value) is not int or value < 0 for value in self.counts.values()):
            raise ReturnBlindViolation("signal-count values must be non-negative integers")
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


def run_s1(*, dataset_id: int, maximum_setups: int) -> SignalCountOutput:
    """Count bounded persisted eligibility facts without importing post-entry execution code."""
    if maximum_setups < 1:
        raise ValueError("maximum_setups must be positive")
    dataset = DatasetVersion.objects.get(pk=dataset_id)
    assert_dataset_usable(dataset)
    setup_ids = list(
        SetupEvent.objects.filter(dataset_version=dataset)
        .order_by("sweep_h1_timestamp", "pk")
        .values_list("pk", flat=True)[:maximum_setups]
    )
    evaluations = list(
        EntryEligibilityEvaluation.objects.filter(setup_id__in=setup_ids)
        .select_related("setup")
        .order_by("setup__sweep_h1_timestamp", "setup_id", "book_identity")
    )
    counts = {field: 0 for field in S1_COUNT_FIELDS}
    counts["physical_setups_processed"] = len(setup_ids)
    projections_read = 0
    projected_entries = set()
    decision_fields = {
        EntryEligibilityEvaluation.Decision.ENTRY_PENDING: "entry_eligible",
        EntryEligibilityEvaluation.Decision.MISSED_FILL: "missed_fill",
        EntryEligibilityEvaluation.Decision.BLOCKED_SESSION: "blocked_session",
        EntryEligibilityEvaluation.Decision.BLOCKED_SPREAD: "blocked_spread",
        EntryEligibilityEvaluation.Decision.NO_TARGET: "no_target",
        EntryEligibilityEvaluation.Decision.INSUFFICIENT_REWARD: "insufficient_reward",
        EntryEligibilityEvaluation.Decision.CANCELLED_DATA_QUALITY: "cancelled_data_quality",
    }
    for evaluation in evaluations:
        counts["eligibility_evaluations_processed"] += 1
        counts[decision_fields[evaluation.decision]] += 1
        if evaluation.decision == EntryEligibilityEvaluation.Decision.ENTRY_PENDING:
            projection_key = (evaluation.setup.instrument_id, evaluation.entry_timestamp)
            if projection_key not in projected_entries:
                read_entry_projection(
                    dataset_id=dataset.pk,
                    instrument_id=evaluation.setup.instrument_id,
                    theoretical_entry_timestamp=evaluation.entry_timestamp,
                    as_of=evaluation.entry_timestamp + timedelta(hours=1),
                )
                projected_entries.add(projection_key)
                projections_read += 1
    configuration = {"dataset_id": dataset.pk, "maximum_setups": maximum_setups}
    return SignalCountOutput(
        SIGNAL_COUNT_IDENTITY,
        "S1",
        counts,
        {
            "dataset_id": dataset.pk,
            "bounded": True,
            "maximum_setups": maximum_setups,
            "entry_projections_read": projections_read,
        },
        stable_hash(configuration),
    )
