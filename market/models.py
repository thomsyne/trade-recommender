import hashlib
import json
from datetime import UTC

from django.conf import settings
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
        or requests[0]
        != {
            "endpoint_identity": (
                f"oanda-v20-{requests[0].get('oanda_environment')}:GET:"
                f"/v3/instruments/{chunk.instrument.code}/candles"
            ),
            "http_method": "GET",
            "oanda_environment": requests[0].get("oanda_environment"),
            "canonical_request_sha256": chunk.canonical_request_sha256,
            "provider_request_id": requests[0].get("provider_request_id"),
            "http_status": 200,
        }
        or requests[0].get("oanda_environment") not in {"practice", "live"}
        or not isinstance(requests[0].get("provider_request_id"), str)
        or not requests[0]["provider_request_id"].strip()
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

        USD_CHF = "USD_CHF", "USD/CHF"
        NZD_USD = "NZD_USD", "NZD/USD"
        EUR_JPY = "EUR_JPY", "EUR/JPY"
        GBP_JPY = "GBP_JPY", "GBP/JPY"
        AUD_JPY = "AUD_JPY", "AUD/JPY"
        AUD_CAD = "AUD_CAD", "AUD/CAD"

    code = models.CharField(max_length=7, choices=Code, unique=True)
    base_currency = models.CharField(max_length=3)
    quote_currency = models.CharField(max_length=3)
    display_order = models.PositiveSmallIntegerField(unique=True)
    active = models.BooleanField(default=True)
    ingestion_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ("display_order",)

    def clean(self):
        super().clean()
        try:
            base, quote = self.Code(self.code).value.split("_")
        except ValueError as error:
            raise ValidationError("unsupported instrument code") from error
        if (self.base_currency, self.quote_currency) != (base, quote):
            raise ValidationError("instrument currencies contradict canonical code")

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


GRANULARITIES = (
    ("W", "Weekly"),
    ("D", "Daily"),
    ("H4", "Four-hour"),
    ("H1", "Hourly"),
    ("M15", "Fifteen-minute"),
)
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
    data_contract_sha256 = models.CharField(max_length=64, null=True, blank=True)
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
    data_contract = models.ForeignKey(
        "market.HistoricalDataContract",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="acquisition_plans",
    )
    data_contract_sha256 = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(data_contract__isnull=True, data_contract_sha256__isnull=True)
                    | models.Q(data_contract__isnull=False, data_contract_sha256__isnull=False)
                ),
                name="historical_plan_contract_fields_together",
            ),
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
    discovery_inventory = models.ForeignKey(
        "market.HistoricalTimestampInventory",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="acquisition_chunks",
    )
    semantic_inventory_sha256 = models.CharField(max_length=64, null=True, blank=True)
    expected_observation_count = models.PositiveIntegerField(null=True, blank=True)
    data_contract_sha256 = models.CharField(max_length=64, null=True, blank=True)
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
                condition=(
                    models.Q(
                        discovery_inventory__isnull=True,
                        semantic_inventory_sha256__isnull=True,
                        expected_observation_count__isnull=True,
                        data_contract_sha256__isnull=True,
                    )
                    | models.Q(
                        discovery_inventory__isnull=False,
                        semantic_inventory_sha256__isnull=False,
                        expected_observation_count__isnull=False,
                        data_contract_sha256__isnull=False,
                    )
                ),
                name="historical_chunk_contract_fields_together",
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


