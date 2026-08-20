from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from forecasts.recommendations import generate_all_recommendations


class RecommendationBatchTests(SimpleTestCase):
    @patch("forecasts.portfolio.assess_recommendation_batch")
    @patch("forecasts.recommendations.size_recommendation")
    @patch("forecasts.recommendations.generate_recommendation")
    @patch("forecasts.recommendations.Instrument.objects.filter")
    def test_every_pair_is_attempted_before_incomplete_batch_is_retried(
        self, instruments, generate, size, assess
    ):
        pairs = [SimpleNamespace(code="USD_CAD"), SimpleNamespace(code="GBP_USD")]
        recommendations = [SimpleNamespace(pk=1), SimpleNamespace(pk=2)]
        instruments.return_value = pairs
        generate.side_effect = [RuntimeError("max tokens"), recommendations[1]]

        with self.assertRaisesRegex(
            RuntimeError, "Recommendation batch incomplete.*USD_CAD: max tokens"
        ):
            generate_all_recommendations()

        self.assertEqual(generate.call_count, 2)
        size.assert_called_once_with(
            recommendations[1], sized_at=generate.call_args.kwargs["generated_at"]
        )
        assess.assert_not_called()

    @patch("forecasts.portfolio.assess_recommendation_batch")
    @patch("forecasts.recommendations.size_recommendation")
    @patch("forecasts.recommendations.generate_recommendation")
    @patch("forecasts.recommendations.Instrument.objects.filter")
    def test_complete_batch_returns_all_pair_results(self, instruments, generate, size, assess):
        pairs = [SimpleNamespace(code="USD_CAD"), SimpleNamespace(code="GBP_USD")]
        recommendations = [SimpleNamespace(pk=1), SimpleNamespace(pk=2)]
        instruments.return_value = pairs
        generate.side_effect = recommendations

        result = generate_all_recommendations()

        self.assertEqual(result, recommendations)
        self.assertEqual(size.call_count, 2)
        assess.assert_called_once()
