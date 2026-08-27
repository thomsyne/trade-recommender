from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from market.models import DatasetVersion, Instrument
from research.failed_break_services import (
    COMBINED_BOOK,
    books_for_setup,
    persist_confirmation,
    persist_entry_evaluation,
    persist_level,
    persist_setup,
)
from research.models import (
    AnalysisRun,
    EntryEligibilityEvaluation,
    Level,
    SetupEvent,
    SetupLevelAttribution,
    SetupTransition,
    StrategyDefinition,
    StrategyParameterManifest,
    StrategyVersion,
)
from research.strategy import (
    Bias,
    Confirmation,
    Context,
    EntryOpen,
    EntryResult,
    Role,
    Side,
    SweepEvent,
    make_level,
)


class StrategyPersistenceTests(TestCase):
    def setUp(self):
        self.at = datetime(2026, 1, 1, tzinfo=UTC)
        self.instrument = Instrument.objects.create(
            code="EUR_USD", base_currency="EUR", quote_currency="USD", display_order=1
        )
        self.dataset = DatasetVersion.objects.create(
            name="candles", version="1", manifest_sha256="0" * 64
        )
        definition = StrategyDefinition.objects.create(key="phase-1", name="Phase 1")
        self.strategy = StrategyVersion.objects.create(
            definition=definition,
            version="1",
            detector_version="detector-1",
            data_identity="data",
            event_identity="event",
            execution_identity="execution",
            cost_identity="cost",
            portfolio_identity="portfolio",
            content_hash="a" * 64,
        )
        self.setup = SetupEvent.objects.create(
            instrument=self.instrument,
            direction=SetupEvent.Direction.LONG,
            sweep_h1_timestamp=self.at,
            detector_version="detector-1",
            dataset_version=self.dataset,
            strategy_version=self.strategy,
            sweep_evidence={},
            bias_evidence={},
            provisional_swing_evidence={},
            threshold_evidence={},
            evidence_hash="b" * 64,
        )
        self.level = Level.objects.create(
            family=Level.Family.WEEKLY,
            role=Level.Role.SUPPORT,
            instrument=self.instrument,
            strategy_version=self.strategy,
            dataset_version=self.dataset,
            source_timeframe="W",
            source_candle_timestamp=self.at,
            central_price=Decimal("1.1"),
            zone_lower=Decimal("1.0"),
            zone_upper=Decimal("1.2"),
            atr_at_activation=Decimal("0.1"),
            activated_at=self.at,
            stable_key="c" * 64,
        )

    def assert_duplicate_rejected(self, model, values):
        model.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.create(**values)

    def test_records_reject_model_save_and_delete(self):
        self.strategy.version = "2"
        with self.assertRaises(ValidationError):
            self.strategy.save()
        with self.assertRaises(ValidationError):
            self.strategy.delete()

    def test_approved_manifest_registration_is_hash_verified_and_idempotent(self):
        call_command("register_failed_break_phase1", verbosity=0)
        call_command("register_failed_break_phase1", verbosity=0)
        registered = StrategyParameterManifest.objects.get(
            phase1_manifest_hash=(
                "f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882"
            )
        )
        self.assertEqual(
            registered.phase1_spec_hash,
            "47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd",
        )
        self.assertEqual(registered.payload["status"], "FROZEN_FOR_REVIEW")

    def test_analysis_setup_attribution_and_transition_idempotency(self):
        self.assert_duplicate_rejected(
            AnalysisRun,
            dict(
                instrument=self.instrument,
                completed_h1_timestamp=self.at,
                strategy_version=self.strategy,
                dataset_version=self.dataset,
                result=AnalysisRun.Result.NO_SETUP,
                evidence_hash="d" * 64,
            ),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SetupEvent.objects.create(
                instrument=self.instrument,
                direction=self.setup.direction,
                sweep_h1_timestamp=self.at,
                detector_version=self.setup.detector_version,
                dataset_version=self.dataset,
                strategy_version=self.strategy,
                sweep_evidence={},
                bias_evidence={},
                provisional_swing_evidence={},
                threshold_evidence={},
                evidence_hash="e" * 64,
            )
        self.assert_duplicate_rejected(
            SetupLevelAttribution, dict(setup=self.setup, level=self.level)
        )
        self.assert_duplicate_rejected(
            SetupTransition,
            dict(
                setup=self.setup,
                from_state=SetupTransition.State.TRIGGER_PENDING,
                to_state=SetupTransition.State.CONFIRMED,
                effective_at=self.at,
                evidence_hash="f" * 64,
            ),
        )

    def test_eligibility_fields_are_enforced_by_database(self):
        invalid = (
            dict(
                decision="MISSED_FILL",
                terminal_reason="no liquidity",
                entry_price=1,
                stop_price=1,
                target_price=1,
            ),
            dict(
                decision="ENTRY_PENDING",
                terminal_reason="",
                entry_price=None,
                stop_price=None,
                target_price=None,
            ),
        )
        for index, values in enumerate(invalid):
            with self.assertRaises(IntegrityError), transaction.atomic():
                EntryEligibilityEvaluation.objects.create(
                    setup=self.setup,
                    book_identity=f"book-{index}",
                    evidence_hash=str(index) * 64,
                    **values,
                )

    def test_duplicate_jobs_create_one_physical_setup_with_multiple_attributions(self):
        context = Context(self.at + timedelta(days=1), "strategy", "dataset")
        specs = [
            make_level(
                key,
                family,
                Role.SUPPORT,
                Decimal("1.1"),
                Decimal("0.1"),
                self.at,
                self.at,
                Decimal("0.00001"),
                context,
            )
            for key, family in (
                ("weekly", Level.Family.WEEKLY),
                ("swing", Level.Family.DAILY_SWING),
            )
        ]
        levels = [
            persist_level(
                instrument=self.instrument,
                strategy_version=self.strategy,
                dataset_version=self.dataset,
                spec=spec,
            )
            for spec in specs
        ]
        event = SweepEvent(
            self.at + timedelta(hours=1),
            Side.LONG,
            tuple(item.stable_key for item in levels),
            Decimal("1.2"),
            Decimal("1.0"),
            Bias.BULLISH,
            Decimal("0.9"),
        )
        evidence = {
            "sweep": {"low": "1.0"},
            "bias": {"value": "bullish"},
            "provisional_swing": {"price": "0.9"},
            "threshold": {"price": "1.2"},
        }
        first = persist_setup(
            instrument=self.instrument,
            strategy_version=self.strategy,
            dataset_version=self.dataset,
            event=event,
            level_attributions=dict(zip(event.level_keys, levels, strict=True)),
            evidence=evidence,
        )
        second = persist_setup(
            instrument=self.instrument,
            strategy_version=self.strategy,
            dataset_version=self.dataset,
            event=event,
            level_attributions=dict(reversed(tuple(zip(event.level_keys, levels, strict=True)))),
            evidence=evidence,
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SetupEvent.objects.count(), 2)  # includes setUp fixture
        self.assertEqual(first.setuplevelattribution_set.count(), 2)
        self.assertEqual(
            set(books_for_setup(first)),
            {
                COMBINED_BOOK,
                "failed-break-weekly-extreme-v1",
                "failed-break-daily-swing-v1",
            },
        )

        confirmed = Confirmation("CONFIRMED", self.at + timedelta(hours=2), Decimal("0.9"))
        transition = persist_confirmation(setup=first, confirmation=confirmed, evidence={})
        self.assertEqual(
            persist_confirmation(setup=first, confirmation=confirmed, evidence={}).pk,
            transition.pk,
        )
        opening = EntryOpen(self.at + timedelta(hours=3), Decimal("1.1"), Decimal("1.1001"))
        result = EntryResult(
            "ENTRY_PENDING",
            "",
            Decimal("1.1001"),
            Decimal("1.0"),
            Decimal("1.4"),
            Decimal("2.99"),
            levels[0].stable_key,
        )
        evaluation = persist_entry_evaluation(
            setup=first,
            book_identity=COMBINED_BOOK,
            result=result,
            opening=opening,
            target_level=levels[0],
            evidence={},
        )
        duplicate = persist_entry_evaluation(
            setup=first,
            book_identity=COMBINED_BOOK,
            result=result,
            opening=opening,
            target_level=levels[0],
            evidence={},
        )
        self.assertEqual(evaluation.pk, duplicate.pk)
        self.assertEqual(
            first.setuptransition_set.filter(to_state=SetupTransition.State.ENTRY_PENDING).count(),
            1,
        )
