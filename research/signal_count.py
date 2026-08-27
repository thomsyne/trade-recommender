"""Return-blind Phase 2A signal-count boundaries.

This module deliberately does not import the strategy or execution code.  It is the
only market-data projection intended for S0/S1 entry-open use.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from market.models import (
    Candle,
    DatasetVersion,
    IngestionRun,
    Instrument,
    dataset_manifest_sha256,
)
from market.quality import expected_candle_timestamps, registered_candle_completion
from market.services import RequiredCandleRange, assert_dataset_window_usable
from research.models import (
    EntryEligibilityEvaluation,
    JobRun,
    SetupEvent,
    StrategyVersion,
)

SIGNAL_COUNT_IDENTITY = "failed-break-signal-count-v1"
S0_JOB_NAME = "failed-break-signal-count-s0"
PHASE1_MANIFEST_SHA256 = "f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882"
FROZEN_INSTRUMENTS = frozenset({"EUR_USD", "GBP_USD", "EUR_GBP", "USD_CAD", "USD_JPY", "AUD_USD"})
S1_GRANULARITIES = frozenset({"W", "D", "H1"})
DEVELOPMENT_START = datetime(2010, 1, 1, tzinfo=ZoneInfo("America/New_York"))
DEVELOPMENT_END = datetime(2019, 1, 1, tzinfo=ZoneInfo("America/New_York"))
WARMUP_CANDLES = {"W": 1, "D": 220, "H1": 14}
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
    {
        "dataset_id",
        "strategy_version_id",
        "s0_report_sha256",
        "as_of",
        "bounded",
        "maximum_setups",
        "entry_projections_read",
    }
)
S1_EVALUATION_FIELDS = (
    "setup_id",
    "setup__instrument_id",
    "decision",
    "entry_timestamp",
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

    dataset = DatasetVersion.objects.get(pk=dataset_id)
    assert_dataset_window_usable(
        dataset,
        instrument_id,
        (
            RequiredCandleRange(
                "H1",
                theoretical_entry_timestamp,
                theoretical_entry_timestamp + timedelta(hours=1),
            ),
        ),
        as_of,
    )

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
    report_sha256: str = field(init=False)

    def __post_init__(self):
        if self.identity != SIGNAL_COUNT_IDENTITY or self.stage not in {"S0", "S1"}:
            raise ValueError("unregistered signal-count identity or stage")
        expected_counts = S0_COUNT_FIELDS if self.stage == "S0" else S1_COUNT_FIELDS
        expected_coverage = S0_COVERAGE_FIELDS if self.stage == "S0" else S1_COVERAGE_FIELDS
        if set(self.counts) != expected_counts or set(self.coverage) != expected_coverage:
            raise ReturnBlindViolation("signal-count output does not match the registered schema")
        if any(type(value) is not int or value < 0 for value in self.counts.values()):
            raise ReturnBlindViolation("signal-count values must be non-negative integers")
        object.__setattr__(
            self,
            "report_sha256",
            stable_hash(
                {
                    "identity": self.identity,
                    "stage": self.stage,
                    "counts": self.counts,
                    "coverage": self.coverage,
                    "configuration_sha256": self.configuration_sha256,
                }
            ),
        )
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


def _declared_required_ranges(dataset):
    raw_ranges = dataset.manifest.get("required_ranges")
    if not isinstance(raw_ranges, list) or not raw_ranges:
        raise ReturnBlindViolation("dataset manifest must declare bounded required_ranges")
    grouped = {}
    for item in raw_ranges:
        try:
            instrument = str(item["instrument"])
            granularity = str(item["granularity"])
            start = parse_datetime(item["start"])
            end = parse_datetime(item["end"])
        except (KeyError, TypeError, ValueError) as error:
            raise ReturnBlindViolation("invalid dataset required_ranges declaration") from error
        if (
            start is None
            or end is None
            or not timezone.is_aware(start)
            or not timezone.is_aware(end)
        ):
            raise ReturnBlindViolation("dataset required_ranges timestamps must be timezone-aware")
        grouped.setdefault(instrument, []).append(RequiredCandleRange(granularity, start, end))
    return grouped


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_s1_contract(dataset, strategy, as_of, s0_job_id):
    if dataset.manifest_sha256 != dataset_manifest_sha256(dataset.manifest):
        raise ReturnBlindViolation("dataset manifest SHA-256 does not match canonical JSON")
    if (
        strategy.content_hash != PHASE1_MANIFEST_SHA256
        or set(strategy.pair_metadata.get("instruments", ())) != FROZEN_INSTRUMENTS
    ):
        raise ReturnBlindViolation("S1 requires the approved frozen six-instrument strategy")
    manifest = dataset.manifest
    if (
        manifest.get("strategy_manifest_sha256") != PHASE1_MANIFEST_SHA256
        or set(manifest.get("instruments", ())) != FROZEN_INSTRUMENTS
        or manifest.get("partition")
        != {"name": "development", "start_year": 2010, "end_year": 2018}
    ):
        raise ReturnBlindViolation("dataset manifest does not match the frozen S1 universe")
    grouped = _declared_required_ranges(dataset)
    if set(grouped) != FROZEN_INSTRUMENTS:
        raise ReturnBlindViolation("S1 required_ranges must contain all six instruments")
    development_start = DEVELOPMENT_START.astimezone(DEVELOPMENT_START.tzinfo)
    development_end = DEVELOPMENT_END.astimezone(DEVELOPMENT_END.tzinfo)
    for instrument, ranges in grouped.items():
        if (
            len(ranges) != len(S1_GRANULARITIES)
            or {required.granularity for required in ranges} != S1_GRANULARITIES
        ):
            raise ReturnBlindViolation(
                f"{instrument} must declare exactly one W, D and H1 S1 range"
            )
        for required in ranges:
            try:
                expected = expected_candle_timestamps(
                    required.start, required.end, required.granularity
                )
            except ValueError as error:
                raise ReturnBlindViolation(str(error)) from error
            warmup = sum(
                registered_candle_completion(timestamp, required.granularity) <= development_start
                for timestamp in expected
            )
            if warmup < WARMUP_CANDLES[required.granularity] or required.end < development_end:
                raise ReturnBlindViolation(
                    f"{instrument} {required.granularity} range lacks development or warm-up coverage"
                )
            if required.end > as_of:
                raise ReturnBlindViolation("S1 as_of precedes required development coverage")

    s0_run = JobRun.objects.filter(
        pk=s0_job_id,
        job_name=S0_JOB_NAME,
        strategy_version=strategy,
        dataset_version=dataset,
        status=JobRun.Status.SUCCEEDED,
    ).first()
    s0_report_sha256 = s0_run.evidence.get("report_sha256") if s0_run else None
    if not _is_sha256(s0_report_sha256):
        raise ReturnBlindViolation("S1 requires a matching immutable S0 audit report")
    return grouped, s0_report_sha256


def _s1_evaluation_queryset(setup_ids):
    return (
        EntryEligibilityEvaluation.objects.filter(setup_id__in=setup_ids)
        .order_by("setup__sweep_h1_timestamp", "setup_id", "book_identity")
        .values(*S1_EVALUATION_FIELDS)
    )


def run_s1(
    *, dataset_id: int, strategy_version_id: int, s0_job_id: int, maximum_setups: int, as_of
) -> SignalCountOutput:
    """Count bounded persisted eligibility facts without importing post-entry execution code."""
    if maximum_setups < 1:
        raise ValueError("maximum_setups must be positive")
    if not timezone.is_aware(as_of):
        raise ValueError("as_of must be timezone-aware")
    dataset = DatasetVersion.objects.get(pk=dataset_id)
    strategy = StrategyVersion.objects.get(pk=strategy_version_id)
    ranges_by_instrument, s0_report_sha256 = _validate_s1_contract(
        dataset, strategy, as_of, s0_job_id
    )
    instruments_by_code = {
        instrument.code: instrument
        for instrument in Instrument.objects.filter(code__in=ranges_by_instrument)
    }
    if set(instruments_by_code) != set(ranges_by_instrument):
        raise ReturnBlindViolation("dataset required_ranges references an unknown instrument")
    for code, ranges in ranges_by_instrument.items():
        assert_dataset_window_usable(dataset, instruments_by_code[code], ranges, as_of)
    ranges_by_instrument_id = {
        instruments_by_code[code].pk: ranges for code, ranges in ranges_by_instrument.items()
    }
    setup_ids = list(
        SetupEvent.objects.filter(dataset_version=dataset, strategy_version=strategy)
        .order_by("sweep_h1_timestamp", "pk")
        .values_list("pk", flat=True)[:maximum_setups]
    )
    evaluations = list(_s1_evaluation_queryset(setup_ids))
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
        counts[decision_fields[evaluation["decision"]]] += 1
        if evaluation["decision"] == EntryEligibilityEvaluation.Decision.ENTRY_PENDING:
            projection_key = (
                evaluation["setup__instrument_id"],
                evaluation["entry_timestamp"],
            )
            entry_ranges = ranges_by_instrument_id.get(evaluation["setup__instrument_id"], ())
            if not any(
                required.granularity == "H1"
                and required.start <= evaluation["entry_timestamp"]
                and evaluation["entry_timestamp"] + timedelta(hours=1) <= required.end
                for required in entry_ranges
            ):
                raise ReturnBlindViolation("entry projection is outside the frozen S1 range")
            if projection_key not in projected_entries:
                read_entry_projection(
                    dataset_id=dataset.pk,
                    instrument_id=evaluation["setup__instrument_id"],
                    theoretical_entry_timestamp=evaluation["entry_timestamp"],
                    as_of=evaluation["entry_timestamp"] + timedelta(hours=1),
                )
                projected_entries.add(projection_key)
                projections_read += 1
    configuration = {
        "dataset_id": dataset.pk,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "strategy_version_id": strategy.pk,
        "strategy_content_hash": strategy.content_hash,
        "s0_job_id": s0_job_id,
        "s0_report_sha256": s0_report_sha256,
        "maximum_setups": maximum_setups,
        "as_of": as_of,
    }
    output = SignalCountOutput(
        SIGNAL_COUNT_IDENTITY,
        "S1",
        counts,
        {
            "dataset_id": dataset.pk,
            "strategy_version_id": strategy.pk,
            "s0_report_sha256": s0_report_sha256,
            "as_of": as_of.isoformat(),
            "bounded": True,
            "maximum_setups": maximum_setups,
            "entry_projections_read": projections_read,
        },
        stable_hash(configuration),
    )
    values = {
        "job_name": "failed-break-signal-count-s1",
        "strategy_version": strategy,
        "dataset_version": dataset,
        "config_hash": output.configuration_sha256,
        "as_of": as_of,
        "status": JobRun.Status.SUCCEEDED,
        "evidence": {
            "report_sha256": output.report_sha256,
            "counts": output.counts,
            "coverage": output.coverage,
        },
    }
    job, created = JobRun.objects.get_or_create(
        idempotency_key=f"s1:{strategy.pk}:{dataset.pk}:{output.configuration_sha256}",
        defaults=values,
    )
    if not created and any(getattr(job, name) != value for name, value in values.items()):
        raise ValueError("S1 run key resolved to different immutable content")
    return output
