from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ScheduledJob(models.Model):
    class ScheduleType(models.TextChoices):
        INTERVAL = "interval", "Interval"
        DAILY = "daily", "Daily wall clock"

    class MissedRunPolicy(models.TextChoices):
        LATEST = "latest", "Latest"
        ALL = "all", "All"
        SKIP = "skip", "Skip"

    name = models.CharField(max_length=120, unique=True)
    task_name = models.CharField(max_length=120)
    parameters = models.JSONField(default=dict)
    interval_seconds = models.PositiveIntegerField(null=True, blank=True)
    schedule_type = models.CharField(
        max_length=12, choices=ScheduleType, default=ScheduleType.INTERVAL
    )
    timezone_name = models.CharField(max_length=64, default="UTC")
    local_time = models.TimeField(null=True, blank=True)
    missed_run_policy = models.CharField(
        max_length=8, choices=MissedRunPolicy, default=MissedRunPolicy.LATEST
    )
    next_run_at = models.DateTimeField()
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("next_run_at",)

    def clean(self):
        if self.schedule_type == self.ScheduleType.INTERVAL and not self.interval_seconds:
            raise ValidationError("An interval schedule requires interval_seconds")
        if self.schedule_type == self.ScheduleType.DAILY and self.local_time is None:
            raise ValidationError("A daily schedule requires local_time")


class JobOccurrence(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    idempotency_key = models.CharField(max_length=200, unique=True)
    scheduled_job = models.ForeignKey(
        ScheduledJob, on_delete=models.PROTECT, null=True, blank=True, related_name="occurrences"
    )
    task_name = models.CharField(max_length=120)
    parameters = models.JSONField(default=dict)
    status = models.CharField(max_length=12, choices=Status, default=Status.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    scheduled_for = models.DateTimeField()
    available_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    lease_owner = models.CharField(max_length=200, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    execution_deadline = models.DateTimeField(null=True, blank=True)
    timeout_seconds = models.PositiveIntegerField(default=900)
    lateness_seconds = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=80, blank=True)
    error_summary = models.CharField(max_length=240, blank=True)
    error = models.TextField(blank=True)  # Legacy field; do not write exception details here.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-scheduled_for",)
        indexes = [models.Index(fields=("status", "available_at"))]


class OutboxMessage(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        UNCERTAIN = "uncertain", "Uncertain"

    idempotency_key = models.CharField(max_length=200, unique=True)
    channel = models.CharField(max_length=40)
    template = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    not_before = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    lease_owner = models.CharField(max_length=200, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=("status", "not_before"))]


class DeliveryAttempt(models.Model):
    class Outcome(models.TextChoices):
        STARTED = "started", "Started"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        UNCERTAIN = "uncertain", "Uncertain"

    message = models.ForeignKey(
        OutboxMessage, on_delete=models.PROTECT, related_name="delivery_attempts"
    )
    attempt_number = models.PositiveSmallIntegerField()
    worker_id = models.CharField(max_length=200)
    outcome = models.CharField(max_length=12, choices=Outcome, default=Outcome.STARTED)
    error_code = models.CharField(max_length=80, blank=True)
    summary = models.CharField(max_length=240, blank=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("message", "attempt_number"), name="unique_delivery_attempt"
            )
        ]


class ProviderBudget(models.Model):
    provider = models.CharField(max_length=80)
    purpose = models.CharField(max_length=80)
    daily_cap_usd = models.DecimalField(max_digits=12, decimal_places=4)
    monthly_cap_usd = models.DecimalField(max_digits=12, decimal_places=4)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("provider", "purpose"), name="unique_provider_budget")
        ]


class ProviderBudgetReservation(models.Model):
    class Status(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        SETTLED = "settled", "Settled"
        RELEASED = "released", "Released"
        UNCERTAIN = "uncertain", "Uncertain"

    budget = models.ForeignKey(
        ProviderBudget, on_delete=models.PROTECT, related_name="reservations"
    )
    idempotency_key = models.CharField(max_length=200, unique=True)
    estimated_usd = models.DecimalField(max_digits=12, decimal_places=6)
    actual_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status, default=Status.RESERVED)
    budget_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