class HistoricalDiscoveryPlan(models.Model):
    identity = models.CharField(max_length=160)
    version = models.CharField(max_length=80)
    source = models.ForeignKey(SourceRegistry, on_delete=models.PROTECT)
    purpose = models.CharField(max_length=80)
    environment = models.CharField(max_length=12)
    phase1_spec_hash = models.CharField(max_length=64)
    phase1_manifest_hash = models.CharField(max_length=64)
    superseded_data_identity = models.CharField(max_length=160)
    declared_chunk_count = models.PositiveIntegerField()
    canonical_request_manifest = models.JSONField()
    canonical_request_manifest_sha256 = models.CharField(max_length=64)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64, unique=True)
    sealed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("identity", "version"), name="unique_historical_discovery_plan_version"
            ),
            models.CheckConstraint(
                condition=models.Q(declared_chunk_count__gte=1),
                name="historical_discovery_plan_nonempty",
            ),
        ]
        permissions = [
            ("approve_historical_discovery", "Can approve historical timestamp discovery")
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(
                "historical discovery plans are immutable outside governed sealing"
            )
        manifest_hash = dataset_manifest_sha256(self.canonical_request_manifest)
        payload_hash = dataset_manifest_sha256(self.payload)
        if self.canonical_request_manifest_sha256 not in {"", manifest_hash}:
            raise ValidationError("discovery request-manifest SHA-256 does not match")
        if self.sha256 not in {"", payload_hash}:
            raise ValidationError("discovery plan SHA-256 does not match")
        self.canonical_request_manifest_sha256 = manifest_hash
        self.sha256 = payload_hash
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("historical discovery plans are append-only")


class HistoricalDiscoveryChunk(ImmutableModel):
    plan = models.ForeignKey(
        HistoricalDiscoveryPlan, on_delete=models.PROTECT, related_name="chunks"
    )
    ordinal = models.PositiveIntegerField()
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    granularity = models.CharField(max_length=3, choices=HISTORICAL_GRANULARITIES)
    requested_from = models.DateTimeField()
    requested_to = models.DateTimeField()
    canonical_request = models.JSONField()
    canonical_request_sha256 = models.CharField(max_length=64)
    logical_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("plan", "ordinal")
        constraints = [
            models.UniqueConstraint(
                fields=("plan", "ordinal"), name="unique_historical_discovery_chunk_ordinal"
            ),
            models.UniqueConstraint(
                fields=("plan", "instrument", "granularity", "requested_from", "requested_to"),
                name="unique_historical_discovery_request",
            ),
            models.CheckConstraint(
                condition=models.Q(ordinal__gte=1), name="historical_discovery_ordinal_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(requested_from__lt=models.F("requested_to")),
                name="historical_discovery_increasing_range",
            ),
        ]


class HistoricalDiscoveryAttempt(ImmutableModel):
    chunk = models.ForeignKey(
        HistoricalDiscoveryChunk, on_delete=models.PROTECT, related_name="attempts"
    )
    ingestion_run = models.OneToOneField(
        IngestionRun, on_delete=models.PROTECT, related_name="historical_discovery_attempt"
    )
    attempt_number = models.PositiveIntegerField()
    idempotency_key = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("chunk", "attempt_number"),
                name="unique_historical_discovery_attempt_number",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_number__gte=1),
                name="historical_discovery_attempt_positive",
            ),
        ]

    def save(self, *args, **kwargs):
        expected = f"historical-discovery-attempt:{self.chunk.logical_key}:{self.attempt_number}"
        if self.idempotency_key not in {"", expected}:
            raise ValidationError("discovery attempt idempotency key does not match")
        self.idempotency_key = expected
        return super().save(*args, **kwargs)


class HistoricalTimestampInventory(ImmutableModel):
    chunk = models.OneToOneField(
        HistoricalDiscoveryChunk, on_delete=models.PROTECT, related_name="inventory"
    )
    accepted_attempt = models.OneToOneField(
        HistoricalDiscoveryAttempt, on_delete=models.PROTECT, related_name="inventory"
    )
    observation_count = models.PositiveIntegerField()
    timestamp_set_sha256 = models.CharField(max_length=64)
    structural_observation_sha256 = models.CharField(max_length=64)
    semantic_inventory_sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(observation_count__gte=1),
                name="historical_timestamp_inventory_nonempty",
            )
        ]


