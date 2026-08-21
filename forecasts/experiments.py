import hashlib
import json
import math
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from forecasts.models import (
    EvaluationPolicy,
    ExperimentAssessment,
    ExperimentAssessmentAttempt,
    ExperimentEra,
    ExperimentSample,
    ForecastMethodIdentity,
    PromotionRecord,
    Recommendation,
)
from market.models import AuditEvent

POLICY_KEY = "dependence-aware-forecast-health"
POLICY_VERSION = 1
METHOD_KEY = "governed-fx-recommendation"
UNIFORM_BRIER = Decimal("0.222222")
SCORE_QUANTUM = Decimal("0.000001")
RATE_QUANTUM = Decimal("0.000001")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def ensure_evaluation_policy():
    identity = {
        "minimum_raw_samples": 50,
        "minimum_calendar_days": 180,
        "minimum_effective_clusters": 24,
        "minimum_resolution_coverage": Decimal("0.9000"),
        "maximum_calibration_error": Decimal("0.1500"),
        "confidence_level": Decimal("0.9500"),
        "cluster_method": "utc-iso-week-common-factor-v1",
        "interval_method": "cluster-mean-hoeffding-v1",
        "primary_metric": "mean-multiclass-brier-v1",
        "baseline_contract": {
            "uniform": "one-third-each-outcome-v1",
            "mechanical": "linked-tactical-control-when-comparable-v1",
        },
        "guardrails": {
            "baseline_outperformance_required": True,
            "calibration_error_maximum": "0.1500",
            "resolution_coverage_minimum": "0.9000",
            "challenger_requires_paired_cluster_interval_below_zero": True,
            "promotion_is_owner_only_and_does_not_activate_policy": True,
        },
    }
    policy, created = EvaluationPolicy.objects.get_or_create(
        policy_key=POLICY_KEY,
        policy_version=POLICY_VERSION,
        defaults=identity,
    )
    if not created:
        for field, expected in identity.items():
            if getattr(policy, field) != expected:
                raise ValidationError(
                    "Evaluation policy identity changed; increment POLICY_VERSION"
                )
    return policy


def ensure_forecast_method(provider):
    from forecasts.recommendations import CONTRACT_VERSION, OUTPUT_SCHEMA, SYSTEM_PROMPT

    identity = {
        "provider": provider.name,
        "requested_model": provider.model,
        "contract_version": CONTRACT_VERSION,
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "output_schema_sha256": _digest(OUTPUT_SCHEMA),
        "input_contract_sha256": _digest(
            {
                "contract": "governed-fx-recommendation-v3",
                "technical_context": "non-reconstructable-labels-v1",
                "numeric_market_values_withheld": True,
            }
        ),
        "setup_policy_key": "deterministic-local-policy-v1",
        "max_output_tokens": settings.RECOMMENDATION_MAX_OUTPUT_TOKENS,
        "rights_manifest": {
            "version": 1,
            "numeric_oanda_values_external_processing": False,
            "raw_provider_payloads_external_processing": False,
            "eligible_research_representations_only": True,
        },
    }
    identity_sha256 = _digest(identity)
    method, created = ForecastMethodIdentity.objects.get_or_create(
        method_key=METHOD_KEY,
        method_version=settings.RECOMMENDATION_METHOD_VERSION,
        defaults=identity | {"identity_sha256": identity_sha256},
    )
    if not created:
        for field, expected in identity.items():
            if getattr(method, field) != expected:
                raise ValidationError(
                    "Forecast method identity changed; increment RECOMMENDATION_METHOD_VERSION"
                )
        if method.identity_sha256 != identity_sha256:
            raise ValidationError("Stored forecast method identity hash is invalid")
    return method


