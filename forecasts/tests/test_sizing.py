from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from forecasts.sizing import calculate_size, quote_to_cad
from market.models import Candle, IngestionRun, Instrument, SourceRegistry


class PositionSizeCalculationTests(SimpleTestCase):
    def test_cad_quote_size_is_floored_to_declared_risk_cap(self):
        stop, units, risk = calculate_size(Decimal("1.350000"), Decimal("1.340000"), Decimal("1"))

        self.assertEqual(stop, Decimal("0.010000"))
        self.assertEqual(units, 12500)
        self.assertEqual(risk, Decimal("125.00"))

    def test_foreign_quote_is_converted_before_units_are_floored(self):
        stop, units, risk = calculate_size(
            Decimal("1.363000"), Decimal("1.355000"), Decimal("1.38000000")
        )

        self.assertEqual(stop, Decimal("0.008000"))
        self.assertEqual(units, 11322)
        self.assertEqual(risk, Decimal("124.99"))

    def test_zero_stop_distance_is_rejected(self):
        with self.assertRaisesMessage(ValidationError, "positive stop distance"):
            calculate_size(Decimal("1.35"), Decimal("1.35"), Decimal("1"))


class CadConversionTests(TestCase):
    def setUp(self):
        self.as_of = timezone.now()
        self.source = SourceRegistry.objects.create(
            name="OANDA v20",
            tier="established",
            base_url="https://developer.oanda.com",
            acquisition_method="v20 REST API",
            retention_policy="test",
        )
        self.usd_cad = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        self.gbp_usd = Instrument.objects.create(
            code="GBP_USD", base_currency="GBP", quote_currency="USD", display_order=2
        )
        self._candle(self.usd_cad, Decimal("1.380000"), "usd-cad")
        self._candle(self.gbp_usd, Decimal("1.360000"), "gbp-usd")

    def _candle(self, instrument, midpoint, digest):
        timestamp = self.as_of - timedelta(hours=1)
        run = IngestionRun.objects.create(
            source=self.source,
            instrument=instrument,
            granularity="H1",
            requested_from=timestamp,
            requested_to=self.as_of,
            parameters={},
            request_manifest_hash=digest,
            status=IngestionRun.Status.SUCCEEDED,
            fetched_count=1,
            stored_count=1,
            finished_at=self.as_of - timedelta(minutes=1),
        )
        spread = Decimal("0.000200")
        Candle.objects.create(
            instrument=instrument,
            ingestion_run=run,
            granularity="H1",
            timestamp=timestamp,
            complete=True,
            volume=1,
            bid_open=midpoint - spread / 2,
            bid_high=midpoint + Decimal("0.001000"),
            bid_low=midpoint - Decimal("0.001000"),
            bid_close=midpoint - spread / 2,
            ask_open=midpoint + spread / 2,
            ask_high=midpoint + Decimal("0.001200"),
            ask_low=midpoint - Decimal("0.000800"),
            ask_close=midpoint + spread / 2,
        )

    def test_direct_and_chained_point_in_time_conversion(self):
        usd_rate, usd_path = quote_to_cad("USD", as_of=self.as_of)
        gbp_rate, gbp_path = quote_to_cad("GBP", as_of=self.as_of)

        self.assertEqual(usd_rate, Decimal("1.38000000"))
        self.assertEqual(len(usd_path), 1)
        self.assertEqual(gbp_rate, Decimal("1.87680000"))
        self.assertEqual([item["instrument"] for item in gbp_path], ["GBP_USD", "USD_CAD"])

    def test_conversion_never_uses_ingestion_completed_after_sizing_time(self):
        with self.assertRaisesMessage(ValidationError, "No point-in-time USD/CAD"):
            quote_to_cad("USD", as_of=self.as_of - timedelta(minutes=2))
