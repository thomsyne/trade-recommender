from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import F, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from dashboard.auth import owner_required
from forecasts.experiments import latest_champion_health, record_promotion_decision
from forecasts.exposure import active_directional_recommendations, build_exposure_report
from forecasts.interpretations import authorize_candidate_hypothesis
from forecasts.models import (
    CandidateHypothesis,
    DeterministicReview,
    ExperimentAssessment,
    ExperimentEra,
    Forecast,
    LearningObservation,
    PaperTradeResult,
    PortfolioCohort,
    PromotionRecord,
    Recommendation,
    RecommendationResolution,
    ReviewCohort,
    ReviewCohortMember,
)
from forecasts.portfolio import cohort_is_open, select_portfolio_cohort
from market.models import (
    AuditEvent,
    Candle,
    IngestionRun,
    Instrument,
    OandaInstrumentTermsSnapshot,
    SourceRegistry,
    TechnicalSnapshot,
)
from operations.models import JobOccurrence, OutboxMessage, OwnerNotification, ScheduledJob
from research.models import (
    EconomicEvent,
    MacroSeries,
    PairEvidenceSnapshot,
    ProviderEvaluation,
    RawRetrieval,
    ResearchDiscrepancy,
    ResearchDocument,
    SourcePolicy,
)


def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        database = cursor.fetchone()[0] == 1
    return JsonResponse({"status": "ok", "database": database})


@owner_required
def today(request):
    cards = []
    for instrument in Instrument.objects.filter(active=True):
        forecast = (
            Forecast.objects.filter(
                instrument=instrument,
                target_contract__product="tactical",
            )
            .select_related("target_contract", "resolution")
            .first()
        )
        snapshot = TechnicalSnapshot.objects.filter(instrument=instrument, granularity="H4").first()
        candle = (
            Candle.objects.filter(instrument=instrument, granularity="H4")
            .select_related("ingestion_run__source")
            .order_by("-timestamp")
            .first()
        )
        cards.append(
            {
                "instrument": instrument,
                "snapshot": snapshot,
                "candle": candle,
                "forecast": forecast,
            }
        )
    return render(
        request,
        "dashboard/today.html",
        {
            "cards": cards,
            "latest_run": IngestionRun.objects.first(),
            "fixture_mode": any(
                card["candle"]
                and card["candle"].ingestion_run.source.name == "Development fixtures"
                for card in cards
            ),
        },
    )


