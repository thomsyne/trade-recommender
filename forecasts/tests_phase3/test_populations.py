from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch

from django.test import SimpleTestCase

from forecasts.populations import assessment_values


class PopulationTests(SimpleTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 1, tzinfo=UTC)
        self.policy = NS(
            minimum_raw_samples=50,
            minimum_calendar_days=180,
            minimum_effective_clusters=24,
            minimum_resolution_coverage=Decimal(".9"),
            maximum_calibration_error=Decimal(".15"),
            confidence_level=Decimal(".95"),
            interval_method="cluster-mean-hoeffding-v1",
        )
        self.era = NS(
            starts_at=self.now - timedelta(days=180), kind="champion", evaluation_policy=self.policy
        )

    def sample(self, key, probabilities, control_probabilities, *, immature=False):
        reference = (
            datetime(2026, 7, 2, 21, tzinfo=UTC)
            if not immature
            else datetime(2026, 7, 30, 21, tzinfo=UTC)
        )
        shared = NS(pk=key, outcome="up", resolved_at=self.now - timedelta(days=1))
        target = NS(
            pk=key,
            instrument_id=1,
            target_contract_id=2,
            information_cutoff=reference + timedelta(days=1),
            reference_midpoint=Decimal("1.1"),
            neutral_band=Decimal(".002"),
            horizon_sessions=5,
            reference_candle=NS(timestamp=reference),
            resolution=shared,
        )
        control = NS(
            target_occurrence_id=key,
            instrument_id=1,
            target_contract_id=2,
            information_cutoff=target.information_cutoff,
            reference_midpoint=target.reference_midpoint,
            neutral_band=target.neutral_band,
            setup_expires_after_sessions=5,
            issued_at=target.information_cutoff,
            method="mechanical-ewma",
            method_version=1,
            probability_up=Decimal(control_probabilities[0]),
            probability_neutral=Decimal(control_probabilities[1]),
            probability_down=Decimal(control_probabilities[2]),
            resolution=NS(resolved_at=shared.resolved_at, target_resolution_id=key),
        )
        rec = NS(
            pk=key,
            instrument_id=1,
            target_occurrence=target,
            target_occurrence_id=key,
            control_forecast=control,
            control_forecast_id=key,
            generated_at=control.issued_at,
            probability_up=Decimal(probabilities[0]),
            probability_neutral=Decimal(probabilities[1]),
            probability_down=Decimal(probabilities[2]),
            action="buy",
            resolution=NS(
                resolved_at=shared.resolved_at,
                target_resolution_id=key,
                directional_hit=True,
                outcome="up",
                brier_score=Decimal(".1"),
            ),
        )
        return NS(
            pk=key,
            recommendation=rec,
            assigned_at=rec.generated_at,
            dependence_cluster_key="2026-W27",
        )

    def assess(self, samples):
        with (
            patch(
                "forecasts.lifecycle.project_lifecycle",
                return_value={
                    "cohort_id": None,
                    "admission_status": "not_admitted",
                    "entry_id": None,
                    "result_id": None,
                },
            ),
            patch("forecasts.experiments._execution_metrics", return_value={}),
        ):
            return assessment_values(self.era, samples, self.now)

    def test_repeats_do_not_reverse_target_balanced_comparison(self):
        a = self.sample(1, (".2", ".3", ".5"), (".6", ".3", ".1"))
        b = self.sample(2, (".8", ".1", ".1"), (".2", ".3", ".5"))
        value = self.assess([a] * 10 + [b])
        comparison = value["metrics"]["mechanical_comparison"]
        # Independent arithmetic: ((.8²+.3²+.5²)/3 + (.2²+.1²+.1²)/3)/2.
        self.assertEqual(Decimal(comparison["model_brier"]), Decimal("0.173334"))
        self.assertEqual(Decimal(comparison["mechanical_brier"]), Decimal("0.206667"))
        self.assertEqual(Decimal(comparison["delta"]), Decimal("-0.033333"))
        self.assertEqual(comparison["distinct_target_count"], 2)
        self.assertEqual(comparison["effective_cluster_count"], 1)
        self.assertEqual(value["raw_sample_count"], 11)
        self.assertEqual(value["metrics"]["populations"]["distinct_targets"], 2)

    def test_immature_does_not_reduce_mature_coverage(self):
        mature = self.sample(1, (".6", ".3", ".1"), (".2", ".3", ".5"))
        immature = self.sample(2, (".6", ".3", ".1"), (".2", ".3", ".5"), immature=True)
        value = self.assess([mature, immature])
        self.assertEqual(value["resolution_coverage"], 1)
        self.assertEqual(value["metrics"]["populations"]["mature_targets"], 1)
        self.assertEqual(value["metrics"]["populations"]["immature_targets"], 1)

    def test_resolution_after_cutoff_does_not_leak(self):
        sample = self.sample(1, (".6", ".3", ".1"), (".2", ".3", ".5"))
        sample.recommendation.target_occurrence.resolution.resolved_at = self.now + timedelta(
            microseconds=1
        )
        value = self.assess([sample])
        self.assertEqual(value["resolved_sample_count"], 0)
        self.assertEqual(value["resolution_coverage"], 0)

    def test_missing_control_cannot_be_counted_paired(self):
        sample = self.sample(1, (".6", ".3", ".1"), (".2", ".3", ".5"))
        sample.recommendation.control_forecast = None
        sample.recommendation.control_forecast_id = None
        value = self.assess([sample])
        self.assertEqual(value["metrics"]["mechanical_comparison"]["sample_count"], 0)
        self.assertEqual(value["metrics"]["populations"]["missing_controls"], 1)