class HistoricalTimestampObservation(ImmutableModel):
    inventory = models.ForeignKey(
        HistoricalTimestampInventory, on_delete=models.PROTECT, related_name="observations"
    )
    timestamp = models.DateTimeField()
    complete = models.BooleanField()
    volume = models.PositiveIntegerField()
    bid_present = models.BooleanField()
    ask_present = models.BooleanField()

    class Meta:
        ordering = ("inventory", "timestamp")
        constraints = [
            models.UniqueConstraint(
                fields=("inventory", "timestamp"),
                name="unique_historical_timestamp_observation",
            ),
            models.CheckConstraint(
                condition=models.Q(complete=True), name="historical_discovery_observation_complete"
            ),
            models.CheckConstraint(
                condition=models.Q(bid_present=True),
                name="historical_discovery_observation_has_bid",
            ),
            models.CheckConstraint(
                condition=models.Q(ask_present=True),
                name="historical_discovery_observation_has_ask",
            ),
        ]


class HistoricalDiscoveryProviderEvidence(ImmutableModel):
    attempt = models.OneToOneField(
        HistoricalDiscoveryAttempt, on_delete=models.PROTECT, related_name="provider_evidence"
    )
    endpoint_identity = models.CharField(max_length=240, null=True, blank=True)
    http_method = models.CharField(max_length=8, null=True, blank=True)
    environment = models.CharField(max_length=12, null=True, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    provider_request_id = models.CharField(max_length=200, null=True, blank=True)
    canonical_request_sha256 = models.CharField(max_length=64, null=True, blank=True)
    unavailable_fields = models.JSONField(default=list)
    terminal_event_sha256 = models.CharField(max_length=64)
    operational_evidence_sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class HistoricalDiscoveryApproval(ImmutableModel):
    plan = models.OneToOneField(
        HistoricalDiscoveryPlan, on_delete=models.PROTECT, related_name="approval"
    )
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    global_semantic_inventory_sha256 = models.CharField(max_length=64)
    accepted_operational_evidence_set_sha256 = models.CharField(max_length=64)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64, unique=True)
    approved_at = models.DateTimeField()


class HistoricalDiscoveryRegistration(ImmutableModel):
    plan = models.OneToOneField(
        HistoricalDiscoveryPlan, on_delete=models.PROTECT, related_name="registration"
    )
    approval = models.OneToOneField(
        HistoricalDiscoveryApproval, on_delete=models.PROTECT, related_name="registration"
    )
    ordered_chunk_manifest_sha256 = models.CharField(max_length=64)
    global_semantic_inventory_sha256 = models.CharField(max_length=64)
    accepted_operational_evidence_set_sha256 = models.CharField(max_length=64)
    cross_series_report_sha256 = models.CharField(max_length=64)
    payload = models.JSONField()
    report_sha256 = models.CharField(max_length=64, unique=True)
    registered_at = models.DateTimeField()


class HistoricalDiscoverySupersession(ImmutableModel):
    REASON_PROVIDER_REQUEST_BOUND_UNSAFE = "PROVIDER_REQUEST_BOUND_UNSAFE"

    superseded_plan = models.OneToOneField(
        HistoricalDiscoveryPlan,
        on_delete=models.PROTECT,
        related_name="supersession",
    )
    replacement_plan = models.OneToOneField(
        HistoricalDiscoveryPlan,
        on_delete=models.PROTECT,
        related_name="replacement_for",
    )
    governing_attempt = models.OneToOneField(
        HistoricalDiscoveryAttempt,
        on_delete=models.PROTECT,
        related_name="governing_supersession",
    )
    reason_code = models.CharField(max_length=80)
    superseded_plan_sha256 = models.CharField(max_length=64)
    replacement_plan_sha256 = models.CharField(max_length=64)
    governing_terminal_event_sha256 = models.CharField(max_length=64)
    governing_operational_evidence_sha256 = models.CharField(max_length=64)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(superseded_plan=models.F("replacement_plan")),
                name="historical_discovery_supersession_distinct_plans",
            ),
            models.CheckConstraint(
                condition=models.Q(reason_code="PROVIDER_REQUEST_BOUND_UNSAFE"),
                name="historical_discovery_supersession_reason",
            ),
        ]