@transaction.atomic
def ensure_champion_era(provider, *, starts_at=None):
    starts_at = starts_at or timezone.now()
    method = ensure_forecast_method(provider)
    policy = ensure_evaluation_policy()
    latest = ExperimentEra.objects.filter(kind=ExperimentEra.Kind.CHAMPION).first()
    if latest and latest.method_id == method.pk and latest.evaluation_policy_id == policy.pk:
        return latest
    material = {
        "kind": ExperimentEra.Kind.CHAMPION,
        "method": method.identity_sha256,
        "policy": f"{policy.policy_key}:v{policy.policy_version}",
        "starts_at": starts_at.isoformat(),
        "supersedes": latest.pk if latest else None,
    }
    era = ExperimentEra.objects.create(
        kind=ExperimentEra.Kind.CHAMPION,
        method=method,
        evaluation_policy=policy,
        supersedes=latest,
        hypothesis_snapshot={},
        registration_sha256=_digest(material),
        starts_at=starts_at,
        registered_at=starts_at,
    )
    AuditEvent.objects.create(
        event_type="forecast.experiment_era_started",
        actor="forecasts.experiments.ensure_champion_era",
        subject_type="ExperimentEra",
        subject_id=str(era.pk),
        payload={
            "kind": era.kind,
            "method_identity": method.identity_sha256,
            "policy_version": policy.policy_version,
            "supersedes_id": latest.pk if latest else None,
        },
    )
    return era


@transaction.atomic
def start_challenger_era(authorization, method, *, actor, starts_at=None):
    if not actor.is_superuser or authorization.actor_id != actor.pk:
        raise ValidationError("Only the authorizing owner may start a challenger")
    existing = ExperimentEra.objects.filter(authorization=authorization).first()
    if existing:
        return existing
    champion = ExperimentEra.objects.filter(kind=ExperimentEra.Kind.CHAMPION).first()
    if not champion:
        raise ValidationError("A champion era must exist before a challenger starts")
    if method.identity_sha256 == champion.method.identity_sha256:
        raise ValidationError("A challenger method must differ from the champion")
    starts_at = starts_at or timezone.now()
    hypothesis = authorization.hypothesis
    snapshot = {
        "hypothesis_id": hypothesis.pk,
        "pattern_key": hypothesis.pattern_key,
        "title": hypothesis.title,
        "statement": hypothesis.statement,
        "proposed_change": hypothesis.proposed_change,
        "evaluation_plan": hypothesis.evaluation_plan,
        "evidence_sha256": hypothesis.evidence_sha256,
        "authorization_id": authorization.pk,
    }
    material = {
        "kind": ExperimentEra.Kind.CHALLENGER,
        "method": method.identity_sha256,
        "champion_era": champion.pk,
        "policy": champion.evaluation_policy_id,
        "hypothesis": snapshot,
        "starts_at": starts_at.isoformat(),
    }
    era = ExperimentEra.objects.create(
        kind=ExperimentEra.Kind.CHALLENGER,
        method=method,
        evaluation_policy=champion.evaluation_policy,
        authorization=authorization,
        champion_era=champion,
        hypothesis_snapshot=snapshot,
        registration_sha256=_digest(material),
        starts_at=starts_at,
        registered_at=starts_at,
    )
    AuditEvent.objects.create(
        event_type="forecast.challenger_era_started",
        actor=f"user:{actor.pk}",
        subject_type="ExperimentEra",
        subject_id=str(era.pk),
        payload={
            "authorization_id": authorization.pk,
            "champion_era_id": champion.pk,
            "method_identity": method.identity_sha256,
            "active_policy_changed": False,
        },
    )
    return era


def _factor_keys(recommendation):
    if recommendation.action == Recommendation.Action.ABSTAIN:
        return ["abstain"]
    base_side = "long" if recommendation.action == Recommendation.Action.BUY else "short"
    quote_side = "short" if base_side == "long" else "long"
    return sorted(
        (
            f"{base_side}:{recommendation.instrument.base_currency}",
            f"{quote_side}:{recommendation.instrument.quote_currency}",
        )
    )


