"""Honest scheduled-job state projection for the operations surface.

Every job maps onto exactly one of these states:

``scheduled``               enabled, no work in flight, last occurrence (if any) succeeded
``queued``                  an occurrence is waiting for a worker (first attempt)
``running``                 an occurrence holds a live worker lease
``retrying``                an occurrence failed at least once and is waiting to retry
``failed``                  the latest occurrence failed terminally and nothing recovered it
``recovered``               a terminal failure exists but a later occurrence succeeded
``disabled_intentional``    switched off by explicit product policy
``disabled_capability``     switched off because the provider/subscription cannot supply it
``disabled_configuration``  switched off because required configuration is absent
``stale``                   a running occurrence stopped heartbeating or the job is overdue

Disabled reasons are derived from data (instrument scope, source-policy
state, provider evaluations) and from the same settings the seed commands use
to decide ``enabled``; nothing is labelled "waiting for credential" by default.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from operations.models import JobOccurrence, ScheduledJob

STALE_HEARTBEAT = timedelta(minutes=10)
OVERDUE_GRACE = timedelta(minutes=10)

STATE_LABELS = {
    "scheduled": "SCHEDULED",
    "queued": "QUEUED",
    "running": "RUNNING",
    "retrying": "RETRYING",
    "failed": "FAILED",
    "recovered": "RECOVERED",
    "disabled_intentional": "DISABLED — INTENTIONAL",
    "disabled_capability": "DISABLED — CAPABILITY",
    "disabled_configuration": "DISABLED — CONFIGURATION",
    "stale": "STALE",
}
STATE_TONES = {
    "scheduled": "healthy",
    "queued": "foundation",
    "running": "foundation",
    "retrying": "warning",
    "failed": "warning",
    "recovered": "healthy",
    "disabled_intentional": "disabled",
    "disabled_capability": "disabled",
    "disabled_configuration": "warning",
    "stale": "warning",
}


@dataclass(frozen=True)
class JobState:
    job: ScheduledJob
    state: str
    reason: str
    latest_occurrence: JobOccurrence | None
    recovered_by: JobOccurrence | None
    next_run_at: object

    @property
    def job_id(self):
        return self.job.pk

    @property
    def label(self):
        return STATE_LABELS[self.state]

    @property
    def tone(self):
        return STATE_TONES[self.state]

    @property
    def is_disabled(self):
        return self.state.startswith("disabled_")


def disabled_reason(job):
    """Return (state, human reason) for a disabled job, derived from data and policy."""
    from market.models import Instrument
    from research.models import ProviderEvaluation, SourcePolicy

    task = job.task_name
    if task == "market.ingest_oanda":
        code = job.parameters.get("instrument", "")
        instrument = Instrument.objects.filter(code=code).first()
        if instrument is not None and not instrument.ingestion_enabled:
            return (
                "disabled_intentional",
                f"Live collection is disabled for {code} (ingestion_enabled=False).",
            )
        if not settings.OANDA_TOKEN:
            return ("disabled_configuration", "OANDA_TOKEN is not configured.")
        return ("disabled_intentional", "Disabled in the schedule registry.")
    if task == "market.capture_oanda_terms":
        missing = [
            name
            for name, value in (
                ("OANDA_TOKEN", settings.OANDA_TOKEN),
                ("OANDA_ACCOUNT_ID", settings.OANDA_ACCOUNT_ID),
            )
            if not value
        ]
        if missing:
            return ("disabled_configuration", f"{' and '.join(missing)} not configured.")
        return ("disabled_intentional", "Disabled in the schedule registry.")
    if task == "research.ingest_eodhd_calendar":
        evaluation = ProviderEvaluation.objects.filter(
            category="economic-calendar", provider="EODHD"
        ).first()
        policy = SourcePolicy.objects.filter(slug="eodhd-calendar").first()
        if evaluation is not None and evaluation.status == ProviderEvaluation.Status.REJECTED:
            return (
                "disabled_capability",
                "EODHD economic events are unavailable under the current subscription; "
                "official statistical schedules are the selected source.",
            )
        if policy is not None and policy.state == SourcePolicy.State.DISABLED:
            return ("disabled_capability", "EODHD source policy is disabled.")
        if not settings.EODHD_API_TOKEN:
            return ("disabled_configuration", "EODHD_API_TOKEN is not configured.")
        return ("disabled_intentional", "Disabled in the schedule registry.")
    if task == "forecast.generate_recommendations":
        if not settings.RECOMMENDATION_SCHEDULE_ENABLED:
            return (
                "disabled_intentional",
                "Scheduled recommendation generation is switched off "
                "(RECOMMENDATION_SCHEDULE_ENABLED).",
            )
        if not settings.ANTHROPIC_API_KEY:
            return ("disabled_configuration", "ANTHROPIC_API_KEY is not configured.")
        return ("disabled_intentional", "Disabled in the schedule registry.")
    if task == "forecast.interpret_postmortems":
        if not settings.POSTMORTEM_INTERPRETATION_ENABLED:
            return (
                "disabled_intentional",
                "Postmortem interpretation is intentionally disabled "
                "(POSTMORTEM_INTERPRETATION_ENABLED).",
            )
        if not settings.ANTHROPIC_API_KEY:
            return ("disabled_configuration", "ANTHROPIC_API_KEY is not configured.")
        return ("disabled_intentional", "Disabled in the schedule registry.")
    if task in {
        "research.ingest_feed",
        "research.ingest_macro",
        "research.ingest_official_calendar",
    }:
        slug = job.parameters.get("source") or job.parameters.get("series", "")
        policy = SourcePolicy.objects.filter(slug=slug).first()
        if policy is not None and policy.state != SourcePolicy.State.ENABLED:
            return ("disabled_capability", f"Source policy '{slug}' is not enabled.")
        return ("disabled_intentional", "Disabled in the schedule registry.")
    return ("disabled_intentional", "Disabled in the schedule registry.")


def project_job_state(job, *, now=None, occurrences=None):
    """Project one job onto a single honest state."""
    now = now or timezone.now()
    if occurrences is None:
        occurrences = list(job.occurrences.order_by("-scheduled_for", "-id")[:25])
    latest = occurrences[0] if occurrences else None
    if not job.enabled:
        state, reason = disabled_reason(job)
        return JobState(job, state, reason, latest, None, None)

    running = next((o for o in occurrences if o.status == JobOccurrence.Status.RUNNING), None)
    if running is not None:
        heartbeat = running.heartbeat_at or running.started_at
        if heartbeat is None or now - heartbeat > STALE_HEARTBEAT:
            return JobState(
                job,
                "stale",
                "Running occurrence stopped heartbeating.",
                running,
                None,
                job.next_run_at,
            )
        return JobState(
            job,
            "running",
            f"Attempt {running.attempts} of {running.max_attempts} in progress.",
            running,
            None,
            job.next_run_at,
        )
    queued = next((o for o in occurrences if o.status == JobOccurrence.Status.QUEUED), None)
    if queued is not None:
        if queued.attempts > 0:
            return JobState(
                job,
                "retrying",
                f"Attempt {queued.attempts} failed; retry {queued.attempts + 1} of "
                f"{queued.max_attempts} waits until {queued.available_at:%b %d %H:%M} UTC.",
                queued,
                None,
                job.next_run_at,
            )
        return JobState(job, "queued", "Waiting for a worker.", queued, None, job.next_run_at)
    if latest is not None and latest.status == JobOccurrence.Status.FAILED:
        # Occurrences are newest-first, so nothing later exists to recover this one.
        return JobState(
            job,
            "failed",
            f"Terminal failure after {latest.attempts} attempt(s): "
            f"{latest.error_code or 'unknown'}.",
            latest,
            None,
            job.next_run_at,
        )
    if job.next_run_at < now - OVERDUE_GRACE:
        return JobState(
            job,
            "stale",
            f"Overdue: due {job.next_run_at:%b %d %H:%M} UTC and no occurrence was enqueued.",
            latest,
            None,
            job.next_run_at,
        )
    if latest is not None and latest.status == JobOccurrence.Status.SUCCEEDED:
        earlier_failure = next(
            (o for o in occurrences if o.status == JobOccurrence.Status.FAILED), None
        )
        if earlier_failure is not None:
            return JobState(
                job,
                "recovered",
                f"Earlier terminal failure ({earlier_failure.error_code or 'unknown'}) "
                "recovered by the latest run.",
                earlier_failure,
                latest,
                job.next_run_at,
            )
    return JobState(job, "scheduled", "Enabled and scheduled.", latest, None, job.next_run_at)


def project_all_job_states(now=None):
    now = now or timezone.now()
    jobs = list(ScheduledJob.objects.order_by("name"))
    by_job = {job.pk: [] for job in jobs}
    for occurrence in JobOccurrence.objects.filter(scheduled_job__in=jobs).order_by(
        "-scheduled_for", "-id"
    ):
        bucket = by_job[occurrence.scheduled_job_id]
        if len(bucket) < 25:
            bucket.append(occurrence)
    return [project_job_state(job, now=now, occurrences=by_job[job.pk]) for job in jobs]
