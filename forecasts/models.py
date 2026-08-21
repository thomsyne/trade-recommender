from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from market.models import Candle, Instrument, TechnicalSnapshot


class ImmutableModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(f"{type(self).__name__} records are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(f"{type(self).__name__} records are immutable")


class TargetContract(ImmutableModel):
    class Product(models.TextChoices):
        MACRO = "macro", "20-session macro outlook"
        TACTICAL = "tactical", "Five-session tactical outlook"

    key = models.SlugField(max_length=80)
    version = models.PositiveSmallIntegerField()
    product = models.CharField(max_length=12, choices=Product)
    horizon_sessions = models.PositiveSmallIntegerField()
    neutral_atr_multiplier = models.DecimalField(max_digits=5, decimal_places=3)
    spread_multiplier = models.DecimalField(max_digits=5, decimal_places=2)
    scoring_rule = models.CharField(max_length=80)
    definition = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("key", "version"), name="unique_target_contract_version"
            )
        ]
        ordering = ("product", "-version")

    def __str__(self):
        return f"{self.key} v{self.version}"


class EvidenceSnapshot(ImmutableModel):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    anchor_candle = models.ForeignKey(Candle, on_delete=models.PROTECT)
    technical_snapshot = models.ForeignKey(TechnicalSnapshot, on_delete=models.PROTECT)
    market_data_cutoff = models.DateTimeField()
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64, unique=True)
    captured_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-captured_at",)


class Forecast(ImmutableModel):
    class Direction(models.TextChoices):
        UP = "up", "Up"
        NEUTRAL = "neutral", "Neutral"
        DOWN = "down", "Down"

    class EntryCondition(models.TextChoices):
        NONE = "none", "No conditional entry"
        AT_OR_BELOW = "at_or_below", "At or below"
        AT_OR_ABOVE = "at_or_above", "At or above"

    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    target_contract = models.ForeignKey(TargetContract, on_delete=models.PROTECT)
    evidence_snapshot = models.ForeignKey(EvidenceSnapshot, on_delete=models.PROTECT)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    method = models.CharField(max_length=80)
    method_version = models.PositiveSmallIntegerField(default=1)
    issued_at = models.DateTimeField(default=timezone.now)
    information_cutoff = models.DateTimeField()
    reference_midpoint = models.DecimalField(max_digits=12, decimal_places=6)
    neutral_band = models.DecimalField(max_digits=12, decimal_places=6)
    direction = models.CharField(max_length=8, choices=Direction)
    probability_up = models.DecimalField(max_digits=5, decimal_places=4)
    probability_neutral = models.DecimalField(max_digits=5, decimal_places=4)
    probability_down = models.DecimalField(max_digits=5, decimal_places=4)
    abstained = models.BooleanField(default=True)
    abstention_reason = models.TextField(blank=True)
    entry_condition = models.CharField(
        max_length=16, choices=EntryCondition, default=EntryCondition.NONE
    )
    entry_level = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    target_level = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    invalidation_level = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    setup_expires_after_sessions = models.PositiveSmallIntegerField()
    rationale = models.TextField()
    idempotency_key = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ("-issued_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(probability_up__gte=0, probability_up__lte=1),
                name="forecast_probability_up_range",
            ),
            models.CheckConstraint(
                condition=models.Q(probability_neutral__gte=0, probability_neutral__lte=1),
                name="forecast_probability_neutral_range",
            ),
            models.CheckConstraint(
                condition=models.Q(probability_down__gte=0, probability_down__lte=1),
                name="forecast_probability_down_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    probability_up=models.Value(1)
                    - models.F("probability_neutral")
                    - models.F("probability_down")
                ),
                name="forecast_probabilities_sum_one",
            ),
            models.CheckConstraint(
                condition=models.Q(information_cutoff__lte=models.F("issued_at")),
                name="forecast_cutoff_not_after_issuance",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    entry_condition="none",
                    entry_level__isnull=True,
                    target_level__isnull=True,
                    invalidation_level__isnull=True,
                    abstained=True,
                )
                | models.Q(
                    entry_condition__in=("at_or_below", "at_or_above"),
                    entry_level__isnull=False,
                    target_level__isnull=False,
                    invalidation_level__isnull=False,
                    abstained=False,
                ),
                name="forecast_setup_shape_valid",
            ),
        ]

    def clean(self):
        if self.probability_up + self.probability_neutral + self.probability_down != 1:
            raise ValidationError("Forecast probabilities must sum to one")
        if self.evidence_snapshot.instrument_id != self.instrument_id:
            raise ValidationError("Forecast and evidence instruments must match")
        if self.target_contract.product == TargetContract.Product.TACTICAL:
            if not self.parent_id:
                raise ValidationError("A tactical forecast requires a parent macro forecast")
            if (
                self.parent.instrument_id != self.instrument_id
                or self.parent.target_contract.product != TargetContract.Product.MACRO
            ):
                raise ValidationError(
                    "Tactical parent must be a macro forecast for the same instrument"
                )
        elif self.parent_id:
            raise ValidationError("A macro forecast cannot have a parent forecast")
        if self.entry_condition == self.EntryCondition.NONE and not self.abstained:
            raise ValidationError("A forecast without an entry condition must explicitly abstain")
        if self.entry_condition != self.EntryCondition.NONE and self.abstained:
            raise ValidationError("An abstaining forecast cannot offer an entry condition")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def is_resolved(self):
        return hasattr(self, "resolution")


