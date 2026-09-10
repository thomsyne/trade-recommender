"""Explicit bounded immutable research storage. No production dispatch integration."""

import json
from datetime import datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from django.db import connection, transaction
from django.db.models import Q

from market.models import (
    CandleObservation,
    MarketStateSnapshot,
    StrategyDefinition,
    StrategyEvaluation,
    StrategySimulation,
)
from market.state.canonical import canonical_json, identity_digest
from market.state.compute import _bars_from_observations
from market.state.integrity import verify_snapshots
from market.state.manifest import FrozenObservation
from market.strategy.contracts import (
    PHASE4_DIGEST,
    ExecutionIntent,
    SetupCandidate,
    SnapshotInput,
    encoded,
)
from market.strategy.definitions import definition, simulator_definition, verify_implementation
from market.strategy.evaluate import cost_from_payload, evaluate


def load_snapshot(snapshot_id):
    verify_implementation()
    snapshot = MarketStateSnapshot.objects.select_related("definition", "instrument").get(
        pk=snapshot_id
    )
    if (
        snapshot.definition.definition_sha256 != PHASE4_DIGEST
        or verify_snapshots([snapshot])["violation_count"]
    ):
        raise ValueError("phase4_integrity_failure")
    manifest = snapshot.input_manifest
    if len(manifest) > 1800:
        raise ValueError("snapshot_manifest_bound")
    observations = []
    for start in range(0, len(manifest), 100):
        predicate = Q(pk__in=[])
        for item in manifest[start : start + 100]:
            predicate |= Q(
                granularity=item["granularity"],
                timestamp=datetime.fromisoformat(item["timestamp"]),
                revision=item["revision"],
                content_sha256=item["content_sha256"],
            )
        observations.extend(
            CandleObservation.objects.filter(predicate, instrument_id=snapshot.instrument_id)
        )
    envelope = {
        "definition_sha256": PHASE4_DIGEST,
        "input_manifest": manifest,
        "input_manifest_sha256": snapshot.input_manifest_sha256,
        "evidence_manifest": snapshot.evidence_manifest,
        "evidence_sha256": identity_digest(snapshot.evidence_manifest),
        "output_payload": snapshot.output_payload,
        "output_sha256": snapshot.output_sha256,
        "idempotency_key": snapshot.idempotency_key,
    }
    return SnapshotInput(
        snapshot.pk,
        canonical_json(envelope),
        tuple(_bars_from_observations(tuple(FrozenObservation.from_row(o) for o in observations))),
    )


def _lock(key):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [f"phase5:{key}"])


@transaction.atomic
def register(strategy):
    verify_implementation()
    body = json.loads(canonical_json(definition(strategy)))
    digest = identity_digest(body)
    _lock(strategy)
    existing = StrategyDefinition.objects.filter(strategy=strategy).first()
    if existing:
        if existing.body_sha256 != digest or existing.body != body:
            raise ValueError("strategy_version_conflict")
        return existing
    return StrategyDefinition.objects.create(strategy=strategy, body=body, body_sha256=digest)


def _previous(previous_id, inputs, strategy):
    if previous_id is None:
        return D(0)
    row = StrategyEvaluation.objects.select_related("definition", "snapshot").get(pk=previous_id)
    if (
        row.definition.strategy != strategy
        or row.snapshot.output_payload["instrument"] != inputs.payload["instrument"]
        or row.snapshot.information_cutoff >= inputs.cutoff
    ):
        raise ValueError("previous_attribution_or_cutoff")
    forecasts = [o for o in row.output["outputs"] if o["schema"] == "phase5/continuous-v1"]
    if len(forecasts) != 1 or forecasts[0]["buffered"] is None:
        raise ValueError("previous_forecast_unavailable")
    return D(forecasts[0]["buffered"])


