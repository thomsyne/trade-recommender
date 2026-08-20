import json
from datetime import timedelta
from decimal import Decimal

import httpx
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from forecasts.models import Forecast, Recommendation
from forecasts.recommendations import (
    AnthropicProvider,
    ProviderResult,
    generate_recommendation,
)
from market.models import AuditEvent, Instrument
from research.models import PairEvidenceSnapshot


def evidence(instrument, captured_at=None, market_as_of=None):
    captured_at = captured_at or timezone.now()
    market_as_of = market_as_of or captured_at
    payload = {
        "schema": "pair-evidence-v1",
        "instrument": instrument.code,
        "currencies": [instrument.base_currency, instrument.quote_currency],
        "market": {
            "anchor_candle_id": 41,
            "as_of": market_as_of.isoformat(),
            "midpoint_close": "1.350000",
            "source": "OANDA v20",
        },
        "technicals": [
            {
                "id": 51,
                "granularity": "H4",
                "as_of": market_as_of.isoformat(),
                "support": "1.340000",
                "resistance": "1.360000",
            }
        ],
        "macro_and_intermarket": [
            {
                "observation_id": 61,
                "series": "CA_RATE",
                "label": "Canada policy rate",
                "indicator": "policy_rate",
                "jurisdiction": "CA",
                "value": "2.50",
                "unit": "percent",
                "period": "2026-08-19",
                "available_at": captured_at.isoformat(),
                "source": "Bank of Canada",
            }
        ],
        "upcoming_events": [],
        "recent_news": [
            {
                "document_id": 71,
                "title": "Eligible",
                "url": "https://example.com/eligible",
                "published_at": captured_at.isoformat(),
                "source": "Test source",
                "model_eligible": True,
            },
            {
                "document_id": 72,
                "title": "Restricted",
                "url": "https://example.com/restricted",
                "published_at": captured_at.isoformat(),
                "source": "Test source",
                "model_eligible": False,
            },
        ],
        "boundaries": {"read_only": True, "forecast_write_authorized": False},
    }
    return PairEvidenceSnapshot.objects.create(
        instrument=instrument,
        information_cutoff=captured_at,
        payload=payload,
        sha256=("a" if not PairEvidenceSnapshot.objects.exists() else "b") * 64,
        captured_at=captured_at,
    )


def output(**changes):
    value = {
        "action": "buy",
        "confidence_percent": 62,
        "summary": "Conditional upside thesis.",
        "technical_case": "Support contains downside while resistance defines the target.",
        "macro_case": "The supplied policy-rate observation supports the relative-rate case.",
        "sentiment_case": "No eligible sentiment item was supplied; confidence is capped.",
        "risks": ["Support may fail."],
        "evidence_ids": ["technical:51", "macro:61"],
        "entry_condition": "at_or_below",
        "entry_level": 1.35,
        "target_level": 1.36,
        "invalidation_level": 1.34,
        "abstention_reason": "",
    }
    value.update(changes)
    return value


class FakeProvider:
    name = "fake"
    model = "fixed-v1"

    def __init__(self, result=None):
        self.result = result or output()
        self.calls = 0

    def generate(self, input_payload):
        self.calls += 1
        return ProviderResult(self.result, "response-1", 1200, 300)