class HistoricalDataContract(ImmutableModel):
    """Gate 1B: the governed provider-observed historical-data identity.

    Binds the unchanged approved StrategyVersion and Phase 1 identities to
    the sealed Gate 5 discovery registration. The portable semantic sha256
    covers only canonical content (never database keys, usernames,
    timestamps or provider request ids); approval and registration lineage
    is bound relationally and by recorded hash columns.
    """

    identity = models.CharField(max_length=160, unique=True)
    strategy_version = models.ForeignKey(
        "research.StrategyVersion",
        on_delete=models.PROTECT,
        related_name="historical_data_contracts",
    )
    discovery_registration = models.OneToOneField(
        HistoricalDiscoveryRegistration, on_delete=models.PROTECT, related_name="data_contract"
    )
    superseded_data_identity = models.CharField(max_length=160)
    phase1_spec_hash = models.CharField(max_length=64)
    phase1_manifest_hash = models.CharField(max_length=64)
    global_semantic_inventory_sha256 = models.CharField(max_length=64)
    approval_sha256 = models.CharField(max_length=64)
    registration_report_sha256 = models.CharField(max_length=64)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        expected_hash = dataset_manifest_sha256(self.payload)
        if self.sha256 and self.sha256 != expected_hash:
            raise ValidationError("data contract SHA-256 does not match canonical payload")
        self.sha256 = expected_hash
        return super().save(*args, **kwargs)


