from django.core.exceptions import ValidationError
from django.db import models

from market.models import Instrument, MarketStateSnapshot, StrategyEvaluation
from research.evidence_models import FrozenEvidencePacket


class ImmutableRecord(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Phase 6A records are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Phase 6A records are immutable")


class AssessmentMethod(ImmutableRecord):
    key = models.CharField(max_length=80)
    version = models.CharField(max_length=40)
    payload = models.JSONField()
    digest = models.CharField(max_length=64, unique=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("key", "version"), name="p6a_method_version")
        ]


class EligibilitySnapshot(ImmutableRecord):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    valid_from = models.DateTimeField(editable=False)
    valid_until = models.DateTimeField(null=True)
    decision_known_at = models.DateTimeField()
    payload = models.JSONField()
    digest = models.CharField(max_length=64, unique=True)
    recorded_at = models.DateTimeField(editable=False)


class CostEvidence(ImmutableRecord):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    known_at = models.DateTimeField()
    stale_after = models.DateTimeField()
    payload = models.JSONField()
    digest = models.CharField(max_length=64, unique=True)
    recorded_at = models.DateTimeField(editable=False)


class CapacityAssessment(ImmutableRecord):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    assessed_at = models.DateTimeField()
    payload = models.JSONField()
    digest = models.CharField(max_length=64, unique=True)
    recorded_at = models.DateTimeField(editable=False)


class MultiTimeframeAssessment(ImmutableRecord):
    method = models.ForeignKey(AssessmentMethod, on_delete=models.PROTECT)
    snapshot = models.ForeignKey(MarketStateSnapshot, on_delete=models.PROTECT)
    eligibility = models.ForeignKey(EligibilitySnapshot, on_delete=models.PROTECT)
    cost = models.ForeignKey(CostEvidence, on_delete=models.PROTECT, null=True)
    capacity = models.ForeignKey(CapacityAssessment, on_delete=models.PROTECT, null=True)
    evidence_packet = models.ForeignKey(FrozenEvidencePacket, on_delete=models.PROTECT, null=True)
    information_cutoff = models.DateTimeField()
    input_manifest = models.JSONField()
    input_digest = models.CharField(max_length=64, unique=True)
    output = models.JSONField()
    output_digest = models.CharField(max_length=64)
    recorded_at = models.DateTimeField(editable=False)


class EligibleTradeIntentCandidate(ImmutableRecord):
    assessment = models.OneToOneField(MultiTimeframeAssessment, on_delete=models.PROTECT)
    evaluation = models.ForeignKey(StrategyEvaluation, on_delete=models.PROTECT)
    predecessor = models.ForeignKey("self", on_delete=models.PROTECT, null=True)
    semantic_identity = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    digest = models.CharField(max_length=64, unique=True)
    recorded_at = models.DateTimeField(editable=False)


class IntentSupersession(ImmutableRecord):
    predecessor = models.ForeignKey(
        EligibleTradeIntentCandidate, on_delete=models.PROTECT, related_name="superseded_by"
    )
    successor = models.OneToOneField(
        EligibleTradeIntentCandidate,
        on_delete=models.PROTECT,
        related_name="supersedes_observation",
    )
    payload = models.JSONField()
    digest = models.CharField(max_length=64, unique=True)
    recorded_at = models.DateTimeField(editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(predecessor=models.F("successor")),
                name="p6a_distinct_successor",
            )
        ]
