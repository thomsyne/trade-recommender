import hashlib
import json
from datetime import UTC

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.dateparse import parse_datetime


def dataset_manifest_sha256(manifest):
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_historical_ingestion_manifest(*, ingestion_run, dataset_version, payload):
    """Validate a persisted provider manifest against its frozen historical attempt."""
    if "historical_plan_sha256" not in dataset_version.manifest:
        return
    try:
        attempt = ingestion_run.historical_attempt
        chunk = attempt.chunk
        requested_from = parse_datetime(payload["from"]).astimezone(UTC)
        requested_to = parse_datetime(payload["to"]).astimezone(UTC)
        requests = payload["requests"]
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ValidationError("historical manifest lacks canonical attempt lineage") from error
    required = {
        "instrument": chunk.instrument.code,
        "granularity": chunk.granularity,
        "price": "BA",
        "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
        "smooth": False,
        "dailyAlignment": 17,
        "alignmentTimezone": "America/New_York",
        "weeklyAlignment": "Friday",
        "includeFirst": True,
        "complete_only": True,
        "historical_logical_key": chunk.logical_key,
        "historical_attempt": attempt.attempt_number,
    }
    if (
        any(payload.get(key) != value for key, value in required.items())
        or requested_from != chunk.requested_from.astimezone(UTC)
        or requested_to != chunk.requested_to.astimezone(UTC)
        or type(requests) is not list
        or len(requests) != 1
        or type(requests[0]) is not dict
        or requests[0].get("status") != 200
        or chunk.dataset_version_id != dataset_version.pk
        or ingestion_run.dataset_version_id != dataset_version.pk
        or ingestion_run.source_id != chunk.plan.source_id
        or ingestion_run.instrument_id != chunk.instrument_id
        or ingestion_run.granularity != chunk.granularity
        or ingestion_run.requested_from != chunk.requested_from
        or ingestion_run.requested_to != chunk.requested_to
        or ingestion_run.parameters != chunk.canonical_request
    ):
        raise ValidationError("historical manifest conflicts with canonical attempt semantics")


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
HISTORICAL_GRANULARITIES = (("W", "Weekly"), ("D", "Daily"), ("H1", "Hourly"))


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


class HistoricalDatasetPlan(ImmutableModel):
    PRICE_COMPONENT = "COMBINED_BID_ASK"

    identity = models.CharField(max_length=160)
    source = models.ForeignKey(SourceRegistry, on_delete=models.PROTECT)
    strategy_version = models.ForeignKey("research.StrategyVersion", on_delete=models.PROTECT)
    instruments = models.JSONField()
    granularities = models.JSONField()
    ranges = models.JSONField()
    alignment = models.JSONField()
    price_component = models.CharField(max_length=32, default=PRICE_COMPONENT)
    complete_only = models.BooleanField(default=True)
    chunk_size = models.PositiveIntegerField(default=4999)
    phase1_spec_hash = models.CharField(max_length=64)
    phase1_manifest_hash = models.CharField(max_length=64)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price_component="COMBINED_BID_ASK"),
                name="historical_plan_combined_bid_ask",
            ),
            models.CheckConstraint(
                condition=models.Q(complete_only=True), name="historical_plan_complete_only"
            ),
            models.CheckConstraint(
                condition=models.Q(chunk_size__gte=1) & models.Q(chunk_size__lte=4999),
                name="historical_plan_chunk_size",
            ),
        ]

    def save(self, *args, **kwargs):
        expected_hash = dataset_manifest_sha256(self.payload)
        if self.sha256 and self.sha256 != expected_hash:
            raise ValidationError("historical plan SHA-256 does not match canonical payload")
        self.sha256 = expected_hash
        return super().save(*args, **kwargs)


class HistoricalIngestionChunk(ImmutableModel):
    plan = models.ForeignKey(HistoricalDatasetPlan, on_delete=models.PROTECT, related_name="chunks")
    dataset_version = models.ForeignKey(
        DatasetVersion, on_delete=models.PROTECT, related_name="historical_chunks"
    )
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    granularity = models.CharField(max_length=3, choices=HISTORICAL_GRANULARITIES)
    requested_from = models.DateTimeField()
    requested_to = models.DateTimeField()
    canonical_request = models.JSONField()
    canonical_request_sha256 = models.CharField(max_length=64)
    logical_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "plan",
                    "instrument",
                    "granularity",
                    "requested_from",
                    "requested_to",
                ),
                name="unique_historical_logical_chunk",
            ),
            models.CheckConstraint(
                condition=models.Q(requested_from__lt=models.F("requested_to")),
                name="historical_chunk_increasing_range",
            ),
        ]


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

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.only("status").get(pk=self.pk)
            if previous.status != self.Status.RUNNING:
                raise ValidationError("terminal ingestion runs are immutable")
            if self.status not in {
                self.Status.SUCCEEDED,
                self.Status.FAILED,
                self.Status.QUARANTINED,
            }:
                raise ValidationError("ingestion runs may only transition from running to terminal")
        return super().save(*args, **kwargs)


