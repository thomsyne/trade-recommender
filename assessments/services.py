"""Explicit append/replay services for dormant Phase 6A records."""

import json
from datetime import UTC

from django.db import connection, transaction
from django.utils import timezone

from market.models import MarketStateSnapshot, StrategyEvaluation
from market.state.canonical import canonical_json, identity_digest
from market.strategy.persistence import _verified_chain, load_snapshot

from .contracts import (
    EMPTY_DECISION_SHA256,
    EMPTY_ELIGIBILITY_ERA,
    EMPTY_MANIFEST_SHA256,
    EMPTY_PROVENANCE_SHA256,
    METHOD_DIGEST,
    METHOD_KEY,
    METHOD_VERSION,
    method_payload,
    verify_implementation,
)
from .engine import build_assessment
from .models import (
    AssessmentMethod,
    CapacityAssessment,
    CostEvidence,
    EligibilitySnapshot,
    IntentSupersession,
    MultiTimeframeAssessment,
)


def _lock(key):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [f"phase6a:{key}"])


def _canonical(value):
    return json.loads(canonical_json(value))


def _iso(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds")


@transaction.atomic
def register_method():
    verify_implementation()
    payload = _canonical(method_payload())
    _lock(METHOD_DIGEST)
    row = AssessmentMethod.objects.filter(key=METHOD_KEY, version=METHOD_VERSION).first()
    if row:
        if row.digest != METHOD_DIGEST or row.payload != payload:
            raise ValueError("method_integrity_failure")
        return row
    return AssessmentMethod.objects.create(
        key=METHOD_KEY, version=METHOD_VERSION, payload=payload, digest=METHOD_DIGEST
    )


def _eligibility_payload(instrument, era, entries, decision, manifest, provenance):
    if entries:
        raise ValueError("phase55_authority_unavailable")
    if (
        era != EMPTY_ELIGIBILITY_ERA
        or decision != EMPTY_DECISION_SHA256
        or manifest != EMPTY_MANIFEST_SHA256
        or provenance != EMPTY_PROVENANCE_SHA256
    ):
        raise ValueError("canonical_empty_eligibility_required")
    return {
        "schema": "phase6a/eligibility-v1",
        "instrument": instrument.code,
        "era": era,
        "phase55_decision_sha256": decision,
        "phase55_manifest_sha256": manifest,
        "admission_provenance_sha256": provenance,
        "entries": [],
    }


@transaction.atomic
def append_reviewed_eligibility(
    instrument,
    *,
    era,
    entries,
    decision_known_at,
    phase55_decision_sha256,
    phase55_manifest_sha256,
    admission_provenance_sha256,
    valid_until=None,
):
    """Append only the canonical empty set until an authoritative Phase 5.5 contract exists."""
    now = timezone.now()
    if decision_known_at.tzinfo is None or decision_known_at > now:
        raise ValueError("eligibility_chronology")
    if valid_until is not None:
        raise ValueError("canonical_empty_eligibility_has_no_expiry")
    payload = _canonical(
        _eligibility_payload(
            instrument,
            era,
            entries,
            phase55_decision_sha256,
            phase55_manifest_sha256,
            admission_provenance_sha256,
        )
    )
    digest = identity_digest(payload)
    _lock(digest)
    existing = EligibilitySnapshot.objects.filter(digest=digest).first()
    if existing:
        if existing.decision_known_at != decision_known_at:
            raise ValueError("eligibility_identity_conflict")
        return existing
    row = EligibilitySnapshot.objects.create(
        instrument=instrument,
        valid_from=now,  # SQL replaces this with its database clock.
        valid_until=None,
        decision_known_at=decision_known_at,
        payload=payload,
        digest=digest,
        recorded_at=timezone.now(),
    )
    row.refresh_from_db()
    return row


@transaction.atomic
def append_cost_evidence(instrument, *, known_at, stale_after, payload):
    raise ValueError("cost_authority_unavailable")


@transaction.atomic
def append_capacity_assessment(instrument, *, assessed_at, payload):
    raise ValueError("capacity_authority_unavailable")


def _evaluation_envelope(row, snapshot_id):
    verified = _verified_chain(row.pk)
    if verified.pk != row.pk or row.snapshot_id != snapshot_id:
        raise ValueError("evaluation_snapshot_attribution")
    return {
        "id": row.pk,
        "identity": row.identity,
        "strategy": row.definition.strategy,
        "definition_sha256": row.definition.body_sha256,
        "evidence_sha256": row.evidence_sha256,
        "output_sha256": row.output_sha256,
        "output": row.output,
    }


def _eligibility_envelope(row, cutoff, instrument_id):
    if (
        row.digest != identity_digest(row.payload)
        or row.instrument_id != instrument_id
        or row.payload["instrument"] != row.instrument.code
        or row.valid_from != row.recorded_at
        or row.valid_until is not None
        or row.decision_known_at > row.recorded_at
        or not row.valid_from <= cutoff
        or (row.valid_until is not None and cutoff >= row.valid_until)
        or row.decision_known_at > cutoff
        or row.recorded_at > cutoff
    ):
        raise ValueError("eligibility_integrity_failure")
    expected = _eligibility_payload(
        row.instrument,
        row.payload["era"],
        row.payload["entries"],
        row.payload["phase55_decision_sha256"],
        row.payload["phase55_manifest_sha256"],
        row.payload["admission_provenance_sha256"],
    )
    if row.payload != expected:
        raise ValueError("eligibility_semantic_forgery")
    return {**row.payload, "identity": row.digest}


def _cost_envelope(row, cutoff, instrument_id):
    if row is None:
        return None
    if row.recorded_at > cutoff:
        raise ValueError("cost_recorded_after_cutoff")
    raise ValueError("cost_authority_unavailable")


def _capacity_envelope(row, cutoff, instrument_id):
    if row is None:
        return None
    if row.recorded_at > cutoff:
        raise ValueError("capacity_recorded_after_cutoff")
    raise ValueError("capacity_authority_unavailable")


def _evidence_envelope(packet_id, cutoff, instrument_id, required_ids):
    if required_ids:
        raise ValueError("method_evidence_requirement_integrity_failure")
    if packet_id is not None:
        raise ValueError("unrequired_evidence_packet")
    return None, None


def _eligibility_reference(row):
    return {
        "digest": row.digest,
        "decision_known_at": _iso(row.decision_known_at),
        "valid_from": _iso(row.valid_from),
        "valid_until": _iso(row.valid_until) if row.valid_until else None,
        "recorded_at": _iso(row.recorded_at),
    }


@transaction.atomic
def assess(
    snapshot_id,
    eligibility_id,
    *,
    evaluation_ids=(),
    cost_id=None,
    capacity_id=None,
    evidence_packet_id=None,
):
    method = register_method()
    inputs = load_snapshot(snapshot_id)
    snapshot_row = MarketStateSnapshot.objects.get(pk=snapshot_id)
    cutoff = inputs.cutoff
    eligibility_row = EligibilitySnapshot.objects.select_related("instrument").get(
        pk=eligibility_id
    )
    eligibility = _eligibility_envelope(eligibility_row, cutoff, snapshot_row.instrument_id)
    if evaluation_ids:
        raise ValueError("evaluation_not_admitted_by_empty_eligibility")
    evaluations = [
        _evaluation_envelope(row, snapshot_id)
        for row in StrategyEvaluation.objects.select_related("definition")
        .filter(pk__in=sorted(set(evaluation_ids)))
        .order_by("identity")
    ]
    if len(evaluations) != len(set(evaluation_ids)):
        raise ValueError("evaluation_missing")
    cost_row = CostEvidence.objects.filter(pk=cost_id).first() if cost_id else None
    capacity_row = (
        CapacityAssessment.objects.filter(pk=capacity_id).first() if capacity_id else None
    )
    cost = _cost_envelope(cost_row, cutoff, snapshot_row.instrument_id)
    capacity = _capacity_envelope(capacity_row, cutoff, snapshot_row.instrument_id)
    required_ids = sorted(
        {digest for item in eligibility["entries"] for digest in item["required_evidence_ids"]}
    )
    evidence_row, evidence = _evidence_envelope(
        evidence_packet_id, cutoff, snapshot_row.instrument_id, required_ids
    )
    manifest = {
        "schema": "phase6a/input-manifest-v1",
        "method": method.digest,
        "snapshot": {"id": snapshot_id, "identity": snapshot_row.idempotency_key},
        "eligibility": _eligibility_reference(eligibility_row),
        "evaluations": [
            {
                "id": item["id"],
                "identity": item["identity"],
                "strategy": item["strategy"],
                "definition_sha256": item["definition_sha256"],
                "evidence_sha256": item["evidence_sha256"],
                "output_sha256": item["output_sha256"],
            }
            for item in evaluations
        ],
        "cost": cost_row.digest if cost_row else None,
        "capacity": capacity_row.digest if capacity_row else None,
        "evidence": evidence_row.digest if evidence_row else None,
    }
    input_digest = identity_digest(manifest)
    _lock(input_digest)
    existing = MultiTimeframeAssessment.objects.filter(input_digest=input_digest).first()
    if existing:
        replay(existing.pk)
        return existing, getattr(existing, "eligibletradeintentcandidate", None), False

    preliminary, candidate = build_assessment(
        method_digest=method.digest,
        snapshot=inputs.payload,
        eligibility=eligibility,
        evaluations=evaluations,
        cost=cost,
        capacity=capacity,
        evidence=evidence,
    )
    if candidate:
        raise ValueError("candidate_without_authoritative_eligibility")
    row = MultiTimeframeAssessment.objects.create(
        method=method,
        snapshot=snapshot_row,
        eligibility=eligibility_row,
        cost=cost_row,
        capacity=capacity_row,
        evidence_packet=evidence_row,
        information_cutoff=cutoff,
        input_manifest=manifest,
        input_digest=input_digest,
        output=preliminary,
        output_digest=identity_digest(preliminary),
        recorded_at=timezone.now(),
    )
    return row, None, True


def replay(assessment_id):
    row = MultiTimeframeAssessment.objects.select_related(
        "method", "snapshot", "eligibility", "cost", "capacity", "evidence_packet"
    ).get(pk=assessment_id)
    if row.method.digest != METHOD_DIGEST or row.method.payload != method_payload():
        raise ValueError("method_integrity_failure")
    inputs = load_snapshot(row.snapshot_id)
    if row.information_cutoff != inputs.cutoff:
        raise ValueError("assessment_cutoff_forgery")
    eligibility = _eligibility_envelope(row.eligibility, inputs.cutoff, row.snapshot.instrument_id)
    if row.input_manifest.get("evaluations"):
        raise ValueError("evaluation_not_admitted_by_empty_eligibility")
    evaluations = []
    for item in row.input_manifest["evaluations"]:
        evaluation = StrategyEvaluation.objects.select_related("definition").get(pk=item["id"])
        envelope = _evaluation_envelope(evaluation, row.snapshot_id)
        if item != {
            "id": envelope["id"],
            "identity": envelope["identity"],
            "strategy": envelope["strategy"],
            "definition_sha256": envelope["definition_sha256"],
            "evidence_sha256": envelope["evidence_sha256"],
            "output_sha256": envelope["output_sha256"],
        }:
            raise ValueError("evaluation_manifest_forgery")
        evaluations.append(envelope)
    cost = _cost_envelope(row.cost, inputs.cutoff, row.snapshot.instrument_id)
    capacity = _capacity_envelope(row.capacity, inputs.cutoff, row.snapshot.instrument_id)
    required_ids = sorted(
        {digest for item in eligibility["entries"] for digest in item["required_evidence_ids"]}
    )
    _, evidence = _evidence_envelope(
        row.evidence_packet_id, inputs.cutoff, row.snapshot.instrument_id, required_ids
    )
    expected_manifest = {
        "schema": "phase6a/input-manifest-v1",
        "method": row.method.digest,
        "snapshot": {"id": row.snapshot_id, "identity": row.snapshot.idempotency_key},
        "eligibility": _eligibility_reference(row.eligibility),
        "evaluations": [],
        "cost": None,
        "capacity": None,
        "evidence": None,
    }
    if (
        row.input_manifest != expected_manifest
        or identity_digest(row.input_manifest) != row.input_digest
    ):
        raise ValueError("assessment_manifest_forgery")
    expected, candidate = build_assessment(
        method_digest=row.method.digest,
        snapshot=inputs.payload,
        eligibility=eligibility,
        evaluations=evaluations,
        cost=cost,
        capacity=capacity,
        evidence=evidence,
        duplicate=row.output["decision"]["primary_reason"] == "unchanged_duplicate_intent",
    )
    if expected != row.output or identity_digest(expected) != row.output_digest:
        raise ValueError("assessment_replay_failure")
    candidate_row = getattr(row, "eligibletradeintentcandidate", None)
    if candidate_row:
        if candidate != candidate_row.payload or identity_digest(candidate) != candidate_row.digest:
            raise ValueError("candidate_replay_failure")
    elif candidate is not None:
        raise ValueError("candidate_missing")
    return row


def _validate_candidate_links(assessment):
    candidate = getattr(assessment, "eligibletradeintentcandidate", None)
    if candidate is None:
        if IntentSupersession.objects.filter(successor__assessment=assessment).exists():
            raise ValueError("supersession_without_candidate")
        return
    observations = list(
        IntentSupersession.objects.select_related(
            "predecessor__assessment__snapshot", "successor__assessment__snapshot"
        ).filter(successor=candidate)
    )
    if (candidate.predecessor_id is None and observations) or (
        candidate.predecessor_id is not None and len(observations) != 1
    ):
        raise ValueError("candidate_supersession_pairing")
    if not observations:
        return
    observation = observations[0]
    predecessor = observation.predecessor
    expected_payload = {
        "schema": "phase6a/intent-supersession-v1",
        "predecessor": predecessor.digest,
        "successor": candidate.digest,
        "observed_at_cutoff": _iso(candidate.assessment.information_cutoff),
    }
    if (
        predecessor.pk != candidate.predecessor_id
        or predecessor.assessment.snapshot.instrument_id
        != candidate.assessment.snapshot.instrument_id
        or predecessor.payload.get("strategy") != candidate.payload.get("strategy")
        or predecessor.payload.get("direction") != candidate.payload.get("direction")
        or observation.payload != expected_payload
        or observation.digest != identity_digest(expected_payload)
        or IntentSupersession.objects.filter(predecessor=predecessor).count() != 1
    ):
        raise ValueError("supersession_integrity_failure")


@transaction.atomic
def audit_integrity(*, after_id=0, limit=20):
    """Bounded read-only semantic audit; never repairs or activates records."""
    if type(after_id) is not int or after_id < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("audit_bounds")
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SET LOCAL statement_timeout='60s'")
        cursor.execute("SET LOCAL lock_timeout='2s'")
    rows = list(
        MultiTimeframeAssessment.objects.filter(pk__gt=after_id).order_by("pk")[: limit + 1]
    )
    violations = []
    for row in rows[:limit]:
        try:
            replay(row.pk)
            _validate_candidate_links(row)
        except Exception:
            violations.append({"id": row.pk, "reason": "phase6a_integrity_failure"})
    checked = rows[:limit]
    return {
        "checked": len(checked),
        "has_more": len(rows) > limit,
        "next_after_id": checked[-1].pk if checked else after_id,
        "violations": violations,
    }