@transaction.atomic
def assign_recommendation(recommendation, method, *, assigned_at=None):
    assigned_at = assigned_at or recommendation.generated_at
    eras = ExperimentEra.objects.filter(
        method=method,
        starts_at__lte=recommendation.generated_at,
        superseded_by__isnull=True,
    ).exclude(
        promotion_records__decision__in=(
            PromotionRecord.Decision.REJECT,
            PromotionRecord.Decision.PROMOTE,
        )
    )
    samples = []
    iso_year, iso_week, _ = recommendation.generated_at.isocalendar()
    for era in eras:
        sample, _ = ExperimentSample.objects.get_or_create(
            era=era,
            recommendation=recommendation,
            defaults={
                "issuance_cluster_key": recommendation.generated_at.isoformat(),
                "dependence_cluster_key": f"{iso_year}-W{iso_week:02d}",
                "factor_keys": _factor_keys(recommendation),
                "assigned_at": assigned_at,
            },
        )
        samples.append(sample)
    return samples


def _brier(probabilities, outcome):
    labels = ("up", "neutral", "down")
    score = sum(
        (probability - (Decimal(1) if label == outcome else Decimal(0))) ** 2
        for label, probability in zip(labels, probabilities, strict=True)
    ) / Decimal(3)
    return score.quantize(SCORE_QUANTUM)


def _mean(values):
    if not values:
        return None
    return (sum(values, start=Decimal(0)) / Decimal(len(values))).quantize(SCORE_QUANTUM)


def _calibration_error(resolved):
    bins = defaultdict(list)
    clusters = defaultdict(list)
    for sample in resolved:
        clusters[sample.dependence_cluster_key].append(sample)
    for cluster_samples in clusters.values():
        weight = Decimal(1) / Decimal(len(cluster_samples))
        for sample in cluster_samples:
            recommendation = sample.recommendation
            probabilities = (
                recommendation.probability_up,
                recommendation.probability_neutral,
                recommendation.probability_down,
            )
            top_index = max(range(3), key=lambda index: probabilities[index])
            top_probability = probabilities[top_index]
            realized_index = ("up", "neutral", "down").index(recommendation.resolution.outcome)
            bins[int(top_probability * 10)].append(
                (
                    top_probability,
                    Decimal(1) if top_index == realized_index else Decimal(0),
                    weight,
                )
            )
    if not resolved:
        return None
    weighted = Decimal(0)
    for values in bins.values():
        bin_weight = sum((item[2] for item in values), start=Decimal(0))
        confidence = sum((item[0] * item[2] for item in values), start=Decimal(0)) / bin_weight
        frequency = sum((item[1] * item[2] for item in values), start=Decimal(0)) / bin_weight
        weighted += bin_weight * abs(confidence - frequency)
    return (weighted / Decimal(len(clusters))).quantize(RATE_QUANTUM)


def _sharpness(resolved):
    if not resolved:
        return None
    uniform = Decimal(1) / Decimal(3)
    values_by_cluster = defaultdict(list)
    for sample in resolved:
        recommendation = sample.recommendation
        values_by_cluster[sample.dependence_cluster_key].append(
            sum(
                (probability - uniform) ** 2
                for probability in (
                    recommendation.probability_up,
                    recommendation.probability_neutral,
                    recommendation.probability_down,
                )
            )
        )
    return _mean([_mean(values) for values in values_by_cluster.values()])


def _cluster_interval(values_by_cluster, *, confidence, value_range):
    if not values_by_cluster:
        return None, None
    cluster_means = [_mean(values) for values in values_by_cluster.values()]
    mean = _mean(cluster_means)
    alpha = Decimal(1) - confidence
    width = Decimal(str(value_range)) * Decimal(
        str(math.sqrt(math.log(2 / float(alpha)) / (2 * len(cluster_means))))
    )
    low = max(Decimal(0), mean - width).quantize(SCORE_QUANTUM)
    high = min(Decimal(str(value_range)), mean + width).quantize(SCORE_QUANTUM)
    return low, high