@transaction.atomic
def calculate(snapshot_id, strategy, *, costs=(), previous_id=None):
    """Manual idempotent task API; deliberately NOT registered as a durable job."""
    inputs = load_snapshot(snapshot_id)
    registered = register(strategy)
    evidence = {
        "snapshot_key": json.loads(inputs.envelope_json)["idempotency_key"],
        "costs": [
            json.loads(encoded(c, exact=True)) for c in sorted(costs, key=lambda c: c.component)
        ],
        "previous_id": previous_id,
    }
    evidence_sha256 = identity_digest(evidence)
    identity = identity_digest([registered.body_sha256, snapshot_id, evidence_sha256])
    output = evaluate(
        inputs, strategy, costs=costs, previous=_previous(previous_id, inputs, strategy)
    )
    output_sha256 = identity_digest(output)
    _lock(identity)
    existing = StrategyEvaluation.objects.filter(identity=identity).first()
    if existing:
        if existing.output_sha256 != output_sha256:
            raise ValueError("strategy_determinism_violation")
        return existing, False
    return StrategyEvaluation.objects.create(
        definition=registered,
        snapshot_id=snapshot_id,
        previous_id=previous_id,
        evidence=evidence,
        evidence_sha256=evidence_sha256,
        output=output,
        output_sha256=output_sha256,
        identity=identity,
    ), True


def integrity(*, after_id=0, limit=20):
    if type(limit) is not int or not 1 <= limit <= 20 or after_id < 0:
        raise ValueError("integrity_bounds")
    rows = list(
        StrategyEvaluation.objects.select_related("definition")
        .filter(pk__gt=after_id)
        .order_by("pk")[: limit + 1]
    )
    violations = []
    for row in rows[:limit]:
        try:
            if row.definition.body != json.loads(
                canonical_json(definition(row.definition.strategy))
            ):
                raise ValueError("unsupported_strategy_definition")
            inputs = load_snapshot(row.snapshot_id)
            costs = tuple(cost_from_payload(c) for c in row.evidence["costs"])
            output = evaluate(
                inputs,
                row.definition.strategy,
                costs=costs,
                previous=_previous(row.previous_id, inputs, row.definition.strategy),
            )
            if (
                output != row.output
                or identity_digest(output) != row.output_sha256
                or identity_digest(row.evidence) != row.evidence_sha256
                or identity_digest(
                    [row.definition.body_sha256, row.snapshot_id, row.evidence_sha256]
                )
                != row.identity
            ):
                raise ValueError("strategy_replay_mismatch")
        except (ValueError, KeyError, TypeError):
            violations.append({"id": row.pk, "reason": "strategy_integrity_failure"})
    return {
        "checked": min(len(rows), limit),
        "has_more": len(rows) > limit,
        "next_after_id": rows[min(len(rows), limit) - 1].pk if rows else after_id,
        "violations": violations,
    }


def setup_from_payload(body):
    values = dict(body)
    if values.pop("schema") != "phase5/setup-v1":
        raise ValueError("setup_schema")
    for name in ("available_at", "signal_start", "entry_at", "expires_at", "exit_at"):
        values[name] = datetime.fromisoformat(values[name])
    for name in ("reference", "stop", "target"):
        values[name] = D(values[name])
    values["evidence"] = tuple(values["evidence"])
    return SetupCandidate(**values)