class Candle(models.Model):
    """One completed bid/ask interval.

    Governed rows (``dataset_version`` set) are owned by an immutable historical
    dataset. Live rows (``dataset_version`` NULL) are frozen at their first
    accepted complete observation: ``content_sha256``/``observed_at`` bind that
    identity, later provider revisions are appended to ``CandleObservation``
    and never rewrite this row. Rows written before Phase 1 carry the honest
    ``legacy_unknown`` provenance marker with no fabricated hash or timestamp.
    """

    class Provenance(models.TextChoices):
        OBSERVED = "observed", "Observed live candle"
        FIXTURE = "fixture", "Development fixture"
        LEGACY_UNKNOWN = "legacy_unknown", "Legacy row; provenance not recorded"

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
    content_sha256 = models.CharField(max_length=64, null=True, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    provenance = models.CharField(max_length=16, choices=Provenance, null=True, blank=True)

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
            models.CheckConstraint(
                condition=(
                    models.Q(dataset_version__isnull=False, provenance__isnull=True)
                    | models.Q(dataset_version__isnull=True, provenance__isnull=False)
                ),
                name="candle_provenance_matches_ownership",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(provenance="observed")
                    | models.Q(content_sha256__isnull=False, observed_at__isnull=False)
                ),
                name="candle_observed_rows_carry_identity",
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

    @property
    def is_live(self):
        return self.dataset_version_id is None

    def authoritative_observation(self):
        """Latest provider view of this interval: the highest recorded revision.

        The evidence contract stays bound to this row (revision 1); a higher
        revision here means the provider later published different content and
        that revision is retained for inspection rather than adopted silently.
        """
        return self.observations.order_by("-revision", "-id").first()

    def save(self, *args, **kwargs):
        if self.pk and self.dataset_version_id:
            raise ValidationError("governed dataset candles are immutable")
        if self.pk:
            raise ValidationError("live candles are append-only; record a revision instead")
        if self.dataset_version_id is None and self.provenance is None:
            # A live row written outside the observation path carries no
            # attested provenance; say so instead of inventing one.
            self.provenance = self.Provenance.LEGACY_UNKNOWN
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.dataset_version_id:
            raise ValidationError("governed dataset candles are immutable")
        if self.provenance != self.Provenance.FIXTURE:
            raise ValidationError("live candles are append-only")
        return super().delete(*args, **kwargs)


class CandleObservation(ImmutableModel):
    """Append-only ledger of every change in the recorded view of a live candle.

    The chain belongs to the canonical candle identity ``(instrument,
    granularity, interval start)``, not to a source: ``revision`` is the row's
    position in that candle's view history across all sources and
    ``supersedes`` always points at revision N-1 of the same candle. Revision 1
    rows are either the ``initial``/``late_arrival`` observation that created
    the frozen ``Candle`` row or the first recorded view of a legacy candle
    (kind ``revision``/``conflict``). Every later change of content appends a
    dense ``revision``/``conflict`` row superseding the current chain head
    without deleting or rewriting anything. ``source`` and ``ingestion_run``
    are provenance attributes of each observation. Content equal to the current
    view creates no row. A revision may repeat a content hash recorded in an
    earlier revision: when a provider publishes A, then B, then A again, the
    ledger holds three rows, so the chain stays faithful to what was observed
    and re-observation of any earlier content can never fail.
    """

    class Kind(models.TextChoices):
        INITIAL = "initial", "First observation"
        LATE_ARRIVAL = "late_arrival", "First observation arriving after later candles"
        REVISION = "revision", "Provider revision of an unreferenced candle"
        CONFLICT = "conflict", "Provider revision of a candle bound to frozen evidence"

    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    granularity = models.CharField(max_length=3, choices=GRANULARITIES)
    timestamp = models.DateTimeField(help_text="UTC interval-start timestamp")
    interval_end = models.DateTimeField(help_text="UTC interval completion under live semantics")
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
    source = models.ForeignKey(SourceRegistry, on_delete=models.PROTECT)
    ingestion_run = models.ForeignKey(
        IngestionRun, on_delete=models.PROTECT, related_name="candle_observations"
    )
    candle = models.ForeignKey(Candle, on_delete=models.PROTECT, related_name="observations")
    kind = models.CharField(max_length=16, choices=Kind)
    revision = models.PositiveIntegerField()
    supersedes = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by"
    )
    content_sha256 = models.CharField(max_length=64)
    differing_fields = models.JSONField(default=list)
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("instrument", "granularity", "timestamp", "revision")
        constraints = [
            models.UniqueConstraint(
                fields=("candle", "revision"),
                name="unique_candle_observation_chain",
            ),
            models.CheckConstraint(
                condition=models.Q(complete=True), name="candle_observation_complete"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind__in=("initial", "late_arrival"),
                        revision=1,
                        supersedes__isnull=True,
                    )
                    | models.Q(
                        kind__in=("revision", "conflict"),
                        revision=1,
                        supersedes__isnull=True,
                    )
                    | models.Q(
                        kind__in=("revision", "conflict"),
                        revision__gt=1,
                        supersedes__isnull=False,
                    )
                ),
                name="candle_observation_revision_shape",
            ),
            models.CheckConstraint(
                condition=models.Q(timestamp__lt=models.F("interval_end")),
                name="candle_observation_increasing_interval",
            ),
        ]
        indexes = [
            models.Index(fields=("candle", "-revision"), name="candle_observation_rev_idx"),
            # Supports the bounded DISTINCT ON (timestamp) eligible-observation scan.
            models.Index(
                fields=("instrument", "granularity", "-timestamp", "-revision"),
                name="candle_obs_series_rev_idx",
            ),
        ]


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
    data_contract = models.ForeignKey(
        "market.HistoricalDataContract",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dataset_registrations",
    )
    global_semantic_inventory_sha256 = models.CharField(max_length=64, null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.data_contract_id is not None:
            configuration = {
                "identity": "failed-break-provider-observed-dataset-registration-v1",
                "plan_sha256": self.plan.sha256,
                "dataset_manifest_sha256": self.dataset_version.manifest_sha256,
                "price_component": HistoricalDatasetPlan.PRICE_COMPONENT,
                "logical_chunk_set_hash": self.logical_chunk_set_hash,
                "data_contract_sha256": self.data_contract.sha256,
                "global_semantic_inventory_sha256": self.global_semantic_inventory_sha256,
            }
        else:
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
    """One deterministic technical calculation over an exact candle set.

    Snapshots are append-only: a recalculation whose source candle set or
    algorithm differs appends a new row instead of rewriting the one that
    existing evidence snapshots and recommendations already reference. The
    authoritative snapshot for (instrument, granularity, as_of) is the most
    recently calculated row. Legacy rows carry ``legacy_unknown`` provenance
    and no source-set hash; their algorithm version is recorded as
    ``technicals-v1`` because the calculation module has never changed.
    """

    ALGORITHM_VERSION = "technicals-v1"

    class Provenance(models.TextChoices):
        OBSERVED = "observed", "Calculated from observed candles"
        FIXTURE = "fixture", "Calculated from development fixtures"
        LEGACY_UNKNOWN = "legacy_unknown", "Legacy row; source binding not recorded"

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
    algorithm_version = models.CharField(max_length=40, default=ALGORITHM_VERSION)
    source_candle_set_sha256 = models.CharField(max_length=64, null=True, blank=True)
    provenance = models.CharField(
        max_length=16, choices=Provenance, default=Provenance.LEGACY_UNKNOWN
    )
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "instrument",
                    "granularity",
                    "as_of",
                    "algorithm_version",
                    "source_candle_set_sha256",
                ),
                name="unique_technical_snapshot_calculation",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(provenance="legacy_unknown", source_candle_set_sha256__isnull=True)
                    | models.Q(
                        provenance__in=("observed", "fixture"),
                        source_candle_set_sha256__isnull=False,
                    )
                ),
                name="technical_snapshot_binding_matches_provenance",
            ),
        ]
        ordering = ("-as_of", "-calculated_at", "-id")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("technical snapshots are append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.provenance != self.Provenance.FIXTURE:
            raise ValidationError("technical snapshots are append-only")
        return super().delete(*args, **kwargs)


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


#: Allowed aggregate data-quality states of a market-state snapshot. This is a
#: coarse status over the whole snapshot; per-feature availability lives inside
#: ``output_payload`` (see docs/phase4/design.md §6) and is never collapsed into
#: this field. ``complete`` = every requested family available; ``partial`` =
#: some family unavailable with a reason; ``degraded`` = an input-quality caveat.
MARKET_STATE_QUALITY_STATES = (
    ("complete", "Complete"),
    ("partial", "Partial"),
    ("degraded", "Degraded"),
)


class MarketStateDefinition(ImmutableModel):
    """Immutable, versioned, content-addressed market-state definition.

    Binds the semantic ``(key, version)`` to a canonical JSON ``definition``
    body (algorithms, feature names, lookbacks, thresholds, calendar/session
    policy, price basis, rounding and missing-data policy) and its SHA-256. A
    definition is content-addressed: the same body always hashes to the same
    ``definition_sha256`` (unique), and each ``(key, version)`` is unique. The
    canonical hash is recomputed and verified on save so a row can never carry a
    digest that disagrees with its content. See docs/phase4/design.md §5.1.
    """

    key = models.CharField(max_length=80)
    version = models.CharField(max_length=40)
    definition = models.JSONField()
    definition_sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("key", "version")
        constraints = [
            models.UniqueConstraint(
                fields=("key", "version"), name="unique_market_state_definition_version"
            ),
            # Reject a malformed digest at the database boundary (also for raw
            # INSERTs that bypass save()): the SHA-256 must be 64 lowercase hex.
            models.CheckConstraint(
                condition=models.Q(definition_sha256__regex=r"^[0-9a-f]{64}$"),
                name="market_state_definition_sha256_hex",
            ),
        ]

    def save(self, *args, **kwargs):
        from market.state.canonical import identity_digest

        expected = identity_digest(self.definition)
        if self.definition_sha256 and self.definition_sha256 != expected:
            raise ValidationError("market-state definition SHA-256 does not match canonical JSON")
        self.definition_sha256 = expected
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.key}@{self.version}"