class ForecastResolution(ImmutableModel):
    class Outcome(models.TextChoices):
        UP = "up", "Up"
        NEUTRAL = "neutral", "Neutral"
        DOWN = "down", "Down"
        CANCELLED = "cancelled", "Cancelled"
        MISSING = "missing", "Missing data"

    class SetupOutcome(models.TextChoices):
        NOT_OFFERED = "not_offered", "No setup offered"
        NOT_ACTIVATED = "not_activated", "Entry not activated"
        ACTIVATED = "activated", "Entry activated; paper resolution deferred"

    forecast = models.OneToOneField(Forecast, on_delete=models.PROTECT, related_name="resolution")
    outcome = models.CharField(max_length=12, choices=Outcome)
    horizon_candle = models.ForeignKey(Candle, on_delete=models.PROTECT, null=True, blank=True)
    endpoint_midpoint = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    midpoint_change = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    setup_outcome = models.CharField(max_length=16, choices=SetupOutcome)
    brier_score = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    details = models.JSONField(default=dict)
    resolved_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-resolved_at",)

    def clean(self):
        scored = self.outcome in {
            self.Outcome.UP,
            self.Outcome.NEUTRAL,
            self.Outcome.DOWN,
        }
        values = (
            self.horizon_candle,
            self.endpoint_midpoint,
            self.midpoint_change,
            self.brier_score,
        )
        if scored and any(value is None for value in values):
            raise ValidationError("A scored resolution requires its horizon values and score")
        if not scored and any(value is not None for value in values):
            raise ValidationError("A cancelled or missing resolution cannot contain a score")
        if self.horizon_candle and self.horizon_candle.instrument_id != self.forecast.instrument_id:
            raise ValidationError("Resolution horizon candle must match the forecast instrument")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Recommendation(ImmutableModel):
    class Action(models.TextChoices):
        ABSTAIN = "abstain", "Abstain"
        BUY = "buy", "Buy"
        SELL = "sell", "Sell"

    class EntryCondition(models.TextChoices):
        NONE = "none", "No conditional entry"
        AT_OR_BELOW = "at_or_below", "At or below"
        AT_OR_ABOVE = "at_or_above", "At or above"

    instrument = models.ForeignKey(
        Instrument, on_delete=models.PROTECT, related_name="recommendations"
    )
    evidence_snapshot = models.ForeignKey(
        "research.PairEvidenceSnapshot", on_delete=models.PROTECT, related_name="recommendations"
    )
    reference_candle = models.ForeignKey(
        Candle,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="model_recommendations",
    )
    control_forecast = models.ForeignKey(
        Forecast, on_delete=models.PROTECT, null=True, blank=True, related_name="recommendations"
    )
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=100)
    contract_version = models.PositiveSmallIntegerField(default=1)
    generated_at = models.DateTimeField(default=timezone.now)
    information_cutoff = models.DateTimeField()
    action = models.CharField(max_length=8, choices=Action)
    confidence_percent = models.PositiveSmallIntegerField()
    reference_midpoint = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    neutral_band = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    probability_up = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    probability_neutral = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    probability_down = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    entry_condition = models.CharField(max_length=16, choices=EntryCondition)
    entry_level = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    target_level = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    invalidation_level = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    expires_after_sessions = models.PositiveSmallIntegerField(default=5)
    output = models.JSONField()
    input_payload = models.JSONField()
    request_sha256 = models.CharField(max_length=64)
    provider_response_id = models.CharField(max_length=120, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    idempotency_key = models.CharField(max_length=240, unique=True)

    class Meta:
        ordering = ("-generated_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(confidence_percent__gte=0, confidence_percent__lte=100),
                name="recommendation_confidence_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    action="abstain",
                    entry_condition="none",
                    entry_level__isnull=True,
                    target_level__isnull=True,
                    invalidation_level__isnull=True,
                )
                | models.Q(
                    action__in=("buy", "sell"),
                    entry_condition__in=("at_or_below", "at_or_above"),
                    entry_level__isnull=False,
                    target_level__isnull=False,
                    invalidation_level__isnull=False,
                ),
                name="recommendation_setup_shape_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(information_cutoff__lte=models.F("generated_at")),
                name="recommendation_cutoff_not_after_generation",
            ),
            models.CheckConstraint(
                condition=models.Q(contract_version__lt=2)
                | models.Q(
                    reference_candle__isnull=False,
                    reference_midpoint__isnull=False,
                    neutral_band__isnull=False,
                    probability_up__isnull=False,
                    probability_up__gte=0,
                    probability_up__lte=1,
                    probability_neutral__isnull=False,
                    probability_neutral__gte=0,
                    probability_neutral__lte=1,
                    probability_down__isnull=False,
                    probability_down__gte=0,
                    probability_down__lte=1,
                    probability_up=models.Value(1)
                    - models.F("probability_neutral")
                    - models.F("probability_down"),
                ),
                name="recommendation_v2_outcome_contract_valid",
            ),
        ]

    def clean(self):
        if self.evidence_snapshot.instrument_id != self.instrument_id:
            raise ValidationError("Recommendation and evidence instruments must match")
        if self.control_forecast_id and self.control_forecast.instrument_id != self.instrument_id:
            raise ValidationError("Recommendation and control instruments must match")
        if self.contract_version not in {1, 2, 3}:
            raise ValidationError("Unsupported recommendation contract version")
        if self.contract_version in {2, 3}:
            if (
                not self.reference_candle_id
                or self.reference_candle.instrument_id != self.instrument_id
            ):
                raise ValidationError("Recommendation reference candle must match its instrument")
            values = (
                self.reference_midpoint,
                self.neutral_band,
                self.probability_up,
                self.probability_neutral,
                self.probability_down,
            )
            if any(value is None for value in values):
                raise ValidationError("A v2 recommendation requires its complete outcome contract")
            if self.probability_up + self.probability_neutral + self.probability_down != 1:
                raise ValidationError("Recommendation probabilities must sum to one")
        levels = (self.entry_level, self.target_level, self.invalidation_level)
        if self.action in {self.Action.BUY, self.Action.SELL} and any(
            value is None for value in levels
        ):
            raise ValidationError("A directional recommendation requires all setup levels")
        if self.action == self.Action.BUY and not (
            self.invalidation_level < self.entry_level < self.target_level
        ):
            raise ValidationError("Buy levels must order invalidation < entry < target")
        if self.action == self.Action.SELL and not (
            self.target_level < self.entry_level < self.invalidation_level
        ):
            raise ValidationError("Sell levels must order target < entry < invalidation")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def position_size(self):
        return self.position_sizes.order_by("-policy_version", "-sized_at", "-id").first()


