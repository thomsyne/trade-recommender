import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import models


def dataset_manifest_sha256(manifest):
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class Instrument(models.Model):
    class Code(models.TextChoices):
        AUD_USD = "AUD_USD", "AUD/USD"
        USD_CAD = "USD_CAD", "USD/CAD"
        GBP_USD = "GBP_USD", "GBP/USD"
        EUR_GBP = "EUR_GBP", "EUR/GBP"
        EUR_USD = "EUR_USD", "EUR/USD"
        USD_JPY = "USD_JPY", "USD/JPY"

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


GRANULARITIES = (("W", "Weekly"), ("D", "Daily"), ("H4", "Four-hour"), ("H1", "Hourly"))


class ImmutableModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(f"{type(self).__name__} records are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(f"{type(self).__name__} records are immutable")


class DatasetVersion(ImmutableModel):
    name = models.CharField(max_length=120)
    version = models.CharField(max_length=80)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True)
    source = models.ForeignKey(SourceRegistry, on_delete=models.PROTECT, null=True, blank=True)
    description = models.TextField(blank=True)
    manifest = models.JSONField(default=dict)
    manifest_sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("name", "version"), name="unique_dataset_version")
        ]

    def save(self, *args, **kwargs):
        expected_hash = dataset_manifest_sha256(self.manifest)
        if self.manifest_sha256 and self.manifest_sha256 != expected_hash:
            raise ValidationError("dataset manifest SHA-256 does not match canonical manifest JSON")
        self.manifest_sha256 = expected_hash
        return super().save(*args, **kwargs)


class IngestionRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        QUARANTINED = "quarantined", "Quarantined"

    source = models.ForeignKey(SourceRegistry, on_delete=models.PROTECT)
    dataset_version = models.ForeignKey(
        DatasetVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ingestion_runs",
    )
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    granularity = models.CharField(max_length=3, choices=GRANULARITIES)
    requested_from = models.DateTimeField()
    requested_to = models.DateTimeField()
    parameters = models.JSONField()
    request_manifest_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status, default=Status.RUNNING)
    fetched_count = models.PositiveIntegerField(default=0)
    stored_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    failure_reason = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("dataset_version", "request_manifest_hash"),
                condition=models.Q(dataset_version__isnull=False),
                name="unique_dataset_ingestion_manifest_hash",
            ),
            models.UniqueConstraint(
                fields=("request_manifest_hash",),
                condition=models.Q(dataset_version__isnull=True),
                name="unique_legacy_ingestion_manifest_hash",
            ),
        ]


class Candle(models.Model):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    ingestion_run = models.ForeignKey(
        IngestionRun, on_delete=models.PROTECT, related_name="candles"
    )
    dataset_version = models.ForeignKey(
        DatasetVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="candles"
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
                fields=("dataset_version", "instrument", "granularity", "timestamp"),
                name="unique_dataset_market_candle",
                condition=models.Q(dataset_version__isnull=False),
            ),
            models.UniqueConstraint(
                fields=("instrument", "granularity", "timestamp"),
                name="unique_legacy_market_candle",
                condition=models.Q(dataset_version__isnull=True),
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

    @property
    def midpoint_open(self):
        return (self.bid_open + self.ask_open) / 2

    @property
    def midpoint_high(self):
        return (self.bid_high + self.ask_high) / 2

    @property
    def midpoint_low(self):
        return (self.bid_low + self.ask_low) / 2

    def save(self, *args, **kwargs):
        if self.pk and self.dataset_version_id:
            raise ValidationError("governed dataset candles are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.dataset_version_id:
            raise ValidationError("governed dataset candles are immutable")
        return super().delete(*args, **kwargs)


class IngestionManifest(ImmutableModel):
    ingestion_run = models.OneToOneField(
        IngestionRun, on_delete=models.PROTECT, related_name="ingestion_manifest"
    )
    dataset_version = models.ForeignKey(
        DatasetVersion, on_delete=models.PROTECT, related_name="manifests"
    )
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("dataset_version", "sha256"), name="unique_dataset_manifest_hash"
            )
        ]


class CandleConflict(ImmutableModel):
    dataset_version = models.ForeignKey(
        DatasetVersion, on_delete=models.PROTECT, related_name="conflicts"
    )
    ingestion_manifest = models.ForeignKey(
        IngestionManifest, on_delete=models.PROTECT, related_name="conflicts"
    )
    existing_candle = models.ForeignKey(Candle, on_delete=models.PROTECT, related_name="conflicts")
    existing_payload_sha256 = models.CharField(max_length=64)
    incoming_payload_sha256 = models.CharField(max_length=64)
    differing_fields = models.JSONField()
    incoming_payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("ingestion_manifest", "existing_candle", "incoming_payload_sha256"),
                name="unique_candle_conflict_payload",
            )
        ]


class DataQualityIncident(ImmutableModel):
    dataset_version = models.ForeignKey(
        DatasetVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="incidents"
    )
    ingestion_run = models.ForeignKey(
        IngestionRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quality_incidents",
    )
    code = models.CharField(max_length=80)
    details = models.JSONField(default=dict)
    evidence_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("dataset_version", "code", "evidence_sha256"),
                name="unique_dataset_quality_incident",
            )
        ]


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


class OandaInstrumentTermsSnapshot(models.Model):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    environment = models.CharField(max_length=12)
    account_fingerprint = models.CharField(max_length=64)
    account_currency = models.CharField(max_length=3)
    long_financing_rate = models.DecimalField(max_digits=15, decimal_places=10)
    short_financing_rate = models.DecimalField(max_digits=15, decimal_places=10)
    financing_days = models.JSONField()
    commission = models.JSONField(default=dict)
    commission_supplied = models.BooleanField(default=False)
    margin_rate = models.DecimalField(max_digits=10, decimal_places=6)
    pip_location = models.SmallIntegerField()
    response_sha256 = models.CharField(max_length=64)
    captured_at = models.DateTimeField()

    class Meta:
        ordering = ("-captured_at", "instrument__display_order")
        constraints = [
            models.UniqueConstraint(
                fields=("instrument", "environment", "account_fingerprint", "captured_at"),
                name="unique_oanda_terms_snapshot",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("OANDA instrument terms snapshots are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("OANDA instrument terms snapshots are immutable")


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
