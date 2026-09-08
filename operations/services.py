from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from market.models import AuditEvent
from operations.diagnostics import record_task_failure
from operations.models import (
    DeliveryAttempt,
    JobOccurrence,
    OutboxMessage,
    ProviderBudget,
    ProviderBudgetReservation,
    ScheduledJob,
    TaskFailure,
)

LEASE_DURATION = timedelta(minutes=5)
MAX_CATCHUP_OCCURRENCES = 1000


def _advance(job, value):
    if job.schedule_type == ScheduledJob.ScheduleType.DAILY:
        local = value.astimezone(ZoneInfo(job.timezone_name))
        next_date = local.date() + timedelta(days=1)
        return datetime.combine(next_date, job.local_time, ZoneInfo(job.timezone_name)).astimezone(
            UTC
        )
    return value + timedelta(seconds=job.interval_seconds)


@transaction.atomic
def enqueue_due_jobs(now=None):
    now = now or timezone.now()
    created = []
    jobs = ScheduledJob.objects.select_for_update(skip_locked=True).filter(
        enabled=True, next_run_at__lte=now
    )
    for job in jobs:
        cursor = job.next_run_at
        if job.schedule_type == ScheduledJob.ScheduleType.INTERVAL:
            interval = timedelta(seconds=job.interval_seconds)
            due_count = int((now - cursor) // interval) + 1
            next_run_at = cursor + due_count * interval
            if job.missed_run_policy == ScheduledJob.MissedRunPolicy.ALL:
                first_selected = max(0, due_count - MAX_CATCHUP_OCCURRENCES)
                selected = [cursor + index * interval for index in range(first_selected, due_count)]
            elif job.missed_run_policy == ScheduledJob.MissedRunPolicy.LATEST:
                selected = [cursor + (due_count - 1) * interval]
            else:
                selected = []
        else:
            due = []
            while cursor <= now:
                due.append(cursor)
                cursor = _advance(job, cursor)
            due_count = len(due)
            next_run_at = cursor
            if job.missed_run_policy == ScheduledJob.MissedRunPolicy.ALL:
                selected = due[-MAX_CATCHUP_OCCURRENCES:]
            elif job.missed_run_policy == ScheduledJob.MissedRunPolicy.LATEST:
                selected = due[-1:]
            else:
                selected = []
        job.next_run_at = next_run_at
        job.save(update_fields=("next_run_at", "updated_at"))
        skipped = due_count - len(selected)
        for scheduled_for in selected:
            occurrence, was_created = JobOccurrence.objects.get_or_create(
                idempotency_key=f"{job.pk}:{scheduled_for.isoformat()}",
                defaults={
                    "scheduled_job": job,
                    "task_name": job.task_name,
                    "parameters": job.parameters,
                    "scheduled_for": scheduled_for,
                    "available_at": now,
                    "lateness_seconds": max(0, int((now - scheduled_for).total_seconds())),
                    "skipped_count": skipped,
                },
            )
            if was_created:
                created.append(occurrence)
    return created


@transaction.atomic
def claim_next_job(worker_id="legacy-worker", now=None, lease_duration=LEASE_DURATION):
    # Compatibility with the original claim_next_job(now) API.
    if isinstance(worker_id, datetime):
        now, worker_id = worker_id, "legacy-worker"
    now = now or timezone.now()
    expired = JobOccurrence.objects.select_for_update(skip_locked=True).filter(
        Q(lease_owner="")
        | Q(lease_expires_at__isnull=True)
        | Q(lease_expires_at__lte=now)
        | Q(execution_deadline__lte=now),
        status=JobOccurrence.Status.RUNNING,
    )
    for stale in expired:
        stale.lease_owner = ""
        stale.lease_expires_at = None
        stale.heartbeat_at = None
        stale.error_code = "lease_expired"
        stale.error_summary = "Worker lease expired"
        terminal = stale.attempts >= stale.max_attempts
        if terminal:
            stale.status = JobOccurrence.Status.FAILED
            stale.finished_at = now
        else:
            stale.status = JobOccurrence.Status.QUEUED
            stale.available_at = now
        stale.save()
        if stale.attempts:
            TaskFailure.objects.get_or_create(
                occurrence=stale,
                attempt_number=stale.attempts,
                defaults={
                    "task_name": stale.task_name,
                    "error_code": "lease_expired",
                    "category": "worker",
                    "stage": "lease",
                    "exception_type": "",
                    "summary": "Worker lease expired before the attempt reported an outcome",
                    "terminal": terminal,
                    "occurred_at": now,
                },
            )
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
    occurrence.lease_owner = worker_id
    occurrence.heartbeat_at = now
    occurrence.lease_expires_at = now + lease_duration
    occurrence.execution_deadline = now + timedelta(seconds=occurrence.timeout_seconds)
    occurrence.error_code = ""
    occurrence.error_summary = ""
    occurrence.save()
    return occurrence


@transaction.atomic
def heartbeat_job(occurrence, worker_id, now=None, lease_duration=LEASE_DURATION):
    now = now or timezone.now()
    row = JobOccurrence.objects.select_for_update().get(pk=occurrence.pk)
    if row.status != row.Status.RUNNING or row.lease_owner != worker_id:
        return False
    if row.execution_deadline and now >= row.execution_deadline:
        row.lease_expires_at = now
        row.save(update_fields=("lease_expires_at",))
        return False
    row.heartbeat_at = now
    row.lease_expires_at = min(now + lease_duration, row.execution_deadline)
    row.save(update_fields=("heartbeat_at", "lease_expires_at"))
    return True


@transaction.atomic
def finish_job(occurrence, worker_id=None, error=None, error_code="task_failed"):
    # Compatibility with the original finish_job(occurrence, error) API.
    if worker_id is not None and not isinstance(worker_id, str):
        error, worker_id = worker_id, occurrence.lease_owner
    worker_id = worker_id or occurrence.lease_owner or "legacy-worker"
    row = JobOccurrence.objects.select_for_update().get(pk=occurrence.pk)
    if row.status != row.Status.RUNNING or row.lease_owner != worker_id:
        return False
    now = timezone.now()
    row.lease_owner = ""
    row.lease_expires_at = None
    row.heartbeat_at = None
    terminal = bool(error) and row.attempts >= row.max_attempts
    if error and not terminal:
        row.status = row.Status.QUEUED
        row.available_at = now + timedelta(seconds=30 * (2 ** (row.attempts - 1)))
    else:
        row.status = row.Status.FAILED if error else row.Status.SUCCEEDED
        row.finished_at = now
    diagnostic = None
    if error:
        if isinstance(error, BaseException):
            _, diagnostic = record_task_failure(
                row, error, attempt_number=row.attempts, terminal=terminal, now=now
            )
        else:
            TaskFailure.objects.get_or_create(
                occurrence=row,
                attempt_number=row.attempts,
                defaults={
                    "task_name": row.task_name,
                    "error_code": error_code,
                    "category": "unclassified",
                    "stage": "",
                    "exception_type": "",
                    "summary": "Task execution failed",
                    "terminal": terminal,
                    "occurred_at": now,
                },
            )
    if diagnostic is not None:
        row.error_code = diagnostic.code
        row.error_summary = diagnostic.summary
    else:
        row.error_code = error_code if error else ""
        row.error_summary = "Task execution failed" if error else ""
    row.save()
    if row.status in (row.Status.FAILED, row.Status.SUCCEEDED):
        AuditEvent.objects.create(
            event_type=f"operations.job_{row.status}",
            actor="operations.worker",
            subject_type="JobOccurrence",
            subject_id=str(row.pk),
            payload={
                "task": row.task_name,
                "attempts": row.attempts,
                "error_code": row.error_code,
                "stage": diagnostic.stage if diagnostic else "",
            },
        )
    return True


@transaction.atomic
def enqueue_outbox(idempotency_key, channel, template, payload, not_before=None):
    message, _ = OutboxMessage.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "channel": channel,
            "template": template,
            "payload": payload,
            "not_before": not_before or timezone.now(),
        },
    )
    return message


