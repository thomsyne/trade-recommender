from decimal import ROUND_HALF_UP, Decimal

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
        if self.contract_version >= 2:
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


class PositionSizeAdvice(ImmutableModel):
    recommendation = models.OneToOneField(
        Recommendation, on_delete=models.PROTECT, related_name="position_size"
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
        if recommendation.contract_version < 2 or recommendation.action not in {
            Recommendation.Action.BUY,
            Recommendation.Action.SELL,
        }:
            raise ValidationError("Only a directional v2 recommendation can be sized")
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
        if recommendation.contract_version < 2:
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
            recommendation.contract_version < 2
            or recommendation.action == Recommendation.Action.ABSTAIN
        ):
            raise ValidationError("Only directional v2 recommendations can enter a paper trade")
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
            recommendation.contract_version < 2
            or recommendation.action == Recommendation.Action.ABSTAIN
        ):
            raise ValidationError("Only directional v2 recommendations have paper results")
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


class PaperTradeCostAssessment(ImmutableModel):
    result = models.OneToOneField(
        PaperTradeResult,
        on_delete=models.PROTECT,
        related_name="cost_assessment",
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
