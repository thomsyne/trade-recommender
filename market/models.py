from django.core.exceptions import ValidationError
from django.db import models


class Instrument(models.Model):
    class Code(models.TextChoices):
        USD_CAD = "USD_CAD", "USD/CAD"
        GBP_USD = "GBP_USD", "GBP/USD"
        EUR_GBP = "EUR_GBP", "EUR/GBP"
        EUR_USD = "EUR_USD", "EUR/USD"

    code = models.CharField(max_length=7, choices=Code, unique=True)
    base_currency = models.CharField(max_length=3)
    quote_currency = models.CharField(max_length=3)
    display_order = models.PositiveSmallIntegerField(unique=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("display_order",)

    def __str__(self):
        return self.get_code_display()


class SourceRegistry(models.Model):
    class Tier(models.TextChoices):
        PRIMARY = "primary", "Primary"
        ESTABLISHED = "established", "Established"
        CONTEXTUAL = "contextual", "Contextual"
        QUARANTINE = "quarantine", "Quarantine"

    name = models.CharField(max_length=120, unique=True)
    tier = models.CharField(max_length=16, choices=Tier)
    base_url = models.URLField()
    terms_url = models.URLField(blank=True)
    terms_reviewed_at = models.DateTimeField(null=True, blank=True)
    acquisition_method = models.CharField(max_length=80)
    retention_policy = models.TextField()
    llm_processing_allowed = models.BooleanField(default=False)
    attribution_required = models.BooleanField(default=True)
    deletion_policy = models.TextField(blank=True)
    export_policy = models.TextField(blank=True)
    enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


GRANULARITIES = (("D", "Daily"), ("H4", "Four-hour"), ("H1", "Hourly"))


class IngestionRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    source = models.ForeignKey(SourceRegistry, on_delete=models.PROTECT)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    granularity = models.CharField(max_length=3, choices=GRANULARITIES)
    requested_from = models.DateTimeField()
    requested_to = models.DateTimeField()
    parameters = models.JSONField()
    request_manifest_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=12, choices=Status, default=Status.RUNNING)
    fetched_count = models.PositiveIntegerField(default=0)
    stored_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    failure_reason = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at",)


class Candle(models.Model):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    ingestion_run = models.ForeignKey(
        IngestionRun, on_delete=models.PROTECT, related_name="candles"
    )
    granularity = models.CharField(max_length=3, choices=GRANULARITIES)
    timestamp = models.DateTimeField(help_text="UTC interval-start timestamp")
    complete = models.BooleanField()
    volume = models.PositiveIntegerField()
    bid_open = models.DecimalField(max_digits=12, decimal_places=6)
    bid_high = models.DecimalField(max_digits=12, decimal_places=6)
    bid_low = models.DecimalField(max_digits=12, decimal_places=6)
    bid_close = models.DecimalField(max_digits=12, decimal_places=6)
    ask_open = models.DecimalField(max_digits=12, decimal_places=6)
    ask_high = models.DecimalField(max_digits=12, decimal_places=6)
    ask_low = models.DecimalField(max_digits=12, decimal_places=6)
    ask_close = models.DecimalField(max_digits=12, decimal_places=6)

    class Meta:
        ordering = ("timestamp",)
        constraints = [
            models.UniqueConstraint(
                fields=("instrument", "granularity", "timestamp"), name="unique_market_candle"
            ),
            models.CheckConstraint(
                condition=models.Q(complete=True), name="stored_candles_complete"
            ),
            models.CheckConstraint(
                condition=models.Q(volume__gte=0), name="candle_volume_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(bid_low__lte=models.F("bid_open"))
                & models.Q(bid_low__lte=models.F("bid_close"))
                & models.Q(bid_high__gte=models.F("bid_open"))
                & models.Q(bid_high__gte=models.F("bid_close")),
                name="candle_bid_ohlc_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(ask_low__lte=models.F("ask_open"))
                & models.Q(ask_low__lte=models.F("ask_close"))
                & models.Q(ask_high__gte=models.F("ask_open"))
                & models.Q(ask_high__gte=models.F("ask_close")),
                name="candle_ask_ohlc_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    bid_open__lte=models.F("ask_open"),
                    bid_high__lte=models.F("ask_high"),
                    bid_low__lte=models.F("ask_low"),
                    bid_close__lte=models.F("ask_close"),
                ),
                name="candle_bid_not_above_ask",
            ),
        ]
        indexes = [models.Index(fields=("instrument", "granularity", "-timestamp"))]

    @property
    def midpoint_close(self):
        return (self.bid_close + self.ask_close) / 2


class TechnicalSnapshot(models.Model):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    granularity = models.CharField(max_length=3, choices=GRANULARITIES)
    as_of = models.DateTimeField()
    candle_count = models.PositiveIntegerField()
    atr_14 = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    ewma_20 = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    prior_high = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    prior_low = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    support = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    resistance = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("instrument", "granularity", "as_of"), name="unique_technical_snapshot"
            )
        ]
        ordering = ("-as_of",)


class AuditEvent(models.Model):
    occurred_at = models.DateTimeField(auto_now_add=True)
    event_type = models.CharField(max_length=80)
    actor = models.CharField(max_length=120)
    subject_type = models.CharField(max_length=80)
    subject_id = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)

    class Meta:
        ordering = ("-occurred_at", "-id")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Audit events are append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit events are append-only")