@transaction.atomic
def claim_outbox(worker_id, now=None, lease_duration=LEASE_DURATION):
    now = now or timezone.now()
    message = (
        OutboxMessage.objects.select_for_update(skip_locked=True)
        .filter(
            Q(status=OutboxMessage.Status.PENDING)
            | Q(status=OutboxMessage.Status.SENDING, lease_expires_at__lte=now),
            not_before__lte=now,
        )
        .order_by("not_before", "id")
        .first()
    )
    if not message:
        return None
    if message.attempts >= message.max_attempts:
        message.status = message.Status.FAILED
        message.completed_at = now
        message.save()
        return None
    if message.status == message.Status.SENDING:
        previous = message.delivery_attempts.get(attempt_number=message.attempts)
        previous.outcome = DeliveryAttempt.Outcome.UNCERTAIN
        previous.error_code = "lease_expired"
        previous.summary = "Delivery lease expired before its outcome was recorded"
        previous.finished_at = now
        previous.save()
    message.status = message.Status.SENDING
    message.attempts += 1
    message.lease_owner = worker_id
    message.heartbeat_at = now
    message.lease_expires_at = now + lease_duration
    message.save()
    DeliveryAttempt.objects.create(
        message=message, attempt_number=message.attempts, worker_id=worker_id, started_at=now
    )
    return message


