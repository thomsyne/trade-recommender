import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from forecasts.models import (
    DeterministicReview,
    PaperLifecycleEvent,
    PaperTradeCostAssessment,
    ReviewCohort,
)
from forecasts.paper import resolve_paper_trade
from forecasts.portfolio import assess_recommendation_batch
from forecasts.recommendations import generate_recommendation, resolve_recommendation
from forecasts.reviews import build_due_review_cohort, reassess_review_cohort
from forecasts.sizing import size_recommendation
from forecasts.tests.test_recommendations import (
    FakeProvider,
    evidence,
    hourly_candle,
    open_market_hours,
    output,
    rising_candle,
)
from market.models import Instrument, SourceRegistry
from market.services import store_ingestion
from market.tests.factories import candle


class DeterministicReviewTests(TestCase):
    def setUp(self):
        self.instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        self.source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="test only",
        )
        reference_at = timezone.now() - timedelta(days=1)
        store_ingestion(
            self.source,
            self.instrument,
            "D",
            reference_at,
            reference_at + timedelta(days=1),
            [candle(reference_at)],
            {"test": "review-reference", "requests": []},
        )
        self.generated_at = timezone.now() + timedelta(seconds=2)
        evidence(self.instrument, self.generated_at)

    def recommendation(self):
        recommendation = generate_recommendation(
            self.instrument,
            provider=FakeProvider(),
            generated_at=self.generated_at,
        )
        size_recommendation(recommendation, sized_at=self.generated_at)
        assess_recommendation_batch([recommendation], generated_at=self.generated_at)
        return recommendation

    def resolve_thesis(self, recommendation):
        start = recommendation.reference_candle.timestamp + timedelta(days=1)
        store_ingestion(
            self.source,
            self.instrument,
            "D",
            start,
            start + timedelta(days=5),
            [rising_candle(start + timedelta(days=index)) for index in range(5)],
            {"test": "review-thesis", "requests": []},
        )
        return resolve_recommendation(recommendation)

    def resolve_target(self, recommendation):
        first = open_market_hours(
            recommendation.generated_at, recommendation.generated_at + timedelta(days=4)
        )[0]
        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            recommendation.generated_at - timedelta(hours=1),
            first + timedelta(hours=2),
            [
                hourly_candle(first),
                hourly_candle(
                    first + timedelta(hours=1),
                    bid_high=Decimal("1.3602"),
                    ask_high=Decimal("1.3604"),
                ),
            ],
            {"test": "review-execution", "requests": []},
        )
        return resolve_paper_trade(recommendation)

    def test_frozen_cohort_is_idempotent_and_correction_supersedes_changed_facts(self):
        recommendation = self.recommendation()
        result = self.resolve_target(recommendation)
        self.resolve_thesis(recommendation)
        cutoff = self.generated_at + timedelta(days=10)

        cohort = build_due_review_cohort(cutoff_at=cutoff)
        first_ids = list(cohort.members.first().reviews.values_list("id", flat=True))

        self.assertEqual(cohort.members.count(), 1)
        self.assertEqual(len(first_ids), 3)
        self.assertIsNone(build_due_review_cohort(cutoff_at=cutoff + timedelta(minutes=1)))
        self.assertEqual(
            list(cohort.members.first().reviews.values_list("id", flat=True)), first_ids
        )
        reviews = {review.kind: review for review in cohort.members.first().reviews.all()}
        self.assertEqual(reviews["thesis"].facts["classification"], "direction_supported")
        self.assertEqual(reviews["execution"].facts["paper_outcome"], "target")
        self.assertEqual(
            reviews["reconciliation"].facts["classification"],
            "direction_supported_and_target_observed",
        )
        self.assertIn(
            result.entry.candle_id, reviews["execution"].source_lineage["hourly_candle_ids"]
        )
        rendered_facts = json.dumps([review.facts for review in reviews.values()]).lower()
        for prohibited in ("because", "caused", "causal"):
            self.assertNotIn(prohibited, rendered_facts)

        original_cost = result.cost_assessment
        corrected_at = cutoff + timedelta(hours=1)
        PaperTradeCostAssessment.objects.create(
            result=result,
            policy_version="paper-cost-correction-v2",
            minimum_financing_days=original_cost.minimum_financing_days,
            maximum_financing_days=original_cost.maximum_financing_days,
            optimistic_net_pips=original_cost.optimistic_net_pips,
            base_net_pips=original_cost.base_net_pips - Decimal("1"),
            conservative_net_pips=original_cost.conservative_net_pips - Decimal("1"),
            optimistic_net_r=original_cost.optimistic_net_r,
            base_net_r=original_cost.base_net_r - Decimal("0.01"),
            conservative_net_r=original_cost.conservative_net_r - Decimal("0.01"),
            details={"correction_fixture": True},
            assessed_at=corrected_at,
        )

        created = reassess_review_cohort(
            cohort, correction_as_of=corrected_at + timedelta(minutes=1)
        )

        self.assertEqual({review.kind for review in created}, {"execution", "reconciliation"})
        self.assertTrue(all(review.supersedes_id for review in created))
        self.assertEqual(cohort.members.count(), 1)
        self.assertEqual(
            cohort.members.first().reviews.filter(kind="thesis").count(),
            1,
        )
        self.assertEqual(
            reassess_review_cohort(cohort, correction_as_of=corrected_at + timedelta(minutes=2)),
            [],
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            ReviewCohort.objects.filter(pk=cohort.pk).update(method_version=2)
        member = cohort.members.first()
        with self.assertRaises(DatabaseError), transaction.atomic():
            cohort.members.filter(pk=member.pk).update(inclusion_reason="rewritten")
        with self.assertRaises(DatabaseError), transaction.atomic():
            member.reviews.filter(pk=first_ids[0]).update(coverage="missing")

    def test_review_waits_for_both_thesis_resolution_and_terminal_execution(self):
        recommendation = self.recommendation()

        self.assertIsNone(build_due_review_cohort(cutoff_at=self.generated_at + timedelta(days=9)))

        self.resolve_thesis(recommendation)
        self.assertIsNone(build_due_review_cohort(cutoff_at=self.generated_at + timedelta(days=9)))

        self.resolve_target(recommendation)
        cohort = build_due_review_cohort(cutoff_at=self.generated_at + timedelta(days=10))
        self.assertEqual(cohort.members.get().recommendation, recommendation)

    def test_future_terminal_event_does_not_leak_across_review_cutoff(self):
        recommendation = self.recommendation()
        self.resolve_thesis(recommendation)
        historical_cutoff = self.generated_at + timedelta(days=8)
        future_terminal_at = historical_cutoff + timedelta(days=1)
        PaperLifecycleEvent.objects.create(
            recommendation=recommendation,
            state=PaperLifecycleEvent.State.MISSING_DATA,
            reason_code="future_gap",
            details={"fixture": True},
            occurred_at=future_terminal_at,
        )

        self.assertIsNone(build_due_review_cohort(cutoff_at=historical_cutoff))
        cohort = build_due_review_cohort(cutoff_at=future_terminal_at + timedelta(minutes=1))
        self.assertEqual(cohort.members.get().recommendation, recommendation)

    def test_non_admitted_recommendation_remains_reviewable(self):
        recommendation = generate_recommendation(
            self.instrument,
            provider=FakeProvider(),
            generated_at=self.generated_at,
        )
        self.resolve_thesis(recommendation)

        cohort = build_due_review_cohort(cutoff_at=self.generated_at + timedelta(days=10))
        execution = cohort.members.get().reviews.get(kind=DeterministicReview.Kind.EXECUTION)
        self.assertEqual(execution.coverage, DeterministicReview.Coverage.NOT_APPLICABLE)
        self.assertEqual(execution.facts["readiness_reason"], "outside_admission_era")

    def test_abstention_receives_thesis_review_without_execution_penalty(self):
        abstention = output(
            action="abstain",
            probability_up_percent=25,
            probability_neutral_percent=50,
            probability_down_percent=25,
            abstention_reason="Evidence is balanced.",
        )
        recommendation = generate_recommendation(
            self.instrument,
            provider=FakeProvider(result=abstention),
            generated_at=self.generated_at,
        )
        self.resolve_thesis(recommendation)

        cohort = build_due_review_cohort(cutoff_at=self.generated_at + timedelta(days=10))
        reviews = {item.kind: item for item in cohort.members.get().reviews.all()}
        self.assertEqual(reviews["thesis"].facts["classification"], "abstention_observed")
        self.assertEqual(reviews["execution"].coverage, DeterministicReview.Coverage.NOT_APPLICABLE)
        self.assertEqual(
            reviews["reconciliation"].facts["classification"],
            "thesis_only_research_record",
        )

    def test_terminal_missing_execution_is_an_explicit_denominator(self):
        recommendation = self.recommendation()
        self.resolve_thesis(recommendation)
        missing_at = self.generated_at + timedelta(days=9)
        PaperLifecycleEvent.objects.create(
            recommendation=recommendation,
            state=PaperLifecycleEvent.State.MISSING_DATA,
            reason_code="hourly_test_gap",
            details={"fixture": True},
            occurred_at=missing_at,
        )

        cohort = build_due_review_cohort(cutoff_at=missing_at + timedelta(minutes=1))
        execution = cohort.members.first().reviews.get(kind=DeterministicReview.Kind.EXECUTION)
        reconciliation = cohort.members.first().reviews.get(
            kind=DeterministicReview.Kind.RECONCILIATION
        )

        self.assertEqual(execution.coverage, DeterministicReview.Coverage.MISSING)
        self.assertEqual(execution.facts["terminal_reason_code"], "hourly_test_gap")
        self.assertEqual(reconciliation.coverage, DeterministicReview.Coverage.MISSING)
        self.assertEqual(cohort.initial_coverage["by_review_and_coverage"]["execution:missing"], 1)

        owner = get_user_model().objects.create_superuser(username="review-owner")
        self.client.force_login(owner)
        notebook = self.client.get(reverse("reviews"), {"instrument": self.instrument.code})
        self.assertContains(notebook, "Direction Supported")
        self.assertContains(notebook, "Missing data")
        self.assertContains(notebook, "Missing denominators")
        self.assertContains(notebook, "hourly_test_gap")
        market = self.client.get(reverse("market-detail", args=(self.instrument.code,)))
        self.assertContains(market, "Deterministic postmortem")
        self.assertContains(market, reverse("reviews"))
