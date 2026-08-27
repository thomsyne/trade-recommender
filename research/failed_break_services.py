"""Idempotent persistence boundary for deterministic failed-break outputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from django.db import transaction

from market.services import DatasetQualityError, assert_dataset_usable
from research.models import (
    AnalysisRun,
    EntryEligibilityEvaluation,
    Level,
    SetupEvent,
    SetupLevelAttribution,
    SetupTransition,
)
from research.strategy import Confirmation, EntryOpen, EntryResult, LevelSpec, SweepEvent

COMBINED_BOOK = "failed-break-any-level-deduplicated-v1"
FAMILY_BOOKS = {
    Level.Family.WEEKLY: "failed-break-weekly-extreme-v1",
    Level.Family.DAILY_SWING: "failed-break-daily-swing-v1",
    Level.Family.BREAKOUT: "failed-break-breakout-flip-v1",
}


def evidence_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@transaction.atomic
def persist_level(*, instrument, strategy_version, dataset_version, spec: LevelSpec) -> Level:
    values = {
        "family": spec.family,
        "role": spec.role.value,
        "instrument": instrument,
        "strategy_version": strategy_version,
        "dataset_version": dataset_version,
        "source_timeframe": "W" if spec.family == Level.Family.WEEKLY else "D",
        "source_candle_timestamp": spec.source_at,
        "central_price": spec.central_price,
        "zone_lower": spec.zone_lower,
        "zone_upper": spec.zone_upper,
        "atr_at_activation": spec.atr_at_activation,
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
    if not created and any(getattr(stored, field) != value for field, value in values.items()):
        raise ValueError("stable level key resolved to different immutable content")
    return stored


@transaction.atomic
def persist_analysis(
    *, instrument, strategy_version, dataset_version, completed_h1_timestamp, result, evidence
) -> AnalysisRun:
    try:
        assert_dataset_usable(dataset_version)
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
) -> SetupEvent:
    assert_dataset_usable(dataset_version)
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
    *, setup: SetupEvent, confirmation: Confirmation, evidence, job_run=None
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
        assert_dataset_usable(setup.dataset_version)
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
    job_run=None,
    expected_entry_timestamp=None,
) -> EntryEligibilityEvaluation:
    setup = SetupEvent.objects.select_for_update().get(pk=setup.pk)
    try:
        assert_dataset_usable(setup.dataset_version)
    except DatasetQualityError:
        if result.decision != EntryEligibilityEvaluation.Decision.CANCELLED_DATA_QUALITY:
            raise
    if book_identity not in books_for_setup(setup):
        raise ValueError("book is not attributable to this physical setup")
    if opening is None and expected_entry_timestamp is None:
        raise ValueError("expected entry timestamp is required when no H1 open exists")
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
    ):
        raise ValueError("target level lineage does not match setup")
    defaults = {
        "decision": result.decision,
        "terminal_reason": result.reason,
        "entry_timestamp": opening.timestamp if permitted and opening else None,
        "entry_price": result.entry if permitted else None,
        "stop_price": result.stop if permitted else None,
        "target_price": result.target if permitted else None,
        "reward_risk": result.reward_risk if permitted else None,
        "risk_per_unit_quote": result.risk_per_unit_quote if permitted else None,
        "conversion_rate_to_cad": result.conversion_rate_to_cad if permitted else None,
        "conversion_effective_at": result.conversion_effective_at if permitted else None,
        "conversion_identity": result.conversion_identity if permitted else "",
        "risk_per_unit_cad": result.risk_per_unit_cad if permitted else None,
        "target_level": target_level if permitted else None,
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
        effective_at=opening.timestamp if opening else expected_entry_timestamp,
        evidence=evidence,
        reason=result.reason,
        job_run=job_run,
        book_identity=book_identity,
    )
    _persist_single_outgoing_transition(
        setup, from_state=SetupTransition.State.CONFIRMED, values=values
    )
    return evaluation