@owner_required
def market_detail(request, code):
    instrument = get_object_or_404(Instrument, code=code, active=True)
    granularity = request.GET.get("granularity", "H4")
    if granularity not in {"H4", "D"}:
        granularity = "H4"
    candles = list(
        Candle.objects.filter(instrument=instrument, granularity=granularity)
        .select_related("ingestion_run__source")
        .order_by("-timestamp")[:120]
    )[::-1]
    snapshot = TechnicalSnapshot.objects.filter(
        instrument=instrument, granularity=granularity
    ).first()
    forecasts = list(
        Forecast.objects.filter(instrument=instrument).select_related(
            "target_contract",
            "evidence_snapshot__anchor_candle",
            "parent",
            "resolution__horizon_candle",
        )[:20]
    )
    tactical_forecast = next(
        (forecast for forecast in forecasts if forecast.target_contract.product == "tactical"),
        None,
    )
    recommendations = list(
        Recommendation.objects.filter(instrument=instrument).select_related(
            "evidence_snapshot",
            "control_forecast",
            "reference_candle",
            "resolution",
            "paper_entry__candle",
            "paper_result__exit_candle",
        )[:20]
    )
    recommendation = recommendations[0] if recommendations else None
    completed_reviews = list(
        DeterministicReview.objects.filter(
            kind=DeterministicReview.Kind.RECONCILIATION,
            superseded_by__isnull=True,
            member__recommendation__instrument=instrument,
        ).select_related("member__recommendation")[:20]
    )
    timeline = sorted(
        [
            {"kind": "recommendation", "at": item.generated_at, "item": item}
            for item in recommendations
        ]
        + [{"kind": "forecast", "at": item.issued_at, "item": item} for item in forecasts]
        + [
            {
                "kind": "review",
                "at": item.assessed_at,
                "item": item,
                "recommendation": item.member.recommendation,
            }
            for item in completed_reviews
        ],
        key=lambda entry: entry["at"],
        reverse=True,
    )
    chart = [
        {
            "time": candle.timestamp.isoformat(),
            "open": float((candle.bid_open + candle.ask_open) / 2),
            "high": float((candle.bid_high + candle.ask_high) / 2),
            "low": float((candle.bid_low + candle.ask_low) / 2),
            "close": float(candle.midpoint_close),
        }
        for candle in candles
    ]
    evidence = PairEvidenceSnapshot.objects.filter(instrument=instrument).first()
    intermarket = []
    pair_macro = []
    evidence_source_count = 0
    evidence_fresh = False
    if evidence:
        context_indicators = {
            MacroSeries.Indicator.EQUITY,
            MacroSeries.Indicator.VOLATILITY,
            MacroSeries.Indicator.CRYPTO,
            MacroSeries.Indicator.COMMODITY,
            MacroSeries.Indicator.YIELD,
            MacroSeries.Indicator.DOLLAR,
        }
        for item in evidence.payload.get("macro_and_intermarket", []):
            (intermarket if item["indicator"] in context_indicators else pair_macro).append(item)
        source_names = {
            item["source"] for item in evidence.payload.get("macro_and_intermarket", [])
        }
        source_names.update(item["source"] for item in evidence.payload.get("recent_news", []))
        source_names.update(item["source"] for item in evidence.payload.get("upcoming_events", []))
        evidence_source_count = len(source_names)
        evidence_fresh = timezone.now() - evidence.captured_at <= timedelta(hours=8)
    return render(
        request,
        "dashboard/market_detail.html",
        {
            "instrument": instrument,
            "snapshot": snapshot,
            "candles": candles,
            "chart": chart,
            "granularity": granularity,
            "forecast": tactical_forecast,
            "recommendation": recommendation,
            "recommendations": recommendations,
            "timeline": timeline,
            "forecasts": forecasts,
            "evidence": evidence,
            "evidence_fresh": evidence_fresh,
            "evidence_source_count": evidence_source_count,
            "intermarket": intermarket,
            "pair_macro": pair_macro,
            "fixture_mode": bool(candles)
            and candles[-1].ingestion_run.source.name == "Development fixtures",
        },
    )


