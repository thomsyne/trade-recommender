from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from market.models import DatasetVersion, Instrument, SourceRegistry
from market.services import store_ingestion
from market.tests.factories import candle
from research.models import (
    EntryEligibilityEvaluation,
    Level,
    SetupEvent,
    SetupTransition,
    StrategyDefinition,
    StrategyVersion,
)
from research.signal_count import (
    ENTRY_FIELDS,
    SIGNAL_COUNT_IDENTITY,
    ReturnBlindViolation,
    SignalCountOutput,
    enforce_price_cutoff,
    generate_spread_ceilings,
    read_entry_projection,
    run_s1,
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
        for forbidden in (
            "pnl",
            "return_bps",
            "exit_price",
            "adverse_excursion",
            "innocent_metric",
        ):
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


class SignalCountFunctionalTests(TestCase):
    def test_s1_reads_bounded_entry_projection_and_emits_strict_counts(self):
        entry_at = datetime(2018, 1, 2, 14, tzinfo=UTC)
        source = SourceRegistry.objects.create(
            name="bounded-fixture",
            tier=SourceRegistry.Tier.QUARANTINE,
            base_url="https://example.invalid",
            acquisition_method="test",
            retention_policy="test",
        )
        instrument = Instrument.objects.create(
            code="EUR_USD", base_currency="EUR", quote_currency="USD", display_order=1
        )
        dataset = DatasetVersion.objects.create(
            name="bounded",
            version="1",
            source=source,
            manifest_sha256="1" * 64,
        )
        store_ingestion(
            source,
            instrument,
            "H1",
            entry_at,
            entry_at + timedelta(hours=1),
            [candle(entry_at)],
            {"bounded": True},
            dataset_version=dataset,
        )
        definition = StrategyDefinition.objects.create(key="s1-test", name="S1 test")
        strategy = StrategyVersion.objects.create(
            definition=definition,
            version="1",
            detector_version="detector",
            data_identity="data",
            event_identity="event",
            execution_identity="execution-h1-stop-first-v1",
            cost_identity="cost",
            portfolio_identity="portfolio",
            content_hash="2" * 64,
        )
        setup = SetupEvent.objects.create(
            instrument=instrument,
            direction=SetupEvent.Direction.LONG,
            sweep_h1_timestamp=entry_at - timedelta(hours=2),
            detector_version=strategy.detector_version,
            dataset_version=dataset,
            strategy_version=strategy,
            sweep_evidence={},
            bias_evidence={},
            provisional_swing_evidence={},
            threshold_evidence={},
            evidence_hash="3" * 64,
        )
        level = Level.objects.create(
            family=Level.Family.WEEKLY,
            role=Level.Role.RESISTANCE,
            instrument=instrument,
            strategy_version=strategy,
            dataset_version=dataset,
            source_timeframe="W",
            source_candle_timestamp=entry_at - timedelta(weeks=1),
            central_price=Decimal("1.2"),
            zone_lower=Decimal("1.19"),
            zone_upper=Decimal("1.21"),
            atr_at_activation=Decimal("0.1"),
            activated_at=entry_at - timedelta(days=1),
            stable_key="4" * 64,
        )
        SetupTransition.objects.create(
            setup=setup,
            from_state=SetupTransition.State.TRIGGER_PENDING,
            to_state=SetupTransition.State.CONFIRMED,
            effective_at=entry_at - timedelta(hours=1),
            evidence_hash="5" * 64,
            strategy_version=strategy,
            dataset_version=dataset,
            execution_identity=strategy.execution_identity,
        )
        EntryEligibilityEvaluation.objects.create(
            setup=setup,
            book_identity="failed-break-any-level-deduplicated-v1",
            decision=EntryEligibilityEvaluation.Decision.ENTRY_PENDING,
            entry_timestamp=entry_at,
            entry_price=Decimal("1.1002"),
            stop_price=Decimal("1.09"),
            target_price=Decimal("1.19"),
            reward_risk=Decimal("7.9"),
            risk_per_unit_quote=Decimal("0.0102"),
            conversion_rate_to_cad=Decimal("1.35"),
            conversion_effective_at=entry_at,
            conversion_identity="USD_CAD@entry",
            risk_per_unit_cad=Decimal("0.01377"),
            target_level=level,
            evidence_hash="6" * 64,
        )

        output = run_s1(dataset_id=dataset.pk, maximum_setups=1)

        self.assertEqual(output.counts["physical_setups_processed"], 1)
        self.assertEqual(output.counts["eligibility_evaluations_processed"], 1)
        self.assertEqual(output.counts["entry_eligible"], 1)
        self.assertEqual(output.coverage["entry_projections_read"], 1)