def _sample_set(samples, assessed_at):
    return _digest(
        [
            {
                "sample": sample.pk,
                "recommendation": sample.recommendation_id,
                "resolution": (
                    sample.recommendation.resolution.pk
                    if hasattr(sample.recommendation, "resolution")
                    and sample.recommendation.resolution.resolved_at <= assessed_at
                    else None
                ),
                "paper_result": (
                    sample.recommendation.paper_result.pk
                    if hasattr(sample.recommendation, "paper_result")
                    and sample.recommendation.paper_result.resolved_at <= assessed_at
                    else None
                ),
            }
            for sample in samples
        ]
    )


def _mechanical_comparison(resolved):
    model_by_cluster = defaultdict(list)
    mechanical_by_cluster = defaultdict(list)
    sample_count = 0
    for sample in resolved:
        recommendation = sample.recommendation
        control = recommendation.control_forecast
        if not control:
            continue
        probabilities = (
            control.probability_up,
            control.probability_neutral,
            control.probability_down,
        )
        cluster = sample.dependence_cluster_key
        model_by_cluster[cluster].append(recommendation.resolution.brier_score)
        mechanical_by_cluster[cluster].append(
            _brier(probabilities, recommendation.resolution.outcome)
        )
        sample_count += 1
    return {
        "model": _mean([_mean(values) for values in model_by_cluster.values()]),
        "mechanical": _mean([_mean(values) for values in mechanical_by_cluster.values()]),
        "sample_count": sample_count,
        "effective_cluster_count": len(mechanical_by_cluster),
    }


def _paired_challenger_metrics(era, resolved, assessed_at):
    if era.kind != ExperimentEra.Kind.CHALLENGER:
        return {}
    champion_samples = ExperimentSample.objects.filter(
        era=era.champion_era,
        recommendation__resolution__isnull=False,
        recommendation__generated_at__lte=assessed_at,
        recommendation__resolution__resolved_at__lte=assessed_at,
    ).select_related("recommendation__resolution", "recommendation__evidence_snapshot")
    champion_by_evidence = {
        (item.recommendation.instrument_id, item.recommendation.evidence_snapshot.sha256): item
        for item in champion_samples
    }
    deltas_by_cluster = defaultdict(list)
    paired = 0
    for sample in resolved:
        key = (
            sample.recommendation.instrument_id,
            sample.recommendation.evidence_snapshot.sha256,
        )
        champion = champion_by_evidence.get(key)
        if not champion:
            continue
        paired += 1
        delta = sample.recommendation.resolution.brier_score - (
            champion.recommendation.resolution.brier_score
        )
        deltas_by_cluster[sample.dependence_cluster_key].append(delta)
    if not paired:
        return {"paired_sample_count": 0, "paired_effective_clusters": 0}
    cluster_means = [_mean(values) for values in deltas_by_cluster.values()]
    mean_delta = _mean(cluster_means)
    confidence = era.evaluation_policy.confidence_level
    alpha = Decimal(1) - confidence
    width = (
        Decimal("1.333334")
        * Decimal(str(math.sqrt(math.log(2 / float(alpha)) / (2 * len(cluster_means)))))
    ).quantize(SCORE_QUANTUM)
    return {
        "paired_sample_count": paired,
        "paired_effective_clusters": len(cluster_means),
        "mean_brier_delta": str(mean_delta),
        "delta_interval_low": str((mean_delta - width).quantize(SCORE_QUANTUM)),
        "delta_interval_high": str((mean_delta + width).quantize(SCORE_QUANTUM)),
    }


