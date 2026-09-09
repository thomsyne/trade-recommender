"""Prospective daily target identity, control issuance and shared outcome ownership."""

import hashlib
import json
from datetime import UTC
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from forecasts.models import (
    EvidenceSnapshot,
    Forecast,
    ForecastResolution,
    RecommendationResolution,
    TargetContract,
    TargetOccurrence,
    TargetResolution,
)
from market.models import Candle, IngestionRun, TechnicalSnapshot
from market.quality import (
    live_interval_is_aligned,
    registered_candle_completion,
    registered_successor,
)

RESOLUTION_METHOD = "registered-session-endpoint-v2"
NEUTRAL_RULE = "absolute-change-less-or-equal-band-v1"
QUANTUM = Decimal("0.000001")


def identity_digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False
        ).encode()
    ).hexdigest()


def target_endpoint(reference, horizon):
    if not isinstance(horizon, int) or isinstance(horizon, bool) or not 1 <= horizon <= 100:
        raise ValidationError("invalid_target_horizon")
    for _ in range(horizon):
        reference = registered_successor(reference, "D")
    return reference


def target_material(target):
    return {
        "instrument": target.instrument.code,
        "contract": [target.target_contract.key, target.target_contract.version],
        "product": target.target_contract.product,
        "definition": target.definition_sha256,
        "reference": target.reference_candle.timestamp.astimezone(UTC).isoformat(
            timespec="microseconds"
        ),
        "content": target.reference_content_sha256,
        "midpoint": format(target.reference_midpoint.quantize(QUANTUM), "f"),
        "band": format(target.neutral_band.quantize(QUANTUM), "f"),
        "horizon": target.horizon_sessions,
        "cutoff": target.information_cutoff.astimezone(UTC).isoformat(timespec="microseconds"),
        "resolution": target.resolution_method,
        "neutral_rule": target.neutral_rule,
    }


def validate_target(target):
    candle = target.reference_candle
    if (
        candle.instrument_id != target.instrument_id
        or candle.granularity != "D"
        or not candle.complete
        or not live_interval_is_aligned(candle.timestamp, "D")
        or candle.content_sha256 != target.reference_content_sha256
        or target.reference_midpoint != candle.midpoint_close.quantize(QUANTUM)
        or target.information_cutoff < registered_candle_completion(candle.timestamp, "D")
        or target.registered_at < target.information_cutoff
        or target.neutral_band < 0
        or target.horizon_sessions != target.target_contract.horizon_sessions
        or target.resolution_method != RESOLUTION_METHOD
        or target.neutral_rule != NEUTRAL_RULE
        or target.definition_sha256 != identity_digest(target.target_contract.definition)
        or target.identity_sha256 != identity_digest(target_material(target))
    ):
        raise ValidationError("invalid_target_identity")


def validate_recommendation(rec):
    target = rec.target_occurrence
    control = rec.control_forecast
    if not target or not control or not comparable_control(rec):
        raise ValidationError("exact_prospective_control_required")
    if (
        rec.reference_candle_id != target.reference_candle_id
        or rec.reference_midpoint != target.reference_midpoint
        or rec.neutral_band != target.neutral_band
        or rec.expires_after_sessions != target.horizon_sessions
        or rec.information_cutoff != target.information_cutoff
    ):
        raise ValidationError("recommendation_target_mismatch")


def comparable_control(rec, as_of=None):
    target, control = rec.target_occurrence, rec.control_forecast
    return bool(
        target
        and control
        and control.target_occurrence_id == target.pk
        and control.instrument_id == rec.instrument_id == target.instrument_id
        and control.target_contract_id == target.target_contract_id
        and control.information_cutoff == target.information_cutoff
        and control.reference_midpoint == target.reference_midpoint
        and control.neutral_band == target.neutral_band
        and control.setup_expires_after_sessions == target.horizon_sessions
        and control.issued_at <= rec.generated_at
        and control.method in {"mechanical-ewma", "fixture-mechanical-ewma"}
        and control.method_version == 1
        and (as_of is None or control.issued_at <= as_of)
    )