@transaction.atomic
def calculate_simulation(
    evaluation_id, outcome_snapshot_id, *, cost=None, calendar=None, profile, terms=None
):
    """Separate explicit outcome task. No outcome flows back into detection."""
    from market.strategy.simulation import simulate

    row = StrategyEvaluation.objects.select_related("snapshot").get(pk=evaluation_id)
    if integrity(after_id=evaluation_id - 1, limit=1)["violations"]:
        raise ValueError("decision_integrity_failure")
    candidates = [p for p in row.output["outputs"] if p["schema"] == "phase5/setup-v1"]
    if len(candidates) != 1:
        raise ValueError("simulation_requires_one_setup")
    setup = setup_from_payload(candidates[0])
    outcome = load_snapshot(outcome_snapshot_id)
    if (
        cost is not None
        and cost.quote_currency != row.snapshot.output_payload["instrument"].split("_")[1]
    ):
        raise ValueError("cost_currency_mismatch")
    if (
        outcome.payload["instrument"] != row.snapshot.output_payload["instrument"]
        or outcome.cutoff <= row.snapshot.information_cutoff
    ):
        raise ValueError("outcome_snapshot_attribution")

    def payload(value):
        return json.loads(encoded(value, exact=True)) if value is not None else None

    intent = json.loads(
        encoded(
            ExecutionIntent(
                identity_digest(candidates[0]),
                identity_digest(simulator_definition()),
                identity_digest(payload(cost)),
                identity_digest(payload(calendar)),
            )
        )
    )
    evidence = {
        "outcome_snapshot_id": outcome_snapshot_id,
        "outcome_snapshot_key": json.loads(outcome.envelope_json)["idempotency_key"],
        "cost": payload(cost),
        "calendar": payload(calendar),
        "profile": profile,
        "terms": payload(terms),
    }
    result = simulate(
        setup,
        outcome.series(setup.granularity),
        cost=cost,
        calendar=calendar,
        profile=profile,
        terms=terms,
    )
    output = json.loads(encoded(result))
    identity = identity_digest([evaluation_id, intent, evidence])
    period = candidates[0]["signal_start"]
    if setup.strategy.startswith("orb-"):
        zone = "Europe/London" if setup.strategy.endswith(":london") else "America/New_York"
        period = setup.signal_start.astimezone(ZoneInfo(zone)).date().isoformat()
    attempt_key = identity_digest([row.definition_id, row.snapshot.instrument_id, period])
    _lock(attempt_key)
    existing = StrategySimulation.objects.filter(identity=identity).first()
    if existing:
        if existing.output != output:
            raise ValueError("simulation_determinism_violation")
        return existing, False
    if StrategySimulation.objects.filter(attempt_key=attempt_key).exists():
        raise ValueError("attempt_already_simulated_new_era_required")
    return StrategySimulation.objects.create(
        evaluation=row,
        outcome_snapshot_id=outcome_snapshot_id,
        attempt_key=attempt_key,
        intent=intent,
        outcome_evidence=evidence,
        output=output,
        output_sha256=identity_digest(output),
        identity=identity,
    ), True


def simulation_integrity(*, after_id=0, limit=20):
    from market.calendar_policy import CalendarAttestation
    from market.strategy.simulation import OutcomeTerms, simulate

    if type(limit) is not int or not 1 <= limit <= 20 or after_id < 0:
        raise ValueError("integrity_bounds")
    rows = list(
        StrategySimulation.objects.select_related("evaluation")
        .filter(pk__gt=after_id)
        .order_by("pk")[: limit + 1]
    )
    violations = []
    for row in rows[:limit]:
        try:
            if integrity(after_id=row.evaluation_id - 1, limit=1)["violations"]:
                raise ValueError("decision_integrity_failure")
            evidence = row.outcome_evidence
            costs = cost_from_payload(evidence["cost"]) if evidence["cost"] else None
            calendar = None
            if evidence["calendar"]:
                values = dict(evidence["calendar"])
                values["known_at"] = datetime.fromisoformat(values["known_at"])
                for field in ("open_intervals", "closed_intervals"):
                    values[field] = tuple(
                        tuple(datetime.fromisoformat(t) for t in interval)
                        for interval in values[field]
                    )
                calendar = CalendarAttestation(**values)
            terms = None
            if evidence["terms"]:
                values = dict(evidence["terms"])
                for field in ("from_at", "through_at", "known_at", "conversion_at"):
                    values[field] = datetime.fromisoformat(values[field])
                values["conversion_rate"] = D(values["conversion_rate"])
                values["rollovers"] = tuple(
                    (datetime.fromisoformat(t), D(rate)) for t, rate in values["rollovers"]
                )
                terms = OutcomeTerms(**values)
            candidates = [
                p for p in row.evaluation.output["outputs"] if p["schema"] == "phase5/setup-v1"
            ]
            if len(candidates) != 1:
                raise ValueError("setup_unavailable")
            setup = setup_from_payload(candidates[0])
            outcome = load_snapshot(row.outcome_snapshot_id)
            expected = json.loads(
                encoded(
                    simulate(
                        setup,
                        outcome.series(setup.granularity),
                        cost=costs,
                        calendar=calendar,
                        profile=evidence["profile"],
                        terms=terms,
                    )
                )
            )
            if (
                expected != row.output
                or identity_digest(expected) != row.output_sha256
                or identity_digest([row.evaluation_id, row.intent, evidence]) != row.identity
            ):
                raise ValueError("simulation_replay_mismatch")
        except (ValueError, KeyError, TypeError):
            violations.append({"id": row.pk, "reason": "simulation_integrity_failure"})
    return {
        "checked": min(len(rows), limit),
        "has_more": len(rows) > limit,
        "next_after_id": rows[min(len(rows), limit) - 1].pk if rows else after_id,
        "violations": violations,
    }
