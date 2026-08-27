from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from research.signal_count import (
    ENTRY_FIELDS,
    SIGNAL_COUNT_IDENTITY,
    ReturnBlindViolation,
    SignalCountOutput,
    enforce_price_cutoff,
    generate_spread_ceilings,
    read_entry_projection,
)


class SignalCountBoundaryTests(SimpleTestCase):
    def test_entry_projection_rejects_forbidden_or_partial_fields_before_query(self):
        for fields in ({"timestamp", "bid_open", "ask_open", "bid_high"}, {"bid_open"}):
            with self.subTest(fields=fields), self.assertRaises(ReturnBlindViolation):
                read_entry_projection(
                    dataset_id=1,
                    instrument_id=1,
                    theoretical_entry_timestamp=datetime(2018, 1, 1, tzinfo=UTC),
                    as_of=datetime(2018, 1, 1, 2, tzinfo=UTC),
                    fields=fields,
                )

    def test_projection_is_exact_and_requires_completion(self):
        timestamp = datetime(2018, 1, 1, tzinfo=UTC)
        with self.assertRaises(ReturnBlindViolation):
            read_entry_projection(
                dataset_id=1,
                instrument_id=1,
                theoretical_entry_timestamp=timestamp,
                as_of=timestamp + timedelta(minutes=59),
                fields=ENTRY_FIELDS,
            )
        row = {"timestamp": timestamp, "bid_open": Decimal("1.1"), "ask_open": Decimal("1.2")}
        with patch("research.signal_count.Candle.objects") as objects:
            objects.filter.return_value.values.return_value.get.return_value = row
            projection = read_entry_projection(
                dataset_id=1,
                instrument_id=2,
                theoretical_entry_timestamp=timestamp,
                as_of=timestamp + timedelta(hours=1),
            )
            objects.filter.return_value.values.assert_called_once_with(*sorted(ENTRY_FIELDS))
        self.assertEqual(projection.ask_open, Decimal("1.2"))

    def test_later_rows_and_m1_fail_closed(self):
        timestamp = datetime(2018, 1, 1, tzinfo=UTC)
        with self.assertRaises(ReturnBlindViolation):
            enforce_price_cutoff(
                row_timestamp=timestamp + timedelta(seconds=1),
                theoretical_entry_timestamp=timestamp,
            )
        with self.assertRaises(ReturnBlindViolation):
            enforce_price_cutoff(
                row_timestamp=timestamp, theoretical_entry_timestamp=timestamp, granularity="M1"
            )

    def test_output_rejects_return_and_excursion_fields(self):
        for forbidden in ("pnl", "return_bps", "exit_price", "adverse_excursion"):
            with self.subTest(forbidden=forbidden), self.assertRaises(ReturnBlindViolation):
                SignalCountOutput(SIGNAL_COUNT_IDENTITY, "S1", {forbidden: 1}, {}, "a" * 64)

    def test_s0_p99_is_deterministic_and_outcome_free(self):
        values = [Decimal(index) / 100_000 for index in range(1, 101)]
        self.assertEqual(
            generate_spread_ceilings(
                {"EUR_USD/NY": reversed(values)}, {"EUR_USD/NY": Decimal("0.00001")}
            ),
            {"EUR_USD/NY": Decimal("0.00099")},
        )