@owner_required
def reviews(request):
    selected_code = request.GET.get("instrument", "")
    instruments = list(Instrument.objects.filter(active=True))
    if selected_code and selected_code not in {item.code for item in instruments}:
        selected_code = ""
    members = ReviewCohortMember.objects.select_related(
        "recommendation__instrument",
        "recommendation__evidence_snapshot",
    ).prefetch_related(
        "reviews__supersedes",
        "interpretation_attempts__interpretation__source_proposals",
    )
    cohorts_query = ReviewCohort.objects.all()
    if selected_code:
        members = members.filter(recommendation__instrument__code=selected_code)
        cohorts_query = cohorts_query.filter(
            members__recommendation__instrument__code=selected_code
        ).distinct()
    cohorts = []
    timeline = []
    complete_count = 0
    missing_count = 0
    correction_count = 0
    interpreted_count = 0
    blocked_count = 0
    for cohort in cohorts_query.prefetch_related(Prefetch("members", queryset=members))[:20]:
        cohort_members = []
        for member in cohort.members.all():
            all_reviews = list(member.reviews.all())
            current = {}
            for review in all_reviews:
                current.setdefault(review.kind, review)
                timeline.append(
                    {
                        "review": review,
                        "recommendation": member.recommendation,
                        "label": review.get_kind_display(),
                    }
                )
                correction_count += bool(review.supersedes_id)
            for review in current.values():
                if review.coverage == DeterministicReview.Coverage.MISSING:
                    missing_count += 1
                else:
                    complete_count += 1
            thesis = current.get(DeterministicReview.Kind.THESIS)
            execution = current.get(DeterministicReview.Kind.EXECUTION)
            reconciliation = current.get(DeterministicReview.Kind.RECONCILIATION)
            interpretation = None
            latest_attempt = member.interpretation_attempts.first()
            for attempt in member.interpretation_attempts.all():
                candidate = getattr(attempt, "interpretation", None)
                if (
                    candidate
                    and reconciliation
                    and candidate.reconciliation_review_id == reconciliation.pk
                ):
                    interpretation = candidate
                    break
            if interpretation:
                interpreted_count += 1
            elif latest_attempt:
                blocked_count += 1
            lineage = thesis.source_lineage if thesis else {}
            cohort_members.append(
                {
                    "member": member,
                    "inclusion_label": member.inclusion_reason.replace("_", " ").title(),
                    "thesis": thesis,
                    "execution": execution,
                    "reconciliation": reconciliation,
                    "interpretation": interpretation,
                    "latest_attempt": latest_attempt,
                    "source_proposals": (
                        list(interpretation.source_proposals.all()) if interpretation else []
                    ),
                    "thesis_label": (
                        thesis.facts["classification"].replace("_", " ").title()
                        if thesis
                        else "Unavailable"
                    ),
                    "execution_label": (
                        execution.facts["readiness_reason"].replace("_", " ").title()
                        if execution
                        else "Unavailable"
                    ),
                    "execution_terminal_label": (
                        (execution.facts.get("terminal_lifecycle_state") or "unobserved")
                        .replace("_", " ")
                        .title()
                        if execution
                        else "Unobserved"
                    ),
                    "reconciliation_label": (
                        reconciliation.facts["classification"].replace("_", " ").title()
                        if reconciliation
                        else "Unavailable"
                    ),
                    "lineage_count": sum(
                        len(value) for value in lineage.values() if isinstance(value, list)
                    ),
                }
            )
        cohorts.append({"cohort": cohort, "members": cohort_members})
    timeline.sort(key=lambda item: (item["review"].assessed_at, item["review"].pk), reverse=True)
    observations = LearningObservation.objects.select_related(
        "interpretation__attempt__member__recommendation__instrument"
    )
    if selected_code:
        observations = observations.filter(
            interpretation__attempt__member__recommendation__instrument__code=selected_code
        )
    observation_rows = []
    for observation in observations[:50]:
        cluster_count = (
            LearningObservation.objects.filter(pattern_key=observation.pattern_key)
            .values("issuance_cluster_key")
            .distinct()
            .count()
        )
        observation_rows.append({"observation": observation, "cluster_count": cluster_count})
    hypotheses = CandidateHypothesis.objects.prefetch_related(
        "observations",
    ).select_related("authorization")
    return render(
        request,
        "dashboard/reviews.html",
        {
            "cohorts": cohorts,
            "timeline": timeline,
            "instruments": instruments,
            "selected_code": selected_code,
            "complete_count": complete_count,
            "missing_count": missing_count,
            "correction_count": correction_count,
            "interpreted_count": interpreted_count,
            "blocked_count": blocked_count,
            "observation_rows": observation_rows,
            "hypotheses": hypotheses,
            "minimum_hypothesis_clusters": 5,
        },
    )


@owner_required
@require_POST
def authorize_challenger(request, hypothesis_id):
    hypothesis = get_object_or_404(CandidateHypothesis, pk=hypothesis_id)
    try:
        authorize_candidate_hypothesis(
            hypothesis,
            actor=request.user,
            idempotency_key=f"candidate-hypothesis:{hypothesis.pk}:{hypothesis.evidence_sha256}",
        )
    except ValidationError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            "Challenger authorized for prospective design only; no active policy changed.",
        )
    return redirect(f"{reverse('reviews')}#hypothesis-{hypothesis.pk}")


