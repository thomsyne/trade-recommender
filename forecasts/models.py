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
