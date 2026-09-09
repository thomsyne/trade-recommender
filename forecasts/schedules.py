"""Four budget-free reconciliation jobs, with exact recurring collision checks."""

from datetime import timedelta
from itertools import combinations
from math import gcd

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from market.live_schedules import deadline_microseconds
from operations.models import ScheduledJob


def recurring_schedules_collide(first, second):
    return (
        deadline_microseconds(first.next_run_at) - deadline_microseconds(second.next_run_at)
    ) % (gcd(first.interval_seconds, second.interval_seconds) * 1_000_000) == 0


CODES = ("EUR_USD", "GBP_USD", "EUR_GBP", "USD_CAD")
TASK = "forecast.reconcile_target_lifecycle"
INTERVAL = 3600


def schedule_errors():
    errors = []
    identities = {}
    for job in ScheduledJob.objects.filter(task_name=TASK).order_by("pk").iterator():
        parameters = job.parameters
        if (
            not isinstance(parameters, dict)
            or set(parameters) != {"instrument"}
            or not isinstance(parameters.get("instrument"), str)
            or parameters["instrument"] not in CODES
        ):
            errors.append({"id": job.pk, "code": "malformed_reconciliation_identity"})
            continue
        code = parameters["instrument"]
        if code in identities:
            errors.append({"id": job.pk, "code": "duplicate_reconciliation_identity"})
        identities[code] = job.pk
        if (
            job.name != f"Phase3 reconcile {code}"
            or job.interval_seconds != INTERVAL
            or job.missed_run_policy != "latest"
            or job.schedule_type != "interval"
            or job.timezone_name != "UTC"
            or job.local_time is not None
        ):
            errors.append({"id": job.pk, "code": "reconciliation_schedule_drift"})
    jobs = list(
        ScheduledJob.objects.filter(task_name__in=(TASK, "market.ingest_oanda"), enabled=True)
    )
    for first, second in combinations(jobs, 2):
        if TASK not in {first.task_name, second.task_name}:
            continue
        if recurring_schedules_collide(first, second):
            errors.append(
                {"id": min(first.pk, second.pk), "code": "recurring_reconciliation_collision"}
            )
    return errors


@transaction.atomic
def seed_schedules():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(724102)")
    errors = schedule_errors()
    if errors:
        raise ValidationError("reconciliation_schedule_integrity")
    for index, code in enumerate(CODES):
        ScheduledJob.objects.get_or_create(
            name=f"Phase3 reconcile {code}",
            defaults={
                "task_name": TASK,
                "parameters": {"instrument": code},
                "interval_seconds": INTERVAL,
                "next_run_at": timezone.now().replace(minute=0, second=0, microsecond=0)
                + timedelta(hours=1, seconds=3001 + index * 60),
                "enabled": False,
                "missed_run_policy": "latest",
                "schedule_type": "interval",
                "timezone_name": "UTC",
            },
        )
