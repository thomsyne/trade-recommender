from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.test import SimpleTestCase

from market.technicals import calculate_technicals
from market.tests.factories import candle


class TechnicalCalculationTests(SimpleTestCase):
    def test_atr_and_ewma_are_deterministic_from_midpoint_prices(self):
        start = datetime(2026, 1, 5, tzinfo=UTC)
        candles = [
            candle(
                start + timedelta(hours=4 * index),
                bid_close=Decimal(f"1.10{index}0"),
                ask_close=Decimal(f"1.10{index}2"),
            )
            for index in range(3)
        ]

        first = calculate_technicals(candles)
        second = calculate_technicals(candles)

        self.assertEqual(first, second)
        self.assertEqual(first.atr_14, Decimal("0.003000"))
        self.assertEqual(first.ewma_20, Decimal("1.100377"))
        self.assertEqual(first.prior_high, Decimal("1.102100"))
