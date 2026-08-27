"""Idempotent persistence boundary for deterministic failed-break outputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from django.db import transaction

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
    record, _ = AnalysisRun.objects.get_or_create(
        instrument=instrument,
        strategy_version=strategy_version,
        dataset_version=dataset_version,
        completed_h1_timestamp=completed_h1_timestamp,
        defaults={"result": result, "evidence_hash": evidence_hash(evidence)},
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
    if set(event.level_keys) != set(level_attributions):
        raise ValueError("setup attributions do not match deterministic sweep keys")
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
        "evidence_hash": evidence_hash(evidence),
    }
    setup, created = SetupEvent.objects.get_or_create(
        **lookup,
        defaults=defaults,
    )
    if not created and any(getattr(setup, field) != value for field, value in defaults.items()):
        raise ValueError("physical setup key resolved to different immutable content")
    for level in level_attributions.values():
        SetupLevelAttribution.objects.get_or_create(setup=setup, level=level)
    return setup


def books_for_setup(setup: SetupEvent) -> tuple[str, ...]:
    families = setup.setuplevelattribution_set.values_list("level__family", flat=True).distinct()
    return tuple(sorted({COMBINED_BOOK, *(FAMILY_BOOKS[family] for family in families)}))


def current_setup_state(setup: SetupEvent) -> str:
    transition = setup.setuptransition_set.order_by("effective_at", "id").last()
    return transition.to_state if transition else setup.initial_state


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
    if current_setup_state(setup) != SetupTransition.State.TRIGGER_PENDING:
        return setup.setuptransition_set.filter(to_state=confirmation.state).first()
    transition, _ = SetupTransition.objects.get_or_create(
        setup=setup,
        from_state=SetupTransition.State.TRIGGER_PENDING,
        to_state=confirmation.state,
        effective_at=confirmation.at,
        defaults={
            "reason": "CONFIRMATION_WINDOW"
            if confirmation.state == SetupTransition.State.EXPIRED
            else "",
            "evidence_hash": evidence_hash(evidence),
            "evidence": evidence,
            "job_run": job_run,
        },
    )
    return transition


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
    if book_identity not in books_for_setup(setup):
        raise ValueError("book is not attributable to this physical setup")
    if opening is None and expected_entry_timestamp is None:
        raise ValueError("expected entry timestamp is required when no H1 open exists")
    permitted = result.decision == EntryEligibilityEvaluation.Decision.ENTRY_PENDING
    defaults = {
        "decision": result.decision,
        "terminal_reason": result.reason,
        "entry_timestamp": opening.timestamp if permitted and opening else None,
        "entry_price": result.entry if permitted else None,
        "stop_price": result.stop if permitted else None,
        "target_price": result.target if permitted else None,
        "reward_risk": result.reward_risk if permitted else None,
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
    if not evaluation.setup.setuptransition_set.filter(
        to_state=SetupTransition.State.CONFIRMED
    ).exists():
        raise ValueError("entry eligibility requires a confirmed setup")
    SetupTransition.objects.get_or_create(
        setup=setup,
        from_state=SetupTransition.State.CONFIRMED,
        to_state=result.decision,
        effective_at=opening.timestamp if opening else expected_entry_timestamp,
        defaults={
            "reason": result.reason,
            "evidence": evidence,
            "evidence_hash": evidence_hash(evidence),
            "job_run": job_run,
        },
    )
    return evaluation