class MarketStateSnapshot(ImmutableModel):
    """Immutable, append-only, idempotent market-state snapshot.

    For a fixed ``(definition, instrument, information_cutoff, input manifest)``
    the ``output_payload`` is byte-equivalent, so the snapshot is identified by
    ``idempotency_key`` (a hash over exactly those inputs). ``input_manifest``
    is the ordered set of eligible candle identities and content hashes that
    were causally available at the cutoff; ``evidence_manifest`` records
    macro/event/spread vintage identities when used. Rows are append-only and
    immutable at both the ORM (``ImmutableModel``) and the database boundary
    (BEFORE UPDATE/DELETE/TRUNCATE triggers). See docs/phase4/design.md §5.2.
    """

    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    definition = models.ForeignKey(MarketStateDefinition, on_delete=models.PROTECT)
    information_cutoff = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    input_manifest = models.JSONField()
    input_manifest_sha256 = models.CharField(max_length=64)
    evidence_manifest = models.JSONField(default=dict)
    output_payload = models.JSONField()
    output_sha256 = models.CharField(max_length=64)
    data_quality_status = models.CharField(max_length=16, choices=MARKET_STATE_QUALITY_STATES)
    idempotency_key = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ("instrument", "information_cutoff", "created_at")
        indexes = [
            models.Index(fields=("instrument", "definition", "-information_cutoff")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    data_quality_status__in=[s for s, _ in MARKET_STATE_QUALITY_STATES]
                ),
                name="market_state_snapshot_quality_status_valid",
            ),
            # DB-boundary rejection of malformed hashes (also for raw INSERTs).
            models.CheckConstraint(
                condition=models.Q(output_sha256__regex=r"^[0-9a-f]{64}$")
                & models.Q(input_manifest_sha256__regex=r"^[0-9a-f]{64}$")
                & models.Q(idempotency_key__regex=r"^[0-9a-f]{64}$"),
                name="market_state_snapshot_sha256_hex",
            ),
        ]

    def __str__(self):
        return f"{self.instrument_id}:{self.definition_id}@{self.information_cutoff.isoformat()}"