class PositionSizeAdvice(ImmutableModel):
    recommendation = models.ForeignKey(
        Recommendation, on_delete=models.PROTECT, related_name="position_sizes"
    )
    policy_key = models.CharField(max_length=80)
    policy_version = models.PositiveSmallIntegerField()
    account_currency = models.CharField(max_length=3, default="CAD")
    model_equity_cad = models.DecimalField(max_digits=14, decimal_places=2)
    risk_fraction = models.DecimalField(max_digits=7, decimal_places=6)
    setup_risk_cap_cad = models.DecimalField(max_digits=12, decimal_places=2)
    aggregate_risk_cap_cad = models.DecimalField(max_digits=12, decimal_places=2)
    currency_direction_risk_cap_cad = models.DecimalField(max_digits=12, decimal_places=2)
    stop_distance_quote = models.DecimalField(max_digits=12, decimal_places=6)
    quote_to_cad_rate = models.DecimalField(max_digits=18, decimal_places=8)
    recommended_units = models.PositiveBigIntegerField()
    projected_risk_cad = models.DecimalField(max_digits=12, decimal_places=2)
    conversion_path = models.JSONField()
    sized_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-sized_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("recommendation", "policy_key", "policy_version"),
                name="unique_position_size_policy_assessment",
            ),
            models.CheckConstraint(
                condition=models.Q(model_equity_cad__gt=0),
                name="position_size_model_equity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(risk_fraction__gt=0, risk_fraction__lte=1),
                name="position_size_risk_fraction_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    setup_risk_cap_cad__gt=0,
                    aggregate_risk_cap_cad__gte=models.F("setup_risk_cap_cad"),
                    currency_direction_risk_cap_cad__gte=models.F("setup_risk_cap_cad"),
                ),
                name="position_size_caps_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(stop_distance_quote__gt=0, quote_to_cad_rate__gt=0),
                name="position_size_conversion_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(recommended_units__gt=0),
                name="position_size_units_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    projected_risk_cad__gt=0,
                    projected_risk_cad__lte=models.F("setup_risk_cap_cad"),
                ),
                name="position_size_projected_risk_within_cap",
            ),
        ]

    def clean(self):
        recommendation = self.recommendation
        if recommendation.contract_version not in {2, 3} or recommendation.action not in {
            Recommendation.Action.BUY,
            Recommendation.Action.SELL,
        }:
            raise ValidationError("Only a directional supported recommendation can be sized")
        if self.account_currency != "CAD":
            raise ValidationError("Position sizing policy v1 requires CAD account currency")
        if self.sized_at < recommendation.generated_at:
            raise ValidationError("Position sizing cannot predate its recommendation")
        expected_stop = abs(recommendation.entry_level - recommendation.invalidation_level)
        if self.stop_distance_quote != expected_stop:
            raise ValidationError("Position sizing stop distance must match the recommendation")
        expected_cap = (self.model_equity_cad * self.risk_fraction).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if self.setup_risk_cap_cad != expected_cap:
            raise ValidationError("Position sizing risk cap must match equity times risk fraction")
        expected_risk = (
            Decimal(self.recommended_units) * self.stop_distance_quote * self.quote_to_cad_rate
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if self.projected_risk_cad != expected_risk:
            raise ValidationError("Projected CAD risk must match units, stop, and conversion rate")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class RecommendationResolution(ImmutableModel):
    recommendation = models.OneToOneField(
        Recommendation, on_delete=models.PROTECT, related_name="resolution"
    )
    outcome = models.CharField(max_length=8, choices=Forecast.Direction)
    horizon_candle = models.ForeignKey(Candle, on_delete=models.PROTECT)
    endpoint_midpoint = models.DecimalField(max_digits=12, decimal_places=6)
    midpoint_change = models.DecimalField(max_digits=12, decimal_places=6)
    directional_hit = models.BooleanField(null=True, blank=True)
    brier_score = models.DecimalField(max_digits=8, decimal_places=6)
    details = models.JSONField(default=dict)
    resolved_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-resolved_at", "-id")

    def clean(self):
        recommendation = self.recommendation
        if recommendation.contract_version not in {2, 3}:
            raise ValidationError("Legacy recommendations do not have a scorable outcome contract")
        if self.horizon_candle.instrument_id != recommendation.instrument_id:
            raise ValidationError(
                "Resolution horizon candle must match the recommendation instrument"
            )
        if recommendation.action == Recommendation.Action.ABSTAIN:
            if self.directional_hit is not None:
                raise ValidationError("An abstention cannot have a directional hit result")
        elif self.directional_hit is None:
            raise ValidationError("A directional recommendation requires a hit result")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PaperTradeEntry(ImmutableModel):
    recommendation = models.OneToOneField(
        Recommendation, on_delete=models.PROTECT, related_name="paper_entry"
    )
    candle = models.ForeignKey(Candle, on_delete=models.PROTECT)
    execution_side = models.CharField(max_length=3, choices=(("ask", "Ask"), ("bid", "Bid")))
    fill_price = models.DecimalField(max_digits=12, decimal_places=6)
    observed_open_spread = models.DecimalField(max_digits=12, decimal_places=6)
    details = models.JSONField(default=dict)
    entered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-entered_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(observed_open_spread__gte=0),
                name="paper_entry_spread_nonnegative",
            )
        ]

    def clean(self):
        recommendation = self.recommendation
        if (
            recommendation.contract_version not in {2, 3}
            or recommendation.action == Recommendation.Action.ABSTAIN
        ):
            raise ValidationError(
                "Only supported directional recommendations can enter a paper trade"
            )
        if (
            self.candle.instrument_id != recommendation.instrument_id
            or self.candle.granularity != "H1"
        ):
            raise ValidationError("Paper entry requires an hourly candle for its instrument")
        expected_side = "ask" if recommendation.action == Recommendation.Action.BUY else "bid"
        if self.execution_side != expected_side:
            raise ValidationError("Paper entry execution side does not match its action")
        if self.candle.timestamp < recommendation.generated_at:
            raise ValidationError("Paper entry evidence cannot predate recommendation generation")
        if self.observed_open_spread < 0:
            raise ValidationError("Paper entry spread cannot be negative")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PaperTradeResult(ImmutableModel):
    class Outcome(models.TextChoices):
        TARGET = "target", "Target hit"
        INVALIDATED = "invalidated", "Invalidated"
        EXPIRED = "expired", "Entered; expired at session close"
        NOT_ACTIVATED = "not_activated", "Entry not activated"

    recommendation = models.OneToOneField(
        Recommendation, on_delete=models.PROTECT, related_name="paper_result"
    )
    entry = models.OneToOneField(
        PaperTradeEntry,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="result",
    )
    outcome = models.CharField(max_length=16, choices=Outcome)
    horizon_candle = models.ForeignKey(
        Candle,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="paper_horizon_results",
    )
    exit_candle = models.ForeignKey(
        Candle,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="paper_exit_results",
    )
    exit_price = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    gross_pips = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    r_multiple = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    details = models.JSONField(default=dict)
    resolved_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-resolved_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    outcome="not_activated",
                    entry__isnull=True,
                    horizon_candle__isnull=False,
                    exit_candle__isnull=True,
                    exit_price__isnull=True,
                    gross_pips__isnull=True,
                    r_multiple__isnull=True,
                )
                | models.Q(
                    outcome__in=("target", "invalidated"),
                    entry__isnull=False,
                    exit_candle__isnull=False,
                    exit_price__isnull=False,
                    gross_pips__isnull=False,
                    r_multiple__isnull=False,
                )
                | models.Q(
                    outcome="expired",
                    entry__isnull=False,
                    horizon_candle__isnull=False,
                    exit_candle__isnull=False,
                    exit_price__isnull=False,
                    gross_pips__isnull=False,
                    r_multiple__isnull=False,
                ),
                name="paper_result_shape_valid",
            )
        ]

    def clean(self):
        recommendation = self.recommendation
        if (
            recommendation.contract_version not in {2, 3}
            or recommendation.action == Recommendation.Action.ABSTAIN
        ):
            raise ValidationError("Only supported directional recommendations have paper results")
        if self.horizon_candle:
            if self.horizon_candle.instrument_id != recommendation.instrument_id:
                raise ValidationError(
                    "Paper horizon candle must match its recommendation instrument"
                )
            if self.horizon_candle.granularity != "D":
                raise ValidationError("Paper horizon must be a daily candle")
        if self.exit_candle and self.exit_candle.instrument_id != recommendation.instrument_id:
            raise ValidationError("Paper exit candle must match its recommendation instrument")
        values = (self.exit_candle, self.exit_price, self.gross_pips, self.r_multiple)
        if self.outcome == self.Outcome.NOT_ACTIVATED:
            if not self.horizon_candle_id:
                raise ValidationError("A non-activated setup requires its expiry horizon")
            if self.entry_id or any(value is not None for value in values):
                raise ValidationError("A non-activated setup cannot contain execution results")
        else:
            if not self.entry_id or any(value is None for value in values):
                raise ValidationError(
                    "An activated paper setup requires complete execution results"
                )
            if self.entry.recommendation_id != recommendation.pk:
                raise ValidationError("Paper entry and result recommendations must match")
            if self.outcome == self.Outcome.EXPIRED and not self.horizon_candle_id:
                raise ValidationError("An expired paper setup requires its horizon candle")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def cost_assessment(self):
        return self.cost_assessments.order_by("-assessed_at", "-id").first()


