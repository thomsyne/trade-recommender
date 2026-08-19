from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from forecasts.models import Forecast
from market.models import (
    AuditEvent,
    Candle,
    IngestionRun,
    Instrument,
    SourceRegistry,
    TechnicalSnapshot,
)
from operations.models import JobOccurrence, ScheduledJob
from research.models import (
    EconomicEvent,
    MacroSeries,
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


@login_required
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


@login_required
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
            "forecasts": forecasts,
            "fixture_mode": bool(candles)
            and candles[-1].ingestion_run.source.name == "Development fixtures",
        },
    )


@login_required
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
    calendar_retrieval = RawRetrieval.objects.filter(
        source_policy__slug="eodhd-calendar", quality=RawRetrieval.Quality.ACCEPTED
    ).first()
    calendar_connected = bool(
        settings.EODHD_API_TOKEN
        and calendar_retrieval
        and timezone.now() - calendar_retrieval.fetched_at <= timedelta(hours=2)
    )
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
            "calendar_events": EconomicEvent.objects.all()[:20],
            "calendar_connected": calendar_connected,
        },
    )


@login_required
def operations(request):
    return render(
        request,
        "dashboard/operations.html",
        {
            "jobs": ScheduledJob.objects.all(),
            "occurrences": JobOccurrence.objects.select_related("scheduled_job")[:20],
            "runs": IngestionRun.objects.select_related("instrument", "source")[:20],
            "events": AuditEvent.objects.all()[:20],
            "sources": SourceRegistry.objects.all(),
            "research_retrievals": RawRetrieval.objects.select_related("source_policy__source")[
                :20
            ],
        },
    )