def _execution_metrics(samples, policy, assessed_at):
    activated = []
    terminal = 0
    for sample in samples:
        result = getattr(sample.recommendation, "paper_result", None)
        if not result or result.resolved_at > assessed_at:
            continue
        terminal += 1
        if result.outcome != result.Outcome.NOT_ACTIVATED:
            activated.append(sample)
    clusters = {sample.dependence_cluster_key for sample in activated}
    days = max(0, (assessed_at - samples[0].era.starts_at).days) if samples else 0
    ready = (
        len(activated) >= policy.minimum_raw_samples
        and days >= policy.minimum_calendar_days
        and len(clusters) >= policy.minimum_effective_clusters
    )
    return {
        "status": "descriptive_ready" if ready else "collecting",
        "activated_sample_count": len(activated),
        "terminal_sample_count": terminal,
        "effective_cluster_count": len(clusters),
        "observation_days": days,
        "minimum_raw_samples": policy.minimum_raw_samples,
        "minimum_calendar_days": policy.minimum_calendar_days,
        "minimum_effective_clusters": policy.minimum_effective_clusters,
    }


def _assessment_values(era, samples, assessed_at):
    policy = era.evaluation_policy
    resolved = [
        sample
        for sample in samples
        if getattr(sample.recommendation, "resolution", None)
        and sample.recommendation.resolution.resolved_at <= assessed_at
    ]
    raw_count = len(samples)
    resolved_count = len(resolved)
    clusters = defaultdict(list)
    for sample in resolved:
        score = sample.recommendation.resolution.brier_score
        clusters[sample.dependence_cluster_key].append(score)
    effective_count = len(clusters)
    observation_days = max(0, (assessed_at - era.starts_at).days)
    coverage = (Decimal(resolved_count) / Decimal(raw_count) if raw_count else Decimal(0)).quantize(
        RATE_QUANTUM
    )
    mean_brier = _mean([_mean(values) for values in clusters.values()])
    directional = [
        sample
        for sample in resolved
        if sample.recommendation.action != Recommendation.Action.ABSTAIN
    ]
    directional_by_cluster = defaultdict(list)
    for sample in directional:
        directional_by_cluster[sample.dependence_cluster_key].append(
            Decimal(sample.recommendation.resolution.directional_hit is True)
        )
    hit_rate = _mean([_mean(values) for values in directional_by_cluster.values()])
    if hit_rate is not None:
        hit_rate = hit_rate.quantize(RATE_QUANTUM)
    calibration_error = _calibration_error(resolved)
    sharpness = _sharpness(resolved)
    interval_low, interval_high = _cluster_interval(
        clusters,
        confidence=policy.confidence_level,
        value_range=Decimal(2) / Decimal(3),
    )
    mechanical = _mechanical_comparison(resolved)
    paired = _paired_challenger_metrics(era, resolved, assessed_at)
    minimums_met = (
        raw_count >= policy.minimum_raw_samples
        and observation_days >= policy.minimum_calendar_days
        and effective_count >= policy.minimum_effective_clusters
    )
    if not minimums_met:
        status = ExperimentAssessment.Status.COLLECTING
    elif coverage < policy.minimum_resolution_coverage:
        status = ExperimentAssessment.Status.COVERAGE_LIMITED
    elif (
        mean_brier is None
        or interval_high is None
        or interval_high >= UNIFORM_BRIER
        or (
            mechanical["mechanical"] is not None and mechanical["model"] >= mechanical["mechanical"]
        )
        or calibration_error is None
        or calibration_error > policy.maximum_calibration_error
    ):
        status = ExperimentAssessment.Status.GUARDRAIL_FAILED
    elif era.kind == ExperimentEra.Kind.CHAMPION:
        status = ExperimentAssessment.Status.DESCRIPTIVE_READY
    else:
        paired_ready = (
            paired.get("paired_sample_count", 0) >= policy.minimum_raw_samples
            and paired.get("paired_effective_clusters", 0) >= policy.minimum_effective_clusters
            and Decimal(paired.get("delta_interval_high", "1")) < 0
        )
        status = (
            ExperimentAssessment.Status.PROMOTION_ELIGIBLE
            if paired_ready
            else ExperimentAssessment.Status.GUARDRAIL_FAILED
        )
    metrics = {
        "policy": {
            "key": policy.policy_key,
            "version": policy.policy_version,
            "minimum_raw_samples": policy.minimum_raw_samples,
            "minimum_calendar_days": policy.minimum_calendar_days,
            "minimum_effective_clusters": policy.minimum_effective_clusters,
            "minimum_resolution_coverage": str(policy.minimum_resolution_coverage),
            "maximum_calibration_error": str(policy.maximum_calibration_error),
        },
        "dependence": {
            "method": policy.cluster_method,
            "issuance_cluster_count": len({item.issuance_cluster_key for item in resolved}),
            "effective_cluster_count": effective_count,
            "factor_keys": sorted({key for item in resolved for key in item.factor_keys}),
        },
        "interval": {
            "method": policy.interval_method,
            "confidence_level": str(policy.confidence_level),
            "low": str(interval_low) if interval_low is not None else None,
            "high": str(interval_high) if interval_high is not None else None,
        },
        "paired_challenger": paired,
        "mechanical_comparison": {
            "model_brier": str(mechanical["model"]) if mechanical["model"] is not None else None,
            "mechanical_brier": (
                str(mechanical["mechanical"]) if mechanical["mechanical"] is not None else None
            ),
            "sample_count": mechanical["sample_count"],
            "effective_cluster_count": mechanical["effective_cluster_count"],
        },
        "execution": _execution_metrics(samples, policy, assessed_at),
        "descriptive_only": True,
        "active_policy_changed": False,
    }
    return {
        "status": status,
        "raw_sample_count": raw_count,
        "resolved_sample_count": resolved_count,
        "effective_cluster_count": effective_count,
        "observation_days": observation_days,
        "resolution_coverage": coverage,
        "mean_brier_score": mean_brier,
        "uniform_baseline_brier": UNIFORM_BRIER if resolved else None,
        "mechanical_baseline_brier": mechanical["mechanical"],
        "directional_hit_rate": hit_rate,
        "calibration_error": calibration_error,
        "sharpness": sharpness,
        "brier_interval_low": interval_low,
        "brier_interval_high": interval_high,
        "metrics": metrics,
    }


