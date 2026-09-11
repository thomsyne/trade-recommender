"""Explicit append/replay services for dormant Phase 6A records."""

import json
from datetime import UTC
from decimal import Decimal

from django.db import connection, transaction
from django.utils import timezone

from market.models import MarketStateSnapshot, StrategyEvaluation
from market.state.canonical import canonical_json, identity_digest
from market.strategy.definitions import STRATEGIES, definition_digest
from market.strategy.persistence import _verified_chain, load_snapshot
from research.evidence_store import load_frozen_packet

from .contracts import (
    METHOD_DIGEST,
    METHOD_KEY,
    METHOD_VERSION,
    ROLES,
    method_payload,
    verify_implementation,
)
from .engine import build_assessment
from .models import (
    AssessmentMethod,
    CapacityAssessment,
    CostEvidence,
    EligibilitySnapshot,
    EligibleTradeIntentCandidate,
    IntentSupersession,
    MultiTimeframeAssessment,
)


def _iso(value):
    if value.tzinfo is None:
        raise ValueError("naive_time")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _hash(value, name):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"invalid_{name}")
    return value


def _lock(key):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [f"phase6a:{key}"])


def _canonical(value):
    return json.loads(canonical_json(value))


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
    normalized = []
    for item in entries:
        strategy = item["strategy"]
        if strategy not in STRATEGIES:
            raise ValueError("unknown_strategy")
        role = item["role"]
        if role != ROLES[strategy] or item["definition_sha256"] != definition_digest(strategy):
            raise ValueError("eligibility_attribution")
        required = sorted(set(item.get("required_evidence_ids", [])))
        if required:
            raise ValueError("strategy_has_no_phase7_requirement_in_method_v1")
        for digest in required:
            _hash(digest, "required_evidence")
        normalized.append(
            {
                "strategy": strategy,
                "definition_sha256": item["definition_sha256"],
                "role": role,
                "required_evidence_ids": required,
            }
        )
    normalized.sort(key=lambda item: item["strategy"])
    if len({item["strategy"] for item in normalized}) != len(normalized):
        raise ValueError("duplicate_eligibility")
    return {
        "schema": "phase6a/eligibility-v1",
        "instrument": instrument.code,
        "era": era,
        "phase55_decision_sha256": _hash(decision, "phase55_decision"),
        "phase55_manifest_sha256": _hash(manifest, "phase55_manifest"),
        "admission_provenance_sha256": _hash(provenance, "admission_provenance"),
        "entries": normalized,
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
    """Future owner seam only; this phase has no command/caller and seeds nothing."""
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
        return existing
    if decision_known_at > timezone.now() or (valid_until and valid_until <= timezone.now()):
        raise ValueError("eligibility_chronology")
    return EligibilitySnapshot.objects.create(
        instrument=instrument,
        valid_from=timezone.now(),  # SQL replaces this with its database clock.
        valid_until=valid_until,
        decision_known_at=decision_known_at,
        payload=payload,
        digest=digest,
        recorded_at=timezone.now(),
    )


@transaction.atomic
def append_cost_evidence(instrument, *, known_at, stale_after, payload):
    required = {"schema", "source_identity", "source_version", "timestamp_precision", "components"}
    if set(payload) != required or payload["schema"] != "phase6a/cost-evidence-v1":
        raise ValueError("cost_schema")
    if payload["timestamp_precision"] not in ("microsecond", "provider_exact"):
        raise ValueError("cost_timestamp_precision")
    if set(payload["components"]) != {"spread", "commission", "slippage_latency", "financing"}:
        raise ValueError("cost_components")
    for name, value in payload["components"].items():
        if value is not None and (
            not Decimal(value).is_finite() or (name != "financing" and Decimal(value) < 0)
        ):
            raise ValueError("cost_value")
    if known_at.tzinfo is None or stale_after <= known_at:
        raise ValueError("cost_chronology")
    body = _canonical({**payload, "known_at": _iso(known_at), "stale_after": _iso(stale_after)})
    digest = identity_digest(body)
    _lock(digest)
    return CostEvidence.objects.get_or_create(
        digest=digest,
        defaults={
            "instrument": instrument,
            "known_at": known_at,
            "stale_after": stale_after,
            "payload": body,
            "recorded_at": timezone.now(),
        },
    )[0]


@transaction.atomic
def append_capacity_assessment(instrument, *, assessed_at, payload):
    required = {"schema", "policy_identity", "source_identity", "aggregate", "currency_legs"}
    if set(payload) != required or payload["schema"] != "phase6a/capacity-v1":
        raise ValueError("capacity_schema")
    currencies = instrument.code.split("_")
    if [leg.get("currency") for leg in payload["currency_legs"]] != currencies:
        raise ValueError("capacity_currency_legs")
    if payload["aggregate"] not in ("available", "exceeded") or any(
        leg.get("disposition") not in ("available", "exceeded")
        or leg.get("direction") not in ("long", "short")
        for leg in payload["currency_legs"]
    ):
        raise ValueError("capacity_disposition")
    body = _canonical({**payload, "assessed_at": _iso(assessed_at)})
    digest = identity_digest(body)
    _lock(digest)
    return CapacityAssessment.objects.get_or_create(
        digest=digest,
        defaults={
            "instrument": instrument,
            "assessed_at": assessed_at,
            "payload": body,
            "recorded_at": timezone.now(),
        },
    )[0]


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
    if (
        row.instrument_id != instrument_id
        or row.digest != identity_digest(row.payload)
        or row.known_at > cutoff
        or row.payload["known_at"] != _iso(row.known_at)
        or row.payload["stale_after"] != _iso(row.stale_after)
    ):
        raise ValueError("cost_integrity_failure")
    return {**row.payload, "identity": row.digest}


def _capacity_envelope(row, cutoff, instrument_id):
    if row is None:
        return None
    if (
        row.instrument_id != instrument_id
        or row.digest != identity_digest(row.payload)
        or row.assessed_at > cutoff
        or row.payload["assessed_at"] != _iso(row.assessed_at)
    ):
        raise ValueError("capacity_integrity_failure")
    return {**row.payload, "identity": row.digest}


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
    evidence_row = None
    evidence = None
    if evidence_packet_id:
        evidence_row = load_frozen_packet(evidence_packet_id)
        if evidence_row.instrument_id != snapshot_row.instrument_id or evidence_row.cutoff > cutoff:
            raise ValueError("evidence_attribution")
        evidence = {**evidence_row.payload, "identity": evidence_row.digest}
        if not any(item["required_evidence_ids"] for item in eligibility["entries"]):
            raise ValueError("unrequired_evidence_packet")
    manifest = {
        "schema": "phase6a/input-manifest-v1",
        "method": method.digest,
        "snapshot": {"id": snapshot_id, "identity": snapshot_row.idempotency_key},
        "eligibility": eligibility_row.digest,
        "evaluations": [
            {
                "id": item["id"],
                "identity": item["identity"],
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
    predecessor = None
    if candidate:
        _lock("candidate:" + candidate["semantic_identity"])
        predecessor = (
            EligibleTradeIntentCandidate.objects.filter(
                assessment__snapshot__instrument_id=snapshot_row.instrument_id,
                payload__strategy=candidate["strategy"],
                payload__direction=candidate["direction"],
            )
            .order_by("-recorded_at", "-pk")
            .first()
        )
        duplicate = (
            predecessor is not None
            and predecessor.semantic_identity == candidate["semantic_identity"]
        )
        if duplicate:
            preliminary, candidate = build_assessment(
                method_digest=method.digest,
                snapshot=inputs.payload,
                eligibility=eligibility,
                evaluations=evaluations,
                cost=cost,
                capacity=capacity,
                evidence=evidence,
                duplicate=True,
            )
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
    candidate_row = None
    if candidate:
        evaluation = next(
            e for e in evaluations if e["identity"] == candidate["evaluation_identity"]
        )
        candidate_row = EligibleTradeIntentCandidate.objects.create(
            assessment=row,
            evaluation_id=evaluation["id"],
            predecessor=predecessor,
            semantic_identity=candidate["semantic_identity"],
            payload=candidate,
            digest=identity_digest(candidate),
            recorded_at=timezone.now(),
        )
        if predecessor:
            supersession = {
                "schema": "phase6a/intent-supersession-v1",
                "predecessor": predecessor.digest,
                "successor": candidate_row.digest,
                "observed_at_cutoff": _iso(cutoff),
            }
            IntentSupersession.objects.create(
                predecessor=predecessor,
                successor=candidate_row,
                payload=supersession,
                digest=identity_digest(supersession),
                recorded_at=timezone.now(),
            )
    return row, candidate_row, True


def replay(assessment_id):
    row = MultiTimeframeAssessment.objects.select_related(
        "method", "snapshot", "eligibility", "cost", "capacity", "evidence_packet"
    ).get(pk=assessment_id)
    if row.method.digest != METHOD_DIGEST or row.method.payload != method_payload():
        raise ValueError("method_integrity_failure")
    inputs = load_snapshot(row.snapshot_id)
    eligibility = _eligibility_envelope(row.eligibility, inputs.cutoff, row.snapshot.instrument_id)
    evaluations = []
    for item in row.input_manifest["evaluations"]:
        evaluation = StrategyEvaluation.objects.select_related("definition").get(pk=item["id"])
        envelope = _evaluation_envelope(evaluation, row.snapshot_id)
        if item != {
            "id": envelope["id"],
            "identity": envelope["identity"],
            "output_sha256": envelope["output_sha256"],
        }:
            raise ValueError("evaluation_manifest_forgery")
        evaluations.append(envelope)
    cost = _cost_envelope(row.cost, inputs.cutoff, row.snapshot.instrument_id)
    capacity = _capacity_envelope(row.capacity, inputs.cutoff, row.snapshot.instrument_id)
    evidence = None
    if row.evidence_packet:
        packet = load_frozen_packet(row.evidence_packet_id)
        evidence = {**packet.payload, "identity": packet.digest}
    if identity_digest(row.input_manifest) != row.input_digest:
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
            supersession = IntentSupersession.objects.filter(successor__assessment=row).first()
            if supersession and (
                supersession.digest != identity_digest(supersession.payload)
                or supersession.successor.predecessor_id != supersession.predecessor_id
            ):
                raise ValueError("supersession_integrity_failure")
        except Exception:
            violations.append({"id": row.pk, "reason": "phase6a_integrity_failure"})
    checked = rows[:limit]
    return {
        "checked": len(checked),
        "has_more": len(rows) > limit,
        "next_after_id": checked[-1].pk if checked else after_id,
        "violations": violations,
    }
