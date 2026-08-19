from datetime import UTC, datetime, timedelta

from django.conf import settings

from forecasts.services import resolve_due_forecasts
from market.models import IngestionRun, Instrument, SourceRegistry
from market.oanda import OandaClient
from market.services import store_ingestion


def execute_task(task_name, parameters):
    if task_name != "market.ingest_oanda":
        raise ValueError(f"Unknown task: {task_name}")
    return ingest_oanda(parameters)


def ingest_oanda(parameters):
    instrument = Instrument.objects.get(code=parameters["instrument"])
    granularity = parameters["granularity"]
    end = _datetime(parameters.get("to")) if parameters.get("to") else datetime.now(UTC)
    days = int(parameters.get("days", 14 if granularity == "H4" else 90))
    start = (
        _datetime(parameters.get("from")) if parameters.get("from") else end - timedelta(days=days)
    )
    source = SourceRegistry.objects.get(name="OANDA v20")
    with OandaClient(settings.OANDA_TOKEN, settings.OANDA_ENVIRONMENT) as client:
        candles, manifest = client.fetch_candles(instrument.code, granularity, start, end)
    run = store_ingestion(source, instrument, granularity, start, end, candles, manifest)
    if run.status == IngestionRun.Status.SUCCEEDED and granularity == "D":
        resolve_due_forecasts(instrument)
    return run


def _datetime(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