class PaperTradeCostAssessment(ImmutableModel):
    result = models.ForeignKey(
        PaperTradeResult,
        on_delete=models.PROTECT,
        related_name="cost_assessments",
    )
    policy_version = models.CharField(max_length=80)
    minimum_financing_days = models.PositiveSmallIntegerField()
    maximum_financing_days = models.PositiveSmallIntegerField()
    optimistic_net_pips = models.DecimalField(max_digits=12, decimal_places=3)
    base_net_pips = models.DecimalField(max_digits=12, decimal_places=3)
    conservative_net_pips = models.DecimalField(max_digits=12, decimal_places=3)
    optimistic_net_r = models.DecimalField(max_digits=12, decimal_places=4)
    base_net_r = models.DecimalField(max_digits=12, decimal_places=4)
    conservative_net_r = models.DecimalField(max_digits=12, decimal_places=4)
    details = models.JSONField()
    assessed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-assessed_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("result", "policy_version"),
                name="unique_paper_cost_policy_assessment",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_financing_days__lte=models.F("maximum_financing_days")),
                name="paper_cost_financing_day_range_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(optimistic_net_pips__gte=models.F("base_net_pips"))
                & models.Q(base_net_pips__gte=models.F("conservative_net_pips")),
                name="paper_cost_net_pip_scenarios_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(optimistic_net_r__gte=models.F("base_net_r"))
                & models.Q(base_net_r__gte=models.F("conservative_net_r")),
                name="paper_cost_net_r_scenarios_ordered",
            ),
        ]

    def clean(self):
        if (
            self.result.outcome == PaperTradeResult.Outcome.NOT_ACTIVATED
            or not self.result.entry_id
        ):
            raise ValidationError("Only activated paper results can have cost assessments")
        if self.minimum_financing_days > self.maximum_financing_days:
            raise ValidationError("Minimum financing days cannot exceed maximum financing days")
        if not (
            self.optimistic_net_pips >= self.base_net_pips >= self.conservative_net_pips
            and self.optimistic_net_r >= self.base_net_r >= self.conservative_net_r
        ):
            raise ValidationError("Paper cost scenarios must be ordered optimistic to conservative")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PaperLifecycleEvent(ImmutableModel):
    class State(models.TextChoices):
        LEGACY_UNADJUDICATED = "legacy_unadjudicated", "Legacy; not adjudicated"
        PENDING = "pending", "Waiting for entry"
        ENTERED = "entered", "Entered"
        CLOSED = "closed", "Closed"
        EXPIRED_UNOBSERVED = "expired_unobserved", "Expired; coverage unavailable"
        CANCELLED = "cancelled", "Cancelled"
        MISSING_DATA = "missing_data", "Missing data"

    recommendation = models.ForeignKey(
        Recommendation, on_delete=models.PROTECT, related_name="paper_lifecycle_events"
    )
    state = models.CharField(max_length=24, choices=State)
    reason_code = models.CharField(max_length=80, blank=True)
    details = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("occurred_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("recommendation", "state"),
                name="unique_paper_lifecycle_state",
            )
        ]

    def clean(self):
        if self.occurred_at < self.recommendation.generated_at:
            raise ValidationError("A lifecycle event cannot predate its recommendation")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PortfolioGuard(models.Model):
    key = models.CharField(max_length=80, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("key",)


class PortfolioCohort(ImmutableModel):
    idempotency_key = models.CharField(max_length=240, unique=True)
    policy_key = models.CharField(max_length=80)
    policy_version = models.PositiveSmallIntegerField()
    generated_at = models.DateTimeField()
    capacity_snapshot = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-generated_at", "-id")


class PortfolioPolicyActivation(ImmutableModel):
    policy_key = models.CharField(max_length=80)
    policy_version = models.PositiveSmallIntegerField()
    effective_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("policy_key", "policy_version"),
                name="unique_portfolio_policy_activation",
            )
        ]