@owner_required
def research(request):
    documents = ResearchDocument.objects.order_by(
        F("published_at").desc(nulls_last=True), "-first_observed_at"
    ).prefetch_related("representations__retrieval__source_policy__source")[:30]
    entries = []
    for document in documents:
        representation = document.representations.first()
        if representation:
            entries.append({"document": document, "representation": representation})
    series_rows = list(
        MacroSeries.objects.filter(enabled=True).select_related("source_policy__source")
    )
    policy_rates = [
        {"series": series, "observation": series.observations.first()}
        for series in series_rows
        if series.indicator == MacroSeries.Indicator.POLICY_RATE
    ]
    macro_regions = []
    for jurisdiction, label in (
        ("CA", "Canada"),
        ("US", "United States"),
        ("GB", "United Kingdom"),
        ("EU", "Euro area"),
    ):
        indicators = []
        for indicator, indicator_label in (
            (MacroSeries.Indicator.CPI, "Inflation"),
            (MacroSeries.Indicator.UNEMPLOYMENT, "Unemployment"),
            (MacroSeries.Indicator.GDP, "GDP"),
            (MacroSeries.Indicator.HOUSING, "Housing"),
        ):
            series = next(
                (
                    item
                    for item in series_rows
                    if item.source_policy.jurisdiction == jurisdiction
                    and item.indicator == indicator
                ),
                None,
            )
            indicators.append(
                {
                    "label": indicator_label,
                    "series": series,
                    "observation": series.observations.first() if series else None,
                }
            )
        macro_regions.append(
            {"jurisdiction": jurisdiction, "label": label, "indicators": indicators}
        )
    policies = list(SourcePolicy.objects.select_related("source"))
    for policy in policies:
        policy.latest_retrieval = RawRetrieval.objects.filter(source_policy=policy).first()
        policy.fresh = bool(
            policy.latest_retrieval
            and timezone.now() - policy.latest_retrieval.fetched_at <= timedelta(hours=36)
        )
    calendar_specs = (
        (
            "CA",
            "Statistics Canada",
            "statistics-canada",
            "schedule-key_indicators-eng.json",
            "CPI · labour · GDP · building permits",
            "Housing starts remain outside this statistical release schedule.",
        ),
        (
            "US",
            "BEA",
            "us-bea",
            "release_dates.json",
            "GDP · personal income/PCE",
            "BLS inflation/labour and Census housing remain explicit gaps.",
        ),
        (
            "GB",
            "ONS",
            "uk-ons",
            "releasecalendar",
            "CPI · labour · GDP · house prices",
            "This is the statistical schedule; policy decisions are collected separately.",
        ),
        (
            "EU",
            "Eurostat",
            "eurostat",
            "eventsIcal",
            "HICP · unemployment · GDP · house prices",
            "Eurostat supplies dates, not exact release times.",
        ),
        (
            "CA",
            "Bank of Canada",
            "bank-of-canada",
            "upcoming-events",
            "Policy-rate decisions",
            "Exact Eastern release time is retained when the Bank supplies it.",
        ),
        (
            "US",
            "Federal Reserve",
            "federal-reserve",
            "fomccalendars",
            "FOMC policy decisions",
            "Meeting dates are retained as date-only; no release time is invented.",
        ),
        (
            "GB",
            "Bank of England",
            "bank-of-england",
            "upcoming-mpc-dates",
            "MPC policy decisions",
            "Decision dates are retained as date-only; no release time is invented.",
        ),
        (
            "EU",
            "European Central Bank",
            "european-central-bank",
            "mgcgc",
            "Governing Council policy decisions",
            "Decision dates are retained as date-only; no release time is invented.",
        ),
    )
    calendar_sources = []
    for jurisdiction, name, slug, url_fragment, coverage, gap in calendar_specs:
        retrieval = (
            RawRetrieval.objects.filter(
                source_policy__slug=slug,
                url__contains=url_fragment,
                quality=RawRetrieval.Quality.ACCEPTED,
            )
            .order_by("-fetched_at")
            .first()
        )
        fresh = bool(retrieval and timezone.now() - retrieval.fetched_at <= timedelta(hours=36))
        calendar_sources.append(
            {
                "jurisdiction": jurisdiction,
                "name": name,
                "coverage": coverage,
                "gap": gap,
                "retrieval": retrieval,
                "fresh": fresh,
            }
        )
    calendar_rows = list(
        EconomicEvent.objects.filter(event_at__gte=timezone.now() - timedelta(days=1))
        .select_related("series")
        .order_by("provider_event_key", "-first_observed_at")
    )
    latest_events = {}
    for event in calendar_rows:
        latest_events.setdefault(event.provider_event_key, event)
    semantic_events = {}
    for event in latest_events.values():
        semantic_key = (event.country, event.event_type, event.event_at, event.period)
        current = semantic_events.get(semantic_key)
        if not current or event.first_observed_at > current.first_observed_at:
            semantic_events[semantic_key] = event
    calendar_events = sorted(semantic_events.values(), key=lambda event: event.event_at)[:20]
    for event in calendar_events:
        event.latest_observation = event.series.observations.first() if event.series else None
    calendar_connected = all(item["fresh"] for item in calendar_sources)
    calendar_coverage_count = sum(bool(item["retrieval"]) for item in calendar_sources)
    return render(
        request,
        "dashboard/research.html",
        {
            "entries": entries,
            "policy_rates": policy_rates,
            "macro_regions": macro_regions,
            "policies": policies,
            "retrieval_count": RawRetrieval.objects.count(),
            "conflict_count": ResearchDiscrepancy.objects.filter(kind="conflict").count(),
            "quarantine_count": ResearchDocument.objects.filter(quality="quarantined").count(),
            "provider_evaluations": ProviderEvaluation.objects.all(),
            "calendar_events": calendar_events,
            "calendar_sources": calendar_sources,
            "calendar_connected": calendar_connected,
            "calendar_coverage_count": calendar_coverage_count,
            "calendar_source_count": len(calendar_sources),
        },
    )