def refresh_experiment_assessment(era, *, assessed_at=None, idempotency_key=None):
    assessed_at = assessed_at or timezone.now()
    samples = list(
        era.samples.filter(recommendation__generated_at__lte=assessed_at).select_related(
            "era__evaluation_policy",
            "recommendation__instrument",
            "recommendation__evidence_snapshot",
            "recommendation__resolution",
            "recommendation__control_forecast",
            "recommendation__paper_result",
        )
    )
    sample_set_sha256 = _digest(
        {
            "samples": _sample_set(samples, assessed_at),
            "assessment_date": assessed_at.date().isoformat(),
        }
    )
    existing = ExperimentAssessment.objects.filter(
        attempt__era=era,
        attempt__sample_set_sha256=sample_set_sha256,
        attempt__status=ExperimentAssessmentAttempt.Status.SUCCEEDED,
    ).first()
    if existing:
        return existing
    idempotency_key = idempotency_key or (
        f"experiment-assessment:{era.pk}:{sample_set_sha256}:{assessed_at.isoformat()}"
    )
    prior_attempt = ExperimentAssessmentAttempt.objects.filter(
        idempotency_key=idempotency_key
    ).first()
    if prior_attempt:
        if prior_attempt.era_id != era.pk or prior_attempt.sample_set_sha256 != sample_set_sha256:
            raise ValidationError("Experiment assessment key was already used")
        return getattr(prior_attempt, "assessment", None)
    try:
        values = _assessment_values(era, samples, assessed_at)
    except Exception:
        ExperimentAssessmentAttempt.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "era": era,
                "sample_set_sha256": sample_set_sha256,
                "status": ExperimentAssessmentAttempt.Status.FAILED,
                "error_code": "assessment_failed",
                "assessed_at": assessed_at,
            },
        )
        return None
    try:
        with transaction.atomic():
            attempt = ExperimentAssessmentAttempt.objects.create(
                era=era,
                idempotency_key=idempotency_key,
                sample_set_sha256=sample_set_sha256,
                status=ExperimentAssessmentAttempt.Status.SUCCEEDED,
                assessed_at=assessed_at,
            )
            previous = ExperimentAssessment.objects.filter(attempt__era=era).first()
            assessment = ExperimentAssessment.objects.create(
                attempt=attempt,
                supersedes=previous,
                created_at=assessed_at,
                **values,
            )
            AuditEvent.objects.create(
                event_type="forecast.experiment_assessed",
                actor="forecasts.experiments.refresh_experiment_assessment",
                subject_type="ExperimentAssessment",
                subject_id=str(assessment.pk),
                payload={
                    "era_id": era.pk,
                    "status": assessment.status,
                    "raw_samples": assessment.raw_sample_count,
                    "effective_clusters": assessment.effective_cluster_count,
                    "sample_set_sha256": sample_set_sha256,
                },
            )
    except IntegrityError:
        concurrent = ExperimentAssessment.objects.filter(
            attempt__era=era,
            attempt__sample_set_sha256=sample_set_sha256,
            attempt__status=ExperimentAssessmentAttempt.Status.SUCCEEDED,
        ).first()
        if concurrent:
            return concurrent
        raise
    return assessment


