"""Phase 1.4 D / 1.5 D — downstream evidence stays frozen; model identity is recorded honestly."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from forecasts.models import PaperTradeEntry, PaperTradeResult, Recommendation
from forecasts.paper import resolve_paper_trade
from forecasts.recommendations import (
    ProviderResult,
    generate_recommendation,
    resolve_recommendation,
)
from forecasts.services import issue_baselines, resolve_forecast
from forecasts.tests.test_recommendations import (
    FakeProvider,
    evidence,
    hourly_candle,
    open_market_hours,
    output,
)
from market.models import AuditEvent, Candle, CandleObservation, Instrument, SourceRegistry
from market.services import store_ingestion
from market.tests.factories import candle
from operations.models import ProviderBudgetReservation


class ReturningModelProvider(FakeProvider):
    def __init__(self, result=None, returned_model="fixed-v1-20260901"):
        super().__init__(result)
        self.returned_model = returned_model

    def generate(self, input_payload):
        self.calls += 1
        return ProviderResult(
            self.result, "response-2", 1200, 300, returned_model=self.returned_model
        )


class FrozenEvidenceTests(TestCase):
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
        # Mirrors forecasts.tests.test_recommendations: the reference candle is
        # yesterday's completed session; later sessions carry future interval
        # starts, which is legitimate for stored evidence.
        self.reference_at = timezone.now() - timedelta(days=1)
        self.daily(self.reference_at, "reference")
        self.now = timezone.now() + timedelta(seconds=1)
        self.snapshot = evidence(self.instrument, self.now)

    def daily(self, timestamp, batch, **changes):
        return store_ingestion(
            self.source,
            self.instrument,
            "D",
            timestamp,
            timestamp + timedelta(days=1),
            [candle(timestamp, **changes)],
            {"test": batch, "requests": []},
        )

    def resolve_after_five_sessions(self, recommendation):
        endpoint = None
        for index in range(1, 6):
            run = self.daily(self.reference_at + timedelta(days=index), f"session-{index}")
            endpoint = run
        return resolve_recommendation(recommendation), endpoint

    def test_recommendation_records_requested_and_returned_model_identity(self):
        provider = ReturningModelProvider()
        recommendation = generate_recommendation(
            self.instrument, provider=provider, generated_at=self.now + timedelta(seconds=1)
        )

        self.assertEqual(recommendation.model, "fixed-v1")
        self.assertEqual(recommendation.returned_model, "fixed-v1-20260901")
        self.assertEqual(recommendation.pricing_version, "anthropic-standard-2026-08-10")
        reservation = ProviderBudgetReservation.objects.get(
            idempotency_key=f"recommendation:{recommendation.idempotency_key}"
        )
        self.assertEqual(reservation.requested_model, "fixed-v1")
        self.assertEqual(reservation.returned_model, "fixed-v1-20260901")
        self.assertEqual(reservation.usage_identity, "response-2")
        self.assertEqual(reservation.outcome, ProviderBudgetReservation.Outcome.VALIDATED)
        self.assertEqual(reservation.status, ProviderBudgetReservation.Status.SETTLED)
        audit = AuditEvent.objects.get(event_type="forecast.recommendation_generated")
        self.assertTrue(audit.payload["model_identity_mismatch"])
        self.assertEqual(
            audit.payload["reference_candle_content_sha256"],
            recommendation.reference_candle.content_sha256,
        )

    def test_missing_returned_model_identity_is_recorded_honestly_not_invented(self):
        recommendation = generate_recommendation(
            self.instrument, provider=FakeProvider(), generated_at=self.now + timedelta(seconds=1)
        )
        reservation = ProviderBudgetReservation.objects.get(
            idempotency_key=f"recommendation:{recommendation.idempotency_key}"
        )
        self.assertEqual(recommendation.returned_model, "")
        self.assertEqual(reservation.returned_model, "")
        self.assertFalse(
            AuditEvent.objects.get(event_type="forecast.recommendation_generated").payload[
                "model_identity_mismatch"
            ]
        )

    def test_rejected_response_is_a_paid_failed_attempt_not_a_recommendation(self):
        provider = FakeProvider(output(evidence_ids=["technical:local-policy-v1", "news:72"]))
        with self.assertRaises(ValidationError):
            generate_recommendation(
                self.instrument, provider=provider, generated_at=self.now + timedelta(seconds=1)
            )
        reservation = ProviderBudgetReservation.objects.get()
        self.assertEqual(reservation.status, ProviderBudgetReservation.Status.SETTLED)
        self.assertEqual(reservation.outcome, ProviderBudgetReservation.Outcome.REJECTED)
        self.assertEqual(Recommendation.objects.count(), 0)

    def test_provider_revision_of_resolved_candles_is_a_conflict_that_changes_nothing(self):
        recommendation = generate_recommendation(
            self.instrument, provider=FakeProvider(), generated_at=self.now + timedelta(seconds=1)
        )
        resolution, endpoint_run = self.resolve_after_five_sessions(recommendation)
        self.assertIsNotNone(resolution)
        endpoint = resolution.horizon_candle
        self.assertEqual(
            resolution.details["horizon_candle_content_sha256"], endpoint.content_sha256
        )
        self.assertEqual(
            resolution.details["reference_candle_content_sha256"],
            recommendation.reference_candle.content_sha256,
        )
        self.assertEqual(len(resolution.details["candle_content_sha256s"]), 5)
        original_outcome = (
            resolution.outcome,
            resolution.endpoint_midpoint,
            resolution.brier_score,
        )

        revised = self.daily(
            endpoint.timestamp,
            "revision",
            bid_close=endpoint.bid_close + Decimal("0.0100"),
            ask_close=endpoint.ask_close + Decimal("0.0100"),
            bid_high=endpoint.bid_high + Decimal("0.0100"),
            ask_high=endpoint.ask_high + Decimal("0.0100"),
        )

        self.assertEqual(revised.stored_count, 0)
        observation = CandleObservation.objects.get(candle=endpoint, revision=2)
        self.assertEqual(observation.kind, CandleObservation.Kind.CONFLICT)
        self.assertTrue(
            AuditEvent.objects.filter(event_type="market.live_candle_conflict").exists()
        )
        endpoint.refresh_from_db()
        self.assertEqual(endpoint.bid_close, candle(endpoint.timestamp).bid_close)
        resolution.refresh_from_db()
        self.assertEqual(
            (resolution.outcome, resolution.endpoint_midpoint, resolution.brier_score),
            original_outcome,
        )
        self.assertEqual(resolve_recommendation(recommendation), resolution)
        reference_revision = self.daily(
            recommendation.reference_candle.timestamp, "reference-revision", volume=1
        )
        self.assertEqual(reference_revision.stored_count, 0)
        self.assertEqual(
            CandleObservation.objects.get(candle=recommendation.reference_candle, revision=2).kind,
            CandleObservation.Kind.CONFLICT,
        )

    def test_unreferenced_candle_revision_is_a_plain_revision(self):
        run = self.daily(self.reference_at + timedelta(days=1), "unreferenced")
        row = Candle.objects.get(ingestion_run=run)
        self.daily(row.timestamp, "unreferenced-revision", volume=3)
        self.assertEqual(
            CandleObservation.objects.get(candle=row, revision=2).kind,
            CandleObservation.Kind.REVISION,
        )

    def test_paper_entry_and_exit_bind_hourly_bid_ask_observations(self):
        from forecasts.portfolio import assess_recommendation_batch
        from forecasts.sizing import size_recommendation

        recommendation = generate_recommendation(
            self.instrument, provider=FakeProvider(), generated_at=self.now + timedelta(seconds=1)
        )
        size_recommendation(recommendation, sized_at=recommendation.generated_at)
        assess_recommendation_batch([recommendation], generated_at=recommendation.generated_at)
        hours = open_market_hours(
            recommendation.generated_at, recommendation.generated_at + timedelta(days=2)
        )[:6]
        # The default hourly candle already satisfies the at-or-below ask entry on
        # the first hour; the target is touched three hours later.
        target_hour = hours[3]
        candles = [
            hourly_candle(hour, bid_high=Decimal("1.3700"), ask_high=Decimal("1.3702"))
            if hour == target_hour
            else hourly_candle(hour)
            for hour in hours
        ]
        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            recommendation.generated_at,
            hours[-1] + timedelta(hours=1),
            candles,
            {"test": "hourly", "requests": []},
        )

        result = resolve_paper_trade(recommendation)

        self.assertIsInstance(result, PaperTradeResult)
        entry = PaperTradeEntry.objects.get(recommendation=recommendation)
        self.assertEqual(entry.execution_side, "ask")
        self.assertEqual(entry.details["candle_content_sha256"], entry.candle.content_sha256)
        self.assertEqual(entry.details["candle_revision_policy"], "first-complete-observation-v1")
        self.assertEqual(result.outcome, PaperTradeResult.Outcome.TARGET)
        self.assertEqual(
            result.details["exit_candle_content_sha256"], result.exit_candle.content_sha256
        )
        frozen = (result.exit_price, result.gross_pips, entry.fill_price)

        store_ingestion(
            self.source,
            self.instrument,
            "H1",
            target_hour,
            target_hour + timedelta(hours=1),
            [hourly_candle(target_hour, bid_high=Decimal("1.3650"), ask_high=Decimal("1.3652"))],
            {"test": "hourly-revision", "requests": []},
        )

        self.assertEqual(
            CandleObservation.objects.get(candle=result.exit_candle, revision=2).kind,
            CandleObservation.Kind.CONFLICT,
        )
        result.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual((result.exit_price, result.gross_pips, entry.fill_price), frozen)
        self.assertEqual(resolve_paper_trade(recommendation), result)

    def test_forecast_evidence_snapshot_and_resolution_stay_bound(self):
        from market.models import TechnicalSnapshot

        macro, tactical = issue_baselines(self.instrument, issued_at=self.now)
        anchor = macro.evidence_snapshot.anchor_candle
        snapshot = macro.evidence_snapshot.technical_snapshot
        self.assertEqual(snapshot.provenance, TechnicalSnapshot.Provenance.OBSERVED)
        for index in range(1, 6):
            self.daily(self.reference_at + timedelta(days=index), f"forecast-session-{index}")
        resolution = resolve_forecast(tactical)
        self.assertIsNotNone(resolution)
        self.daily(anchor.timestamp, "anchor-revision", volume=2)
        self.assertEqual(
            CandleObservation.objects.get(candle=anchor, revision=2).kind,
            CandleObservation.Kind.CONFLICT,
        )
        snapshot.refresh_from_db()
        self.assertEqual(macro.evidence_snapshot.technical_snapshot_id, snapshot.pk)
        self.assertEqual(resolve_forecast(tactical), resolution)
