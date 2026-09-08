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
        generate.side_effect = [
            RuntimeError("max tokens; token=should-not-appear"),
            recommendations[1],
        ]

        with self.assertRaisesRegex(
            RuntimeError, r"^Recommendation batch incomplete — USD_CAD: RuntimeError$"
        ) as caught:
            generate_all_recommendations()

        # The batch summary is persisted and rendered: it names the pair and the
        # inner exception type only, never the inner message.
        self.assertNotIn("max tokens", str(caught.exception))
        self.assertNotIn("should-not-appear", str(caught.exception))
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

    @patch("forecasts.portfolio.assess_recommendation_batch")
    @patch("forecasts.recommendations.size_recommendation")
    @patch("forecasts.recommendations.generate_recommendation")
    @patch("forecasts.recommendations.Instrument.objects.filter")
    def test_incomplete_batch_summary_carries_pair_codes_and_exception_types_only(
        self, instruments, generate, size, assess
    ):
        from operations.diagnostics import classify_failure

        instruments.return_value = [
            SimpleNamespace(code="USD_CAD"),
            SimpleNamespace(code="GBP_USD"),
        ]
        generate.side_effect = [
            ValueError("provider body: {api_key: 'sk-secret-VALUE111'}"),
            KeyError("Authorization: Bearer short-BEARER222"),
        ]

        with self.assertRaises(RuntimeError) as caught:
            generate_all_recommendations()

        message = str(caught.exception)
        self.assertEqual(
            message, "Recommendation batch incomplete — USD_CAD: ValueError; GBP_USD: KeyError"
        )
        diagnostic = classify_failure(caught.exception)
        self.assertEqual(diagnostic.code, "batch_incomplete")
        self.assertEqual(diagnostic.summary, message)
        for inner in ("VALUE111", "BEARER222", "provider body", "api_key"):
            self.assertNotIn(inner, diagnostic.summary)
        size.assert_not_called()
        assess.assert_not_called()