@owner_required
def calibration(request):
    experiment_era, experiment_assessment = latest_champion_health()
    experiment_attempt = experiment_era.assessment_attempts.first() if experiment_era else None
    experiment_refresh_failed = bool(
        experiment_attempt and experiment_attempt.status == experiment_attempt.Status.FAILED
    )
    experiment_rows = []
    for era in ExperimentEra.objects.select_related(
        "method", "evaluation_policy", "authorization__hypothesis", "champion_era"
    ).prefetch_related("promotion_records"):
        latest_attempt = era.assessment_attempts.first()
        assessment = ExperimentAssessment.objects.filter(attempt__era=era).first()
        experiment_rows.append(
            {
                "era": era,
                "assessment": assessment,
                "latest_attempt": latest_attempt,
                "refresh_failed": bool(
                    latest_attempt and latest_attempt.status == latest_attempt.Status.FAILED
                ),
                "latest_decision": era.promotion_records.first(),
            }
        )
    policy = experiment_era.evaluation_policy if experiment_era else None
    health_status = (
        experiment_assessment.status
        if experiment_assessment
        else ExperimentAssessment.Status.COLLECTING
    )
    health_status_label = (
        "REFRESH FAILED"
        if experiment_refresh_failed
        else {
            ExperimentAssessment.Status.COLLECTING: "COLLECTING",
            ExperimentAssessment.Status.COVERAGE_LIMITED: "COVERAGE LIMITED",
            ExperimentAssessment.Status.GUARDRAIL_FAILED: "GUARDRAIL FAILED",
            ExperimentAssessment.Status.DESCRIPTIVE_READY: "DESCRIPTIVE READY",
            ExperimentAssessment.Status.PROMOTION_ELIGIBLE: "OWNER REVIEW",
        }[health_status]
    )
    resolutions = list(
        RecommendationResolution.objects.select_related("recommendation__instrument")
    )
    directional = [
        item for item in resolutions if item.recommendation.action != Recommendation.Action.ABSTAIN
    ]
    hits = sum(item.directional_hit is True for item in directional)
    pair_rows = []
    for instrument in Instrument.objects.filter(active=True):
        pair_resolutions = [
            item for item in resolutions if item.recommendation.instrument_id == instrument.pk
        ]
        pair_directional = [
            item
            for item in pair_resolutions
            if item.recommendation.action != Recommendation.Action.ABSTAIN
        ]
        pair_hits = sum(item.directional_hit is True for item in pair_directional)
        pair_rows.append(
            {
                "instrument": instrument,
                "count": len(pair_resolutions),
                "directional_count": len(pair_directional),
                "hit_rate": (pair_hits * 100 / len(pair_directional) if pair_directional else None),
                "mean_brier": (
                    sum(item.brier_score for item in pair_resolutions) / len(pair_resolutions)
                    if pair_resolutions
                    else None
                ),
            }
        )
    bins = []
    for lower, upper in ((0, 49), (50, 59), (60, 69), (70, 79), (80, 100)):
        members = [
            item for item in directional if lower <= item.recommendation.confidence_percent <= upper
        ]
        bins.append(
            {
                "label": f"{lower}–{upper}%",
                "count": len(members),
                "mean_confidence": (
                    sum(item.recommendation.confidence_percent for item in members) / len(members)
                    if members
                    else None
                ),
                "hit_rate": (
                    sum(item.directional_hit is True for item in members) * 100 / len(members)
                    if members
                    else None
                ),
            }
        )
    return render(
        request,
        "dashboard/calibration.html",
        {
            "resolved_count": len(resolutions),
            "directional_count": len(directional),
            "hit_rate": hits * 100 / len(directional) if directional else None,
            "mean_brier": (
                sum(item.brier_score for item in resolutions) / len(resolutions)
                if resolutions
                else None
            ),
            "experiment_era": experiment_era,
            "experiment_assessment": experiment_assessment,
            "experiment_attempt": experiment_attempt,
            "experiment_refresh_failed": experiment_refresh_failed,
            "experiment_rows": experiment_rows,
            "experiment_policy": policy,
            "health_status": health_status,
            "health_status_label": health_status_label,
            "health_ready": not experiment_refresh_failed
            and health_status
            in {
                ExperimentAssessment.Status.DESCRIPTIVE_READY,
                ExperimentAssessment.Status.PROMOTION_ELIGIBLE,
            },
            "open_count": Recommendation.objects.filter(
                contract_version__in=(2, 3), resolution__isnull=True
            ).count(),
            "legacy_count": Recommendation.objects.filter(contract_version__lt=2).count(),
            "pair_rows": pair_rows,
            "bins": bins,
            "recent_resolutions": resolutions[:20],
        },
    )


