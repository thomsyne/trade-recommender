import json

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.freshness import series_freshness
from market.management.commands.seed_canonical import INSTRUMENTS, PROSPECTIVE_INSTRUMENT_CODES
from market.models import Candle, CandleObservation, IngestionRun, Instrument, TechnicalSnapshot
from operations.models import ScheduledJob


def forbidden_artifacts(instrument):
    """Artifact roots plus direct children; absent roots imply absent protected descendants."""
    result = {}
    for app_label in ("forecasts", "research"):
        for model in apps.get_app_config(app_label).get_models():
            if app_label == "research" and model.__name__ != "PairEvidenceSnapshot":
                continue
            fields = {field.name for field in model._meta.fields}
            lookup = None
            if "instrument" in fields:
                lookup = "instrument"
            elif app_label == "forecasts" and "recommendation" in fields:
                lookup = "recommendation__instrument"
            elif app_label == "forecasts" and "forecast" in fields:
                lookup = "forecast__instrument"
            extra_paths = {
                "PaperTradeCostAssessment": "result__recommendation__instrument",
                "DeterministicReview": "member__recommendation__instrument",
                "InterpretationAttempt": "member__recommendation__instrument",
                "ReviewInterpretation": "attempt__member__recommendation__instrument",
                "LearningObservation": "interpretation__attempt__member__recommendation__instrument",
                "PortfolioCohort": "members__recommendation__instrument",
                "PortfolioSelection": "selected_members__recommendation__instrument",
                "ReviewCohort": "members__recommendation__instrument",
            }
            lookup = lookup or extra_paths.get(model.__name__)
            if lookup:
                result[model.__name__] = (
                    model.objects.filter(**{lookup: instrument}).distinct().count()
                )
    return result


class Command(BaseCommand):
    help = "Read-only, bounded JSON health and isolation report for eight FX onboarding pairs"

    def handle(self, *args, **options):
        now = timezone.now()
        rows, errors = [], []
        for code, base, quote, order in INSTRUMENTS:
            if code in PROSPECTIVE_INSTRUMENT_CODES:
                continue
            instrument = Instrument.objects.filter(code=code).first()
            if instrument is None:
                errors.append(f"{code}: missing registry")
                rows.append({"instrument": code, "state": "not yet registered"})
                continue
            artifacts = forbidden_artifacts(instrument)
            if instrument.active or any(artifacts.values()):
                errors.append(f"{code}: ingestion-only boundary violated")
            if (instrument.base_currency, instrument.quote_currency, instrument.display_order) != (
                base,
                quote,
                order,
            ):
                errors.append(f"{code}: registry metadata drift")
            for granularity, interval in (("H1", 3600), ("H4", 14400), ("D", 86400), ("W", 604800)):
                name = f"OANDA {code} {granularity}"
                job = ScheduledJob.objects.filter(name=name).first()
                if job is None or (
                    job.task_name,
                    job.parameters,
                    job.interval_seconds,
                    job.schedule_type,
                ) != (
                    "market.ingest_oanda",
                    {"instrument": code, "granularity": granularity},
                    interval,
                    "interval",
                ):
                    errors.append(f"{name}: missing or invalid schedule")
                if job and job.enabled and not instrument.ingestion_enabled:
                    errors.append(f"{name}: enabled schedule for disabled instrument")
                runs = IngestionRun.objects.filter(
                    instrument=instrument, granularity=granularity, dataset_version=None
                )
                latest = runs.order_by("-started_at", "-pk").first()
                success = runs.filter(status="succeeded").order_by("-finished_at", "-pk").first()
                occurrence = (
                    job.occurrences.order_by("-scheduled_for", "-pk").first() if job else None
                )
                freshness = series_freshness(instrument, granularity, now=now, job=job)
                state = "not yet ingested" if freshness.state == "missing" else freshness.state
                if latest and latest.status in ("failed", "quarantined"):
                    state = latest.status
                if (
                    occurrence
                    and occurrence.status == "failed"
                    and (
                        not success
                        or occurrence.finished_at
                        and occurrence.finished_at > success.finished_at
                    )
                ):
                    state = "failed"
                if not instrument.ingestion_enabled or not job or not job.enabled:
                    state = "disabled"
                observations = CandleObservation.objects.filter(
                    instrument=instrument, granularity=granularity
                )
                rows.append(
                    {
                        "instrument": code,
                        "granularity": granularity,
                        "ingestion_enabled": instrument.ingestion_enabled,
                        "decision_enabled": instrument.active,
                        "schedule": name,
                        "schedule_enabled": job.enabled if job else False,
                        "interval_seconds": job.interval_seconds if job else None,
                        "next_occurrence": job.next_run_at if job else None,
                        "last_occurrence": occurrence.scheduled_for if occurrence else None,
                        "last_occurrence_status": occurrence.status if occurrence else None,
                        "latest_successful_ingestion": success.finished_at if success else None,
                        "latest_complete_interval_start": freshness.latest_interval_start,
                        "latest_complete_interval_end": freshness.latest_completion,
                        "candle_count": Candle.objects.filter(
                            instrument=instrument, granularity=granularity, dataset_version=None
                        ).count(),
                        "state": state,
                        "freshness": freshness.state,
                        "failed_runs": runs.filter(status="failed").count(),
                        "quarantined_runs": runs.filter(status="quarantined").count(),
                        "failed_occurrences": job.occurrences.filter(status="failed").count()
                        if job
                        else 0,
                        "revisions": observations.filter(kind="revision").count(),
                        "conflicts": observations.filter(kind="conflict").count(),
                        "technical_snapshot_available": TechnicalSnapshot.objects.filter(
                            instrument=instrument, granularity=granularity
                        ).exists(),
                        "forbidden_artifacts": artifacts,
                    }
                )
        self.stdout.write(
            json.dumps(
                {"as_of": now.isoformat(), "rows": rows, "integrity_errors": errors},
                default=lambda value: value.isoformat(),
                sort_keys=True,
            )
        )
        if errors:
            raise CommandError("FX onboarding integrity checks failed; see report")