class StrategyDefinition(ImmutableModel):
    """Offline preregistration only; never a promotion or execution authority."""

    strategy = models.CharField(max_length=100, unique=True)
    body = models.JSONField()
    body_sha256 = models.CharField(max_length=64, unique=True)
    registered_at = models.DateTimeField(auto_now_add=True)


class StrategyEvaluation(ImmutableModel):
    """One attributed calculation from an exact immutable descriptor snapshot."""

    definition = models.ForeignKey(StrategyDefinition, on_delete=models.PROTECT)
    snapshot = models.ForeignKey(MarketStateSnapshot, on_delete=models.PROTECT)
    previous = models.ForeignKey("self", on_delete=models.PROTECT, null=True)
    evidence = models.JSONField()
    evidence_sha256 = models.CharField(max_length=64)
    output = models.JSONField()
    output_sha256 = models.CharField(max_length=64)
    identity = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class StrategySimulation(ImmutableModel):
    """Offline modeled outcome, separately stored from decision-time evidence."""

    evaluation = models.ForeignKey(StrategyEvaluation, on_delete=models.PROTECT)
    outcome_snapshot = models.ForeignKey(MarketStateSnapshot, on_delete=models.PROTECT)
    attempt_key = models.CharField(max_length=64, unique=True)
    intent = models.JSONField()
    outcome_evidence = models.JSONField()
    output = models.JSONField()
    output_sha256 = models.CharField(max_length=64)
    identity = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
