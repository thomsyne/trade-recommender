from django.core.exceptions import ValidationError
from django.db import models

from market.models import Instrument, SourceRegistry


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
        EQUITY = "equity", "Equity market"
        VOLATILITY = "volatility", "Market volatility"
        CRYPTO = "crypto", "Cryptoasset"
        COMMODITY = "commodity", "Commodity"
        YIELD = "yield", "Government yield"
        DOLLAR = "dollar", "US dollar index"

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
        DATE_VALUE_CSV = "date_value_csv", "Date/value CSV"

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
    class TimePrecision(models.TextChoices):
        EXACT = "exact", "Exact time"
        DATE = "date", "Date only"

    retrieval = models.ForeignKey(RawRetrieval, on_delete=models.PROTECT)
    series = models.ForeignKey(
        MacroSeries, on_delete=models.PROTECT, null=True, blank=True, related_name="release_events"
    )
    provider_event_key = models.CharField(max_length=64)
    event_at = models.DateTimeField()
    time_precision = models.CharField(
        max_length=8, choices=TimePrecision, default=TimePrecision.EXACT
    )
    country = models.CharField(max_length=2)
    event_type = models.CharField(max_length=240)
    source_url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(max_length=24, default="scheduled")
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


class PairEvidenceSnapshot(ImmutableRecord):
    instrument = models.ForeignKey(
        Instrument, on_delete=models.PROTECT, related_name="research_evidence_snapshots"
    )
    information_cutoff = models.DateTimeField()
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64, unique=True)
    captured_at = models.DateTimeField()

    class Meta:
        ordering = ("-captured_at", "-id")
        indexes = [models.Index(fields=("instrument", "-captured_at"))]


class StrategyDefinition(ImmutableRecord):
    key = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=240)
    description = models.TextField(blank=True)


class StrategyVersion(ImmutableRecord):
    definition = models.ForeignKey(StrategyDefinition, on_delete=models.PROTECT)
    version = models.CharField(max_length=80)
    detector_version = models.CharField(max_length=80)
    data_identity = models.CharField(max_length=160)
    event_identity = models.CharField(max_length=160)
    execution_identity = models.CharField(max_length=160)
    cost_identity = models.CharField(max_length=160)
    portfolio_identity = models.CharField(max_length=160)
    pair_metadata = models.JSONField(default=dict)
    timeframe_metadata = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("definition", "version"), name="unique_strategy_definition_version"
            )
        ]


class StrategyParameterManifest(ImmutableRecord):
    strategy_version = models.OneToOneField(StrategyVersion, on_delete=models.PROTECT)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64, unique=True)
    phase1_spec_hash = models.CharField(max_length=64)
    phase1_manifest_hash = models.CharField(max_length=64)


class Level(ImmutableRecord):
    class Family(models.TextChoices):
        WEEKLY = "PREVIOUS_WEEKLY_EXTREME", "Previous weekly extreme"
        DAILY_SWING = "CONFIRMED_DAILY_SWING", "Confirmed daily swing"
        BREAKOUT = "TWENTY_SESSION_BREAKOUT_FLIP", "Twenty-session breakout flip"

    class Role(models.TextChoices):
        SUPPORT = "support", "Support"
        RESISTANCE = "resistance", "Resistance"

    family = models.CharField(max_length=32, choices=Family)
    role = models.CharField(max_length=12, choices=Role)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT)
    dataset_version = models.ForeignKey("market.DatasetVersion", on_delete=models.PROTECT)
    source_timeframe = models.CharField(max_length=8)
    source_candle_timestamp = models.DateTimeField()
    central_price = models.DecimalField(max_digits=20, decimal_places=10)
    zone_lower = models.DecimalField(max_digits=20, decimal_places=10)
    zone_upper = models.DecimalField(max_digits=20, decimal_places=10)
    atr_at_activation = models.DecimalField(max_digits=20, decimal_places=10)
    activated_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    stable_key = models.CharField(max_length=64, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(zone_lower__lte=models.F("central_price")),
                name="level_low_lte_central",
            ),
            models.CheckConstraint(
                condition=models.Q(central_price__lte=models.F("zone_upper")),
                name="level_central_lte_high",
            ),
            models.CheckConstraint(
                condition=models.Q(atr_at_activation__gt=0), name="level_atr_positive"
            ),
        ]


