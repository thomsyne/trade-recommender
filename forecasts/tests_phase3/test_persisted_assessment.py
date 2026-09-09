"""Full current-policy persisted samples for readiness and owner-cutoff boundaries."""

import hashlib
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase


class PersistedAssessmentTests(TestCase):
    def setUp(self):
        from forecasts.recommendations import generate_recommendation, resolve_recommendation
        from forecasts.services import resolve_forecast
        from forecasts.tests.test_recommendations import FakeProvider, evidence, output
        from market.models import Instrument, SourceRegistry
        from market.tests.factories import candle
        from market.tests.timeline import EvidenceTimeline

        self.timeline = EvidenceTimeline(daily=310)
        self.instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        self.source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://example.com",
            acquisition_method="synthetic",
            retention_policy="test",
        )
        self.records = []
        for index in range(50):
            reference = self.timeline.session(index * 6)
            run = self.timeline.ingest(
                self.source,
                self.instrument,
                "D",
                [candle(reference)],
                manifest={"test": "persisted-ready-reference", "index": index, "requests": []},
            )
            now = self.timeline.after(run, seconds=2)
            probabilities = (100, 0, 0)
            if self._testMethodName == "test_fully_unmocked_uniform_equality":
                neutral = [4, 16, 17, 18, 19][index] if index < 5 else 0
                probabilities = (62, neutral, 38 - neutral)
            with self.timeline.at(now):
                evidence(
                    self.instrument,
                    now,
                    sha256=hashlib.sha256(f"persisted-ready-{index}".encode()).hexdigest(),
                )
                rec = generate_recommendation(
                    self.instrument,
                    provider=FakeProvider(
                        output(
                            action="abstain",
                            abstention_reason="Synthetic probability experiment",
                            probability_up_percent=probabilities[0],
                            probability_neutral_percent=probabilities[1],
                            probability_down_percent=probabilities[2],
                        )
                    ),
                    generated_at=now,
                )
            endpoint = self.timeline.session(index * 6 + 5)
            run = self.timeline.ingest(
                self.source,
                self.instrument,
                "D",
                [
                    candle(
                        endpoint,
                        bid_close=Decimal("1.3600"),
                        ask_close=Decimal("1.3602"),
                        bid_high=Decimal("1.3610"),
                        ask_high=Decimal("1.3612"),
                    )
                ],
                manifest={"test": "persisted-ready-endpoint", "index": index, "requests": []},
            )
            with self.timeline.at(self.timeline.after(run)):
                resolve_forecast(rec.control_forecast)
                resolve_recommendation(rec)
            self.records.append(rec)
        self.era = self.records[0].experiment_samples.get().era
        self.as_of = self.timeline.after(run)

    def test_persisted_ready_and_exact_uniform_boundary(self):
        from forecasts.experiments import (
            UNIFORM_BRIER,
            _cluster_interval,
            refresh_experiment_assessment,
        )
        from forecasts.models import ExperimentAssessment

        ready = refresh_experiment_assessment(self.era, assessed_at=self.as_of)
        self.assertEqual(ready.raw_sample_count, 50)
        self.assertEqual(ready.resolved_sample_count, 50)
        self.assertGreaterEqual(ready.effective_cluster_count, 24)
        self.assertEqual(ready.mean_brier_score, Decimal(0))
        self.assertEqual(ready.resolution_coverage, Decimal(1))
        self.assertEqual(ready.status, ExperimentAssessment.Status.DESCRIPTIVE_READY)
        # Full persisted records remain in place. Substitute only the already
        # independently tested unsigned interval upper endpoint to exercise the
        # strict equality comparator without inventing probability precision.
        from datetime import timedelta

        def boundary(*args, **kwargs):
            low, high = _cluster_interval(*args, **kwargs)
            return (
                (low, UNIFORM_BRIER) if kwargs.get("support_low", Decimal(0)) == 0 else (low, high)
            )

        with patch("forecasts.experiments._cluster_interval", side_effect=boundary):
            equal = refresh_experiment_assessment(
                self.era, assessed_at=self.as_of + timedelta(seconds=1)
            )
        self.assertEqual(equal.brier_interval_high, UNIFORM_BRIER)
        self.assertEqual(equal.status, ExperimentAssessment.Status.GUARDRAIL_FAILED)
        from django.contrib.auth import get_user_model
        from django.core.exceptions import ValidationError
        from django.test import override_settings

        from forecasts.experiments import ensure_champion_era, record_promotion_decision
        from forecasts.tests.test_recommendations import FakeProvider

        owner = get_user_model().objects.create_superuser(username="persisted-ready-owner")
        with self.assertRaisesMessage(ValidationError, "latest successful health refresh"):
            record_promotion_decision(
                self.era,
                ready,
                actor=owner,
                decision="promote",
                idempotency_key="stale-ready-assessment",
            )

        class OtherProvider(FakeProvider):
            model = "different-ready-model"

        with self.timeline.at(self.as_of), override_settings(RECOMMENDATION_METHOD_VERSION=41):
            other = ensure_champion_era(OtherProvider(), starts_at=self.as_of, register=True)
        with self.assertRaisesMessage(ValidationError, "latest successful health refresh"):
            record_promotion_decision(
                other,
                ready,
                actor=owner,
                decision="promote",
                idempotency_key="wrong-era-ready-assessment",
            )
        self.assertFalse(self.era.promotion_records.exists())

    def test_fully_unmocked_uniform_equality(self):
        from forecasts.experiments import UNIFORM_BRIER, refresh_experiment_assessment

        assessment = refresh_experiment_assessment(self.era, assessed_at=self.as_of)
        # Independently selected integer-percentage distributions yield these
        # five six-decimal Briers; the other45 are .096267. No score or interval
        # helper is substituted in this persisted boundary fixture.
        total = sum(
            map(Decimal, [".087200", ".072800", ".072467", ".072267", ".072200"])
        ) + 45 * Decimal(".096267")
        self.assertEqual(total, Decimal("4.708949"))
        self.assertEqual(assessment.mean_brier_score, Decimal(".094179"))
        self.assertEqual(assessment.effective_cluster_count, 50)
        self.assertEqual(assessment.raw_sample_count, 50)
        self.assertEqual(assessment.resolution_coverage, Decimal(1))
        self.assertEqual(assessment.brier_interval_high, UNIFORM_BRIER)
        self.assertEqual(assessment.status, "guardrail_failed")
