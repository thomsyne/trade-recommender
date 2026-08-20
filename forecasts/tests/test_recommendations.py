import json
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from forecasts.models import (
    Forecast,
    PaperTradeCostAssessment,
    PaperTradeEntry,
    PaperTradeResult,
    Recommendation,
)
from forecasts.paper import resolve_paper_trade
from forecasts.recommendations import (
    AnthropicProvider,
    ProviderResult,
    generate_recommendation,
    resolve_recommendation,
)
from market.models import AuditEvent, Instrument, SourceRegistry
from market.services import store_ingestion
from market.tests.factories import candle
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
        "probability_up_percent": 62,
        "probability_neutral_percent": 23,
        "probability_down_percent": 15,
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


def rising_candle(timestamp):
    return candle(
        timestamp,
        bid_open=Decimal("1.3590"),
        bid_high=Decimal("1.3610"),
        bid_low=Decimal("1.3580"),
        bid_close=Decimal("1.3598"),
        ask_open=Decimal("1.3592"),
        ask_high=Decimal("1.3612"),
        ask_low=Decimal("1.3582"),
        ask_close=Decimal("1.3600"),
    )


def hourly_candle(timestamp, **changes):
    values = {
        "bid_open": Decimal("1.3510"),
        "bid_high": Decimal("1.3520"),
        "bid_low": Decimal("1.3496"),
        "bid_close": Decimal("1.3505"),
        "ask_open": Decimal("1.3512"),
        "ask_high": Decimal("1.3522"),
        "ask_low": Decimal("1.3498"),
        "ask_close": Decimal("1.3507"),
    }
    values.update(changes)
    return candle(timestamp, **values)