def validate_resolution(resolution):
    target = resolution.target
    scored = resolution.outcome in {"up", "neutral", "down"}
    values = (
        resolution.horizon_candle_id,
        resolution.endpoint_midpoint,
        resolution.midpoint_change,
    )
    if resolution.outcome not in {"up", "neutral", "down", "missing", "cancelled"}:
        raise ValidationError("invalid_target_outcome")
    if resolution.resolution_method != target.resolution_method:
        raise ValidationError("resolution_method_mismatch")
    if scored:
        if any(value is None for value in values):
            raise ValidationError("scored_endpoint_required")
        candle = resolution.horizon_candle
        from forecasts.services import classify_change

        if (
            candle.instrument_id != target.instrument_id
            or candle.granularity != "D"
            or candle.timestamp
            != target_endpoint(target.reference_candle.timestamp, target.horizon_sessions)
            or candle.content_sha256 != resolution.horizon_content_sha256
            or resolution.resolved_at < registered_candle_completion(candle.timestamp, "D")
            or resolution.endpoint_midpoint != candle.midpoint_close.quantize(QUANTUM)
            or resolution.midpoint_change
            != resolution.endpoint_midpoint - target.reference_midpoint
            or resolution.outcome
            != classify_change(resolution.midpoint_change, target.neutral_band)
        ):
            raise ValidationError("shared_endpoint_mismatch")
    else:
        if any(value is not None for value in values) or resolution.horizon_content_sha256:
            raise ValidationError("unscored_endpoint_forbidden")
        if (
            resolution.outcome == "missing"
            and resolution.resolved_at
            < registered_candle_completion(
                target_endpoint(target.reference_candle.timestamp, target.horizon_sessions), "D"
            )
        ):
            raise ValidationError("immature_missing_forbidden")


def target_contract():
    from forecasts.services import CONTRACTS

    spec = dict(next(item for item in CONTRACTS if item["product"] == "tactical"))
    spec["version"] = 2
    spec["definition"] = spec["definition"] | {
        "occurrence": "canonical-v1",
        "resolution": RESOLUTION_METHOD,
    }
    contract, created = TargetContract.objects.get_or_create(
        key=spec["key"], version=2, defaults=spec
    )
    if not created and any(getattr(contract, key) != value for key, value in spec.items()):
        raise ValidationError("target_contract_drift")
    return contract


@transaction.atomic
def reconcile_targets(instrument, *, as_of=None, allow_fixture=False):
    as_of = as_of or timezone.now()
    if (
        not type(instrument)
        .objects.select_for_update()
        .filter(
            pk=instrument.pk, active=True, code__in=("EUR_USD", "GBP_USD", "EUR_GBP", "USD_CAD")
        )
        .exists()
    ):
        raise ValidationError("decision_instrument_required")
    for target in TargetOccurrence.objects.filter(instrument=instrument, resolution__isnull=True):
        resolve_target(target, as_of=as_of)
    from forecasts.recommendations import _build_outcome_contract

    candle, contract_values = _build_outcome_contract(
        instrument, as_of, allow_fixture=allow_fixture
    )
    technical = TechnicalSnapshot.objects.filter(
        instrument=instrument, granularity="D", as_of=candle.timestamp, calculated_at__lte=as_of
    ).first()
    cutoff = max(
        candle.ingestion_run.finished_at,
        technical.calculated_at,
        registered_candle_completion(candle.timestamp, "D"),
    )
    if as_of >= registered_candle_completion(target_endpoint(candle.timestamp, 5), "D"):
        raise ValidationError("target_already_mature")
    contract = target_contract()
    target = TargetOccurrence(
        instrument=instrument,
        target_contract=contract,
        reference_candle=candle,
        reference_content_sha256=candle.content_sha256,
        information_cutoff=cutoff,
        reference_midpoint=Decimal(contract_values["reference_midpoint"]),
        neutral_band=Decimal(contract_values["neutral_band"]),
        horizon_sessions=5,
        resolution_method=RESOLUTION_METHOD,
        neutral_rule=NEUTRAL_RULE,
        definition_sha256=identity_digest(contract.definition),
        registered_at=as_of,
    )
    target.identity_sha256 = identity_digest(target_material(target))
    existing = TargetOccurrence.objects.filter(identity_sha256=target.identity_sha256).first()
    if existing:
        target = existing
    else:
        target.save()
    existing = Forecast.objects.filter(target_occurrence=target, method_version=1).first()
    if existing:
        return target, existing
    if technical.ewma_20 is None:
        raise ValidationError("mechanical_technical_evidence_missing")
    payload = {"target": target.identity_sha256, "technical_id": technical.pk}
    evidence, _ = EvidenceSnapshot.objects.get_or_create(
        sha256=identity_digest(payload),
        defaults={
            "instrument": instrument,
            "anchor_candle": candle,
            "technical_snapshot": technical,
            "market_data_cutoff": cutoff,
            "captured_at": as_of,
            "payload": payload,
        },
    )
    from forecasts.services import _issue_baseline, ensure_target_contracts

    macro = _issue_baseline(ensure_target_contracts()["macro"], evidence, as_of)
    control = _issue_baseline(contract, evidence, as_of, parent=macro, target=target)
    return target, control