class PortfolioCohortMember(ImmutableModel):
    cohort = models.ForeignKey(PortfolioCohort, on_delete=models.PROTECT, related_name="members")
    recommendation = models.OneToOneField(
        Recommendation, on_delete=models.PROTECT, related_name="portfolio_membership"
    )
    position_size = models.ForeignKey(PositionSizeAdvice, on_delete=models.PROTECT)
    projected_risk_cad = models.DecimalField(max_digits=12, decimal_places=2)
    currency_legs = models.JSONField()
    eligible = models.BooleanField(default=True)
    reason_code = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("recommendation__instrument__display_order", "recommendation_id")
        constraints = [
            models.UniqueConstraint(
                fields=("cohort", "recommendation"), name="unique_portfolio_cohort_member"
            )
        ]


class PortfolioSelection(ImmutableModel):
    class Mode(models.TextChoices):
        AUTOMATIC = "automatic", "Automatic; all fit"
        OWNER = "owner", "Owner selection"

    cohort = models.ForeignKey(PortfolioCohort, on_delete=models.PROTECT, related_name="selections")
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="portfolio_selections",
    )
    mode = models.CharField(max_length=12, choices=Mode)
    idempotency_key = models.CharField(max_length=240, unique=True)
    selected_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-selected_at", "-id")


class PortfolioSelectionMember(ImmutableModel):
    selection = models.ForeignKey(
        PortfolioSelection, on_delete=models.PROTECT, related_name="selected_members"
    )
    recommendation = models.ForeignKey(Recommendation, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("selection", "recommendation"),
                name="unique_portfolio_selection_member",
            )
        ]


class PortfolioAdmissionEvent(ImmutableModel):
    class State(models.TextChoices):
        ADMITTED = "admitted", "Admitted to paper portfolio"
        REVOKED = "revoked", "Admission revoked while pending"

    recommendation = models.ForeignKey(
        Recommendation, on_delete=models.PROTECT, related_name="portfolio_admission_events"
    )
    cohort = models.ForeignKey(
        PortfolioCohort, on_delete=models.PROTECT, related_name="admission_events"
    )
    selection = models.ForeignKey(
        PortfolioSelection, on_delete=models.PROTECT, related_name="admission_events"
    )
    state = models.CharField(max_length=12, choices=State)
    reason_code = models.CharField(max_length=80)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("occurred_at", "id")