class RecommendationTests(TestCase):
    def setUp(self):
        self.instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        self.now = timezone.now()
        self.snapshot = evidence(self.instrument, self.now)

    def test_generation_is_bounded_immutable_audited_and_idempotent(self):
        provider = FakeProvider()
        forecast_count = Forecast.objects.count()

        first = generate_recommendation(
            self.instrument, provider=provider, generated_at=self.now + timedelta(seconds=1)
        )
        second = generate_recommendation(
            self.instrument, provider=provider, generated_at=self.now + timedelta(minutes=1)
        )

        self.assertEqual(first, second)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(first.entry_level, Decimal("1.350000"))
        self.assertEqual(
            first.input_payload["evidence"]["technicals"][0]["evidence_id"], "technical:51"
        )
        self.assertEqual(
            [item["document_id"] for item in first.input_payload["evidence"]["recent_news"]],
            [71],
        )
        self.assertEqual(first.output["evidence_ids"], ["technical:51", "macro:61"])
        self.assertEqual(first.provider_response_id, "response-1")
        self.assertEqual(first.cost_usd, Decimal("0.005400"))
        self.assertEqual(Forecast.objects.count(), forecast_count)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type="forecast.recommendation_generated", subject_id=str(first.pk)
            ).exists()
        )
        first.output = {"rewritten": True}
        with self.assertRaises(ValidationError):
            first.save()

    def test_hallucinated_citation_discards_entire_response(self):
        provider = FakeProvider(output(evidence_ids=["technical:51", "news:72"]))

        with self.assertRaisesMessage(ValidationError, "unavailable evidence"):
            generate_recommendation(
                self.instrument, provider=provider, generated_at=self.now + timedelta(seconds=1)
            )

        self.assertEqual(Recommendation.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_stale_evidence_fails_before_provider_call(self):
        old_instrument = Instrument.objects.create(
            code="EUR_USD", base_currency="EUR", quote_currency="USD", display_order=2
        )
        evidence(old_instrument, self.now - timedelta(hours=9))
        provider = FakeProvider()

        with self.assertRaisesMessage(ValidationError, "is stale"):
            generate_recommendation(old_instrument, provider=provider, generated_at=self.now)

        self.assertEqual(provider.calls, 0)

    def test_stale_underlying_market_data_fails_before_provider_call(self):
        stale_instrument = Instrument.objects.create(
            code="GBP_USD", base_currency="GBP", quote_currency="USD", display_order=3
        )
        stale_at = self.now - timedelta(days=1)
        evidence(stale_instrument, self.now, market_as_of=stale_at)
        provider = FakeProvider()

        with self.assertRaisesMessage(ValidationError, "Market candle is stale"):
            generate_recommendation(
                stale_instrument, provider=provider, generated_at=self.now + timedelta(seconds=1)
            )

        self.assertEqual(provider.calls, 0)

    def test_invalid_level_order_is_rejected(self):
        provider = FakeProvider(output(target_level=1.33))

        with self.assertRaisesMessage(ValidationError, "invalidation < entry < target"):
            generate_recommendation(
                self.instrument, provider=provider, generated_at=self.now + timedelta(seconds=1)
            )

        self.assertEqual(Recommendation.objects.count(), 0)

    @override_settings(RECOMMENDATION_MAX_RUN_COST_USD=Decimal("0.001"))
    def test_spend_cap_fails_before_provider_call(self):
        provider = FakeProvider()

        with self.assertRaisesMessage(ValidationError, "per-run spend cap"):
            generate_recommendation(
                self.instrument, provider=provider, generated_at=self.now + timedelta(seconds=1)
            )

        self.assertEqual(provider.calls, 0)

    @override_settings(ANTHROPIC_API_KEY="secret-test-key", RECOMMENDATION_MODEL="test-sonnet")
    def test_anthropic_adapter_requests_strict_schema_without_leaking_key(self):
        observed = {}

        def handler(request):
            observed["headers"] = request.headers
            observed["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "id": "msg_test",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": json.dumps(output())}],
                    "usage": {"input_tokens": 10, "output_tokens": 20},
                },
            )

        result = AnthropicProvider(transport=httpx.MockTransport(handler)).generate({"safe": True})

        self.assertEqual(result.response_id, "msg_test")
        self.assertEqual(observed["headers"]["x-api-key"], "secret-test-key")
        self.assertNotIn("secret-test-key", json.dumps(observed["body"]))
        self.assertEqual(observed["body"]["output_config"]["format"]["type"], "json_schema")
        schema = observed["body"]["output_config"]["format"]["schema"]
        self.assertNotIn("minimum", json.dumps(schema))
        self.assertNotIn("maximum", json.dumps(schema))


class RecommendationDatabaseTests(TransactionTestCase):
    def test_database_rejects_recommendation_mutation(self):
        instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        now = timezone.now()
        evidence(instrument, now)
        recommendation = generate_recommendation(
            instrument, provider=FakeProvider(), generated_at=now + timedelta(seconds=1)
        )

        with self.assertRaises(DatabaseError), transaction.atomic():
            Recommendation.objects.filter(pk=recommendation.pk).update(confidence_percent=99)

        recommendation.refresh_from_db()
        self.assertEqual(recommendation.confidence_percent, 62)