def refresh_all_experiments(*, assessed_at=None, occurrence_key=None):
    assessed_at = assessed_at or timezone.now()
    results = []
    for era in ExperimentEra.objects.select_related("evaluation_policy", "champion_era"):
        key = f"{occurrence_key}:era:{era.pk}" if occurrence_key else None
        assessment = refresh_experiment_assessment(
            era, assessed_at=assessed_at, idempotency_key=key
        )
        if assessment:
            results.append(assessment)
    return results


@transaction.atomic
def record_promotion_decision(
    era, assessment, *, actor, decision, idempotency_key, rationale="", decided_at=None
):
    existing = PromotionRecord.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if (
            existing.era_id != era.pk
            or existing.assessment_id != assessment.pk
            or existing.actor_id != actor.pk
            or existing.decision != decision
        ):
            raise ValidationError("Promotion decision key was already used")
        return existing
    latest_attempt = ExperimentAssessmentAttempt.objects.filter(era=era).first()
    if (
        not latest_attempt
        or latest_attempt.status != ExperimentAssessmentAttempt.Status.SUCCEEDED
        or not hasattr(latest_attempt, "assessment")
        or latest_attempt.assessment.pk != assessment.pk
    ):
        raise ValidationError("Promotion decisions require the latest successful health refresh")
    latest = ExperimentAssessment.objects.filter(attempt__era=era).first()
    if not latest or latest.pk != assessment.pk:
        raise ValidationError("Promotion decisions require the latest experiment assessment")
    if era.promotion_records.filter(
        decision__in=(PromotionRecord.Decision.REJECT, PromotionRecord.Decision.PROMOTE)
    ).exists():
        raise ValidationError("This challenger already has a terminal owner decision")
    record = PromotionRecord.objects.create(
        era=era,
        assessment=assessment,
        actor=actor,
        decision=decision,
        idempotency_key=idempotency_key,
        rationale=rationale,
        active_policy_changed=False,
        decided_at=decided_at or timezone.now(),
    )
    AuditEvent.objects.create(
        event_type="forecast.promotion_decision_recorded",
        actor=f"user:{actor.pk}",
        subject_type="PromotionRecord",
        subject_id=str(record.pk),
        payload={
            "era_id": era.pk,
            "assessment_id": assessment.pk,
            "decision": decision,
            "active_policy_changed": False,
        },
    )
    return record


def latest_champion_health():
    era = ExperimentEra.objects.filter(kind=ExperimentEra.Kind.CHAMPION).first()
    if not era:
        return None, None
    return era, ExperimentAssessment.objects.filter(attempt__era=era).first()
