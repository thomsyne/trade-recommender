"""Idempotent persistence boundary for deterministic failed-break outputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal

from django.db import transaction

from market.models import Candle as MarketCandle
from market.quality import (
    expected_candle_timestamps,
    registered_candle_completion,
    registered_successor,
)
from market.services import (
    DatasetQualityError,
    RequiredCandleRange,
    assert_dataset_window_usable,
    candle_completion,
    provider_observed_contract,
    sealed_inventory_membership,
)
from research.models import (
    AnalysisRun,
    EntryEligibilityEvaluation,
    Level,
    SetupEvent,
    SetupLevelAttribution,
    SetupTransition,
)
from research.provider_observed import inventory_timestamps
from research.strategy import Confirmation, EntryOpen, EntryResult, LevelSpec, SweepEvent

COMBINED_BOOK = "failed-break-any-level-deduplicated-v1"
FAMILY_BOOKS = {
    Level.Family.WEEKLY: "failed-break-weekly-extreme-v1",
    Level.Family.DAILY_SWING: "failed-break-daily-swing-v1",
    Level.Family.BREAKOUT: "failed-break-breakout-flip-v1",
}
DB_DECIMAL_QUANTUM = Decimal("0.0000000001")


def _stored_decimal(value):
    return value.quantize(DB_DECIMAL_QUANTUM) if value is not None else None


def evidence_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _derive_history(
    required_ranges,
    minimum_candles,
    decision_at,
    *,
    exact_completion=None,
    required_timestamps=None,
    decision_boundaries=None,
    dataset_version=None,
    instrument=None,
):
    required_ranges = tuple(required_ranges)
    exact_completion = exact_completion or {}
    required_timestamps = required_timestamps or {}
    decision_boundaries = decision_boundaries or {}
    contract = provider_observed_contract(dataset_version) if dataset_version is not None else None
    supplied = {required.granularity for required in required_ranges}
    missing = set(minimum_candles) - supplied
    if missing:
        raise DatasetQualityError(
            f"operation is missing required dataset ranges: {', '.join(sorted(missing))}"
        )
    derived = []
    insufficient = []
    for granularity, minimum in minimum_candles.items():
        boundary = decision_boundaries.get(granularity, decision_at)
        if contract is not None:
            # Provider-observed v2: eligible history is the chronological
            # sealed inventory; whether history reaches the decision boundary
            # is an inventory-membership question, never a calendar one.
            timestamps = sorted(
                {
                    timestamp
                    for required in required_ranges
                    if required.granularity == granularity
                    for timestamp in sealed_inventory_membership(
                        contract,
                        getattr(instrument, "pk", instrument),
                        granularity,
                        required.start,
                        required.end,
                    )
                }
            )
        else:
            timestamps = sorted(
                {
                    timestamp
                    for required in required_ranges
                    if required.granularity == granularity
                    for timestamp in expected_candle_timestamps(
                        required.start, required.end, granularity
                    )
                }
            )
        eligible = [
            timestamp
            for timestamp in timestamps
            if candle_completion(timestamp, granularity, contract) <= boundary
        ]
        if len(eligible) < minimum:
            insufficient.append(granularity)
            continue
        latest = eligible[-1]
        if contract is None and (
            registered_candle_completion(registered_successor(latest, granularity), granularity)
            <= boundary
        ):
            raise DatasetQualityError(
                f"{granularity} history does not reach the operation decision boundary"
            )
        if (
            granularity in exact_completion
            and candle_completion(latest, granularity, contract) != exact_completion[granularity]
        ):
            raise DatasetQualityError(
                f"{granularity} history does not terminate at the evidence timestamp"
            )
        selected = eligible[-minimum:]
        required_timestamp = required_timestamps.get(granularity)
        if required_timestamp is not None:
            if required_timestamp not in eligible:
                raise DatasetQualityError(
                    f"{granularity} history does not contain the required evidence candle"
                )
            selected = eligible[min(eligible.index(required_timestamp), len(eligible) - minimum) :]
        derived.append(
            RequiredCandleRange(
                granularity,
                selected[0],
                candle_completion(selected[-1], granularity, contract),
            )
        )
    if insufficient:
        raise DatasetQualityError(
            f"operation lacks indicator warm-up history: {', '.join(sorted(insufficient))}"
        )
    return tuple(derived)


@transaction.atomic
def persist_level(
    *, instrument, strategy_version, dataset_version, spec: LevelSpec, required_ranges, as_of
) -> Level:
    minimum_history = (
        {"W": 1, "D": 14}
        if spec.family == Level.Family.WEEKLY
        else {"D": 21}
        if spec.family == Level.Family.BREAKOUT
        else {"D": 14}
    )
    source_granularity = "W" if spec.family == Level.Family.WEEKLY else "D"
    activation_granularity = "D" if ":flip:" in spec.key else source_granularity
    required_ranges = _derive_history(
        required_ranges,
        minimum_history,
        spec.activated_at,
        exact_completion={activation_granularity: spec.activated_at},
        required_timestamps={source_granularity: spec.source_at},
        dataset_version=dataset_version,
        instrument=instrument,
    )
    assert_dataset_window_usable(dataset_version, instrument, required_ranges, as_of)
    values = {
        "family": spec.family,
        "role": spec.role.value,
        "instrument": instrument,
        "strategy_version": strategy_version,
        "dataset_version": dataset_version,
        "source_timeframe": "W" if spec.family == Level.Family.WEEKLY else "D",
        "source_candle_timestamp": spec.source_at,
        "central_price": _stored_decimal(spec.central_price),
        "zone_lower": _stored_decimal(spec.zone_lower),
        "zone_upper": _stored_decimal(spec.zone_upper),
        "atr_at_activation": _stored_decimal(spec.atr_at_activation),
        "activated_at": spec.activated_at,
        "expires_at": spec.expires_at,
    }
    stable_key = evidence_hash(
        {
            "instrument": instrument.code,
            "strategy": strategy_version.content_hash,
            "dataset": dataset_version.manifest_sha256,
            "level": asdict(spec),
        }
    )
    stored, created = Level.objects.get_or_create(stable_key=stable_key, defaults=values)
    mismatches = [field for field, value in values.items() if getattr(stored, field) != value]
    if not created and mismatches:
        raise ValueError(
            f"stable level key resolved to different immutable content: {', '.join(mismatches)}"
        )
    return stored


@transaction.atomic
def persist_analysis(
    *,
    instrument,
    strategy_version,
    dataset_version,
    completed_h1_timestamp,
    result,
    evidence,
    required_ranges,
    as_of,
) -> AnalysisRun:
    try:
        required_ranges = _derive_history(
            required_ranges,
            {"W": 1, "D": 220, "H1": 14},
            completed_h1_timestamp,
            exact_completion={"H1": completed_h1_timestamp},
            dataset_version=dataset_version,
            instrument=instrument,
        )
        assert_dataset_window_usable(dataset_version, instrument, required_ranges, as_of)
    except DatasetQualityError:
        if result != AnalysisRun.Result.DATA_INCOMPLETE:
            raise
    record, _ = AnalysisRun.objects.get_or_create(
        instrument=instrument,
        detector_version=strategy_version.detector_version,
        dataset_version=dataset_version,
        completed_h1_timestamp=completed_h1_timestamp,
        defaults={
            "strategy_version": strategy_version,
            "result": result,
            "evidence_hash": evidence_hash(evidence),
        },
    )
    if record.result != result or record.evidence_hash != evidence_hash(evidence):
        raise ValueError("analysis key resolved to different immutable content")
    return record


@transaction.atomic
def persist_setup(
    *,
    instrument,
    strategy_version,
    dataset_version,
    event: SweepEvent,
    level_attributions,
    evidence,
    required_ranges,
    as_of,
) -> SetupEvent:
    required_ranges = _derive_history(
        required_ranges,
        {"W": 1, "D": 220, "H1": 14},
        event.at,
        exact_completion={"H1": event.at},
        dataset_version=dataset_version,
        instrument=instrument,
    )
    assert_dataset_window_usable(dataset_version, instrument, required_ranges, as_of)
    if set(event.level_keys) != set(level_attributions):
        raise ValueError("setup attributions do not match deterministic sweep keys")
    expected_role = Level.Role.SUPPORT if event.side.value == "long" else Level.Role.RESISTANCE
    for key, level in level_attributions.items():
        if key != level.stable_key:
            raise ValueError("attribution key does not identify its level")
        if (
            level.instrument_id != instrument.pk
            or level.strategy_version_id != strategy_version.pk
            or level.dataset_version_id != dataset_version.pk
            or level.role != expected_role
        ):
            raise ValueError("attributed level lineage or direction does not match setup")
    lookup = {
        "instrument": instrument,
        "direction": event.side.value,
        "sweep_h1_timestamp": event.at,
        "detector_version": strategy_version.detector_version,
        "dataset_version": dataset_version,
    }
    defaults = {
        "strategy_version": strategy_version,
        "sweep_evidence": evidence["sweep"],
        "bias_evidence": evidence["bias"],
        "provisional_swing_evidence": evidence["provisional_swing"],
        "threshold_evidence": evidence["threshold"],
        "attribution_keys": sorted(event.level_keys),
        "evidence_hash": evidence_hash(evidence),
    }
    setup, created = SetupEvent.objects.get_or_create(
        **lookup,
        defaults=defaults,
    )
    setup = SetupEvent.objects.select_for_update().get(pk=setup.pk)
    if not created:
        if any(
            getattr(setup, field) != value
            for field, value in defaults.items()
            if field != "attribution_keys"
        ):
            raise ValueError("physical setup key resolved to different immutable content")
        if setup.attribution_keys != sorted(event.level_keys):
            raise ValueError("physical setup attribution set is immutable")
    existing_keys = set(setup.setuplevelattribution_set.values_list("level__stable_key", flat=True))
    if created:
        SetupLevelAttribution.objects.bulk_create(
            SetupLevelAttribution(setup=setup, level=level) for level in level_attributions.values()
        )
    elif existing_keys != set(event.level_keys):
        raise ValueError("physical setup attribution set is immutable")
    return setup


def books_for_setup(setup: SetupEvent) -> tuple[str, ...]:
    families = setup.setuplevelattribution_set.values_list("level__family", flat=True).distinct()
    return tuple(sorted({COMBINED_BOOK, *(FAMILY_BOOKS[family] for family in families)}))


def derive_expected_entry_timestamp(setup: SetupEvent, *, sealed_h1_inventory=None):
    """Select the entry open from sealed provider-observed H1 membership."""
    confirmation = setup.setuptransition_set.get(
        from_state=SetupTransition.State.TRIGGER_PENDING,
        to_state=SetupTransition.State.CONFIRMED,
        book_identity="",
    )
    if sealed_h1_inventory is None:
        contract = provider_observed_contract(setup.dataset_version)
        sealed_h1_inventory = (
            inventory_timestamps(contract, setup.instrument.code, "H1")
            if contract is not None
            else MarketCandle.objects.filter(
                dataset_version=setup.dataset_version,
                instrument=setup.instrument,
                granularity="H1",
                complete=True,
            )
            .order_by("timestamp")
            .values_list("timestamp", flat=True)
        )
    successors = sorted(
        timestamp
        for timestamp in set(sealed_h1_inventory)
        if timestamp >= confirmation.effective_at
    )
    if not successors:
        raise DatasetQualityError("no sealed H1 entry successor exists after confirmation")
    return successors[0]


def current_setup_state(setup: SetupEvent) -> str:
    transition = setup.setuptransition_set.filter(book_identity="").first()
    return transition.to_state if transition else setup.initial_state


def _transition_values(setup, *, to_state, effective_at, evidence, reason, job_run, book_identity):
    if job_run and (
        job_run.strategy_version_id != setup.strategy_version_id
        or job_run.dataset_version_id != setup.dataset_version_id
    ):
        raise ValueError("transition job lineage does not match setup")
    return {
        "book_identity": book_identity,
        "to_state": to_state,
        "effective_at": effective_at,
        "reason": reason,
        "evidence_hash": evidence_hash(evidence),
        "evidence": evidence,
        "strategy_version": setup.strategy_version,
        "dataset_version": setup.dataset_version,
        "execution_identity": setup.strategy_version.execution_identity,
        "job_run": job_run,
    }


def _persist_single_outgoing_transition(setup, *, from_state, values):
    existing = SetupTransition.objects.filter(
        setup=setup,
        from_state=from_state,
        book_identity=values["book_identity"],
    ).first()
    if existing:
        comparable = {
            "to_state": existing.to_state,
            "effective_at": existing.effective_at,
            "reason": existing.reason,
            "evidence_hash": existing.evidence_hash,
            "evidence": existing.evidence,
            "strategy_version": existing.strategy_version,
            "dataset_version": existing.dataset_version,
            "execution_identity": existing.execution_identity,
            "job_run": existing.job_run,
            "book_identity": existing.book_identity,
        }
        if any(comparable[field] != value for field, value in values.items()):
            raise ValueError("conflicting replay attempted to fork setup transition")
        return existing
    return SetupTransition.objects.create(setup=setup, from_state=from_state, **values)


@transaction.atomic
def persist_confirmation(
    *,
    setup: SetupEvent,
    confirmation: Confirmation,
    evidence,
    required_ranges,
    as_of,
    job_run=None,
) -> SetupTransition | None:
    if confirmation.state == SetupTransition.State.TRIGGER_PENDING:
        return None
    if confirmation.state not in {
        SetupTransition.State.CONFIRMED,
        SetupTransition.State.INVALIDATED,
        SetupTransition.State.EXPIRED,
        SetupTransition.State.CANCELLED_DATA_QUALITY,
    }:
        raise ValueError("unsupported Phase 2A confirmation state")
    setup = SetupEvent.objects.select_for_update().get(pk=setup.pk)
    try:
        required_ranges = _derive_history(
            required_ranges,
            {"D": 1, "H1": 1},
            confirmation.at,
            exact_completion={"H1": confirmation.at},
            dataset_version=setup.dataset_version,
            instrument=setup.instrument,
        )
        assert_dataset_window_usable(
            setup.dataset_version, setup.instrument, required_ranges, as_of
        )
    except DatasetQualityError:
        if confirmation.state != SetupTransition.State.CANCELLED_DATA_QUALITY:
            raise
    values = _transition_values(
        setup,
        to_state=confirmation.state,
        effective_at=confirmation.at,
        evidence=evidence,
        reason=(
            "CONFIRMATION_WINDOW" if confirmation.state == SetupTransition.State.EXPIRED else ""
        ),
        job_run=job_run,
        book_identity="",
    )
    return _persist_single_outgoing_transition(
        setup, from_state=SetupTransition.State.TRIGGER_PENDING, values=values
    )


@transaction.atomic
def persist_entry_evaluation(
    *,
    setup: SetupEvent,
    book_identity: str,
    result: EntryResult,
    opening: EntryOpen | None,
    target_level: Level | None,
    evidence,
    required_ranges,
    as_of,
    job_run=None,
    expected_entry_timestamp=None,
) -> EntryEligibilityEvaluation:
    setup = SetupEvent.objects.select_for_update().get(pk=setup.pk)
    derived_entry_timestamp = derive_expected_entry_timestamp(setup)
    supplied_entry_timestamp = opening.timestamp if opening else expected_entry_timestamp
    if supplied_entry_timestamp is not None and supplied_entry_timestamp != derived_entry_timestamp:
        raise ValueError(
            "entry timestamp does not match the first registered H1 open after confirmation"
        )
    entry_timestamp = derived_entry_timestamp
    try:
        entry_completion = candle_completion(
            entry_timestamp, "H1", provider_observed_contract(setup.dataset_version)
        )
        required_ranges = _derive_history(
            required_ranges,
            {"W": 1, "D": 1, "H1": 15},
            entry_completion,
            required_timestamps={"H1": entry_timestamp},
            decision_boundaries={"W": entry_timestamp, "D": entry_timestamp},
            dataset_version=setup.dataset_version,
            instrument=setup.instrument,
        )
        assert_dataset_window_usable(
            setup.dataset_version, setup.instrument, required_ranges, as_of
        )
    except DatasetQualityError:
        if result.decision != EntryEligibilityEvaluation.Decision.CANCELLED_DATA_QUALITY:
            raise
    if book_identity not in books_for_setup(setup):
        raise ValueError("book is not attributable to this physical setup")
    permitted = result.decision == EntryEligibilityEvaluation.Decision.ENTRY_PENDING
    if not setup.setuptransition_set.filter(
        from_state=SetupTransition.State.TRIGGER_PENDING,
        to_state=SetupTransition.State.CONFIRMED,
        book_identity="",
    ).exists():
        raise ValueError("entry eligibility requires a confirmed setup")
    if permitted and (
        target_level is None
        or target_level.instrument_id != setup.instrument_id
        or target_level.strategy_version_id != setup.strategy_version_id
        or target_level.dataset_version_id != setup.dataset_version_id
        or target_level.role
        != (
            Level.Role.RESISTANCE
            if setup.direction == SetupEvent.Direction.LONG
            else Level.Role.SUPPORT
        )
        or target_level.stable_key != result.target_key
        or result.target
        != (
            target_level.zone_lower
            if setup.direction == SetupEvent.Direction.LONG
            else target_level.zone_upper
        )
    ):
        raise ValueError("target identity, boundary, or lineage does not match entry result")
    defaults = {
        "decision": result.decision,
        "terminal_reason": result.reason,
        "entry_timestamp": opening.timestamp if permitted and opening else None,
        "entry_price": _stored_decimal(result.entry) if permitted else None,
        "stop_price": _stored_decimal(result.stop) if permitted else None,
        "target_price": _stored_decimal(result.target) if permitted else None,
        "reward_risk": _stored_decimal(result.reward_risk) if permitted else None,
        "risk_per_unit_quote": _stored_decimal(result.risk_per_unit_quote) if permitted else None,
        "conversion_rate_to_cad": (
            _stored_decimal(result.conversion_rate_to_cad) if permitted else None
        ),
        "conversion_effective_at": result.conversion_effective_at if permitted else None,
        "conversion_identity": result.conversion_identity if permitted else "",
        "risk_per_unit_cad": _stored_decimal(result.risk_per_unit_cad) if permitted else None,
        "target_level": target_level if permitted else None,
        "target_stable_key": result.target_key if permitted else "",
        "evidence": evidence,
        "evidence_hash": evidence_hash(evidence),
    }
    evaluation, created = EntryEligibilityEvaluation.objects.get_or_create(
        setup=setup, book_identity=book_identity, defaults=defaults
    )
    if not created and any(
        getattr(evaluation, field) != value for field, value in defaults.items()
    ):
        raise ValueError("setup/book evaluation resolved to different immutable content")
    values = _transition_values(
        setup,
        to_state=result.decision,
        effective_at=entry_timestamp,
        evidence=evidence,
        reason=result.reason,
        job_run=job_run,
        book_identity=book_identity,
    )
    _persist_single_outgoing_transition(
        setup, from_state=SetupTransition.State.CONFIRMED, values=values
    )
    return evaluation
