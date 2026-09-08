from datetime import UTC, datetime, timedelta

from django.conf import settings

from forecasts.experiments import refresh_all_experiments
from forecasts.interpretations import interpret_due_reviews
from forecasts.paper import resolve_due_paper_trades
from forecasts.recommendations import generate_all_recommendations, resolve_due_recommendations
from forecasts.reviews import build_due_review_cohort
from forecasts.services import resolve_due_forecasts
from market.models import IngestionRun, Instrument, SourceRegistry
from market.oanda import OandaClient
from market.services import store_ingestion, store_oanda_terms
from operations.diagnostics import task_stage
from research.models import MacroSeries, SourcePolicy
from research.services import (
    capture_all_pair_evidence,
    ingest_eodhd_calendar,
    ingest_feed,
    ingest_macro,
    ingest_official_calendar,
)


def execute_task(task_name, parameters):
    if task_name == "market.ingest_oanda":
        return ingest_oanda(parameters)
    if task_name == "market.capture_oanda_terms":
        return capture_oanda_terms()
    if task_name == "research.ingest_feed":
        policy = SourcePolicy.objects.get(slug=parameters["source"])
        with task_stage("research_fetch"):
            return ingest_feed(policy, parameters["url"])
    if task_name == "research.ingest_macro":
        series = MacroSeries.objects.get(code=parameters["series"], enabled=True)
        with task_stage("research_fetch"):
            return ingest_macro(series)
    if task_name == "research.ingest_eodhd_calendar":
        if not settings.EODHD_API_TOKEN:
            raise ValueError("EODHD_API_TOKEN is not configured")
        policy = SourcePolicy.objects.get(slug="eodhd-calendar", state=SourcePolicy.State.ENABLED)
        with task_stage("research_fetch"):
            return ingest_eodhd_calendar(policy, settings.EODHD_API_TOKEN)
    if task_name == "research.ingest_official_calendar":
        policy = SourcePolicy.objects.get(
            slug=parameters["source"], state=SourcePolicy.State.ENABLED
        )
        with task_stage("research_fetch"):
            return ingest_official_calendar(policy, parameters["parser"], parameters["url"])
    if task_name == "research.capture_pair_evidence":
        with task_stage("evidence_capture"):
            return capture_all_pair_evidence()
    if task_name == "forecast.generate_recommendations":
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        with task_stage("recommendation_batch"):
            return generate_all_recommendations()
    if task_name == "forecast.interpret_postmortems":
        if not settings.POSTMORTEM_INTERPRETATION_ENABLED:
            raise ValueError("Postmortem interpretation is disabled")
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        with task_stage("interpretation"):
            return interpret_due_reviews()
    if task_name == "forecast.refresh_experiment_health":
        with task_stage("experiment_refresh"):
            return refresh_all_experiments()
    raise ValueError(f"Unknown task: {task_name}")


def ingest_oanda(parameters):
    instrument = Instrument.objects.get(code=parameters["instrument"])
    if not instrument.ingestion_enabled:
        raise ValueError(f"Live ingestion is disabled for {instrument.code}")
    granularity = parameters["granularity"]
    end = _datetime(parameters.get("to")) if parameters.get("to") else datetime.now(UTC)
    default_days = {"H1": 14, "H4": 14, "D": 90, "W": 730}[granularity]
    days = int(parameters.get("days", default_days))
    start = (
        _datetime(parameters.get("from")) if parameters.get("from") else end - timedelta(days=days)
    )
    source = SourceRegistry.objects.get(name="OANDA v20")
    if not source.enabled:
        raise ValueError("OANDA source is disabled")
    with task_stage("provider_fetch"):
        with OandaClient(settings.OANDA_TOKEN, settings.OANDA_ENVIRONMENT) as client:
            candles, manifest = client.fetch_candles(instrument.code, granularity, start, end)
    with task_stage("store"):
        run = store_ingestion(source, instrument, granularity, start, end, candles, manifest)
    if run.status != IngestionRun.Status.SUCCEEDED:
        raise ValueError(f"OANDA ingestion ended as {run.status}")
    # Recheck decision eligibility after the provider round trip.
    instrument.refresh_from_db(fields=("active",))
    if instrument.active and run.status == IngestionRun.Status.SUCCEEDED and granularity == "D":
        with task_stage("resolve"):
            resolve_due_forecasts(instrument)
            resolve_due_recommendations(instrument)
    if (
        instrument.active
        and run.status == IngestionRun.Status.SUCCEEDED
        and granularity in {"H1", "D"}
    ):
        with task_stage("paper"):
            resolve_due_paper_trades(instrument)
            build_due_review_cohort(instrument=instrument)
    return run


def capture_oanda_terms():
    if not settings.OANDA_ACCOUNT_ID:
        raise ValueError("OANDA_ACCOUNT_ID is not configured")
    if not settings.OANDA_TOKEN:
        raise ValueError("OANDA_TOKEN is not configured")
    codes = list(Instrument.objects.filter(ingestion_enabled=True).values_list("code", flat=True))
    if not codes:
        return []
    with task_stage("provider_fetch"):
        with OandaClient(settings.OANDA_TOKEN, settings.OANDA_ENVIRONMENT) as client:
            payload = client.fetch_account_terms(settings.OANDA_ACCOUNT_ID, codes)
    with task_stage("store"):
        return store_oanda_terms(payload, settings.OANDA_ACCOUNT_ID)


def _datetime(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Ingestion timestamps must be timezone-aware")
    return parsed.astimezone(UTC)
