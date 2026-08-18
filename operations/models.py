from django.db import models


class ScheduledJob(models.Model):
    name = models.CharField(max_length=120, unique=True)
    task_name = models.CharField(max_length=120)
    parameters = models.JSONField(default=dict)
    interval_seconds = models.PositiveIntegerField()
    next_run_at = models.DateTimeField()
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("next_run_at",)


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
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-scheduled_for",)
        indexes = [models.Index(fields=("status", "available_at"))]