def exact_control(instrument, candle, outcome, generated_at):
    candidates = Forecast.objects.filter(
        target_occurrence__instrument=instrument,
        target_occurrence__reference_candle=candle,
        target_occurrence__reference_content_sha256=candle.content_sha256,
        target_occurrence__reference_midpoint=Decimal(outcome["reference_midpoint"]),
        target_occurrence__neutral_band=Decimal(outcome["neutral_band"]),
        target_occurrence__horizon_sessions=5,
        target_occurrence__target_contract__version=2,
        issued_at__lte=generated_at,
        method_version=1,
    ).select_related("target_occurrence")
    technical = TechnicalSnapshot.objects.filter(
        instrument=instrument,
        granularity="D",
        as_of=candle.timestamp,
        calculated_at__lte=generated_at,
    ).first()
    if not technical:
        raise ValidationError("exact_prospective_control_required")
    cutoff = max(
        candle.ingestion_run.finished_at,
        technical.calculated_at,
        registered_candle_completion(candle.timestamp, "D"),
    )
    control = candidates.filter(
        target_occurrence__information_cutoff=cutoff,
        method__in=("mechanical-ewma", "fixture-mechanical-ewma"),
    ).first()
    if not control:
        raise ValidationError("exact_prospective_control_required")
    if generated_at >= registered_candle_completion(target_endpoint(candle.timestamp, 5), "D"):
        raise ValidationError("target_already_mature")
    validate_target(control.target_occurrence)
    target = control.target_occurrence
    if control.evidence_snapshot.technical_snapshot.calculated_at > cutoff:
        raise ValidationError("control_later_evidence")
    return target, control


@transaction.atomic
def resolve_target(target, *, as_of=None):
    as_of = as_of or timezone.now()
    target = TargetOccurrence.objects.select_for_update().get(pk=target.pk)
    existing = TargetResolution.objects.filter(target=target).first()
    if existing:
        return existing if existing.resolved_at <= as_of else None
    endpoint_time = target_endpoint(target.reference_candle.timestamp, target.horizon_sessions)
    if registered_candle_completion(endpoint_time, "D") > as_of:
        return None
    endpoint = Candle.objects.filter(
        instrument=target.instrument,
        granularity="D",
        timestamp=endpoint_time,
        complete=True,
        ingestion_run__status=IngestionRun.Status.SUCCEEDED,
        ingestion_run__finished_at__lte=as_of,
    ).first()
    from forecasts.services import classify_change

    midpoint = endpoint.midpoint_close.quantize(QUANTUM) if endpoint else None
    change = midpoint - target.reference_midpoint if endpoint else None
    return TargetResolution.objects.create(
        target=target,
        outcome=classify_change(change, target.neutral_band) if endpoint else "missing",
        horizon_candle=endpoint,
        horizon_content_sha256=endpoint.content_sha256 if endpoint else "",
        endpoint_midpoint=midpoint,
        midpoint_change=change,
        resolution_method=target.resolution_method,
        resolved_at=as_of,
        idempotency_key=f"target-resolution:{target.identity_sha256}",
        details={"schema_version": 1, "expected_endpoint": endpoint_time.isoformat()},
    )


def derive_resolution(prediction):
    shared = resolve_target(prediction.target_occurrence)
    if not shared:
        return None
    from forecasts.services import multiclass_brier

    scored = shared.outcome in {"up", "neutral", "down"}
    common = dict(
        target_resolution=shared,
        outcome=shared.outcome,
        horizon_candle=shared.horizon_candle,
        endpoint_midpoint=shared.endpoint_midpoint,
        midpoint_change=shared.midpoint_change,
        brier_score=multiclass_brier(prediction, shared.outcome) if scored else None,
        details={
            "schema_version": 1,
            "target_resolution_id": shared.pk,
            "sessions_observed": prediction.target_occurrence.horizon_sessions if scored else 0,
            "setup_performance_not_measured": True,
            "horizon_candle_content_sha256": shared.horizon_content_sha256,
            "reference_candle_content_sha256": prediction.target_occurrence.reference_content_sha256,
            "candle_revision_policy": "first-complete-observation-v1",
        },
        resolved_at=timezone.now(),
    )
    if isinstance(prediction, Forecast):
        return ForecastResolution.objects.create(
            forecast=prediction, setup_outcome="not_offered", **common
        )
    hit = (
        None
        if not scored or prediction.action == "abstain"
        else shared.outcome == ("up" if prediction.action == "buy" else "down")
    )
    return RecommendationResolution.objects.create(
        recommendation=prediction, directional_hit=hit, **common
    )


def control_readiness(instrument, *, as_of=None):
    """Read-only issuance readiness; never manufactures an absent control."""
    from forecasts.recommendations import _build_outcome_contract

    as_of = as_of or timezone.now()
    try:
        candle, contract = _build_outcome_contract(instrument, as_of, allow_fixture=False)
    except ValidationError:
        return "Awaiting eligible daily evidence"
    try:
        exact_control(instrument, candle, contract, as_of)
    except ValidationError:
        if Forecast.objects.filter(
            instrument=instrument, evidence_snapshot__anchor_candle=candle
        ).exists():
            return "Incompatible control — model issuance blocked"
        return "Missing control — model issuance blocked"
    return "Exact prospective control available"
