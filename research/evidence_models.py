"""Dormant Phase7 records, registered by ResearchConfig during model import.

Keep the historical models.py source pin intact. App labels, tables and migration
ownership remain research; this module changes no persistence contract.
"""

from django.db import models
from django.utils import timezone

from market.models import Instrument, SourceRegistry
from research.models import (
    ImmutableRecord,
    MacroObservation,
    RawRetrieval,
    ResearchDiscrepancy,
    ResearchDocument,
)


class EvidenceRightsReview(ImmutableRecord):
    """Prospective field/use decisions. No historical permissions are inferred."""

    source = models.ForeignKey(SourceRegistry, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    digest = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()


class ExactEvidence(ImmutableRecord):
    """Opt-in representation; existing ingestion and documents remain unchanged."""

    document = models.ForeignKey(ResearchDocument, on_delete=models.PROTECT, null=True)
    observation = models.ForeignKey(MacroObservation, on_delete=models.PROTECT, null=True)
    retrieval = models.ForeignKey(RawRetrieval, on_delete=models.PROTECT)
    storage_review = models.ForeignKey(EvidenceRightsReview, on_delete=models.PROTECT)
    admitted_macro_label = models.TextField(null=True, editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    digest = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()


class EvidenceConflict(ImmutableRecord):
    earlier = models.ForeignKey(
        ExactEvidence, on_delete=models.PROTECT, related_name="later_changes"
    )
    later = models.ForeignKey(
        ExactEvidence, on_delete=models.PROTECT, related_name="earlier_changes"
    )
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    digest = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()


class FrozenEvidencePacket(ImmutableRecord):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    cutoff = models.DateTimeField()
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    digest = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()


class EvidenceIncident(ImmutableRecord):
    """Logical notification identity only; no delivery/outbox side effect."""

    conflict = models.ForeignKey(EvidenceConflict, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    digest = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()


class EvidenceContextResult(ImmutableRecord):
    """Explicit offline validated context, never a recommendation or authority."""

    packet = models.ForeignKey(FrozenEvidencePacket, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    digest = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()


class EvidenceLegacyAdmission(ImmutableRecord):
    """Phase7 discovery time, independent of caller-supplied legacy observed_at."""

    discrepancy = models.OneToOneField(ResearchDiscrepancy, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    digest = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
