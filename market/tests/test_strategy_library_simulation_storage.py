import json
from datetime import UTC, datetime

from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from market.models import StrategyEvaluation, StrategySimulation
from market.state.canonical import identity_digest
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.strategy.contracts import ExecutionIntent, Unavailable, encoded
from market.strategy.definitions import simulator_definition
from market.strategy.persistence import (
    calculate_simulation,
    integrity,
    register,
    simulation_integrity,
)
from market.strategy.setups import candidate
from market.tests.test_strategy_library_persistence import snapshot
from market.tests.test_strategy_library_simulation import bar


class SimulationStorageTests(TestCase):
    def test_raw_contracts_are_immutable_but_hashes_do_not_certify_semantics(self):
        # Deliberately forged price hypothesis on an empty *real* descriptor.
        # SQL owns schema/identity, Python replay must reject the semantic lie.
        source = snapshot()
        definition = register("orb-m15-confirmed-v1:london")
        setup = candidate(
            definition.strategy, bar(datetime(2026, 1, 5, 12, 45, tzinfo=UTC)), 1, bar().low
        )
        setup_payload = json.loads(encoded(setup))
        output = {
            "schema": "phase5/evaluation-v1",
            "strategy": definition.strategy,
            "outputs": [setup_payload],
            "activation": "forbidden",
        }
        evidence = {"snapshot_key": source.idempotency_key, "costs": [], "previous_id": None}
        evidence_hash = identity_digest(evidence)
        past = output | {
            "outputs": [
                setup_payload
                | {
                    "available_at": "2026-01-05T12:59:00+00:00",
                    "entry_at": "2026-01-05T12:59:59.999999+00:00",
                }
            ]
        }
        with (
            self.assertRaisesMessage(DatabaseError, "phase5_setup_chronology"),
            transaction.atomic(),
        ):
            StrategyEvaluation.objects.create(
                definition=definition,
                snapshot=source,
                evidence=evidence,
                evidence_sha256=evidence_hash,
                output=past,
                output_sha256=identity_digest(past),
                identity=identity_digest([definition.body_sha256, source.pk, evidence_hash]),
            )
        row = StrategyEvaluation.objects.create(
            definition=definition,
            snapshot=source,
            evidence=evidence,
            evidence_sha256=evidence_hash,
            output=output,
            output_sha256=identity_digest(output),
            identity=identity_digest([definition.body_sha256, source.pk, evidence_hash]),
        )
        self.assertEqual(len(integrity()["violations"]), 1)
        later, _ = compute_market_state(
            source.instrument,
            ensure_descriptor_definition(),
            datetime(2026, 1, 5, 14, tzinfo=UTC),
            ["M15"],
        )
        with self.assertRaisesMessage(ValueError, "decision_integrity_failure"):
            calculate_simulation(row.pk, later.pk, profile="fixture")
        intent = json.loads(
            encoded(
                ExecutionIntent(
                    identity_digest(setup_payload),
                    identity_digest(simulator_definition()),
                    identity_digest(None),
                    identity_digest(None),
                )
            )
        )
        evidence = {
            "outcome_snapshot_id": later.pk,
            "outcome_snapshot_key": later.idempotency_key,
            "cost": None,
            "calendar": None,
            "profile": "fixture",
            "terms": None,
        }
        output = json.loads(encoded(Unavailable(definition.strategy, "cost_unavailable")))
        values = {
            "evaluation": row,
            "outcome_snapshot": later,
            "attempt_key": identity_digest([definition.pk, source.instrument_id, "2026-01-05"]),
            "intent": intent,
            "outcome_evidence": evidence,
            "output": output,
            "output_sha256": identity_digest(output),
            "identity": identity_digest([row.pk, intent, evidence]),
        }
        record = StrategySimulation.objects.create(**values)
        self.assertEqual(len(simulation_integrity()["violations"]), 1)
        for sql in (
            "UPDATE market_strategysimulation SET output=output WHERE id=%s",
            "DELETE FROM market_strategysimulation WHERE id=%s",
        ):
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(sql, [record.pk])
        evidence = evidence | {"extra_attempt": True}
        with self.assertRaises(DatabaseError), transaction.atomic():
            StrategySimulation.objects.create(
                **(
                    values
                    | {
                        "outcome_evidence": evidence,
                        "identity": identity_digest([row.pk, intent, evidence]),
                    }
                )
            )
