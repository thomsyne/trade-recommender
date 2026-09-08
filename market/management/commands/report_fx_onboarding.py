import json

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.freshness import series_freshness
from market.live_acquisition import LIVE_INTERVALS, MAX_COVERAGE_INTERVALS, complete_live_intervals
from market.live_schedules import validate_live_schedules
from market.management.commands.seed_canonical import INSTRUMENTS, PROSPECTIVE_INSTRUMENT_CODES
from market.models import (
    Candle,
    CandleObservation,
    IngestionRun,
    Instrument,
    SourceRegistry,
    TechnicalSnapshot,
)


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


def window_coverage(run):
    if run is None:
        return {"state": "not_yet_ingested", "expected": None, "observed": 0, "returned": 0}
    result = {
        "run_id": run.pk,
        "requested_from": run.requested_from,
        "requested_to": run.requested_to,
        "returned": run.fetched_count,
    }
    try:
        if run.finished_at is None:
            raise ValueError("Successful run has no completion timestamp")
        expected = set(
            complete_live_intervals(run.requested_from, run.requested_to, run.granularity)
        )
    except ValueError as exc:
        return {
            **result,
            "state": "integrity_violation",
            "reason": str(exc),
            "expected": None,
            "observed": None,
        }
    observed = set(
        CandleObservation.objects.filter(
            instrument=run.instrument,
            source=run.source,
            granularity=run.granularity,
            timestamp__gte=run.requested_from,
            timestamp__lt=run.requested_to,
            observed_at__lte=run.finished_at,
        )
        .order_by("timestamp")
        .values_list("timestamp", flat=True)
        .distinct()[: MAX_COVERAGE_INTERVALS + 1]
    )
    missing, extra = expected - observed, observed - expected
    # No new observation is needed for unchanged overlap. fetched_count still
    # attests this request's returned complete population, independently of storage.
    state = (
        "integrity_violation"
        if extra or run.fetched_count > len(expected)
        else ("partial" if missing or run.fetched_count < len(expected) else "complete")
    )
    return {
        **result,
        "state": state,
        "expected": len(expected),
        "observed": len(observed & expected),
        "missing": len(missing),
        "unexpected": len(extra),
        "missing_sample": sorted(missing)[:5],
        "unexpected_sample": sorted(extra)[:5],
    }


class Command(BaseCommand):
    help = "Read-only bounded collection, coverage, freshness and isolation report"

    def handle(self, *args, **options):
        now = timezone.now()
        rows = []
        source = SourceRegistry.objects.filter(name="OANDA v20").first()
        token_available = bool(settings.OANDA_TOKEN)
        environment_available = settings.OANDA_ENVIRONMENT in {"practice", "live"}
        provider_available = bool(
            source and source.enabled and token_available and environment_available
        )
        instruments = {
            i.code: i for i in Instrument.objects.filter(code__in=[r[0] for r in INSTRUMENTS])
        }
        jobs, schedule_issues, errors = validate_live_schedules(
            instruments, provider_available=provider_available
        )
        for code, base, quote, order in INSTRUMENTS:
            if code in PROSPECTIVE_INSTRUMENT_CODES:
                continue
            instrument = instruments.get(code)
            if instrument is None:
                errors.append(f"{code}: missing registry")
                rows.append({"instrument": code, "state": "integrity_violation"})
                continue
            artifacts = forbidden_artifacts(instrument)
            registry_error = (
                instrument.active
                or any(artifacts.values())
                or (instrument.base_currency, instrument.quote_currency, instrument.display_order)
                != (base, quote, order)
            )
            if registry_error:
                errors.append(f"{code}: registry or ingestion-only boundary violated")
            for granularity, interval in LIVE_INTERVALS.items():
                name = f"OANDA {code} {granularity}"
                job = jobs.get(name)
                issues = schedule_issues[code, granularity]
                runs = IngestionRun.objects.filter(
                    instrument=instrument,
                    granularity=granularity,
                    dataset_version=None,
                    source=source,
                )
                latest = runs.order_by("-started_at", "-pk").first()
                success = runs.filter(status="succeeded").order_by("-finished_at", "-pk").first()
                coverage = window_coverage(success)
                if coverage["state"] in {"partial", "integrity_violation"}:
                    errors.append(f"{name}: {coverage['state']} requested-window coverage")
                occurrence = (
                    job.occurrences.order_by("-scheduled_for", "-pk").first() if job else None
                )
                freshness = series_freshness(instrument, granularity, now=now, job=job)
                observations = CandleObservation.objects.filter(
                    instrument=instrument, granularity=granularity
                )
                revisions = observations.filter(kind="revision").count()
                conflicts = observations.filter(kind="conflict").count()
                snapshot = TechnicalSnapshot.objects.filter(
                    instrument=instrument, granularity=granularity, provenance="observed"
                ).exists()
                collection_state, reason = "available", "Collection enabled"
                if not instrument.ingestion_enabled:
                    collection_state, reason = "disabled", "Instrument collection disabled"
                elif not provider_available:
                    collection_state, reason = (
                        "unavailable",
                        (
                            "OANDA token is not configured"
                            if not token_available
                            else (
                                "OANDA environment is not supported"
                                if not environment_available
                                else "OANDA source unavailable or disabled"
                            )
                        ),
                    )
                elif not job:
                    collection_state, reason = "unavailable", "Canonical schedule missing"
                elif not job.enabled:
                    collection_state, reason = "disabled", "Schedule explicitly disabled"
                state = "not_yet_ingested" if freshness.state == "missing" else freshness.state
                if revisions:
                    state = "revised"
                if conflicts:
                    state = "conflicted"
                if coverage["state"] == "partial":
                    state = "partial"
                if latest and latest.status in {"failed", "quarantined"}:
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
                if collection_state != "available":
                    state = collection_state
                if registry_error or issues or coverage["state"] == "integrity_violation":
                    state = "integrity_violation"
                # Availability remains explicit even if mis-enabled jobs also
                # cause a nonzero integrity result.
                if (
                    not registry_error
                    and collection_state == "unavailable"
                    and provider_available is False
                ):
                    state = "unavailable"
                rows.append(
                    {
                        "instrument": code,
                        "granularity": granularity,
                        "ingestion_enabled": instrument.ingestion_enabled,
                        "decision_enabled": instrument.active,
                        "collection_state": collection_state,
                        "collection_reason": reason,
                        "source_enabled": bool(source and source.enabled),
                        "token_configured": token_available,
                        "schedule": name,
                        "schedule_enabled": job.enabled if job else False,
                        "schedule_integrity_errors": issues,
                        "missed_run_policy": job.missed_run_policy if job else None,
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
                        "coverage": coverage,
                        "failed_runs": runs.filter(status="failed").count(),
                        "quarantined_runs": runs.filter(status="quarantined").count(),
                        "failed_occurrences": job.occurrences.filter(status="failed").count()
                        if job
                        else 0,
                        "revisions": revisions,
                        "conflicts": conflicts,
                        "technical_snapshot_available": snapshot,
                        "forbidden_artifacts": artifacts,
                    }
                )
        self.stdout.write(
            json.dumps(
                {"as_of": now.isoformat(), "rows": rows, "integrity_errors": sorted(set(errors))},
                default=lambda v: v.isoformat(),
                sort_keys=True,
            )
        )
        if errors:
            raise CommandError("FX onboarding integrity checks failed; see report")
