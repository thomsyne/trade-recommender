from django.core.exceptions import ValidationError
from django.db import models

from market.models import SourceRegistry


class ImmutableRecord(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(f"{type(self).__name__} records are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(f"{type(self).__name__} records are immutable")


class SourcePolicy(models.Model):
    class State(models.TextChoices):
        ENABLED = "enabled", "Enabled"
        QUARANTINED = "quarantined", "Quarantined"
        DISABLED = "disabled", "Disabled"

    source = models.OneToOneField(SourceRegistry, on_delete=models.PROTECT, related_name="policy")
    slug = models.SlugField(unique=True)
    jurisdiction = models.CharField(max_length=2)
    currency = models.CharField(max_length=3)
    allowed_hosts = models.JSONField(default=list)
    allowed_content_types = models.JSONField(default=list)
    max_response_bytes = models.PositiveIntegerField(default=2_000_000)
    rights_url = models.URLField()
    rights_reviewed_at = models.DateTimeField(null=True, blank=True)
    retention_class = models.CharField(max_length=40, default="official-public-record")
    full_text_allowed = models.BooleanField(default=False)
    state = models.CharField(max_length=16, choices=State, default=State.QUARANTINED)
    quality_note = models.TextField(blank=True)

    class Meta:
        ordering = ("jurisdiction", "source__name")

    def __str__(self):
        return self.source.name


class RawRetrieval(ImmutableRecord):
    class Quality(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        QUARANTINED = "quarantined", "Quarantined"
        REJECTED = "rejected", "Rejected"

    source_policy = models.ForeignKey(SourcePolicy, on_delete=models.PROTECT)
    url = models.URLField(max_length=1000)
    request_fingerprint = models.CharField(max_length=64)
    fetched_at = models.DateTimeField()
    http_status = models.PositiveSmallIntegerField()
    content_type = models.CharField(max_length=120)
    byte_count = models.PositiveIntegerField()
    body_sha256 = models.CharField(max_length=64)
    body = models.BinaryField()
    etag = models.CharField(max_length=500, blank=True)
    last_modified = models.CharField(max_length=200, blank=True)
    quality = models.CharField(max_length=16, choices=Quality, default=Quality.ACCEPTED)
    quality_reason = models.TextField(blank=True)
    retention_decision = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-fetched_at", "-id")
        indexes = [models.Index(fields=("source_policy", "-fetched_at"))]


class ResearchDocument(models.Model):
    class Quality(models.TextChoices):
        VERIFIED = "verified", "Verified timestamp"
        QUARANTINED = "quarantined", "Quarantined"
        CONFLICT = "conflict", "Conflict"

    canonical_url = models.URLField(max_length=1000)
    canonical_hash = models.CharField(max_length=64, unique=True)
    title = models.TextField()
    published_at = models.DateTimeField(null=True, blank=True)
    first_observed_at = models.DateTimeField()
    language = models.CharField(max_length=12, default="en")
    quality = models.CharField(max_length=16, choices=Quality)
    quality_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("-published_at", "-first_observed_at")


class DocumentRepresentation(ImmutableRecord):
    document = models.ForeignKey(
        ResearchDocument, on_delete=models.PROTECT, related_name="representations"
    )
    retrieval = models.ForeignKey(
        RawRetrieval, on_delete=models.PROTECT, related_name="document_representations"
    )
    source_item_id = models.TextField()
    dedup_key = models.CharField(max_length=64, unique=True)
    source_title = models.TextField()
    source_published_at = models.DateTimeField(null=True, blank=True)
    summary = models.TextField(blank=True)

    class Meta:
        ordering = ("-source_published_at", "-id")


class MacroSeries(models.Model):
    class Indicator(models.TextChoices):
        POLICY_RATE = "policy_rate", "Policy rate"
        CPI = "cpi", "Inflation"
        UNEMPLOYMENT = "unemployment", "Unemployment"
        GDP = "gdp", "GDP growth"
        HOUSING = "housing", "Housing"

    class Parser(models.TextChoices):
        BOC_VALET = "boc_valet", "Bank of Canada Valet JSON"
        FRED_CSV = "fred_csv", "FRED CSV"
        ECB_CSV = "ecb_csv", "ECB Data API CSV"
        BOE_CSV = "boe_csv", "Bank of England IADB CSV"
        STATCAN_WDS = "statcan_wds", "Statistics Canada WDS JSON"
        BLS_JSON = "bls_json", "US BLS JSON"
        ONS_CSV = "ons_csv", "UK ONS generator CSV"
        EUROSTAT_JSON = "eurostat_json", "Eurostat JSON-stat"
        LAND_REGISTRY_CSV = "land_registry_csv", "UK HPI linked-data CSV"
        STATCAN_ZIP = "statcan_zip", "Statistics Canada bounded table ZIP"

    class RequestMethod(models.TextChoices):
        GET = "GET", "GET"
        POST = "POST", "POST"

    class Transformation(models.TextChoices):
        NONE = "none", "None"
        YEAR_OVER_YEAR = "year_over_year", "Year-over-year percent change"

    source_policy = models.ForeignKey(SourcePolicy, on_delete=models.PROTECT)
    code = models.CharField(max_length=80, unique=True)
    provider_series_id = models.CharField(max_length=160)
    label = models.CharField(max_length=240)
    indicator = models.CharField(max_length=20, choices=Indicator, default=Indicator.POLICY_RATE)
    unit = models.CharField(max_length=40)
    frequency = models.CharField(max_length=40)
    parser = models.CharField(max_length=20, choices=Parser)
    url = models.URLField(max_length=1000)
    request_method = models.CharField(
        max_length=4, choices=RequestMethod, default=RequestMethod.GET
    )
    request_payload = models.JSONField(default=dict, blank=True)
    transformation = models.CharField(
        max_length=20, choices=Transformation, default=Transformation.NONE
    )
    enabled = models.BooleanField(default=True)
    point_in_time_note = models.TextField()

    class Meta:
        ordering = ("source_policy__jurisdiction", "label")


class MacroObservation(ImmutableRecord):
    class AvailabilityPrecision(models.TextChoices):
        PROVIDER = "provider", "Provider timestamp"
        RETRIEVAL = "retrieval", "First known at retrieval"

    series = models.ForeignKey(MacroSeries, on_delete=models.PROTECT, related_name="observations")
    retrieval = models.ForeignKey(RawRetrieval, on_delete=models.PROTECT)
    observation_period = models.DateField()
    value = models.DecimalField(max_digits=24, decimal_places=8)
    normalized_value = models.CharField(max_length=80)
    available_at = models.DateTimeField()
    vintage_at = models.DateTimeField()
    revision_sequence = models.PositiveIntegerField(default=0)
    availability_precision = models.CharField(
        max_length=12, choices=AvailabilityPrecision, default=AvailabilityPrecision.RETRIEVAL
    )
    provider_status = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("-observation_period", "-revision_sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("series", "observation_period", "normalized_value"),
                name="unique_macro_series_period_value",
            )
        ]


class ResearchDiscrepancy(ImmutableRecord):
    class Kind(models.TextChoices):
        DUPLICATE = "duplicate", "Duplicate"
        CONFLICT = "conflict", "Conflict"
        REVISION = "revision", "Revision"

    kind = models.CharField(max_length=12, choices=Kind)
    entity_key = models.CharField(max_length=240)
    earlier_retrieval = models.ForeignKey(
        RawRetrieval, on_delete=models.PROTECT, related_name="earlier_discrepancies"
    )
    later_retrieval = models.ForeignKey(
        RawRetrieval, on_delete=models.PROTECT, related_name="later_discrepancies"
    )
    detail = models.JSONField(default=dict)
    observed_at = models.DateTimeField()

    class Meta:
        ordering = ("-observed_at",)


class ProviderEvaluation(models.Model):
    class Status(models.TextChoices):
        CANDIDATE = "candidate", "Candidate"
        TESTING = "testing", "Testing"
        SELECTED = "selected", "Selected"
        REJECTED = "rejected", "Rejected"

    category = models.CharField(max_length=80)
    provider = models.CharField(max_length=120)
    status = models.CharField(max_length=12, choices=Status, default=Status.CANDIDATE)
    evidence_url = models.URLField()
    pricing_status = models.CharField(max_length=120)
    timestamp_semantics = models.CharField(max_length=240)
    revision_support = models.CharField(max_length=240)
    retention_rights = models.CharField(max_length=240)
    reliability_result = models.CharField(max_length=240)
    next_check = models.TextField()
    checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("category", "provider"), name="unique_research_provider_evaluation"
            )
        ]
        ordering = ("category", "provider")


class EconomicEvent(ImmutableRecord):
    retrieval = models.ForeignKey(RawRetrieval, on_delete=models.PROTECT)
    provider_event_key = models.CharField(max_length=64)
    event_at = models.DateTimeField()
    country = models.CharField(max_length=2)
    event_type = models.CharField(max_length=240)
    comparison = models.CharField(max_length=12, blank=True)
    period = models.CharField(max_length=40, blank=True)
    actual = models.DecimalField(max_digits=24, decimal_places=8, null=True)
    estimate = models.DecimalField(max_digits=24, decimal_places=8, null=True)
    previous = models.DecimalField(max_digits=24, decimal_places=8, null=True)
    payload_fingerprint = models.CharField(max_length=64)
    first_observed_at = models.DateTimeField()

    class Meta:
        ordering = ("-event_at", "country", "event_type")
        constraints = [
            models.UniqueConstraint(
                fields=("provider_event_key", "payload_fingerprint"),
                name="unique_economic_event_vintage",
            )
        ]
