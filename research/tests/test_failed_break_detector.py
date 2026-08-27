from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase

from market.models import DatasetVersion, Instrument, SourceRegistry
from market.oanda import CandleData
from market.quality import expected_candle_timestamps
from market.services import RequiredCandleRange, store_ingestion
from research.failed_break_detector import _assert_complete_setup_lifecycle, run_s1_detector
from research.models import (
    AnalysisRun,
    EntryEligibilityEvaluation,
    JobRun,
    Level,
    SetupEvent,
    StrategyDefinition,
    StrategyVersion,
)
from research.signal_count import (
    FROZEN_INSTRUMENTS,
    PHASE1_MANIFEST_SHA256,
    S1_DETECTOR_JOB_NAME,
    ReturnBlindViolation,
    _validate_detector_coverage,
    expected_analysis_keys,
    run_s1,
    stable_hash,
)


def _candle(timestamp, midpoint, *, high=None, low=None, spread="0.0002"):
    midpoint = Decimal(midpoint)
    high = Decimal(high if high is not None else midpoint + Decimal("0.001"))
    low = Decimal(low if low is not None else midpoint - Decimal("0.001"))
    half = Decimal(spread) / 2
    return CandleData(
        timestamp=timestamp,
        complete=True,
        volume=100,
        bid_open=midpoint - half,
        bid_high=high - half,
        bid_low=low - half,
        bid_close=midpoint - half,
        ask_open=midpoint + half,
        ask_high=high + half,
        ask_low=low + half,
        ask_close=midpoint + half,
    )