class HistoricalIngestionAttempt(ImmutableModel):
    chunk = models.ForeignKey(
        HistoricalIngestionChunk, on_delete=models.PROTECT, related_name="attempts"
    )
    ingestion_run = models.OneToOneField(
        IngestionRun, on_delete=models.PROTECT, related_name="historical_attempt"
    )
    attempt_number = models.PositiveIntegerField()
    idempotency_key = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("chunk", "attempt_number"), name="unique_historical_chunk_attempt"
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_number__gte=1), name="historical_attempt_number_positive"
            ),
        ]

    def save(self, *args, **kwargs):
        expected_key = (
            f"failed-break-ingestion-attempt:{self.chunk.logical_key}:{self.attempt_number}"
        )
        if self.idempotency_key and self.idempotency_key != expected_key:
            raise ValidationError("historical attempt idempotency key does not match its chunk")
        self.idempotency_key = expected_key
        return super().save(*args, **kwargs)


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

    def save(self, *args, **kwargs):
        validate_historical_ingestion_manifest(
            ingestion_run=self.ingestion_run,
            dataset_version=self.dataset_version,
            payload=self.payload,
        )
        expected_hash = dataset_manifest_sha256(self.payload)
        if self.sha256 and self.sha256 != expected_hash:
            raise ValidationError("ingestion manifest SHA-256 does not match canonical JSON")
        self.sha256 = expected_hash
        return super().save(*args, **kwargs)


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


class DatasetRegistration(ImmutableModel):
    dataset_version = models.OneToOneField(
        DatasetVersion, on_delete=models.PROTECT, related_name="registration"
    )
    plan = models.OneToOneField(
        HistoricalDatasetPlan, on_delete=models.PROTECT, related_name="registration"
    )
    series_manifest = models.JSONField()
    row_counts = models.JSONField()
    first_last_timestamps = models.JSONField()
    missingness = models.JSONField()
    conflict_count = models.PositiveIntegerField()
    incident_count = models.PositiveIntegerField()
    logical_chunk_set_hash = models.CharField(max_length=64)
    successful_attempt_set_hash = models.CharField(max_length=64)
    ingestion_manifest_set_hash = models.CharField(max_length=64)
    candle_key_hash = models.CharField(max_length=64)
    candle_payload_hash = models.CharField(max_length=64)
    configuration_sha256 = models.CharField(max_length=64)
    report_sha256 = models.CharField(max_length=64, unique=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        configuration = {
            "identity": "failed-break-historical-dataset-registration-v1",
            "plan_sha256": self.plan.sha256,
            "dataset_manifest_sha256": self.dataset_version.manifest_sha256,
            "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
            "logical_chunk_set_hash": self.logical_chunk_set_hash,
        }
        expected_configuration = dataset_manifest_sha256(configuration)
        if self.configuration_sha256 and self.configuration_sha256 != expected_configuration:
            raise ValidationError("dataset registration configuration SHA-256 does not match")
        self.configuration_sha256 = expected_configuration
        report = {
            "configuration_sha256": expected_configuration,
            "series_manifest": self.series_manifest,
            "row_counts": self.row_counts,
            "first_last_timestamps": self.first_last_timestamps,
            "missingness": self.missingness,
            "conflict_count": self.conflict_count,
            "incident_count": self.incident_count,
            "logical_chunk_set_hash": self.logical_chunk_set_hash,
            "successful_attempt_set_hash": self.successful_attempt_set_hash,
            "ingestion_manifest_set_hash": self.ingestion_manifest_set_hash,
            "candle_key_hash": self.candle_key_hash,
            "candle_payload_hash": self.candle_payload_hash,
        }
        expected_report = dataset_manifest_sha256(report)
        if self.report_sha256 and self.report_sha256 != expected_report:
            raise ValidationError("dataset registration report SHA-256 does not match")
        self.report_sha256 = expected_report
        return super().save(*args, **kwargs)


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