@owner_required
def paper_trades(request):
    experiment_era, experiment_assessment = latest_champion_health()
    execution_health = (
        experiment_assessment.metrics.get("execution", {}) if experiment_assessment else {}
    )
    recommendations = list(
        Recommendation.objects.filter(
            contract_version__in=(2, 3),
            action__in=(Recommendation.Action.BUY, Recommendation.Action.SELL),
        )
        .select_related(
            "instrument",
            "paper_entry__candle",
            "paper_result__exit_candle",
            "paper_result__horizon_candle",
        )
        .prefetch_related("paper_result__cost_assessments")
    )
    rows = []
    for recommendation in recommendations:
        entry = getattr(recommendation, "paper_entry", None)
        result = getattr(recommendation, "paper_result", None)
        cost = getattr(result, "cost_assessment", None) if result else None
        if result:
            state = result.outcome
            state_label = result.get_outcome_display()
        elif entry:
            state = "entered"
            state_label = "Entered; monitoring exit"
        else:
            state = "waiting"
            state_label = "Waiting for entry"
        rows.append(
            {
                "recommendation": recommendation,
                "entry": entry,
                "result": result,
                "cost": cost,
                "state": state,
                "state_label": state_label,
            }
        )
    results = [row["result"] for row in rows if row["result"]]
    executed_results = [
        result for result in results if result.outcome != PaperTradeResult.Outcome.NOT_ACTIVATED
    ]
    cost_assessments = [row["cost"] for row in rows if row["cost"]]
    gross_pips = sum(
        (result.gross_pips for result in executed_results if result.gross_pips is not None),
        start=0,
    )
    return render(
        request,
        "dashboard/paper_trades.html",
        {
            "rows": rows,
            "waiting_count": sum(row["state"] == "waiting" for row in rows),
            "entered_count": sum(row["state"] == "entered" for row in rows),
            "resolved_count": len(results),
            "executed_count": len(executed_results),
            "target_count": sum(
                result.outcome == PaperTradeResult.Outcome.TARGET for result in results
            ),
            "gross_pips": gross_pips,
            "costed_count": len(cost_assessments),
            "base_net_pips": sum(
                (assessment.base_net_pips for assessment in cost_assessments), start=0
            ),
            "conservative_net_pips": sum(
                (assessment.conservative_net_pips for assessment in cost_assessments), start=0
            ),
            "experiment_era": experiment_era,
            "execution_health": execution_health,
        },
    )