class LevelLifecycleEvent(ImmutableRecord):
    class State(models.TextChoices):
        INVALIDATED = "invalidated", "Invalidated"
        EXPIRED = "expired", "Expired"
        SUPERSEDED = "superseded", "Superseded"
        SUPERSEDED_BY_FLIP = "superseded_by_flip", "Superseded by flip"

    level = models.ForeignKey(Level, on_delete=models.PROTECT)
    state = models.CharField(max_length=20, choices=State)
    effective_at = models.DateTimeField()
    evidence = models.JSONField(default=dict)
    evidence_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("level", "state", "effective_at", "evidence_hash"),
                name="unique_level_lifecycle_event",
            )
        ]


class LevelProximityEvent(ImmutableRecord):
    class Kind(models.TextChoices):
        APPROACHING = "approaching", "Approaching"
        TOUCHED = "touched", "Touched"

    level = models.ForeignKey(Level, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=Kind)
    observed_at = models.DateTimeField()
    observation_bucket = models.DateTimeField()
    evidence_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("level", "kind", "observation_bucket"), name="unique_level_proximity_bucket"
            )
        ]


class AnalysisRun(ImmutableRecord):
    class Result(models.TextChoices):
        NO_SETUP = "NO_SETUP", "No setup"
        LEVEL_ACTIVE = "LEVEL_ACTIVE", "Level active"
        CANDIDATE_CREATED = "CANDIDATE_CREATED", "Candidate created"
        DATA_INCOMPLETE = "DATA_INCOMPLETE", "Data incomplete"

    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    completed_h1_timestamp = models.DateTimeField()
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT)
    dataset_version = models.ForeignKey("market.DatasetVersion", on_delete=models.PROTECT)
    result = models.CharField(max_length=20, choices=Result)
    evidence_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "instrument",
                    "completed_h1_timestamp",
                    "strategy_version",
                    "dataset_version",
                ),
                name="unique_analysis_instrument_h1_strategy_dataset",
            )
        ]


class SetupEvent(ImmutableRecord):
    class Direction(models.TextChoices):
        LONG = "long", "Long"
        SHORT = "short", "Short"

    class InitialState(models.TextChoices):
        TRIGGER_PENDING = "TRIGGER_PENDING", "Trigger pending"

    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    direction = models.CharField(max_length=5, choices=Direction)
    sweep_h1_timestamp = models.DateTimeField()
    detector_version = models.CharField(max_length=80)
    dataset_version = models.ForeignKey("market.DatasetVersion", on_delete=models.PROTECT)
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT)
    sweep_evidence = models.JSONField()
    bias_evidence = models.JSONField()
    provisional_swing_evidence = models.JSONField()
    threshold_evidence = models.JSONField()
    evidence_hash = models.CharField(max_length=64)
    initial_state = models.CharField(
        max_length=16, choices=InitialState, default=InitialState.TRIGGER_PENDING
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "instrument",
                    "direction",
                    "sweep_h1_timestamp",
                    "detector_version",
                    "dataset_version",
                ),
                name="unique_physical_setup_event",
            )
        ]


class SetupLevelAttribution(ImmutableRecord):
    setup = models.ForeignKey(SetupEvent, on_delete=models.PROTECT)
    level = models.ForeignKey(Level, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("setup", "level"), name="unique_setup_level_attribution"
            )
        ]


class JobRun(ImmutableRecord):
    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        DATA_INCOMPLETE = "data_incomplete", "Data incomplete"

    job_name = models.CharField(max_length=120)
    occurrence = models.ForeignKey(
        "operations.JobOccurrence", on_delete=models.PROTECT, null=True, blank=True
    )
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT)
    dataset_version = models.ForeignKey("market.DatasetVersion", on_delete=models.PROTECT)
    config_hash = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=200, unique=True)
    as_of = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status)
    evidence = models.JSONField(default=dict)