class ReviewCohort(ImmutableModel):
    idempotency_key = models.CharField(max_length=240, unique=True)
    method_key = models.CharField(max_length=80)
    method_version = models.PositiveSmallIntegerField()
    cutoff_at = models.DateTimeField()
    membership_sha256 = models.CharField(max_length=64, unique=True)
    initial_coverage = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-cutoff_at", "-id")


class ReviewCohortMember(ImmutableModel):
    cohort = models.ForeignKey(ReviewCohort, on_delete=models.PROTECT, related_name="members")
    recommendation = models.OneToOneField(
        Recommendation, on_delete=models.PROTECT, related_name="review_membership"
    )
    inclusion_reason = models.CharField(max_length=80)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("recommendation__instrument__display_order", "recommendation_id")


class DeterministicReview(ImmutableModel):
    class Kind(models.TextChoices):
        THESIS = "thesis", "Thesis review"
        EXECUTION = "execution", "Execution review"
        RECONCILIATION = "reconciliation", "Combined reconciliation"

    class Coverage(models.TextChoices):
        COMPLETE = "complete", "Complete"
        NOT_APPLICABLE = "not_applicable", "Not applicable"
        MISSING = "missing", "Missing data"

    member = models.ForeignKey(ReviewCohortMember, on_delete=models.PROTECT, related_name="reviews")
    kind = models.CharField(max_length=16, choices=Kind)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    method_key = models.CharField(max_length=80)
    method_version = models.PositiveSmallIntegerField()
    input_sha256 = models.CharField(max_length=64)
    coverage = models.CharField(max_length=16, choices=Coverage)
    facts = models.JSONField()
    source_lineage = models.JSONField()
    assessed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-assessed_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("member", "kind", "input_sha256"),
                name="unique_deterministic_review_input",
            )
        ]

    def clean(self):
        expected_schema = f"{self.kind}-review-v{self.method_version}"
        if self.facts.get("schema") != expected_schema:
            raise ValidationError("Deterministic review facts do not match their schema")
        if self.supersedes_id and (
            self.supersedes.member_id != self.member_id or self.supersedes.kind != self.kind
        ):
            raise ValidationError("A review may only supersede the same member and review kind")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class InterpretationMethod(ImmutableModel):
    method_key = models.CharField(max_length=80)
    method_version = models.PositiveSmallIntegerField()
    provider = models.CharField(max_length=80)
    requested_model = models.CharField(max_length=120)
    system_prompt_sha256 = models.CharField(max_length=64)
    output_schema_sha256 = models.CharField(max_length=64)
    pricing_version = models.CharField(max_length=80)
    input_usd_per_mtok = models.DecimalField(max_digits=12, decimal_places=4)
    output_usd_per_mtok = models.DecimalField(max_digits=12, decimal_places=4)
    max_output_tokens = models.PositiveIntegerField()
    rights_manifest = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("method_key", "method_version"),
                name="unique_interpretation_method_version",
            )
        ]


class InterpretationAttempt(ImmutableModel):
    class Status(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected output"
        PROVIDER_FAILED = "provider_failed", "Provider failed"
        BUDGET_BLOCKED = "budget_blocked", "Budget blocked"
        RIGHTS_BLOCKED = "rights_blocked", "Rights blocked"

    member = models.ForeignKey(
        ReviewCohortMember, on_delete=models.PROTECT, related_name="interpretation_attempts"
    )
    method = models.ForeignKey(
        InterpretationMethod, on_delete=models.PROTECT, related_name="attempts"
    )
    packet_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status)
    error_code = models.CharField(max_length=80, blank=True)
    provider_response_id = models.CharField(max_length=160, blank=True)
    returned_model = models.CharField(max_length=120, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    budget_reservation = models.ForeignKey(
        "operations.ProviderBudgetReservation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="interpretation_attempts",
    )
    attempted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-attempted_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("member", "method", "packet_sha256"),
                name="unique_interpretation_attempt",
            )
        ]


class ReviewInterpretation(ImmutableModel):
    attempt = models.OneToOneField(
        InterpretationAttempt, on_delete=models.PROTECT, related_name="interpretation"
    )
    thesis_review = models.ForeignKey(
        DeterministicReview, on_delete=models.PROTECT, related_name="thesis_interpretations"
    )
    execution_review = models.ForeignKey(
        DeterministicReview, on_delete=models.PROTECT, related_name="execution_interpretations"
    )
    reconciliation_review = models.ForeignKey(
        DeterministicReview, on_delete=models.PROTECT, related_name="reconciliation_interpretations"
    )
    request_sha256 = models.CharField(max_length=64, unique=True)
    output = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at", "-id")

    def clean(self):
        reviews = (self.thesis_review, self.execution_review, self.reconciliation_review)
        if any(review.member_id != self.attempt.member_id for review in reviews):
            raise ValidationError("Interpretation reviews must belong to the attempted member")
        if tuple(review.kind for review in reviews) != (
            DeterministicReview.Kind.THESIS,
            DeterministicReview.Kind.EXECUTION,
            DeterministicReview.Kind.RECONCILIATION,
        ):
            raise ValidationError("Interpretation review kinds are invalid")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class LearningObservation(ImmutableModel):
    interpretation = models.OneToOneField(
        ReviewInterpretation, on_delete=models.PROTECT, related_name="observation"
    )
    issuance_cluster_key = models.CharField(max_length=120)
    pattern_key = models.SlugField(max_length=120)
    title = models.CharField(max_length=200)
    statement = models.TextField()
    evidence_ids = models.JSONField(default=list)
    proposed_change = models.TextField()
    evaluation_plan = models.TextField()
    non_actionable = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(non_actionable=True),
                name="learning_observation_non_actionable",
            )
        ]

    def clean(self):
        if not self.non_actionable:
            raise ValidationError("Learning observations are always non-actionable")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CandidateHypothesis(ImmutableModel):
    pattern_key = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    statement = models.TextField()
    proposed_change = models.TextField()
    evaluation_plan = models.TextField()
    issuance_cluster_keys = models.JSONField()
    evidence_sha256 = models.CharField(max_length=64, unique=True)
    observations = models.ManyToManyField(
        LearningObservation,
        through="CandidateHypothesisObservation",
        related_name="candidate_hypotheses",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at", "-id")


class CandidateHypothesisObservation(ImmutableModel):
    hypothesis = models.ForeignKey(
        CandidateHypothesis, on_delete=models.PROTECT, related_name="observation_links"
    )
    observation = models.ForeignKey(
        LearningObservation, on_delete=models.PROTECT, related_name="hypothesis_links"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("hypothesis", "observation"),
                name="unique_candidate_hypothesis_observation",
            )
        ]


