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
        return ingest_feed(policy, parameters["url"])
    if task_name == "research.ingest_macro":
        series = MacroSeries.objects.get(code=parameters["series"], enabled=True)
        return ingest_macro(series)
    if task_name == "research.ingest_eodhd_calendar":
        if not settings.EODHD_API_TOKEN:
            raise ValueError("EODHD_API_TOKEN is not configured")
        policy = SourcePolicy.objects.get(slug="eodhd-calendar", state=SourcePolicy.State.ENABLED)
        return ingest_eodhd_calendar(policy, settings.EODHD_API_TOKEN)
    if task_name == "research.ingest_official_calendar":
        policy = SourcePolicy.objects.get(
            slug=parameters["source"], state=SourcePolicy.State.ENABLED
        )
        return ingest_official_calendar(policy, parameters["parser"], parameters["url"])
    if task_name == "research.capture_pair_evidence":
        return capture_all_pair_evidence()
    if task_name == "forecast.generate_recommendations":
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        return generate_all_recommendations()
    if task_name == "forecast.interpret_postmortems":
        if not settings.POSTMORTEM_INTERPRETATION_ENABLED:
            raise ValueError("Postmortem interpretation is disabled")
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        return interpret_due_reviews()
    if task_name == "forecast.refresh_experiment_health":
        return refresh_all_experiments()
    raise ValueError(f"Unknown task: {task_name}")


def ingest_oanda(parameters):
    instrument = Instrument.objects.get(code=parameters["instrument"])
    granularity = parameters["granularity"]
    end = _datetime(parameters.get("to")) if parameters.get("to") else datetime.now(UTC)
    default_days = {"H1": 14, "H4": 14, "D": 90, "W": 730}[granularity]
    days = int(parameters.get("days", default_days))
    start = (
        _datetime(parameters.get("from")) if parameters.get("from") else end - timedelta(days=days)
    )
    source = SourceRegistry.objects.get(name="OANDA v20")
    with OandaClient(settings.OANDA_TOKEN, settings.OANDA_ENVIRONMENT) as client:
        candles, manifest = client.fetch_candles(instrument.code, granularity, start, end)
    run = store_ingestion(source, instrument, granularity, start, end, candles, manifest)
    if run.status == IngestionRun.Status.SUCCEEDED and granularity == "D":
        resolve_due_forecasts(instrument)
        resolve_due_recommendations(instrument)
    if run.status == IngestionRun.Status.SUCCEEDED and granularity in {"H1", "D"}:
        resolve_due_paper_trades(instrument)
        build_due_review_cohort(instrument=instrument)
    return run


def capture_oanda_terms():
    if not settings.OANDA_ACCOUNT_ID:
        raise ValueError("OANDA_ACCOUNT_ID is not configured")
    codes = list(Instrument.objects.filter(active=True).values_list("code", flat=True))
    with OandaClient(settings.OANDA_TOKEN, settings.OANDA_ENVIRONMENT) as client:
        payload = client.fetch_account_terms(settings.OANDA_ACCOUNT_ID, codes)
    return store_oanda_terms(payload, settings.OANDA_ACCOUNT_ID)


def _datetime(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
