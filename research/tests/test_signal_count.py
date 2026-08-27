from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from market.models import DatasetVersion, Instrument, SourceRegistry, dataset_manifest_sha256
from market.services import DatasetQualityError, RequiredCandleRange, store_ingestion
from market.tests.factories import candle
from research.models import (
    AnalysisRun,
    EntryEligibilityEvaluation,
    JobRun,
    Level,
    SetupEvent,
    SetupLevelAttribution,
    SetupTransition,
    StrategyDefinition,
    StrategyVersion,
)
from research.signal_count import (
    ENTRY_FIELDS,
    FROZEN_INSTRUMENTS,
    PHASE1_MANIFEST_SHA256,
    S0_JOB_NAME,
    SIGNAL_COUNT_IDENTITY,
    ReturnBlindViolation,
    SignalCountOutput,
    _analysis_data_incomplete_count,
    _maximum_horizon_end,
    _next_registered_h1_open,
    _s1_evaluation_queryset,
    _validate_s1_contract,
    _validated_s0_job,
    enforce_price_cutoff,
    generate_spread_ceilings,
    read_entry_projection,
    run_s0,
    run_s1,
)


class SignalCountBoundaryTests(SimpleTestCase):
    def test_partition_boundary_purge_uses_new_york_confirmation_and_weekend_alignment(self):
        new_york = ZoneInfo("America/New_York")
        retained_confirmation = datetime(2018, 12, 14, 17, tzinfo=new_york)
        purged_confirmation = datetime(2018, 12, 28, 17, tzinfo=new_york)

        retained_entry = _next_registered_h1_open(retained_confirmation)
        purged_entry = _next_registered_h1_open(purged_confirmation)
        self.assertEqual(retained_entry, datetime(2018, 12, 16, 17, tzinfo=new_york))
        self.assertEqual(purged_entry, datetime(2018, 12, 30, 17, tzinfo=new_york))
        self.assertLess(
            _maximum_horizon_end(retained_entry),
            datetime(2019, 1, 1, tzinfo=new_york),
        )
        self.assertGreaterEqual(
            _maximum_horizon_end(purged_entry),
            datetime(2019, 1, 1, tzinfo=new_york),
        )

    def test_s1_contract_rejects_missing_frozen_instrument(self):
        strategy = SimpleNamespace(
            content_hash=PHASE1_MANIFEST_SHA256,
            pair_metadata={"instruments": sorted(FROZEN_INSTRUMENTS)},
        )
        dataset = SimpleNamespace(
            manifest_sha256="0" * 64,
            manifest={
                "strategy_manifest_sha256": PHASE1_MANIFEST_SHA256,
                "instruments": sorted(FROZEN_INSTRUMENTS - {"USD_JPY"}),
                "partition": {"name": "development", "start_year": 2010, "end_year": 2018},
            },
        )

        dataset.manifest_sha256 = dataset_manifest_sha256(dataset.manifest)
        with self.assertRaisesMessage(ReturnBlindViolation, "frozen S1 universe"):
            _validate_s1_contract(dataset, strategy, datetime(2019, 1, 5, tzinfo=UTC), 1)

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
        with (
            patch("research.signal_count.DatasetVersion.objects.get"),
            patch("research.signal_count.assert_dataset_window_usable"),
            patch("research.signal_count.Candle.objects") as objects,
        ):
            objects.filter.return_value.values.return_value.get.return_value = row
            projection = read_entry_projection(
                dataset_id=1,
                instrument_id=2,
                theoretical_entry_timestamp=timestamp,
                as_of=timestamp + timedelta(hours=1),
            )
            objects.filter.return_value.values.assert_called_once_with(*sorted(ENTRY_FIELDS))
        self.assertEqual(projection.ask_open, Decimal("1.2"))

    def test_s1_contract_rejects_insufficient_indicator_warmup(self):
        strategy = SimpleNamespace(
            content_hash=PHASE1_MANIFEST_SHA256,
            pair_metadata={"instruments": sorted(FROZEN_INSTRUMENTS)},
        )
        range_specs = (
            ("W", datetime(2009, 12, 18, 22, tzinfo=UTC), datetime(2019, 1, 4, 22, tzinfo=UTC)),
            ("D", datetime(2009, 12, 27, 22, tzinfo=UTC), datetime(2019, 1, 1, 22, tzinfo=UTC)),
            ("H1", datetime(2009, 12, 30, 5, tzinfo=UTC), datetime(2019, 1, 1, 5, tzinfo=UTC)),
        )
        manifest = {
            "strategy_manifest_sha256": PHASE1_MANIFEST_SHA256,
            "instruments": sorted(FROZEN_INSTRUMENTS),
            "partition": {"name": "development", "start_year": 2010, "end_year": 2018},
            "required_ranges": [
                {
                    "instrument": code,
                    "granularity": granularity,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                }
                for code in sorted(FROZEN_INSTRUMENTS)
                for granularity, start, end in range_specs
            ],
        }
        dataset = SimpleNamespace(
            manifest=manifest,
            manifest_sha256=dataset_manifest_sha256(manifest),
        )

        with self.assertRaisesMessage(ReturnBlindViolation, "lacks development or warm-up"):
            _validate_s1_contract(dataset, strategy, datetime(2019, 1, 5, tzinfo=UTC), 1)

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
        instruments = {}
        for display_order, code in enumerate(sorted(FROZEN_INSTRUMENTS), 1):
            base_currency, quote_currency = code.split("_")
            instruments[code] = Instrument.objects.create(
                code=code,
                base_currency=base_currency,
                quote_currency=quote_currency,
                display_order=display_order,
            )
        instrument = instruments["EUR_USD"]
        range_specs = (
            ("W", datetime(2009, 12, 18, 22, tzinfo=UTC), datetime(2019, 1, 4, 22, tzinfo=UTC)),
            ("D", datetime(2009, 1, 4, 22, tzinfo=UTC), datetime(2019, 1, 1, 22, tzinfo=UTC)),
            ("H1", datetime(2009, 12, 30, 5, tzinfo=UTC), datetime(2019, 1, 1, 5, tzinfo=UTC)),
        )
        dataset = DatasetVersion.objects.create(
            name="bounded",
            version="1",
            source=source,
            manifest={
                "strategy_manifest_sha256": PHASE1_MANIFEST_SHA256,
                "instruments": sorted(FROZEN_INSTRUMENTS),
                "partition": {"name": "development", "start_year": 2010, "end_year": 2018},
                "required_ranges": [
                    {
                        "instrument": code,
                        "granularity": granularity,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                    }
                    for code in sorted(FROZEN_INSTRUMENTS)
                    for granularity, start, end in range_specs
                ],
            },
        )
        fixture_ranges = {}
        for code, registered_instrument in instruments.items():
            raw_ranges = (
                ("W", datetime(2017, 12, 29, 22, tzinfo=UTC), datetime(2018, 1, 5, 22, tzinfo=UTC)),
                ("D", datetime(2018, 1, 1, 22, tzinfo=UTC), datetime(2018, 1, 2, 22, tzinfo=UTC)),
                ("H1", entry_at, entry_at + timedelta(hours=1)),
            )
            fixture_ranges[code] = [
                RequiredCandleRange(granularity, start, end)
                for granularity, start, end in raw_ranges
            ]
            for granularity, start, end in raw_ranges:
                store_ingestion(
                    source,
                    registered_instrument,
                    granularity,
                    start,
                    end,
                    [candle(start)],
                    {"bounded": True, "instrument": code, "granularity": granularity},
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
            pair_metadata={"instruments": sorted(FROZEN_INSTRUMENTS)},
            content_hash=PHASE1_MANIFEST_SHA256,
        )
        as_of = datetime(2019, 1, 4, 22, tzinfo=UTC)
        arbitrary_s0 = JobRun.objects.create(
            job_name=S0_JOB_NAME,
            strategy_version=strategy,
            dataset_version=dataset,
            config_hash="a" * 64,
            idempotency_key="arbitrary-s0",
            as_of=as_of,
            status=JobRun.Status.SUCCEEDED,
            evidence={"report_sha256": "b" * 64},
        )
        with self.assertRaisesMessage(ReturnBlindViolation, "genuine immutable S0 audit"):
            _validated_s0_job(
                s0_job_id=arbitrary_s0.pk,
                dataset=dataset,
                strategy=strategy,
            )
        with patch("research.signal_count._validate_dataset_contract", return_value=fixture_ranges):
            s0_output, s0_job = run_s0(
                dataset_id=dataset.pk,
                strategy_version_id=strategy.pk,
                maximum_observations=10,
                as_of=as_of,
            )
            s0_replay, replay_job = run_s0(
                dataset_id=dataset.pk,
                strategy_version_id=strategy.pk,
                maximum_observations=10,
                as_of=as_of,
            )
            with self.assertRaisesMessage(ReturnBlindViolation, "would truncate"):
                run_s0(
                    dataset_id=dataset.pk,
                    strategy_version_id=strategy.pk,
                    maximum_observations=5,
                    as_of=as_of,
                )
        self.assertEqual(s0_output.counts["observations"], 6)
        self.assertEqual(s0_replay.report_sha256, s0_output.report_sha256)
        self.assertEqual(replay_job.pk, s0_job.pk)
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
            attribution_keys=["4" * 64],
            evidence_hash="3" * 64,
        )
        level = Level.objects.create(
            family=Level.Family.WEEKLY,
            role=Level.Role.SUPPORT,
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
        SetupLevelAttribution.objects.create(setup=setup, level=level)
        SetupTransition.objects.create(
            setup=setup,
            from_state=SetupTransition.State.TRIGGER_PENDING,
            to_state=SetupTransition.State.CONFIRMED,
            effective_at=entry_at,
            evidence_hash="5" * 64,
            strategy_version=strategy,
            dataset_version=dataset,
            execution_identity=strategy.execution_identity,
        )
        SetupTransition.objects.create(
            setup=setup,
            book_identity="failed-break-any-level-deduplicated-v1",
            from_state=SetupTransition.State.CONFIRMED,
            to_state=SetupTransition.State.ENTRY_PENDING,
            effective_at=entry_at,
            evidence_hash="7" * 64,
            strategy_version=strategy,
            dataset_version=dataset,
            execution_identity=strategy.execution_identity,
        )
        SetupTransition.objects.create(
            setup=setup,
            book_identity="failed-break-weekly-extreme-v1",
            from_state=SetupTransition.State.CONFIRMED,
            to_state=SetupTransition.State.NO_TARGET,
            effective_at=entry_at,
            reason="NO_ACTIVE_OPPOSING_LEVEL",
            evidence_hash="8" * 64,
            strategy_version=strategy,
            dataset_version=dataset,
            execution_identity=strategy.execution_identity,
        )
        target_level = Level.objects.create(
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
            stable_key="a" * 64,
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
            target_level=target_level,
            target_stable_key=target_level.stable_key,
            evidence_hash="6" * 64,
        )
        EntryEligibilityEvaluation.objects.create(
            setup=setup,
            book_identity="failed-break-weekly-extreme-v1",
            decision=EntryEligibilityEvaluation.Decision.NO_TARGET,
            terminal_reason="NO_ACTIVE_OPPOSING_LEVEL",
            evidence_hash="9" * 64,
        )
        for index, terminal in enumerate(
            (
                SetupTransition.State.INVALIDATED,
                SetupTransition.State.EXPIRED,
                SetupTransition.State.CANCELLED_DATA_QUALITY,
            ),
            start=1,
        ):
            terminal_setup = SetupEvent.objects.create(
                instrument=instrument,
                direction=SetupEvent.Direction.LONG,
                sweep_h1_timestamp=entry_at - timedelta(days=index, hours=2),
                detector_version=strategy.detector_version,
                dataset_version=dataset,
                strategy_version=strategy,
                sweep_evidence={},
                bias_evidence={},
                provisional_swing_evidence={},
                threshold_evidence={},
                attribution_keys=[level.stable_key],
                evidence_hash=str(index + 3) * 64,
            )
            SetupLevelAttribution.objects.create(setup=terminal_setup, level=level)
            SetupTransition.objects.create(
                setup=terminal_setup,
                from_state=SetupTransition.State.TRIGGER_PENDING,
                to_state=terminal,
                effective_at=entry_at - timedelta(days=index, hours=1),
                reason=terminal,
                evidence_hash=str(index + 4) * 64,
                strategy_version=strategy,
                dataset_version=dataset,
                execution_identity=strategy.execution_identity,
            )
        for index, (sweep_at, confirmed_at) in enumerate(
            (
                (
                    datetime(2009, 12, 20, 12, tzinfo=UTC),
                    datetime(2009, 12, 20, 13, tzinfo=UTC),
                ),
                (
                    datetime(2019, 1, 2, 12, tzinfo=UTC),
                    datetime(2019, 1, 2, 13, tzinfo=UTC),
                ),
            )
        ):
            excluded = SetupEvent.objects.create(
                instrument=instrument,
                direction=SetupEvent.Direction.LONG,
                sweep_h1_timestamp=sweep_at,
                detector_version=strategy.detector_version,
                dataset_version=dataset,
                strategy_version=strategy,
                sweep_evidence={},
                bias_evidence={},
                provisional_swing_evidence={},
                threshold_evidence={},
                evidence_hash=str(index + 1) * 64,
            )
            SetupTransition.objects.create(
                setup=excluded,
                from_state=SetupTransition.State.TRIGGER_PENDING,
                to_state=SetupTransition.State.CONFIRMED,
                effective_at=confirmed_at,
                evidence_hash=str(index + 2) * 64,
                strategy_version=strategy,
                dataset_version=dataset,
                execution_identity=strategy.execution_identity,
            )

        with self.assertRaises(DatasetQualityError):
            run_s1(
                dataset_id=dataset.pk,
                strategy_version_id=strategy.pk,
                s0_job_id=s0_job.pk,
                detector_job_id=0,
                maximum_setups=1,
                as_of=as_of,
            )

        detector = type("Detector", (), {"pk": 17})()
        with (
            patch("research.signal_count.assert_dataset_window_usable"),
            patch(
                "research.signal_count._validate_detector_coverage",
                return_value=(detector, "d" * 64),
            ),
        ):
            output = run_s1(
                dataset_id=dataset.pk,
                strategy_version_id=strategy.pk,
                s0_job_id=s0_job.pk,
                detector_job_id=detector.pk,
                maximum_setups=1,
                as_of=as_of,
            )
            replay = run_s1(
                dataset_id=dataset.pk,
                strategy_version_id=strategy.pk,
                s0_job_id=s0_job.pk,
                detector_job_id=detector.pk,
                maximum_setups=1,
                as_of=as_of,
            )

        self.assertEqual(output.counts["physical_setups_processed"], 1)
        self.assertEqual(output.counts["sweeps"], 4)
        self.assertEqual(output.counts["confirmations"], 1)
        self.assertEqual(output.counts["attributions"], 4)
        self.assertEqual(output.counts["setup_invalidated"], 1)
        self.assertEqual(output.counts["setup_expired"], 1)
        self.assertEqual(output.counts["setup_cancelled_data_quality"], 1)
        self.assertEqual(output.counts["eligibility_evaluations_processed"], 2)
        self.assertEqual(output.counts["entry_eligible"], 1)
        self.assertEqual(output.coverage["by_confirmation_year"], {"2018": 1})
        self.assertEqual(output.coverage["entry_projections_read"], 1)
        self.assertEqual(output.coverage["by_pair"], {"EUR_USD": 1})
        self.assertEqual(output.coverage["data_quality_coverage"]["analysis_data_incomplete"], 0)
        self.assertTrue(output.coverage["complete"])
        self.assertEqual(replay.report_sha256, output.report_sha256)
        job = JobRun.objects.get(job_name="failed-break-signal-count-s1")
        self.assertEqual(job.evidence["report"]["report_sha256"], output.report_sha256)
        self.assertEqual(JobRun.objects.filter(job_name="failed-break-signal-count-s1").count(), 1)

        sibling_strategy = StrategyVersion.objects.create(
            definition=definition,
            version="sibling-detector-consumer",
            detector_version=strategy.detector_version,
            data_identity="data",
            event_identity="sibling-event",
            execution_identity="execution-h1-stop-first-v1",
            cost_identity="cost",
            portfolio_identity="portfolio",
            content_hash="f" * 64,
        )
        AnalysisRun.objects.create(
            instrument=instrument,
            completed_h1_timestamp=entry_at - timedelta(days=4),
            detector_version=strategy.detector_version,
            strategy_version=sibling_strategy,
            dataset_version=dataset,
            result=AnalysisRun.Result.DATA_INCOMPLETE,
            evidence_hash="e" * 64,
        )
        self.assertEqual(_analysis_data_incomplete_count(dataset, strategy), 1)

        second = SetupEvent.objects.create(
            instrument=instrument,
            direction=SetupEvent.Direction.LONG,
            sweep_h1_timestamp=entry_at + timedelta(days=1, hours=-2),
            detector_version=strategy.detector_version,
            dataset_version=dataset,
            strategy_version=strategy,
            sweep_evidence={},
            bias_evidence={},
            provisional_swing_evidence={},
            threshold_evidence={},
            attribution_keys=[level.stable_key],
            evidence_hash="b" * 64,
        )
        SetupLevelAttribution.objects.create(setup=second, level=level)
        SetupTransition.objects.create(
            setup=second,
            from_state=SetupTransition.State.TRIGGER_PENDING,
            to_state=SetupTransition.State.CONFIRMED,
            effective_at=entry_at + timedelta(days=1),
            evidence_hash="c" * 64,
            strategy_version=strategy,
            dataset_version=dataset,
            execution_identity=strategy.execution_identity,
        )
        for index, book in enumerate(
            ("failed-break-any-level-deduplicated-v1", "failed-break-weekly-extreme-v1")
        ):
            SetupTransition.objects.create(
                setup=second,
                book_identity=book,
                from_state=SetupTransition.State.CONFIRMED,
                to_state=SetupTransition.State.NO_TARGET,
                effective_at=entry_at + timedelta(days=1),
                reason="NO_ACTIVE_OPPOSING_LEVEL",
                evidence_hash=str(index + 5) * 64,
                strategy_version=strategy,
                dataset_version=dataset,
                execution_identity=strategy.execution_identity,
            )
            EntryEligibilityEvaluation.objects.create(
                setup=second,
                book_identity=book,
                decision=EntryEligibilityEvaluation.Decision.NO_TARGET,
                terminal_reason="NO_ACTIVE_OPPOSING_LEVEL",
                evidence_hash=str(index + 7) * 64,
            )
        with (
            patch("research.signal_count.assert_dataset_window_usable"),
            patch(
                "research.signal_count._validate_detector_coverage",
                return_value=(detector, "d" * 64),
            ),
            self.assertRaisesMessage(ReturnBlindViolation, "would truncate"),
        ):
            run_s1(
                dataset_id=dataset.pk,
                strategy_version_id=strategy.pk,
                s0_job_id=s0_job.pk,
                detector_job_id=detector.pk,
                maximum_setups=1,
                as_of=as_of,
            )

        incomplete = SetupEvent.objects.create(
            instrument=instrument,
            direction=SetupEvent.Direction.LONG,
            sweep_h1_timestamp=entry_at + timedelta(days=2, hours=-2),
            detector_version=strategy.detector_version,
            dataset_version=dataset,
            strategy_version=strategy,
            sweep_evidence={},
            bias_evidence={},
            provisional_swing_evidence={},
            threshold_evidence={},
            attribution_keys=[level.stable_key],
            evidence_hash="d" * 64,
        )
        SetupLevelAttribution.objects.create(setup=incomplete, level=level)
        SetupTransition.objects.create(
            setup=incomplete,
            from_state=SetupTransition.State.TRIGGER_PENDING,
            to_state=SetupTransition.State.CONFIRMED,
            effective_at=entry_at + timedelta(days=2, hours=-1),
            evidence_hash="e" * 64,
            strategy_version=strategy,
            dataset_version=dataset,
            execution_identity=strategy.execution_identity,
        )
        with (
            patch("research.signal_count.assert_dataset_window_usable"),
            patch(
                "research.signal_count._validate_detector_coverage",
                return_value=(detector, "d" * 64),
            ),
            self.assertRaisesMessage(ReturnBlindViolation, "lifecycle is incomplete"),
        ):
            run_s1(
                dataset_id=dataset.pk,
                strategy_version_id=strategy.pk,
                s0_job_id=s0_job.pk,
                detector_job_id=detector.pk,
                maximum_setups=10,
                as_of=as_of,
            )

        job.evidence = {"report_sha256": "tampered"}
        with self.assertRaisesMessage(ValidationError, "immutable"):
            job.save()

    def test_s1_evaluation_query_projects_no_frozen_price_risk_or_evidence_fields(self):
        sql = str(_s1_evaluation_queryset([0]).query)

        for forbidden_column in (
            "stop_price",
            "target_price",
            "reward_risk",
            "risk_per_unit_quote",
            "conversion_rate_to_cad",
            "risk_per_unit_cad",
            "evidence",
        ):
            with self.subTest(forbidden_column=forbidden_column):
                self.assertNotIn(forbidden_column, sql)