def open_market_hours(start, end):
    cursor = start.replace(minute=0, second=0, microsecond=0)
    if cursor < start:
        cursor += timedelta(hours=1)
    values = []
    new_york = ZoneInfo("America/New_York")
    while cursor < end:
        local = cursor.astimezone(new_york)
        market_open = (
            local.weekday() < 4
            or (local.weekday() == 4 and local.hour < 17)
            or (local.weekday() == 6 and local.hour >= 17)
        )
        if market_open:
            values.append(cursor)
        cursor += timedelta(hours=1)
    return values


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
            {"test": "recommendation-reference", "requests": []},
        )
        self.now = timezone.now() + timedelta(seconds=1)
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
        self.assertEqual(first.contract_version, 2)
        self.assertEqual(first.probability_up, Decimal("0.6200"))
        self.assertEqual(first.probability_neutral, Decimal("0.2300"))
        self.assertEqual(first.probability_down, Decimal("0.1500"))
        self.assertEqual(first.confidence_percent, 62)
        self.assertEqual(
            first.input_payload["outcome_contract"]["reference_candle_id"],
            first.reference_candle_id,
        )
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
        self.assertFalse(
            AuditEvent.objects.filter(event_type="forecast.recommendation_generated").exists()
        )

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

    def test_probabilities_must_sum_to_one_hundred(self):
        provider = FakeProvider(output(probability_up_percent=61))

        with self.assertRaisesMessage(ValidationError, "summing to 100"):
            generate_recommendation(
                self.instrument, provider=provider, generated_at=self.now + timedelta(seconds=1)
            )

        self.assertEqual(Recommendation.objects.count(), 0)

    def test_resolution_waits_for_five_daily_sessions_and_scores_probabilities(self):
        recommendation = generate_recommendation(
            self.instrument,
            provider=FakeProvider(),
            generated_at=self.now + timedelta(seconds=1),
        )
        start = recommendation.reference_candle.timestamp + timedelta(days=1)
        store_ingestion(
            self.source,
            self.instrument,
            "D",
            start,
            start + timedelta(days=4),
            [rising_candle(start + timedelta(days=index)) for index in range(4)],
            {"test": "recommendation-future-four", "requests": []},
        )
        self.assertIsNone(resolve_recommendation(recommendation))

        store_ingestion(
            self.source,
            self.instrument,
            "D",
            start + timedelta(days=4),
            start + timedelta(days=5),
            [rising_candle(start + timedelta(days=4))],
            {"test": "recommendation-future-five", "requests": []},
        )
        resolution = resolve_recommendation(recommendation)

        self.assertEqual(resolution.outcome, Forecast.Direction.UP)
        self.assertTrue(resolution.directional_hit)
        self.assertEqual(resolution.brier_score, Decimal("0.073267"))
        self.assertEqual(resolution.details["sessions_observed"], 5)
        self.assertTrue(resolution.details["setup_performance_not_measured"])
        self.assertEqual(resolve_recommendation(recommendation), resolution)

    def test_paper_trade_uses_hourly_ask_entry_and_bid_target_after_entry_candle(self):
        recommendation = generate_recommendation(
            self.instrument,
            provider=FakeProvider(),
            generated_at=self.now + timedelta(seconds=1),
        )
        first = recommendation.generated_at.replace(minute=0, second=0, microsecond=0) + timedelta(
            hours=1
        )
        candles = [
            hourly_candle(
                first,
                bid_high=Decimal("1.3605"),
                ask_high=Decimal("1.3607"),
            ),
            hourly_candle(
                first + timedelta(hours=1),
                bid_high=Decimal("1.3602"),
                ask_high=Decimal("1.3604"),
            ),
        ]
        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            recommendation.generated_at - timedelta(hours=1),
            first + timedelta(hours=2),
            candles,
            {"test": "paper-target", "requests": []},
        )

        result = resolve_paper_trade(recommendation)

        self.assertEqual(result.outcome, PaperTradeResult.Outcome.TARGET)
        self.assertEqual(result.entry.execution_side, "ask")
        self.assertEqual(result.entry.fill_price, Decimal("1.350000"))
        self.assertTrue(result.entry.details["target_touch_on_entry_candle_ignored"])
        self.assertEqual(result.exit_candle.timestamp, first + timedelta(hours=1))
        self.assertEqual(result.exit_price, Decimal("1.360000"))
        self.assertEqual(result.gross_pips, Decimal("100.000"))
        self.assertEqual(result.r_multiple, Decimal("1.0000"))
        self.assertEqual(result.cost_assessment.optimistic_net_pips, Decimal("100.000"))
        self.assertEqual(result.cost_assessment.base_net_pips, Decimal("99.500"))
        self.assertEqual(result.cost_assessment.conservative_net_pips, Decimal("99.000"))
        self.assertFalse(result.cost_assessment.details["historical_financing_rates_available"])
        self.assertEqual(result.cost_assessment.policy_version, "paper-cost-sensitivity-v1")

    def test_paper_trade_applies_adverse_stop_precedence_on_ambiguous_entry_candle(self):
        recommendation = generate_recommendation(
            self.instrument,
            provider=FakeProvider(),
            generated_at=self.now + timedelta(seconds=1),
        )
        first = recommendation.generated_at.replace(minute=0, second=0, microsecond=0) + timedelta(
            hours=1
        )
        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            recommendation.generated_at - timedelta(hours=1),
            first + timedelta(hours=1),
            [
                hourly_candle(
                    first,
                    bid_open=Decimal("1.3490"),
                    bid_high=Decimal("1.3610"),
                    bid_low=Decimal("1.3390"),
                    ask_open=Decimal("1.3492"),
                    ask_high=Decimal("1.3612"),
                    ask_low=Decimal("1.3392"),
                )
            ],
            {"test": "paper-ambiguous", "requests": []},
        )

        result = resolve_paper_trade(recommendation)

        self.assertEqual(result.outcome, PaperTradeResult.Outcome.INVALIDATED)
        self.assertTrue(result.details["same_candle_target_and_stop"])
        self.assertTrue(result.details["adverse_invalidation_precedence"])
        self.assertEqual(result.exit_price, Decimal("1.340000"))
        self.assertEqual(result.gross_pips, Decimal("-100.000"))

    def test_paper_trade_waits_when_hourly_coverage_does_not_start_after_generation(self):
        recommendation = generate_recommendation(
            self.instrument,
            provider=FakeProvider(),
            generated_at=self.now + timedelta(seconds=1),
        )
        late = recommendation.generated_at.replace(minute=0, second=0, microsecond=0) + timedelta(
            hours=3
        )
        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            recommendation.generated_at - timedelta(hours=1),
            late + timedelta(hours=1),
            [hourly_candle(late)],
            {"test": "paper-incomplete-coverage", "requests": []},
        )

        self.assertIsNone(resolve_paper_trade(recommendation))
        self.assertFalse(PaperTradeEntry.objects.exists())

    def test_paper_trade_expires_unactivated_only_after_complete_hourly_coverage(self):
        recommendation = generate_recommendation(
            self.instrument,
            provider=FakeProvider(),
            generated_at=self.now + timedelta(seconds=1),
        )
        first_daily = (recommendation.reference_candle.timestamp + timedelta(days=1)).replace(
            minute=0, second=0, microsecond=0
        )
        future_daily = [rising_candle(first_daily + timedelta(days=index)) for index in range(5)]
        store_ingestion(
            self.source,
            self.instrument,
            "D",
            first_daily,
            first_daily + timedelta(days=5),
            future_daily,
            {"test": "paper-expiry-daily", "requests": []},
        )
        horizon = future_daily[-1].timestamp
        local_horizon = horizon.astimezone(ZoneInfo("America/New_York"))
        expiry = (local_horizon + timedelta(days=1)).astimezone(horizon.tzinfo)
        hours = open_market_hours(recommendation.generated_at, expiry)
        no_touch = [
            hourly_candle(
                timestamp,
                bid_open=Decimal("1.3550"),
                bid_high=Decimal("1.3560"),
                bid_low=Decimal("1.3540"),
                bid_close=Decimal("1.3552"),
                ask_open=Decimal("1.3552"),
                ask_high=Decimal("1.3562"),
                ask_low=Decimal("1.3542"),
                ask_close=Decimal("1.3554"),
            )
            for timestamp in hours
        ]
        hourly_run = store_ingestion(
            self.source,
            self.instrument,
            "H1",
            recommendation.generated_at - timedelta(hours=1),
            expiry,
            no_touch,
            {"test": "paper-expiry-hourly", "requests": []},
        )
        self.assertEqual(hourly_run.status, "succeeded")
        self.assertEqual(hourly_run.candles.count(), len(no_touch))

        result = resolve_paper_trade(recommendation)

        self.assertEqual(result.outcome, PaperTradeResult.Outcome.NOT_ACTIVATED)
        self.assertIsNone(result.entry)
        self.assertEqual(result.horizon_candle.timestamp, horizon)
        self.assertTrue(result.details["hourly_coverage_verified"])
        self.assertFalse(PaperTradeCostAssessment.objects.filter(result=result).exists())

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
    def test_database_rejects_recommendation_and_resolution_mutation(self):
        instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="test only",
        )
        reference_at = timezone.now() - timedelta(days=1)
        store_ingestion(
            source,
            instrument,
            "D",
            reference_at,
            reference_at + timedelta(days=1),
            [candle(reference_at)],
            {"test": "database-reference", "requests": []},
        )
        now = timezone.now() + timedelta(seconds=1)
        evidence(instrument, now)
        recommendation = generate_recommendation(
            instrument, provider=FakeProvider(), generated_at=now + timedelta(seconds=1)
        )

        with self.assertRaises(DatabaseError), transaction.atomic():
            Recommendation.objects.filter(pk=recommendation.pk).update(confidence_percent=99)

        recommendation.refresh_from_db()
        self.assertEqual(recommendation.confidence_percent, 62)

        first_hour = recommendation.generated_at.replace(
            minute=0, second=0, microsecond=0
        ) + timedelta(hours=1)
        store_ingestion(
            source,
            instrument,
            "H1",
            recommendation.generated_at - timedelta(hours=1),
            first_hour + timedelta(hours=1),
            [
                hourly_candle(
                    first_hour,
                    bid_open=Decimal("1.3490"),
                    bid_high=Decimal("1.3610"),
                    bid_low=Decimal("1.3390"),
                    ask_open=Decimal("1.3492"),
                    ask_high=Decimal("1.3612"),
                    ask_low=Decimal("1.3392"),
                )
            ],
            {"test": "database-paper-result", "requests": []},
        )
        paper_result = resolve_paper_trade(recommendation)
        with self.assertRaises(DatabaseError), transaction.atomic():
            PaperTradeEntry.objects.filter(pk=paper_result.entry_id).update(fill_price=0)
        with self.assertRaises(DatabaseError), transaction.atomic():
            PaperTradeResult.objects.filter(pk=paper_result.pk).update(gross_pips=0)
        with self.assertRaises(DatabaseError), transaction.atomic():
            PaperTradeCostAssessment.objects.filter(pk=paper_result.cost_assessment.pk).update(
                base_net_pips=0
            )

        paper_result.refresh_from_db()
        self.assertEqual(paper_result.gross_pips, Decimal("-100.000"))

        start = recommendation.reference_candle.timestamp + timedelta(days=1)
        store_ingestion(
            source,
            instrument,
            "D",
            start,
            start + timedelta(days=5),
            [rising_candle(start + timedelta(days=index)) for index in range(5)],
            {"test": "database-resolution", "requests": []},
        )
        resolution = resolve_recommendation(recommendation)
        with self.assertRaises(DatabaseError), transaction.atomic():
            type(resolution).objects.filter(pk=resolution.pk).update(brier_score=0)

        resolution.refresh_from_db()
        self.assertEqual(resolution.brier_score, Decimal("0.073267"))