class SourceProposal(ImmutableModel):
    class State(models.TextChoices):
        QUARANTINED = "quarantined", "Quarantined"

    interpretation = models.ForeignKey(
        ReviewInterpretation, on_delete=models.PROTECT, related_name="source_proposals"
    )
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=120)
    use_case = models.TextField()
    state = models.CharField(max_length=16, choices=State, default=State.QUARANTINED)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("interpretation", "name", "category"),
                name="unique_interpretation_source_proposal",
            )
        ]


class ChallengerAuthorization(ImmutableModel):
    class State(models.TextChoices):
        AUTHORIZED_NOT_STARTED = "authorized_not_started", "Authorized; not started"

    hypothesis = models.OneToOneField(
        CandidateHypothesis, on_delete=models.PROTECT, related_name="authorization"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="challenger_authorizations",
    )
    idempotency_key = models.CharField(max_length=200, unique=True)
    state = models.CharField(max_length=24, choices=State, default=State.AUTHORIZED_NOT_STARTED)
    authorized_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-authorized_at", "-id")


class EvaluationPolicy(ImmutableModel):
    policy_key = models.CharField(max_length=80)
    policy_version = models.PositiveSmallIntegerField()
    minimum_raw_samples = models.PositiveSmallIntegerField()
    minimum_calendar_days = models.PositiveSmallIntegerField()
    minimum_effective_clusters = models.PositiveSmallIntegerField()
    minimum_resolution_coverage = models.DecimalField(max_digits=5, decimal_places=4)
    maximum_calibration_error = models.DecimalField(max_digits=5, decimal_places=4)
    confidence_level = models.DecimalField(max_digits=5, decimal_places=4)
    cluster_method = models.CharField(max_length=120)
    interval_method = models.CharField(max_length=120)
    primary_metric = models.CharField(max_length=120)
    baseline_contract = models.JSONField()
    guardrails = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("policy_key", "policy_version"),
                name="unique_evaluation_policy_version",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_raw_samples__gt=0)
                & models.Q(minimum_calendar_days__gt=0)
                & models.Q(minimum_effective_clusters__gt=0),
                name="evaluation_policy_minimums_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    minimum_resolution_coverage__gt=0,
                    minimum_resolution_coverage__lte=1,
                    maximum_calibration_error__gte=0,
                    maximum_calibration_error__lte=1,
                    confidence_level__gt=0,
                    confidence_level__lt=1,
                ),
                name="evaluation_policy_rates_valid",
            ),
        ]


class ForecastMethodIdentity(ImmutableModel):
    method_key = models.CharField(max_length=80)
    method_version = models.PositiveSmallIntegerField()
    provider = models.CharField(max_length=80)
    requested_model = models.CharField(max_length=120)
    contract_version = models.PositiveSmallIntegerField()
    system_prompt_sha256 = models.CharField(max_length=64)
    output_schema_sha256 = models.CharField(max_length=64)
    input_contract_sha256 = models.CharField(max_length=64)
    setup_policy_key = models.CharField(max_length=120)
    max_output_tokens = models.PositiveIntegerField()
    rights_manifest = models.JSONField()
    identity_sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("method_key", "method_version"),
                name="unique_forecast_method_version",
            )
        ]


