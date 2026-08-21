from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from forecasts.experiments import (
    _brier,
    assign_recommendation,
    ensure_champion_era,
    ensure_forecast_method,
    record_promotion_decision,
    refresh_experiment_assessment,
    start_challenger_era,
)
from forecasts.interpretations import authorize_candidate_hypothesis
from forecasts.models import (
    CandidateHypothesis,
    ExperimentAssessment,
    ExperimentAssessmentAttempt,
    ExperimentEra,
    PromotionRecord,
    Recommendation,
    RecommendationResolution,
)
from forecasts.recommendations import generate_recommendation
from forecasts.tests.test_recommendations import FakeProvider, evidence
from market.models import Instrument, SourceRegistry
from market.services import store_ingestion
from market.tests.factories import candle


@override_settings(
    RECOMMENDATION_METHOD_VERSION=1,
    RECOMMENDATION_MAX_OUTPUT_TOKENS=6000,
    EMAIL_DELIVERY_ENABLED=False,
)
class ExperimentHealthTests(TestCase):
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
        reference_at = timezone.now() - timedelta(days=2)
        store_ingestion(
            self.source,
            self.instrument,
            "D",
            reference_at,
            reference_at + timedelta(days=1),
            [candle(reference_at)],
            {"test": "experiment-reference", "requests": []},
        )
        self.started_at = (timezone.now() + timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        evidence(self.instrument, self.started_at)
        self.base = generate_recommendation(
            self.instrument,
            provider=FakeProvider(),
            generated_at=self.started_at,
        )
        self.method = ensure_forecast_method(FakeProvider())
        self.era = ExperimentEra.objects.get(kind=ExperimentEra.Kind.CHAMPION)

    def _resolved_recommendation(self, index, generated_at, *, method=None):
        base = self.base
        method = method or self.method
        recommendation = Recommendation.objects.create(
            instrument=base.instrument,
            evidence_snapshot=base.evidence_snapshot,
            reference_candle=base.reference_candle,
            control_forecast=base.control_forecast,
            provider=method.provider,
            model=method.requested_model,
            contract_version=base.contract_version,
            generated_at=generated_at,
            information_cutoff=base.information_cutoff,
            action=Recommendation.Action.BUY,
            confidence_percent=90,
            reference_midpoint=base.reference_midpoint,
            neutral_band=base.neutral_band,
            probability_up=Decimal("0.9000"),
            probability_neutral=Decimal("0.0500"),
            probability_down=Decimal("0.0500"),
            entry_condition=base.entry_condition,
            entry_level=base.entry_level,
            target_level=base.target_level,
            invalidation_level=base.invalidation_level,
            expires_after_sessions=base.expires_after_sessions,
            output=base.output,
            input_payload=base.input_payload,
            request_sha256=f"{index + 1000:064x}",
            provider_response_id=f"experiment-response-{index}",
            input_tokens=100,
            output_tokens=100,
            cost_usd=Decimal("0.001"),
            idempotency_key=f"experiment-recommendation-{index}",
        )
        assign_recommendation(recommendation, method)
        probabilities = (
            recommendation.probability_up,
            recommendation.probability_neutral,
            recommendation.probability_down,
        )
        RecommendationResolution.objects.create(
            recommendation=recommendation,
            outcome="up",
            horizon_candle=base.reference_candle,
            endpoint_midpoint=base.reference_midpoint + base.neutral_band * 2,
            midpoint_change=base.neutral_band * 2,
            directional_hit=True,
            brier_score=_brier(probabilities, "up"),
            details={"test": "experiment-outcome"},
            resolved_at=generated_at + timedelta(days=6),
        )
        return recommendation

    def _resolve_base(self):
        probabilities = (
            self.base.probability_up,
            self.base.probability_neutral,
            self.base.probability_down,
        )
        RecommendationResolution.objects.create(
            recommendation=self.base,
            outcome="up",
            horizon_candle=self.base.reference_candle,
            endpoint_midpoint=self.base.reference_midpoint + self.base.neutral_band * 2,
            midpoint_change=self.base.neutral_band * 2,
            directional_hit=True,
            brier_score=_brier(probabilities, "up"),
            details={"test": "base-experiment-outcome"},
            resolved_at=self.started_at + timedelta(days=6),
        )

    def test_thirty_correlated_rows_remain_collecting(self):
        self._resolve_base()
        for index in range(1, 30):
            self._resolved_recommendation(index, self.started_at + timedelta(minutes=index))

        assessment = refresh_experiment_assessment(
            self.era, assessed_at=self.started_at + timedelta(days=200)
        )

        self.assertEqual(assessment.raw_sample_count, 30)
        self.assertEqual(assessment.resolved_sample_count, 30)
        self.assertEqual(assessment.effective_cluster_count, 1)
        self.assertEqual(assessment.status, ExperimentAssessment.Status.COLLECTING)
        self.assertFalse(assessment.metrics["active_policy_changed"])

    def test_assessment_is_as_of_its_timestamp_and_appends_daily(self):
        self._resolve_base()

        before_resolution = refresh_experiment_assessment(
            self.era, assessed_at=self.started_at + timedelta(days=1)
        )
        after_resolution = refresh_experiment_assessment(
            self.era, assessed_at=self.started_at + timedelta(days=7)
        )
        next_day = refresh_experiment_assessment(
            self.era, assessed_at=self.started_at + timedelta(days=8)
        )

        self.assertEqual(before_resolution.raw_sample_count, 1)
        self.assertEqual(before_resolution.resolved_sample_count, 0)
        self.assertEqual(after_resolution.resolved_sample_count, 1)
        self.assertEqual(after_resolution.supersedes, before_resolution)
        self.assertEqual(next_day.supersedes, after_resolution)
        self.assertEqual(ExperimentAssessment.objects.count(), 3)

    def test_frozen_gate_reports_raw_effective_time_baselines_and_intervals(self):
        self._resolve_base()
        for index in range(1, 50):
            self._resolved_recommendation(
                index,
                self.started_at + timedelta(weeks=index // 2, minutes=index),
            )

        assessed_at = self.started_at + timedelta(days=200)
        reassessed_at = assessed_at + timedelta(hours=1)
        assessment = refresh_experiment_assessment(self.era, assessed_at=assessed_at)
        repeated = refresh_experiment_assessment(self.era, assessed_at=reassessed_at)

        self.assertEqual(repeated, assessment)
        self.assertEqual(assessment.raw_sample_count, 50)
        self.assertGreaterEqual(assessment.effective_cluster_count, 24)
        self.assertEqual(assessment.observation_days, 200)
        self.assertEqual(assessment.resolution_coverage, Decimal("1.000000"))
        self.assertLess(assessment.mean_brier_score, assessment.uniform_baseline_brier)
        self.assertLessEqual(
            assessment.calibration_error,
            self.era.evaluation_policy.maximum_calibration_error,
        )
        self.assertIsNotNone(assessment.brier_interval_low)
        self.assertIsNotNone(assessment.brier_interval_high)
        self.assertEqual(assessment.status, ExperimentAssessment.Status.DESCRIPTIVE_READY)

    def test_method_identity_change_starts_a_new_era_without_rewriting_old_one(self):
        class ChangedProvider(FakeProvider):
            model = "fixed-v2"

        with override_settings(RECOMMENDATION_METHOD_VERSION=2):
            changed = ensure_champion_era(
                ChangedProvider(), starts_at=self.started_at + timedelta(days=1)
            )

        self.assertNotEqual(changed.pk, self.era.pk)
        self.assertEqual(changed.supersedes, self.era)
        self.assertNotEqual(changed.method.identity_sha256, self.era.method.identity_sha256)
        self.era.refresh_from_db()
        self.assertEqual(self.era.starts_at, self.started_at)

    def test_superseded_era_and_pre_start_recommendation_receive_no_sample(self):
        class ChangedProvider(FakeProvider):
            model = "fixed-v2"

        with override_settings(RECOMMENDATION_METHOD_VERSION=2):
            changed_method = ensure_forecast_method(ChangedProvider())
            changed_era = ensure_champion_era(
                ChangedProvider(), starts_at=self.started_at + timedelta(days=1)
            )

        self.assertEqual(assign_recommendation(self.base, changed_method), [])
        self.assertEqual(changed_era.samples.count(), 0)

        class ChangedAgainProvider(FakeProvider):
            model = "fixed-v3"

        with override_settings(RECOMMENDATION_METHOD_VERSION=3):
            newest = ensure_champion_era(
                ChangedAgainProvider(), starts_at=self.started_at + timedelta(days=2)
            )
        with override_settings(RECOMMENDATION_METHOD_VERSION=3):
            newest_method = ensure_forecast_method(ChangedAgainProvider())
        future = self._resolved_recommendation(
            800, self.started_at + timedelta(days=3), method=newest_method
        )

        assigned = assign_recommendation(future, newest_method)

        self.assertEqual([sample.era_id for sample in assigned], [newest.pk])
        self.assertEqual(changed_era.samples.count(), 0)

    def test_failed_assessment_attempt_is_retained_with_safe_error(self):
        with patch(
            "forecasts.experiments._assessment_values",
            side_effect=RuntimeError("sensitive diagnostic"),
        ):
            result = refresh_experiment_assessment(
                self.era,
                assessed_at=self.started_at + timedelta(days=1),
                idempotency_key="failed-assessment-attempt",
            )

        self.assertIsNone(result)
        attempt = ExperimentAssessmentAttempt.objects.get(
            idempotency_key="failed-assessment-attempt"
        )
        self.assertEqual(attempt.status, ExperimentAssessmentAttempt.Status.FAILED)
        self.assertEqual(attempt.error_code, "assessment_failed")
        self.assertNotIn("sensitive", attempt.error_code)
        owner = get_user_model().objects.create_superuser(username="failed-health-owner")
        self.client.force_login(owner)
        response = self.client.get(reverse("calibration"))
        self.assertContains(response, "REFRESH FAILED")
        self.assertContains(response, "owner decisions are blocked")

    def test_owner_can_reject_but_cannot_promote_collecting_challenger(self):
        owner = get_user_model().objects.create_superuser(username="experiment-owner")
        viewer = get_user_model().objects.create_user(username="experiment-viewer")
        candidate = CandidateHypothesis.objects.create(
            pattern_key="candidate-pattern",
            title="Candidate pattern",
            statement="A prospective candidate statement.",
            proposed_change="Test one declared feature.",
            evaluation_plan="Compare paired future cohorts.",
            issuance_cluster_keys=[f"cluster-{index}" for index in range(5)],
            evidence_sha256="a" * 64,
        )
        authorization = authorize_candidate_hypothesis(
            candidate,
            actor=owner,
            idempotency_key="authorize-experiment-candidate",
        )

        class ChallengerProvider(FakeProvider):
            model = "fixed-challenger"

        with override_settings(RECOMMENDATION_METHOD_VERSION=2):
            challenger_method = ensure_forecast_method(ChallengerProvider())
        challenger = start_challenger_era(
            authorization,
            challenger_method,
            actor=owner,
            starts_at=self.started_at + timedelta(minutes=1),
        )
        assessment = refresh_experiment_assessment(
            challenger, assessed_at=self.started_at + timedelta(days=1)
        )
        with self.assertRaisesMessage(ValidationError, "promotion-eligible"):
            record_promotion_decision(
                challenger,
                assessment,
                actor=owner,
                decision=PromotionRecord.Decision.PROMOTE,
                idempotency_key="premature-promotion",
            )
        with self.assertRaisesMessage(ValidationError, "owner"):
            record_promotion_decision(
                challenger,
                assessment,
                actor=viewer,
                decision=PromotionRecord.Decision.REJECT,
                idempotency_key="viewer-rejection",
            )
        latest_assessment = refresh_experiment_assessment(
            challenger, assessed_at=self.started_at + timedelta(days=2)
        )
        with self.assertRaisesMessage(ValidationError, "latest"):
            record_promotion_decision(
                challenger,
                assessment,
                actor=owner,
                decision=PromotionRecord.Decision.REJECT,
                idempotency_key="stale-owner-rejection",
            )

        record = record_promotion_decision(
            challenger,
            latest_assessment,
            actor=owner,
            decision=PromotionRecord.Decision.REJECT,
            idempotency_key="owner-rejection",
        )

        self.assertEqual(record.decision, PromotionRecord.Decision.REJECT)
        self.assertFalse(record.active_policy_changed)
        self.assertEqual(
            record_promotion_decision(
                challenger,
                latest_assessment,
                actor=owner,
                decision=PromotionRecord.Decision.REJECT,
                idempotency_key="owner-rejection",
            ),
            record,
        )
        self.assertTrue(ExperimentEra.objects.filter(pk=challenger.pk).exists())
        self._resolved_recommendation(
            900,
            self.started_at + timedelta(days=3),
            method=challenger_method,
        )
        self.assertEqual(challenger.samples.count(), 0)

    def test_experiment_records_are_database_immutable(self):
        assessment = refresh_experiment_assessment(
            self.era, assessed_at=self.started_at + timedelta(days=1)
        )
        records_and_changes = (
            (self.era.evaluation_policy, {"minimum_raw_samples": 1}),
            (self.method, {"requested_model": "changed"}),
            (self.era, {"starts_at": timezone.now()}),
            (self.era.samples.get(), {"dependence_cluster_key": "changed"}),
            (assessment.attempt, {"error_code": "changed"}),
            (assessment, {"status": ExperimentAssessment.Status.DESCRIPTIVE_READY}),
        )
        for record, changes in records_and_changes:
            with self.assertRaises(DatabaseError), transaction.atomic():
                record.__class__.objects.filter(pk=record.pk).update(**changes)

    def test_calibration_page_never_claims_raw_count_reportability(self):
        assessment = refresh_experiment_assessment(
            self.era, assessed_at=self.started_at + timedelta(days=1)
        )
        owner = get_user_model().objects.create_superuser(username="calibration-owner")
        self.client.force_login(owner)

        response = self.client.get(reverse("calibration"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Raw observations are not independent evidence")
        self.assertContains(response, "50 prospective recommendations")
        self.assertContains(response, "24 distinct UTC weekly dependence clusters")
        self.assertNotContains(response, "REPORTABLE")
        self.assertEqual(assessment.status, ExperimentAssessment.Status.COLLECTING)

    def test_experiment_decision_endpoint_is_owner_post_and_csrf_only(self):
        assessment = refresh_experiment_assessment(
            self.era, assessed_at=self.started_at + timedelta(days=1)
        )
        owner = get_user_model().objects.create_superuser(username="decision-owner")
        viewer = get_user_model().objects.create_user(username="decision-viewer")
        url = reverse("decide-experiment", args=(self.era.pk, assessment.pk))

        self.client.force_login(owner)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(viewer)
        self.assertEqual(
            self.client.post(url, {"decision": PromotionRecord.Decision.REJECT}).status_code,
            403,
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(owner)
        self.assertEqual(
            csrf_client.post(url, {"decision": PromotionRecord.Decision.REJECT}).status_code,
            403,
        )
        self.assertFalse(PromotionRecord.objects.exists())
