from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from assessments.models import EligibleTradeIntentCandidate, IntentSupersession
from assessments.services import (
    append_capacity_assessment,
    append_cost_evidence,
    append_reviewed_eligibility,
    assess,
    replay,
)
from assessments.tests.test_engine import STRATEGY, evaluation, snapshot
from market.models import StrategyEvaluation
from market.state.canonical import identity_digest
from market.state.compute import compute_market_state, ensure_descriptor_definition
from market.strategy.definitions import definition_digest
from market.strategy.persistence import register
from market.tests.test_live_observations import make_market


class CandidatePersistenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument, _ = make_market()

    def setUp(self):
        self.definition = register(STRATEGY)
        self.eligibility = append_reviewed_eligibility(
            self.instrument,
            era="synthetic-reviewed-fixture-v1",
            entries=[
                {
                    "strategy": STRATEGY,
                    "definition_sha256": definition_digest(STRATEGY),
                    "role": "setup",
                }
            ],
            decision_known_at=timezone.now(),
            phase55_decision_sha256="1" * 64,
            phase55_manifest_sha256="2" * 64,
            admission_provenance_sha256="3" * 64,
        )

    def market_snapshot(self):
        return compute_market_state(
            self.instrument,
            ensure_descriptor_definition(),
            timezone.now(),
            ["M15", "H1", "H4", "D", "W"],
        )[0]

    def evaluation(self, state, *, target="1.104000", times_from=None):
        item = evaluation()
        setup = item["output"]["outputs"][0]
        cutoff = (times_from or state).information_cutoff
        setup.update(
            signal_start=(cutoff - timedelta(minutes=30)).isoformat(timespec="microseconds"),
            available_at=(cutoff - timedelta(minutes=15)).isoformat(timespec="microseconds"),
            entry_at=(cutoff + timedelta(minutes=15)).isoformat(timespec="microseconds"),
            expires_at=(cutoff + timedelta(minutes=30)).isoformat(timespec="microseconds"),
            exit_at=(cutoff + timedelta(hours=8)).isoformat(timespec="microseconds"),
            target=target,
        )
        evidence = {"snapshot_key": state.idempotency_key, "costs": [], "previous_id": None}
        output = item["output"]
        return StrategyEvaluation.objects.create(
            definition=self.definition,
            snapshot=state,
            previous=None,
            evidence=evidence,
            evidence_sha256=identity_digest(evidence),
            output=output,
            output_sha256=identity_digest(output),
            identity=identity_digest(
                [self.definition.body_sha256, state.pk, identity_digest(evidence)]
            ),
        )

    def frozen_dependencies(self, cutoff):
        cost = append_cost_evidence(
            self.instrument,
            known_at=cutoff - timedelta(seconds=1),
            stale_after=cutoff + timedelta(hours=1),
            payload={
                "schema": "phase6a/cost-evidence-v1",
                "source_identity": "synthetic-cost-fixture",
                "source_version": "v1",
                "timestamp_precision": "microsecond",
                "components": {
                    "spread": "0.000100",
                    "commission": "0.000020",
                    "slippage_latency": "0.000030",
                    "financing": "0.000000",
                },
            },
        )
        capacity = append_capacity_assessment(
            self.instrument,
            assessed_at=cutoff - timedelta(seconds=1),
            payload={
                "schema": "phase6a/capacity-v1",
                "policy_identity": "synthetic-hard-risk-v1",
                "source_identity": "synthetic-capacity-fixture",
                "aggregate": "available",
                "currency_legs": [
                    {"currency": "USD", "direction": "long", "disposition": "available"},
                    {"currency": "CAD", "direction": "short", "disposition": "available"},
                ],
            },
        )
        return cost, capacity

    def payload(self, state):
        payload = snapshot()
        payload["information_cutoff"] = state.information_cutoff.isoformat(timespec="microseconds")
        return payload

    def test_semantic_duplicate_and_material_successor_are_append_only(self):
        first_state = self.market_snapshot()
        first_eval = self.evaluation(first_state)
        cost, capacity = self.frozen_dependencies(first_state.information_cutoff)
        second_state = self.market_snapshot()
        second_eval = self.evaluation(second_state, times_from=first_state)
        third_state = self.market_snapshot()
        changed_eval = self.evaluation(third_state, target="1.105000", times_from=first_state)
        payloads = {
            first_state.pk: self.payload(first_state),
            second_state.pk: self.payload(second_state),
            third_state.pk: self.payload(third_state),
        }

        def loaded(snapshot_id):
            state = {item.pk: item for item in (first_state, second_state, third_state)}[
                snapshot_id
            ]
            return SimpleNamespace(payload=payloads[snapshot_id], cutoff=state.information_cutoff)

        def verified(evaluation_id):
            return StrategyEvaluation.objects.get(pk=evaluation_id)

        with (
            patch("assessments.services.load_snapshot", side_effect=loaded),
            patch("assessments.services._verified_chain", side_effect=verified),
        ):
            first, candidate, _ = assess(
                first_state.pk,
                self.eligibility.pk,
                evaluation_ids=(first_eval.pk,),
                cost_id=cost.pk,
                capacity_id=capacity.pk,
            )
            duplicate, duplicate_candidate, _ = assess(
                second_state.pk,
                self.eligibility.pk,
                evaluation_ids=(second_eval.pk,),
                cost_id=cost.pk,
                capacity_id=capacity.pk,
            )
            successor, successor_candidate, _ = assess(
                third_state.pk,
                self.eligibility.pk,
                evaluation_ids=(changed_eval.pk,),
                cost_id=cost.pk,
                capacity_id=capacity.pk,
            )
            replay(first.pk)
            replay(duplicate.pk)
            replay(successor.pk)

        self.assertIsNotNone(candidate)
        self.assertIsNone(duplicate_candidate)
        self.assertEqual(
            duplicate.output["decision"]["primary_reason"], "unchanged_duplicate_intent"
        )
        self.assertEqual(successor_candidate.predecessor_id, candidate.pk)
        self.assertNotEqual(successor_candidate.semantic_identity, candidate.semantic_identity)
        self.assertEqual(EligibleTradeIntentCandidate.objects.count(), 2)
        self.assertEqual(IntentSupersession.objects.count(), 1)