class ExperimentEra(ImmutableModel):
    class Kind(models.TextChoices):
        CHAMPION = "champion", "Champion monitoring"
        CHALLENGER = "challenger", "Prospective challenger"

    kind = models.CharField(max_length=12, choices=Kind)
    method = models.ForeignKey(
        ForecastMethodIdentity, on_delete=models.PROTECT, related_name="experiment_eras"
    )
    evaluation_policy = models.ForeignKey(
        EvaluationPolicy, on_delete=models.PROTECT, related_name="experiment_eras"
    )
    authorization = models.OneToOneField(
        ChallengerAuthorization,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="experiment_era",
    )
    champion_era = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="challenger_eras",
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    hypothesis_snapshot = models.JSONField(default=dict, blank=True)
    registration_sha256 = models.CharField(max_length=64, unique=True)
    starts_at = models.DateTimeField()
    registered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-starts_at", "-id")

    def clean(self):
        if self.kind == self.Kind.CHAMPION:
            if self.authorization_id or self.champion_era_id:
                raise ValidationError("A champion era cannot have challenger authorization")
        elif not self.authorization_id or not self.champion_era_id:
            raise ValidationError("A challenger era requires authorization and a champion era")
        if self.champion_era_id and self.champion_era.kind != self.Kind.CHAMPION:
            raise ValidationError("A challenger must reference a champion era")
        if self.supersedes_id and self.supersedes.kind != self.kind:
            raise ValidationError("An experiment era may only supersede the same kind")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ExperimentSample(ImmutableModel):
    era = models.ForeignKey(ExperimentEra, on_delete=models.PROTECT, related_name="samples")
    recommendation = models.ForeignKey(
        Recommendation, on_delete=models.PROTECT, related_name="experiment_samples"
    )
    issuance_cluster_key = models.CharField(max_length=120)
    dependence_cluster_key = models.CharField(max_length=120)
    factor_keys = models.JSONField()
    assigned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("recommendation__generated_at", "recommendation_id")
        constraints = [
            models.UniqueConstraint(
                fields=("era", "recommendation"), name="unique_experiment_sample"
            )
        ]

    def clean(self):
        recommendation = self.recommendation
        if recommendation.contract_version != self.era.method.contract_version:
            raise ValidationError("Experiment sample contract does not match its method")
        if (
            recommendation.provider != self.era.method.provider
            or recommendation.model != self.era.method.requested_model
        ):
            raise ValidationError("Experiment sample provider identity does not match its method")
        if recommendation.generated_at < self.era.starts_at:
            raise ValidationError("Experiment samples must be issued after the era starts")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ExperimentAssessmentAttempt(ImmutableModel):
    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    era = models.ForeignKey(
        ExperimentEra, on_delete=models.PROTECT, related_name="assessment_attempts"
    )
    idempotency_key = models.CharField(max_length=240, unique=True)
    sample_set_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status)
    error_code = models.CharField(max_length=80, blank=True)
    assessed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-assessed_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("era", "sample_set_sha256"),
                condition=models.Q(status="succeeded"),
                name="unique_successful_experiment_sample_set",
            )
        ]


class ExperimentAssessment(ImmutableModel):
    class Status(models.TextChoices):
        COLLECTING = "collecting", "Collecting"
        COVERAGE_LIMITED = "coverage_limited", "Coverage limited"
        GUARDRAIL_FAILED = "guardrail_failed", "Guardrail failed"
        DESCRIPTIVE_READY = "descriptive_ready", "Descriptive evidence ready"
        PROMOTION_ELIGIBLE = "promotion_eligible", "Eligible for owner promotion review"

    attempt = models.OneToOneField(
        ExperimentAssessmentAttempt, on_delete=models.PROTECT, related_name="assessment"
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    status = models.CharField(max_length=24, choices=Status)
    raw_sample_count = models.PositiveIntegerField()
    resolved_sample_count = models.PositiveIntegerField()
    effective_cluster_count = models.PositiveIntegerField()
    observation_days = models.PositiveIntegerField()
    resolution_coverage = models.DecimalField(max_digits=7, decimal_places=6)
    mean_brier_score = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    uniform_baseline_brier = models.DecimalField(
        max_digits=8, decimal_places=6, null=True, blank=True
    )
    mechanical_baseline_brier = models.DecimalField(
        max_digits=8, decimal_places=6, null=True, blank=True
    )
    directional_hit_rate = models.DecimalField(
        max_digits=7, decimal_places=6, null=True, blank=True
    )
    calibration_error = models.DecimalField(max_digits=7, decimal_places=6, null=True, blank=True)
    sharpness = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    brier_interval_low = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    brier_interval_high = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    metrics = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at", "-id")

    def clean(self):
        if self.supersedes_id and self.supersedes.attempt.era_id != self.attempt.era_id:
            raise ValidationError("An assessment may only supersede one from the same era")
        if self.resolved_sample_count > self.raw_sample_count:
            raise ValidationError("Resolved experiment samples cannot exceed assigned samples")
        if self.effective_cluster_count > self.resolved_sample_count:
            raise ValidationError("Effective clusters cannot exceed resolved samples")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PromotionRecord(ImmutableModel):
    class Decision(models.TextChoices):
        CONTINUE = "continue", "Continue collecting"
        REJECT = "reject", "Reject challenger"
        PROMOTE = "promote", "Promote challenger"

    era = models.ForeignKey(
        ExperimentEra, on_delete=models.PROTECT, related_name="promotion_records"
    )
    assessment = models.ForeignKey(
        ExperimentAssessment, on_delete=models.PROTECT, related_name="promotion_records"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="promotion_records"
    )
    decision = models.CharField(max_length=12, choices=Decision)
    idempotency_key = models.CharField(max_length=240, unique=True)
    rationale = models.TextField(blank=True)
    active_policy_changed = models.BooleanField(default=False)
    decided_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-decided_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(active_policy_changed=False),
                name="promotion_record_does_not_mutate_active_policy",
            )
        ]

    def clean(self):
        if self.era.kind != ExperimentEra.Kind.CHALLENGER:
            raise ValidationError("Promotion records apply only to challenger eras")
        if self.assessment.attempt.era_id != self.era_id:
            raise ValidationError("Promotion assessment must belong to its challenger era")
        if (
            self.decision == self.Decision.PROMOTE
            and self.assessment.status != ExperimentAssessment.Status.PROMOTION_ELIGIBLE
        ):
            raise ValidationError("Only a promotion-eligible assessment may be promoted")
        if not self.actor.is_superuser:
            raise ValidationError("Only the owner may record a promotion decision")
        if self.active_policy_changed:
            raise ValidationError("A promotion record cannot mutate the active policy")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