class BoundedS1DetectorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceRegistry.objects.create(
            name="bounded-detector-fixture",
            tier=SourceRegistry.Tier.QUARANTINE,
            base_url="https://example.invalid",
            acquisition_method="bounded deterministic test fixture",
            retention_policy="test only",
        )
        currencies = {
            "EUR_USD": ("EUR", "USD"),
            "GBP_USD": ("GBP", "USD"),
            "EUR_GBP": ("EUR", "GBP"),
            "USD_CAD": ("USD", "CAD"),
            "USD_JPY": ("USD", "JPY"),
            "AUD_USD": ("AUD", "USD"),
        }
        cls.instruments = {
            code: Instrument.objects.create(
                code=code,
                base_currency=currencies[code][0],
                quote_currency=currencies[code][1],
                display_order=index,
            )
            for index, code in enumerate(sorted(FROZEN_INSTRUMENTS), start=1)
        }
        cls.range_specs = (
            ("W", datetime(2009, 12, 18, 22, tzinfo=UTC), datetime(2010, 1, 1, 22, tzinfo=UTC)),
            ("D", datetime(2009, 1, 4, 22, tzinfo=UTC), datetime(2010, 1, 5, 22, tzinfo=UTC)),
            ("H1", datetime(2009, 12, 31, 12, tzinfo=UTC), datetime(2010, 1, 5, 22, tzinfo=UTC)),
        )
        cls.dataset = DatasetVersion.objects.create(
            name="bounded-detector",
            version="1",
            source=cls.source,
            manifest={"fixture": "bounded-detector"},
        )
        cls.ranges = {
            code: tuple(
                RequiredCandleRange(granularity, start, end)
                for granularity, start, end in cls.range_specs
            )
            for code in FROZEN_INSTRUMENTS
        }
        for code, instrument in cls.instruments.items():
            for granularity, start, end in cls.range_specs:
                timestamps = expected_candle_timestamps(start, end, granularity)
                rows = cls._rows(code, granularity, timestamps)
                store_ingestion(
                    cls.source,
                    instrument,
                    granularity,
                    start,
                    end,
                    rows,
                    {"instrument": code, "granularity": granularity},
                    dataset_version=cls.dataset,
                )
        definition = StrategyDefinition.objects.create(
            key="bounded-detector", name="Bounded detector"
        )
        cls.strategy = StrategyVersion.objects.create(
            definition=definition,
            version="1",
            detector_version="failed-break-detector-bounded-v1",
            data_identity="data",
            event_identity="event",
            execution_identity="execution-h1-stop-first-v1",
            cost_identity="cost",
            portfolio_identity="portfolio",
            pair_metadata={"instruments": sorted(FROZEN_INSTRUMENTS)},
            content_hash=PHASE1_MANIFEST_SHA256,
        )
        cls.as_of = datetime(2010, 1, 5, 22, tzinfo=UTC)
        cls.s0_output = SimpleNamespace(
            report_sha256="a" * 64,
            counts={"observations": 1},
            coverage={
                "spread_ceilings": {code: "0.001" for code in FROZEN_INSTRUMENTS},
                "missingness": {
                    code: {granularity: 0 for granularity in ("W", "D", "H1")}
                    for code in FROZEN_INSTRUMENTS
                },
            },
        )

    @classmethod
    def _rows(cls, code, granularity, timestamps):
        if granularity == "W":
            return [_candle(timestamp, "1.05", high="1.08", low="1.02") for timestamp in timestamps]
        if granularity == "D":
            if code != "EUR_USD":
                return [_candle(timestamp, "1.05") for timestamp in timestamps]
            waves = tuple(
                map(Decimal, ("0", "0.003", "0.006", "0.003", "0", "-0.003", "-0.006", "-0.003"))
            )
            return [
                _candle(
                    timestamp, Decimal("1") + Decimal(index) * Decimal("0.0001") + waves[index % 8]
                )
                for index, timestamp in enumerate(timestamps)
            ]
        rows = [_candle(timestamp, "1.03") for timestamp in timestamps]
        if code != "EUR_USD":
            return rows
        sweep_index = next(
            index
            for index, timestamp in enumerate(timestamps)
            if timestamp.astimezone(ZoneInfo("America/New_York")).weekday() == 0
            and timestamp.astimezone(ZoneInfo("America/New_York")).hour == 10
        )
        rows[sweep_index - 1] = _candle(timestamps[sweep_index - 1], "1.021")
        rows[sweep_index] = _candle(timestamps[sweep_index], "1.021", high="1.024", low="1.018")
        rows[sweep_index + 1] = _candle(timestamps[sweep_index + 1], "1.025")
        rows[sweep_index + 2] = _candle(timestamps[sweep_index + 2], "1.025")
        return rows

    def _fake_detector_job(self, *, omit_analysis=0):
        expected = expected_analysis_keys(self.ranges)
        observed = expected[:-omit_analysis] if omit_analysis else expected
        AnalysisRun.objects.bulk_create(
            AnalysisRun(
                instrument=self.instruments[code],
                completed_h1_timestamp=datetime.fromisoformat(timestamp),
                detector_version=self.strategy.detector_version,
                strategy_version=self.strategy,
                dataset_version=self.dataset,
                result=AnalysisRun.Result.NO_SETUP,
                evidence_hash="0" * 64,
            )
            for code, timestamp in observed
        )
        configuration = {
            "identity": S1_DETECTOR_JOB_NAME,
            "dataset_id": self.dataset.pk,
            "dataset_manifest_sha256": self.dataset.manifest_sha256,
            "strategy_version_id": self.strategy.pk,
            "strategy_content_hash": self.strategy.content_hash,
            "detector_version": self.strategy.detector_version,
            "s0_job_id": 1,
            "s0_report_sha256": self.s0_output.report_sha256,
            "as_of": self.as_of.isoformat(),
        }
        report_body = {
            "expected_analysis_count": len(expected),
            "expected_analysis_sha256": stable_hash(expected),
            "observed_analysis_count": len(observed),
            "observed_analysis_sha256": stable_hash(observed),
        }
        report = {**report_body, "report_sha256": stable_hash(report_body)}
        return JobRun.objects.create(
            job_name=S1_DETECTOR_JOB_NAME,
            strategy_version=self.strategy,
            dataset_version=self.dataset,
            config_hash=stable_hash(configuration),
            idempotency_key=f"fake-detector-{omit_analysis}",
            as_of=self.as_of,
            status=JobRun.Status.SUCCEEDED,
            evidence={"configuration": configuration, "report": report},
        )

    def test_zero_or_missing_analysis_cannot_verify_as_complete(self):
        expected = expected_analysis_keys(self.ranges)
        configuration = {
            "identity": S1_DETECTOR_JOB_NAME,
            "dataset_id": self.dataset.pk,
            "dataset_manifest_sha256": self.dataset.manifest_sha256,
            "strategy_version_id": self.strategy.pk,
            "strategy_content_hash": self.strategy.content_hash,
            "detector_version": self.strategy.detector_version,
            "s0_job_id": 1,
            "s0_report_sha256": self.s0_output.report_sha256,
            "as_of": self.as_of.isoformat(),
        }
        report_body = {
            "expected_analysis_count": len(expected),
            "expected_analysis_sha256": stable_hash(expected),
            "observed_analysis_count": 0,
            "observed_analysis_sha256": stable_hash(()),
        }
        report = {**report_body, "report_sha256": stable_hash(report_body)}
        job = JobRun.objects.create(
            job_name=S1_DETECTOR_JOB_NAME,
            strategy_version=self.strategy,
            dataset_version=self.dataset,
            config_hash=stable_hash(configuration),
            idempotency_key="zero-analysis",
            as_of=self.as_of,
            status=JobRun.Status.SUCCEEDED,
            evidence={"configuration": configuration, "report": report},
        )
        with self.assertRaisesMessage(ReturnBlindViolation, "coverage is incomplete"):
            _validate_detector_coverage(
                detector_job_id=job.pk,
                dataset=self.dataset,
                strategy=self.strategy,
                ranges_by_instrument=self.ranges,
                s0_job_id=1,
                s0_report_sha256=self.s0_output.report_sha256,
                as_of=self.as_of,
            )

    def test_one_missing_instrument_h1_analysis_fails_closed(self):
        job = self._fake_detector_job(omit_analysis=1)
        with self.assertRaisesMessage(ReturnBlindViolation, "coverage is incomplete"):
            _validate_detector_coverage(
                detector_job_id=job.pk,
                dataset=self.dataset,
                strategy=self.strategy,
                ranges_by_instrument=self.ranges,
                s0_job_id=1,
                s0_report_sha256=self.s0_output.report_sha256,
                as_of=self.as_of,
            )

    def test_detector_audit_cannot_be_reused_by_another_registered_identity(self):
        job = self._fake_detector_job()
        sibling = StrategyVersion.objects.create(
            definition=self.strategy.definition,
            version="mismatched-detector",
            detector_version="another-detector",
            data_identity="data",
            event_identity="event",
            execution_identity="execution-h1-stop-first-v1",
            cost_identity="cost",
            portfolio_identity="portfolio",
            content_hash="8" * 64,
        )
        with self.assertRaisesMessage(ReturnBlindViolation, "registered detector JobRun"):
            _validate_detector_coverage(
                detector_job_id=job.pk,
                dataset=self.dataset,
                strategy=sibling,
                ranges_by_instrument=self.ranges,
                s0_job_id=1,
                s0_report_sha256=self.s0_output.report_sha256,
                as_of=self.as_of,
            )

    def test_unresolved_trigger_pending_setup_fails_detector_lifecycle(self):
        SetupEvent.objects.create(
            instrument=self.instruments["EUR_USD"],
            direction=SetupEvent.Direction.LONG,
            sweep_h1_timestamp=datetime(2010, 1, 4, 15, tzinfo=UTC),
            detector_version=self.strategy.detector_version,
            dataset_version=self.dataset,
            strategy_version=self.strategy,
            sweep_evidence={},
            bias_evidence={},
            provisional_swing_evidence={},
            threshold_evidence={},
            evidence_hash="7" * 64,
        )
        with self.assertRaisesMessage(ValueError, "TRIGGER_PENDING"):
            _assert_complete_setup_lifecycle(self.dataset, self.strategy)

    def test_bounded_detector_builds_and_replays_complete_return_blind_chain(self):
        with patch(
            "research.failed_break_detector._validate_s1_contract",
            return_value=(self.ranges, self.s0_output),
        ):
            detector_job = run_s1_detector(
                dataset_id=self.dataset.pk,
                strategy_version_id=self.strategy.pk,
                s0_job_id=1,
                as_of=self.as_of,
            )
            replay = run_s1_detector(
                dataset_id=self.dataset.pk,
                strategy_version_id=self.strategy.pk,
                s0_job_id=1,
                as_of=self.as_of,
            )
        self.assertEqual(replay.pk, detector_job.pk)
        self.assertEqual(
            detector_job.evidence["report"]["report_sha256"],
            replay.evidence["report"]["report_sha256"],
        )
        self.assertEqual(AnalysisRun.objects.count(), len(expected_analysis_keys(self.ranges)))
        self.assertTrue(Level.objects.exists())
        self.assertTrue(SetupEvent.objects.exists())
        self.assertTrue(EntryEligibilityEvaluation.objects.exists())

        with (
            patch(
                "research.signal_count._validate_s1_contract",
                return_value=(self.ranges, self.s0_output),
            ),
            patch("research.signal_count.assert_dataset_window_usable"),
        ):
            output = run_s1(
                dataset_id=self.dataset.pk,
                strategy_version_id=self.strategy.pk,
                s0_job_id=1,
                detector_job_id=detector_job.pk,
                maximum_setups=20,
                as_of=self.as_of,
            )
        self.assertTrue(output.coverage["complete"])
        self.assertEqual(output.coverage["detector_job_id"], detector_job.pk)
        self.assertGreater(output.counts["eligibility_evaluations_processed"], 0)

    def test_fully_analyzed_zero_signal_fixture_is_complete(self):
        zero_signal_strategy = StrategyVersion.objects.create(
            definition=self.strategy.definition,
            version="zero-signal",
            detector_version="failed-break-detector-zero-signal-v1",
            data_identity="data",
            event_identity="event",
            execution_identity="execution-h1-stop-first-v1",
            cost_identity="cost",
            portfolio_identity="portfolio",
            pair_metadata={"instruments": sorted(FROZEN_INSTRUMENTS)},
            content_hash="9" * 64,
        )
        with (
            patch(
                "research.failed_break_detector._validate_s1_contract",
                return_value=(self.ranges, self.s0_output),
            ),
            patch("research.failed_break_detector.detect_failed_sweep", return_value=None),
        ):
            detector_job = run_s1_detector(
                dataset_id=self.dataset.pk,
                strategy_version_id=zero_signal_strategy.pk,
                s0_job_id=1,
                as_of=self.as_of,
            )
        self.assertEqual(
            AnalysisRun.objects.filter(strategy_version=zero_signal_strategy).count(),
            len(expected_analysis_keys(self.ranges)),
        )
        self.assertFalse(SetupEvent.objects.filter(strategy_version=zero_signal_strategy).exists())
        with (
            patch(
                "research.signal_count._validate_s1_contract",
                return_value=(self.ranges, self.s0_output),
            ),
            patch("research.signal_count.assert_dataset_window_usable"),
        ):
            output = run_s1(
                dataset_id=self.dataset.pk,
                strategy_version_id=zero_signal_strategy.pk,
                s0_job_id=1,
                detector_job_id=detector_job.pk,
                maximum_setups=1,
                as_of=self.as_of,
            )
        self.assertEqual(output.counts["sweeps"], 0)
        self.assertEqual(output.counts["confirmations"], 0)
        self.assertTrue(output.coverage["complete"])
