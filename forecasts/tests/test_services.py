from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase, TransactionTestCase

from forecasts.models import Forecast, ForecastResolution, TargetContract
from forecasts.services import (
    classify_change,
    ensure_target_contracts,
    issue_baselines,
    resolve_forecast,
)
from market.models import Instrument, SourceRegistry
from market.services import store_ingestion
from market.tests.factories import candle


class ForecastServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        cls.source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="test only",
        )
        cls.start = datetime(2026, 1, 1, 22, tzinfo=UTC)
        cls._store_daily_batch(
            cls.start,
            20,
            "initial",
            bid_close=Decimal("1.1010"),
            ask_close=Decimal("1.1012"),
        )

    @classmethod
    def _store_daily_batch(cls, start, count, manifest, **changes):
        data = [candle(start + timedelta(days=index), **changes) for index in range(count)]
        return store_ingestion(
            cls.source,
            cls.instrument,
            "D",
            start,
            start + timedelta(days=count),
            data,
            {"test": manifest, "requests": []},
        )

    def test_contracts_and_baselines_are_versioned_parented_and_idempotent(self):
        contracts = ensure_target_contracts()
        issued_at = self.start + timedelta(days=20)

        first = issue_baselines(self.instrument, issued_at)
        second = issue_baselines(self.instrument, issued_at + timedelta(hours=1))
        macro, tactical = first

        self.assertEqual(first, second)
        self.assertEqual(contracts[TargetContract.Product.TACTICAL].horizon_sessions, 5)
        self.assertEqual(
            contracts[TargetContract.Product.TACTICAL].neutral_atr_multiplier, Decimal("0.250")
        )
        self.assertEqual(tactical.parent, macro)
        self.assertTrue(tactical.abstained)
        self.assertEqual(tactical.entry_condition, Forecast.EntryCondition.NONE)
        self.assertEqual(
            tactical.probability_up + tactical.probability_neutral + tactical.probability_down,
            Decimal("1.0000"),
        )
        self.assertEqual(
            tactical.evidence_snapshot.anchor_candle.timestamp, self.start + timedelta(days=19)
        )
        self.assertEqual(tactical.information_cutoff, issued_at)

    def test_resolution_waits_for_five_later_sessions_then_scores_golden_outcome(self):
        _, tactical = issue_baselines(self.instrument, self.start + timedelta(days=20))
        future_start = self.start + timedelta(days=20)
        self._store_daily_batch(
            future_start,
            4,
            "future-four",
            bid_close=Decimal("1.1200"),
            bid_high=Decimal("1.1210"),
            ask_close=Decimal("1.1202"),
            ask_high=Decimal("1.1212"),
        )

        self.assertIsNone(resolve_forecast(tactical))

        self._store_daily_batch(
            future_start + timedelta(days=4),
            1,
            "future-five",
            bid_close=Decimal("1.1200"),
            bid_high=Decimal("1.1210"),
            ask_close=Decimal("1.1202"),
            ask_high=Decimal("1.1212"),
        )
        resolution = resolve_forecast(tactical)

        self.assertEqual(resolution.outcome, ForecastResolution.Outcome.UP)
        self.assertEqual(resolution.endpoint_midpoint, Decimal("1.120100"))
        self.assertEqual(resolution.midpoint_change, Decimal("0.019000"))
        self.assertEqual(resolution.brier_score, Decimal("0.291667"))
        self.assertEqual(resolution.setup_outcome, ForecastResolution.SetupOutcome.NOT_OFFERED)
        self.assertEqual(resolve_forecast(tactical), resolution)

    def test_conditional_entry_records_touch_without_claiming_a_fill(self):
        macro, tactical = issue_baselines(self.instrument, self.start + timedelta(days=20))
        conditional = Forecast.objects.create(
            instrument=self.instrument,
            target_contract=tactical.target_contract,
            evidence_snapshot=tactical.evidence_snapshot,
            parent=macro,
            method="golden-conditional-fixture",
            method_version=1,
            issued_at=tactical.issued_at,
            information_cutoff=tactical.information_cutoff,
            reference_midpoint=tactical.reference_midpoint,
            neutral_band=tactical.neutral_band,
            direction=Forecast.Direction.UP,
            probability_up=Decimal("0.5000"),
            probability_neutral=Decimal("0.3000"),
            probability_down=Decimal("0.2000"),
            abstained=False,
            entry_condition=Forecast.EntryCondition.AT_OR_BELOW,
            entry_level=Decimal("1.100000"),
            target_level=Decimal("1.120000"),
            invalidation_level=Decimal("1.090000"),
            setup_expires_after_sessions=5,
            rationale="Golden contract fixture.",
            idempotency_key="golden-conditional-fixture",
        )
        self._store_daily_batch(self.start + timedelta(days=20), 5, "conditional-future")

        resolution = resolve_forecast(conditional)

        self.assertEqual(resolution.setup_outcome, ForecastResolution.SetupOutcome.ACTIVATED)
        self.assertTrue(resolution.details["entry_is_daily_touch_not_assumed_fill"])
        self.assertEqual(resolution.details["entry_touch_side"], "ask")

    def test_neutral_band_equality_is_neutral(self):
        self.assertEqual(
            classify_change(Decimal("0.001"), Decimal("0.001")), Forecast.Direction.NEUTRAL
        )
        self.assertEqual(
            classify_change(Decimal("-0.001"), Decimal("0.001")), Forecast.Direction.NEUTRAL
        )

    def test_fixture_baseline_requires_explicit_test_only_override(self):
        self.source.name = "Development fixtures"
        self.source.save(update_fields=("name",))

        with self.assertRaisesMessage(
            ValidationError, "Refusing to issue a prospective baseline from development fixtures"
        ):
            issue_baselines(self.instrument, self.start + timedelta(days=20))

    def test_python_layer_rejects_forecast_mutation(self):
        _, forecast = issue_baselines(self.instrument, self.start + timedelta(days=20))
        forecast.rationale = "changed after issuance"
        with self.assertRaises(ValidationError):
            forecast.save()


class ForecastDatabaseInvariantTests(TransactionTestCase):
    def test_database_rejects_forecast_mutation(self):
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
        start = datetime(2026, 1, 1, 22, tzinfo=UTC)
        data = [candle(start + timedelta(days=index)) for index in range(20)]
        store_ingestion(
            source,
            instrument,
            "D",
            start,
            start + timedelta(days=20),
            data,
            {"test": "database-trigger", "requests": []},
        )
        _, forecast = issue_baselines(instrument, start + timedelta(days=20))

        with self.assertRaises(DatabaseError), transaction.atomic():
            Forecast.objects.filter(pk=forecast.pk).update(rationale="mutated")

        forecast.refresh_from_db()
        self.assertNotEqual(forecast.rationale, "mutated")