@transaction.atomic
def finish_outbox(message, worker_id, outcome, error_code="", summary=""):
    row = OutboxMessage.objects.select_for_update().get(pk=message.pk)
    if row.status != row.Status.SENDING or row.lease_owner != worker_id:
        return False
    attempt = row.delivery_attempts.get(attempt_number=row.attempts)
    now = timezone.now()
    attempt.outcome = outcome
    attempt.error_code = error_code
    attempt.summary = summary[:240]
    attempt.finished_at = now
    attempt.save()
    if outcome == DeliveryAttempt.Outcome.SUCCEEDED:
        row.status, row.completed_at = row.Status.SENT, now
    elif outcome == DeliveryAttempt.Outcome.UNCERTAIN:
        row.status, row.completed_at = row.Status.UNCERTAIN, now
    elif row.attempts >= row.max_attempts:
        row.status, row.completed_at = row.Status.FAILED, now
    else:
        row.status = row.Status.PENDING
        row.not_before = now + timedelta(seconds=30 * (2 ** (row.attempts - 1)))
    row.lease_owner, row.lease_expires_at, row.heartbeat_at = "", None, None
    row.save()
    return True


def _reservation_amount(row):
    if row.status == row.Status.SETTLED:
        return row.actual_usd
    if row.status == row.Status.UNCERTAIN:
        return row.actual_usd if row.actual_usd is not None else row.estimated_usd
    if row.status == row.Status.RESERVED:
        return row.estimated_usd
    return Decimal("0")


@transaction.atomic
def reserve_provider_budget(
    provider,
    purpose,
    idempotency_key,
    estimated_usd,
    now=None,
    *,
    requested_model="",
    pricing_version="",
):
    existing = ProviderBudgetReservation.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        existing._was_created = False
        return existing
    now = (now or timezone.now()).astimezone(UTC)
    budget = ProviderBudget.objects.select_for_update().get(provider=provider, purpose=purpose)
    rows = budget.reservations.exclude(status=ProviderBudgetReservation.Status.RELEASED)
    daily = sum(
        (_reservation_amount(row) for row in rows.filter(budget_at__date=now.date())), Decimal("0")
    )
    monthly = sum(
        (
            _reservation_amount(row)
            for row in rows.filter(budget_at__year=now.year, budget_at__month=now.month)
        ),
        Decimal("0"),
    )
    estimate = Decimal(estimated_usd)
    if daily + estimate > budget.daily_cap_usd or monthly + estimate > budget.monthly_cap_usd:
        return None
    reservation = ProviderBudgetReservation.objects.create(
        budget=budget,
        idempotency_key=idempotency_key,
        estimated_usd=estimate,
        budget_at=now,
        outcome=ProviderBudgetReservation.Outcome.PENDING,
        requested_model=requested_model[:120],
        pricing_version=pricing_version[:80],
    )
    reservation._was_created = True
    return reservation


@transaction.atomic
def settle_provider_budget(
    reservation, actual_usd, *, returned_model=None, usage_identity=None, pricing_version=None
):
    row = ProviderBudgetReservation.objects.select_for_update().get(pk=reservation.pk)
    if row.status != row.Status.RESERVED:
        return False
    row.status, row.actual_usd = row.Status.SETTLED, Decimal(actual_usd)
    if returned_model is not None:
        row.returned_model = str(returned_model)[:120]
    if usage_identity is not None:
        row.usage_identity = str(usage_identity)[:160]
    if pricing_version is not None and not row.pricing_version:
        row.pricing_version = str(pricing_version)[:80]
    row.save()
    return True


@transaction.atomic
def record_reservation_outcome(reservation, outcome):
    """Record the validation outcome once; never rewrite a recorded outcome."""
    row = ProviderBudgetReservation.objects.select_for_update().get(pk=reservation.pk)
    if row.outcome not in {"", ProviderBudgetReservation.Outcome.PENDING}:
        return False
    if row.outcome == "":
        # Legacy rows predate outcome recording; leave them honest rather than
        # retro-fitting an outcome they never carried.
        return False
    row.outcome = outcome
    row.save(update_fields=("outcome", "updated_at"))
    return True


@transaction.atomic
def release_provider_budget(reservation):
    row = ProviderBudgetReservation.objects.select_for_update().get(pk=reservation.pk)
    if row.status != row.Status.RESERVED:
        return False
    row.status = row.Status.RELEASED
    row.save()
    return True


@transaction.atomic
def mark_provider_budget_uncertain(reservation, actual_usd=None):
    row = ProviderBudgetReservation.objects.select_for_update().get(pk=reservation.pk)
    if row.status != row.Status.RESERVED:
        return False
    row.status = row.Status.UNCERTAIN
    row.actual_usd = Decimal(actual_usd) if actual_usd is not None else None
    row.save()
    return True
