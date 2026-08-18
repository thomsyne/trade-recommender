from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from market.models import AuditEvent
from operations.models import JobOccurrence, ScheduledJob


@transaction.atomic
def enqueue_due_jobs(now=None):
    now = now or timezone.now()
    created = []
    jobs = ScheduledJob.objects.select_for_update(skip_locked=True).filter(
        enabled=True, next_run_at__lte=now
    )
    for job in jobs:
        scheduled_for = job.next_run_at
        occurrence, was_created = JobOccurrence.objects.get_or_create(
            idempotency_key=f"{job.pk}:{scheduled_for.isoformat()}",
            defaults={
                "scheduled_job": job,
                "task_name": job.task_name,
                "parameters": job.parameters,
                "scheduled_for": scheduled_for,
                "available_at": now,
            },
        )
        if was_created:
            created.append(occurrence)
        while job.next_run_at <= now:
            job.next_run_at += timedelta(seconds=job.interval_seconds)
        job.save(update_fields=("next_run_at", "updated_at"))
    return created


@transaction.atomic
def claim_next_job(now=None):
    now = now or timezone.now()
    occurrence = (
        JobOccurrence.objects.select_for_update(skip_locked=True)
        .filter(status=JobOccurrence.Status.QUEUED, available_at__lte=now)
        .order_by("available_at", "id")
        .first()
    )
    if not occurrence:
        return None
    occurrence.status = JobOccurrence.Status.RUNNING
    occurrence.attempts += 1
    occurrence.started_at = now
    occurrence.save(update_fields=("status", "attempts", "started_at"))
    return occurrence


def finish_job(occurrence, error=None):
    now = timezone.now()
    if error and occurrence.attempts < occurrence.max_attempts:
        occurrence.status = JobOccurrence.Status.QUEUED
        occurrence.available_at = now + timedelta(seconds=30 * (2 ** (occurrence.attempts - 1)))
        occurrence.error = str(error)[:4000]
        occurrence.save(update_fields=("status", "available_at", "error"))
        return
    occurrence.status = JobOccurrence.Status.FAILED if error else JobOccurrence.Status.SUCCEEDED
    occurrence.error = str(error)[:4000] if error else ""
    occurrence.finished_at = now
    occurrence.save(update_fields=("status", "error", "finished_at"))
    AuditEvent.objects.create(
        event_type=f"operations.job_{occurrence.status}",
        actor="operations.worker",
        subject_type="JobOccurrence",
        subject_id=str(occurrence.pk),
        payload={"task": occurrence.task_name, "attempts": occurrence.attempts},
    )