@owner_required
@require_POST
def decide_experiment(request, era_id, assessment_id):
    era = get_object_or_404(ExperimentEra, pk=era_id)
    assessment = get_object_or_404(ExperimentAssessment, pk=assessment_id)
    decision = request.POST.get("decision", "")
    if decision not in PromotionRecord.Decision.values:
        messages.error(request, "Unknown experiment decision.")
        return redirect(f"{reverse('calibration')}#experiment-{era.pk}")
    try:
        record_promotion_decision(
            era,
            assessment,
            actor=request.user,
            decision=decision,
            rationale=request.POST.get("rationale", "")[:500],
            idempotency_key=f"experiment-decision:{era.pk}:{assessment.pk}:{decision}",
        )
    except ValidationError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            "Experiment decision recorded. No active method or policy was changed.",
        )
    return redirect(f"{reverse('calibration')}#experiment-{era.pk}")


@owner_required
def exposure(request):
    report = build_exposure_report(active_directional_recommendations())
    return render(request, "dashboard/exposure.html", report)


@owner_required
def inbox(request):
    cohorts = []
    for cohort in PortfolioCohort.objects.prefetch_related(
        "members__recommendation__instrument",
        "members__position_size",
        "selections__selected_members",
    )[:12]:
        latest = cohort.selections.first()
        selected_ids = (
            set(latest.selected_members.values_list("recommendation_id", flat=True))
            if latest
            else set()
        )
        cohorts.append(
            {
                "cohort": cohort,
                "members": list(cohort.members.all()),
                "selection": latest,
                "selected_ids": selected_ids,
                "open": cohort_is_open(cohort),
            }
        )
    return render(
        request,
        "dashboard/inbox.html",
        {
            "cohorts": cohorts,
            "notifications": OwnerNotification.objects.all()[:30],
        },
    )


@owner_required
@require_POST
def select_cohort(request, cohort_id):
    cohort = get_object_or_404(PortfolioCohort, pk=cohort_id)
    try:
        selection = select_portfolio_cohort(
            cohort,
            request.POST.getlist("recommendation"),
            actor=request.user,
        )
    except (ValidationError, ValueError) as error:
        messages.error(
            request, "; ".join(error.messages) if hasattr(error, "messages") else str(error)
        )
    else:
        count = selection.selected_members.count()
        messages.success(
            request,
            f"Selection recorded. {count} setup{'s' if count != 1 else ''} admitted to paper monitoring.",
        )
    return redirect("inbox")


@owner_required
def operations(request):
    recommendation_run = JobOccurrence.objects.filter(
        task_name="forecast.generate_recommendations"
    ).first()
    failed_recommendation_runs = JobOccurrence.objects.filter(
        task_name="forecast.generate_recommendations",
        status=JobOccurrence.Status.FAILED,
        created_at__gte=timezone.now() - timedelta(hours=24),
    ).count()
    return render(
        request,
        "dashboard/operations.html",
        {
            "jobs": ScheduledJob.objects.all(),
            "occurrences": JobOccurrence.objects.select_related("scheduled_job")[:20],
            "runs": IngestionRun.objects.select_related("instrument", "source")[:20],
            "events": AuditEvent.objects.all()[:20],
            "sources": SourceRegistry.objects.all(),
            "oanda_terms": OandaInstrumentTermsSnapshot.objects.select_related("instrument")[:4],
            "research_retrievals": RawRetrieval.objects.select_related("source_policy__source")[
                :20
            ],
            "recommendation_run": recommendation_run,
            "failed_recommendation_runs": failed_recommendation_runs,
            "active_pair_count": Instrument.objects.filter(active=True).count(),
            "outbox_messages": OutboxMessage.objects.all()[:20],
            "email_delivery_enabled": settings.EMAIL_DELIVERY_ENABLED,
        },
    )
