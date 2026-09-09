"""Version two assessment: targets first, then conservative weekly clusters."""

from collections import defaultdict
from decimal import Decimal

from forecasts.models import ExperimentAssessment, ExperimentSample
from forecasts.targets import comparable_control, target_endpoint
from market.quality import registered_candle_completion


def assessment_values(era, samples, as_of):
    from forecasts.experiments import (
        UNIFORM_BRIER,
        _brier,
        _calibration_error,
        _cluster_interval,
        _execution_metrics,
        _mean,
        _sharpness,
    )
    from forecasts.lifecycle import project_lifecycle

    policy = era.evaluation_policy
    samples = [
        s
        for s in samples
        if s.assigned_at <= as_of and era.starts_at <= s.recommendation.generated_at <= as_of
    ]
    by_target = defaultdict(list)
    missing_controls = incompatible_controls = 0
    for sample in samples:
        rec = sample.recommendation
        by_target[rec.target_occurrence_id].append(sample)
        if not rec.control_forecast_id:
            missing_controls += 1
        elif not comparable_control(rec, as_of):
            incompatible_controls += 1
    mature = {}
    scored = {}
    missing = cancelled = 0
    clusters = defaultdict(list)
    paired_clusters = defaultdict(list)
    control_clusters = defaultdict(list)
    paired_samples = paired_targets = 0
    resolved_samples = []
    for key, members in by_target.items():
        target = members[0].recommendation.target_occurrence
        if (
            not target
            or registered_candle_completion(
                target_endpoint(target.reference_candle.timestamp, target.horizon_sessions), "D"
            )
            > as_of
        ):
            continue
        mature[key] = members
        resolution = getattr(target, "resolution", None)
        if not resolution or resolution.resolved_at > as_of:
            continue
        if resolution.outcome == "missing":
            missing += 1
            continue
        if resolution.outcome == "cancelled":
            cancelled += 1
            continue
        valid = [
            s
            for s in members
            if getattr(s.recommendation, "resolution", None)
            and s.recommendation.resolution.resolved_at <= as_of
            and s.recommendation.resolution.target_resolution_id == resolution.pk
        ]
        if not valid:
            continue
        scored[key] = valid
        resolved_samples.extend(valid)
        scores = [
            _brier(
                (
                    s.recommendation.probability_up,
                    s.recommendation.probability_neutral,
                    s.recommendation.probability_down,
                ),
                resolution.outcome,
            )
            for s in valid
        ]
        cluster = valid[0].dependence_cluster_key
        clusters[cluster].append(_mean(scores))
        paired = [
            s
            for s in valid
            if comparable_control(s.recommendation, as_of)
            and getattr(s.recommendation.control_forecast, "resolution", None)
            and s.recommendation.control_forecast.resolution.resolved_at <= as_of
            and s.recommendation.control_forecast.resolution.target_resolution_id == resolution.pk
        ]
        if not paired:
            continue
        controls = {
            _brier(
                (
                    s.recommendation.control_forecast.probability_up,
                    s.recommendation.control_forecast.probability_neutral,
                    s.recommendation.control_forecast.probability_down,
                ),
                resolution.outcome,
            )
            for s in paired
        }
        model = _mean(
            [
                _brier(
                    (
                        s.recommendation.probability_up,
                        s.recommendation.probability_neutral,
                        s.recommendation.probability_down,
                    ),
                    resolution.outcome,
                )
                for s in paired
            ]
        )
        paired_clusters[cluster].append(model)
        control_clusters[cluster].append(_mean(list(controls)))
        paired_samples += len(paired)
        paired_targets += 1
    mean = _mean([_mean(v) for v in clusters.values()])
    model = _mean([_mean(v) for v in paired_clusters.values()])
    control = _mean([_mean(v) for v in control_clusters.values()])
    coverage = Decimal(len(scored)) / len(mature) if mature else Decimal(0)
    days = max(0, (as_of - era.starts_at).days)
    low, high = _cluster_interval(
        clusters, confidence=policy.confidence_level, value_range=Decimal(2) / 3
    )
    deltas = {
        k: [a - b for a, b in zip(paired_clusters[k], control_clusters[k], strict=True)]
        for k in paired_clusters
    }
    delta_low, delta_high = _cluster_interval(
        deltas,
        confidence=policy.confidence_level,
        value_range=Decimal(4) / 3,
        support_low=-Decimal(2) / 3,
    )
    calibration = _calibration_error(resolved_samples, target_balanced=True)
    readiness = (
        len(samples) >= policy.minimum_raw_samples
        and len(scored) >= policy.minimum_raw_samples
        and days >= policy.minimum_calendar_days
        and len(clusters) >= policy.minimum_effective_clusters
    )
    status = ExperimentAssessment.Status.COLLECTING
    if readiness:
        if coverage < policy.minimum_resolution_coverage:
            status = ExperimentAssessment.Status.COVERAGE_LIMITED
        elif (
            missing_controls
            or incompatible_controls
            or paired_targets != len(scored)
            or high is None
            or high >= UNIFORM_BRIER
            or model is None
            or model >= control
            or calibration is None
            or calibration > policy.maximum_calibration_error
        ):
            status = ExperimentAssessment.Status.GUARDRAIL_FAILED
        elif era.kind == "champion":
            status = ExperimentAssessment.Status.DESCRIPTIVE_READY
        else:
            status = ExperimentAssessment.Status.GUARDRAIL_FAILED
    # Canonical champion pairing, one mean per target, then a mean per weekly cluster.
    challenger_pairs = defaultdict(list)
    if era.kind == "challenger":
        champion = defaultdict(list)
        for sample in ExperimentSample.objects.filter(
            era=era.champion_era,
            assigned_at__lte=as_of,
            recommendation__generated_at__lte=as_of,
            recommendation__resolution__resolved_at__lte=as_of,
        ):
            rec = sample.recommendation
            if (
                rec.target_occurrence_id
                and rec.resolution.outcome in {"up", "neutral", "down"}
                and comparable_control(rec, as_of)
                and getattr(rec.target_occurrence, "resolution", None)
                and rec.target_occurrence.resolution.resolved_at <= as_of
                and rec.resolution.target_resolution_id == rec.target_occurrence.resolution.pk
                and getattr(rec.control_forecast, "resolution", None)
                and rec.control_forecast.resolution.resolved_at <= as_of
                and rec.control_forecast.resolution.target_resolution_id
                == rec.resolution.target_resolution_id
            ):
                champion[rec.target_occurrence_id].append(rec.resolution.brier_score)
        for key, members in scored.items():
            if key in champion:
                challenger_pairs[members[0].dependence_cluster_key].append(
                    _mean([s.recommendation.resolution.brier_score for s in members])
                    - _mean(champion[key])
                )
        _c_low, c_high = _cluster_interval(
            challenger_pairs,
            confidence=policy.confidence_level,
            value_range=Decimal(4) / 3,
            support_low=-Decimal(2) / 3,
        )
        if (
            readiness
            and coverage >= policy.minimum_resolution_coverage
            and not missing_controls
            and not incompatible_controls
            and paired_targets == len(scored)
            and model is not None
            and model < control
            and high < UNIFORM_BRIER
            and calibration <= policy.maximum_calibration_error
            and len(challenger_pairs) >= policy.minimum_effective_clusters
            and sum(map(len, challenger_pairs.values())) >= policy.minimum_raw_samples
            and c_high is not None
            and c_high < 0
        ):
            status = ExperimentAssessment.Status.PROMOTION_ELIGIBLE
    else:
        c_high = None
    projections = [project_lifecycle(s.recommendation, as_of=as_of) for s in samples]
    population = {
        "assigned_recommendations": len(samples),
        "distinct_targets": len(by_target),
        "immature_targets": len(by_target) - len(mature),
        "mature_targets": len(mature),
        "scored_mature_targets": len(scored),
        "missing_data_mature_targets": missing,
        "cancelled_mature_targets": cancelled,
        "comparable_controls": len(samples) - missing_controls - incompatible_controls,
        "missing_controls": missing_controls,
        "incompatible_controls": incompatible_controls,
        "directional": sum(s.recommendation.action != "abstain" for s in samples),
        "abstentions": sum(s.recommendation.action == "abstain" for s in samples),
        "portfolio_eligible": sum(p["cohort_id"] is not None for p in projections),
        "admitted": sum(p["admission_status"] == "admitted" for p in projections),
        "entered_paper": sum(p["entry_id"] is not None for p in projections),
        "terminal_paper": sum(p["result_id"] is not None for p in projections),
        "effective_issuance_clusters": len(by_target),
        "effective_dependence_clusters": len(clusters),
        "observation_calendar_days": days,
        "mature_recommendations": sum(map(len, mature.values())),
        "scored_mature_recommendations": len(resolved_samples),
        "coverage_basis": "distinct_mature_targets",
    }
    metrics = {
        "populations": population,
        "mechanical_comparison": {
            "sample_count": paired_samples,
            "distinct_target_count": paired_targets,
            "effective_cluster_count": len(paired_clusters),
            "model_brier": str(model) if model is not None else None,
            "mechanical_brier": str(control) if control is not None else None,
            "delta": str(model - control) if model is not None else None,
            "delta_interval_low": str(delta_low) if delta_low is not None else None,
            "delta_interval_high": str(delta_high) if delta_high is not None else None,
            "interval_method": policy.interval_method,
        },
        "paired_challenger": {
            "paired_distinct_targets": sum(map(len, challenger_pairs.values())),
            "paired_effective_clusters": len(challenger_pairs),
            "delta_interval_high": str(c_high) if c_high is not None else None,
        },
        "execution": _execution_metrics(samples, policy, as_of),
        "descriptive_only": True,
        "active_policy_changed": False,
        "weekly_clusters_not_proven_independent": True,
    }
    hit_clusters = defaultdict(list)
    sharpness_clusters = defaultdict(list)
    for members in scored.values():
        cluster = members[0].dependence_cluster_key
        directional = [s for s in members if s.recommendation.action != "abstain"]
        if directional:
            hit_clusters[cluster].append(
                _mean(
                    [
                        Decimal(s.recommendation.resolution.directional_hit is True)
                        for s in directional
                    ]
                )
            )
        sharpness_clusters[cluster].append(_sharpness(members))
    return dict(
        status=status,
        raw_sample_count=len(samples),
        resolved_sample_count=len(resolved_samples),
        effective_cluster_count=len(clusters),
        observation_days=days,
        resolution_coverage=coverage,
        mean_brier_score=mean,
        uniform_baseline_brier=UNIFORM_BRIER if scored else None,
        mechanical_baseline_brier=control,
        directional_hit_rate=_mean([_mean(values) for values in hit_clusters.values()]),
        calibration_error=calibration,
        sharpness=_mean([_mean(values) for values in sharpness_clusters.values()]),
        brier_interval_low=low,
        brier_interval_high=high,
        metrics=metrics,
    )