class SetupTransition(ImmutableRecord):
    class State(models.TextChoices):
        TRIGGER_PENDING = "TRIGGER_PENDING", "Trigger pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        ENTRY_PENDING = "ENTRY_PENDING", "Entry pending"
        INVALIDATED = "INVALIDATED", "Invalidated"
        EXPIRED = "EXPIRED", "Expired"
        MISSED_FILL = "MISSED_FILL", "Missed fill"
        BLOCKED_SESSION = "BLOCKED_SESSION", "Blocked session"
        BLOCKED_SPREAD = "BLOCKED_SPREAD", "Blocked spread"
        NO_TARGET = "NO_TARGET", "No target"
        INSUFFICIENT_REWARD = "INSUFFICIENT_REWARD", "Insufficient reward"
        CANCELLED_DATA_QUALITY = "CANCELLED_DATA_QUALITY", "Cancelled data quality"

    setup = models.ForeignKey(SetupEvent, on_delete=models.PROTECT)
    from_state = models.CharField(max_length=24, choices=State)
    to_state = models.CharField(max_length=24, choices=State)
    effective_at = models.DateTimeField()
    evidence = models.JSONField(default=dict)
    evidence_hash = models.CharField(max_length=64)
    reason = models.CharField(max_length=240, blank=True)
    job_run = models.ForeignKey(JobRun, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("setup", "from_state", "to_state", "effective_at"),
                name="unique_setup_transition",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        from_state="TRIGGER_PENDING",
                        to_state__in=(
                            "CONFIRMED",
                            "INVALIDATED",
                            "EXPIRED",
                            "CANCELLED_DATA_QUALITY",
                        ),
                    )
                    | models.Q(
                        from_state="CONFIRMED",
                        to_state__in=(
                            "ENTRY_PENDING",
                            "MISSED_FILL",
                            "BLOCKED_SESSION",
                            "BLOCKED_SPREAD",
                            "NO_TARGET",
                            "INSUFFICIENT_REWARD",
                            "CANCELLED_DATA_QUALITY",
                        ),
                    )
                ),
                name="valid_phase2a_setup_transition",
            ),
        ]


class EntryEligibilityEvaluation(ImmutableRecord):
    class Decision(models.TextChoices):
        ENTRY_PENDING = "ENTRY_PENDING", "Entry pending"
        MISSED_FILL = "MISSED_FILL", "Missed fill"
        BLOCKED_SESSION = "BLOCKED_SESSION", "Blocked session"
        BLOCKED_SPREAD = "BLOCKED_SPREAD", "Blocked spread"
        NO_TARGET = "NO_TARGET", "No target"
        INSUFFICIENT_REWARD = "INSUFFICIENT_REWARD", "Insufficient reward"
        CANCELLED_DATA_QUALITY = "CANCELLED_DATA_QUALITY", "Cancelled data quality"

    setup = models.ForeignKey(SetupEvent, on_delete=models.PROTECT)
    book_identity = models.CharField(max_length=160)
    decision = models.CharField(max_length=24, choices=Decision)
    terminal_reason = models.CharField(max_length=240, blank=True)
    entry_timestamp = models.DateTimeField(null=True, blank=True)
    entry_price = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    stop_price = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    target_price = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    reward_risk = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    target_level = models.ForeignKey(
        Level, on_delete=models.PROTECT, null=True, blank=True, related_name="entry_evaluations"
    )
    evidence = models.JSONField(default=dict)
    evidence_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("setup", "book_identity"), name="unique_setup_book_eligibility"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        decision="ENTRY_PENDING",
                        terminal_reason="",
                        entry_timestamp__isnull=False,
                        entry_price__isnull=False,
                        stop_price__isnull=False,
                        target_price__isnull=False,
                        reward_risk__isnull=False,
                        target_level__isnull=False,
                    )
                    | models.Q(
                        decision__in=(
                            "MISSED_FILL",
                            "BLOCKED_SESSION",
                            "BLOCKED_SPREAD",
                            "NO_TARGET",
                            "INSUFFICIENT_REWARD",
                            "CANCELLED_DATA_QUALITY",
                        ),
                        terminal_reason__gt="",
                        entry_timestamp__isnull=True,
                        entry_price__isnull=True,
                        stop_price__isnull=True,
                        target_price__isnull=True,
                        reward_risk__isnull=True,
                        target_level__isnull=True,
                    )
                ),
                name="eligibility_fields_match_decision",
            ),
        ]
