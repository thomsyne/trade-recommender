from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from market.models import DatasetRegistration
from research import failed_break_detector_v2_governance as governance
from research.failed_break_detector_v2 import (
    GRANULARITY_ORDER,
    PHASE_ORDER,
    SUCCESSOR_CONTRACT_SHA256,
    SUCCESSOR_DATA_IDENTITY,
    SUCCESSOR_DATASET_VERSION,
    SUCCESSOR_INVENTORY_SHA256,
    SUCCESSOR_MANIFEST_SHA256,
    DetectorV2EvidenceError,
    IncrementalDailyState,
    SealedHorizonIndex,
    assert_complete_projection,
    completion_stream,
    confirm_sweep_v2,
    drive_admission,
    latest_valid_supporting_swing_v2,
    project_admission,
    reference_completion_stream,
    validate_registered_successor,
)
from research.failed_break_detector_v2_governance import (
    DetectorV2GovernanceRefusal,
    canonical_bytes,
    digest,
    load_v2_policy,
    v2_readiness,
)
from research.strategy import (
    Bias,
    Candle,
    Confirmation,
    Context,
    Pivot,
    Side,
    SweepEvent,
    atr14,
    daily_pivots,
    ema50,
    ema200,
)

ROOT = Path(__file__).resolve().parents[2]


def at(day=1, hour=0):
    return datetime(2015, 1, day, hour, tzinfo=UTC)


def strategy_candle(opened_at, close="1.1000", high=None, low=None, duration=timedelta(days=1)):
    close = Decimal(close)
    high = Decimal(high) if high is not None else close + Decimal("0.0020")
    low = Decimal(low) if low is not None else close - Decimal("0.0020")
    spread = Decimal("0.0002")
    return Candle(
        opened_at=opened_at,
        completed_at=opened_at + duration,
        bid_open=close - spread,
        bid_high=high - spread,
        bid_low=low - spread,
        bid_close=close - spread,
        ask_open=close + spread,
        ask_high=high + spread,
        ask_low=low + spread,
        ask_close=close + spread,
    )


def sweep(side=Side.LONG, event_at=None):
    return SweepEvent(
        at=event_at or at(6),
        side=side,
        level_keys=("level",),
        confirmation_threshold=Decimal("1.2"),
        sweep_extreme=Decimal("0.9"),
        frozen_bias=Bias.BULLISH,
        provisional_swing=Decimal("0.95"),
    )


class CompletionAdmissionTests(SimpleTestCase):
    def completion(self, granularity, opened_at):
        offsets = {"H1": timedelta(hours=1), "D": timedelta(hours=7), "W": timedelta(hours=9)}
        return opened_at + offsets[granularity]

    def test_d_and_w_without_h1_completion_are_admitted_exactly_once(self):
        inventory = {"H1": (at(2),), "D": (at(1), at(3)), "W": (at(1),)}
        projection = project_admission(completion_stream(inventory, self.completion))
        assert_complete_projection(projection, inventory)
        self.assertEqual(projection.counters["daily_members_admitted"], 2)
        self.assertEqual(projection.counters["weekly_members_admitted"], 1)
        self.assertEqual(projection.analysis_timestamps, (at(2),))
        for granularity in GRANULARITY_ORDER:
            expected_hash = hashlib.sha256(
                json.dumps(
                    [timestamp.isoformat() for timestamp in inventory[granularity]],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            self.assertEqual(projection.membership_sha256[granularity], expected_hash)

    def test_same_completion_uses_frozen_phase_order(self):
        opened = {"H1": at(2, 9), "W": at(1, 1), "D": at(2, 3)}
        inventory = {granularity: (opened[granularity],) for granularity in GRANULARITY_ORDER}
        completion_at = at(2, 10)
        events = completion_stream(inventory, lambda granularity, timestamp: completion_at)
        projection = project_admission(events)
        self.assertEqual(tuple(event.granularity for event in events), GRANULARITY_ORDER)
        self.assertEqual(projection.phase_trace, ((completion_at, PHASE_ORDER),))

    def test_driver_executes_non_h1_state_transition_without_analysis(self):
        inventory = {"H1": (), "D": (at(1),), "W": ()}
        events = completion_stream(inventory, self.completion)
        trace = []
        handlers = {
            phase: (lambda batch, event, phase=phase: trace.append((phase, event)))
            for phase in PHASE_ORDER
        }
        projection = drive_admission(events, handlers)
        self.assertEqual(
            [phase for phase, _ in trace],
            ["ADMIT_D", "UPDATE_DW_LIFECYCLE_BIAS_AND_STRUCTURE"],
        )
        self.assertEqual(projection.analysis_timestamps, ())

    def test_only_h1_creates_analysis_and_weekend_members_are_retained(self):
        saturday = datetime(2015, 1, 3, 12, tzinfo=UTC)
        sunday = datetime(2015, 1, 4, 22, tzinfo=UTC)
        inventory = {"H1": (saturday, sunday), "D": (at(2),), "W": (at(1),)}
        projection = project_admission(completion_stream(inventory, self.completion))
        self.assertEqual(projection.analysis_timestamps, (saturday, sunday))
        self.assertEqual(projection.counters["analysis_runs_projected"], 2)

    def test_missing_or_substituted_member_fails_closed(self):
        inventory = {"H1": (at(2),), "D": (at(1),), "W": (at(1),)}
        projection = project_admission(completion_stream(inventory, self.completion))
        changed = {**inventory, "D": (at(3),)}
        with self.assertRaisesRegex(DetectorV2EvidenceError, "D projection"):
            assert_complete_projection(projection, changed)

        missing = project_admission(
            tuple(
                event
                for event in completion_stream(inventory, self.completion)
                if event.granularity != "D"
            )
        )
        with self.assertRaisesRegex(DetectorV2EvidenceError, "D projection"):
            assert_complete_projection(missing, inventory)

        extra = project_admission(
            completion_stream({**inventory, "D": (at(1), at(3))}, self.completion)
        )
        with self.assertRaisesRegex(DetectorV2EvidenceError, "D projection"):
            assert_complete_projection(extra, inventory)

        with self.assertRaisesRegex(DetectorV2EvidenceError, "not unique"):
            completion_stream({**inventory, "D": (at(1), at(1))}, self.completion)

    def test_reference_and_optimized_streams_are_identical(self):
        inventory = {
            "H1": tuple(at(day, hour) for day in range(1, 12) for hour in (0, 7, 19)),
            "D": tuple(at(day, 17) for day in range(1, 12)),
            "W": (at(1, 17), at(8, 17)),
        }
        reference = reference_completion_stream(inventory, self.completion)
        optimized = completion_stream(inventory, self.completion)
        self.assertEqual(optimized, reference)
        self.assertEqual(project_admission(optimized), project_admission(reference))

    def test_detector_and_b7_share_one_sealed_daily_sequence(self):
        inventory = {
            "H1": tuple(at(day, hour) for day in range(1, 16) for hour in (0, 12)),
            "D": tuple(at(day, 17) for day in (1, 2, 5, 6, 7, 8, 9, 12, 13, 14, 15)),
            "W": (at(1, 17), at(8, 17)),
        }
        projection = project_admission(completion_stream(inventory, self.completion))
        index = SealedHorizonIndex.from_projection(projection)
        self.assertEqual(index.daily_opened_at, projection.admitted_members["D"])
        for entry in projection.analysis_timestamps[:4]:
            self.assertEqual(
                index.maximum_exit_open(entry), index.reference_maximum_exit_open(entry)
            )


class IncrementalIndicatorTests(SimpleTestCase):
    def test_incremental_indicators_match_golden_batch_functions(self):
        candles = tuple(
            strategy_candle(
                at(1) + timedelta(days=index),
                close=str(Decimal("1") + Decimal(index) / Decimal("1000")),
            )
            for index in range(205)
        )
        state = IncrementalDailyState()
        updates = [state.update(candle) for candle in candles]
        context = Context(candles[-1].completed_at, "v2", "fixture")
        self.assertEqual(updates[-1].ema50, ema50(candles, context)[-1].value)
        self.assertEqual(updates[-1].ema200, ema200(candles, context)[-1].value)
        self.assertEqual(updates[-1].atr14, atr14(candles, context)[-1].value)
        incremental_pivots = tuple(pivot for update in updates for pivot in update.new_pivots)
        self.assertEqual(incremental_pivots, daily_pivots(candles, context))


class SupportingSwingV2Tests(SimpleTestCase):
    def test_breach_after_availability_before_sweep_rejects_pivot(self):
        pivot = Pivot(at(1), at(3), Decimal("1.0"), "low")
        daily = (strategy_candle(at(3), close="0.99"),)
        self.assertIsNone(latest_valid_supporting_swing_v2(sweep(), daily, (pivot,), at(8)))

    def test_unbreached_latest_pivot_remains_valid(self):
        older = Pivot(at(1), at(3), Decimal("0.9"), "low")
        latest = Pivot(at(2), at(4), Decimal("1.0"), "low")
        daily = (strategy_candle(at(4), close="1.01"),)
        self.assertEqual(
            latest_valid_supporting_swing_v2(sweep(), daily, (older, latest), at(8)),
            latest,
        )

    def test_confirmation_rejects_breached_pivot_and_preserves_provisional_fallback(self):
        event = sweep()
        pivot = Pivot(at(1), at(3), Decimal("1.0"), "low")
        daily = (strategy_candle(at(3), close="0.99"),)
        confirmation_candle = strategy_candle(at(6), close="1.3", duration=timedelta(hours=1))
        result = confirm_sweep_v2(
            event,
            (confirmation_candle,),
            daily,
            Context(at(7), "v2", "fixture"),
            attributed_level_inactive_at={"level": None},
            sealed_h1_inventory=(at(6),),
            supporting_swings=(pivot,),
        )
        self.assertEqual(result, Confirmation("CONFIRMED", at(6, 1), event.provisional_swing))

    def test_time_and_price_boundaries_are_explicit(self):
        pivot = Pivot(at(1), at(3), Decimal("1.0"), "low")
        at_availability = strategy_candle(at(2), close="0.99")
        price_equal = strategy_candle(at(3), close="1.0")
        self.assertEqual(
            latest_valid_supporting_swing_v2(
                sweep(), (at_availability, price_equal), (pivot,), at(5)
            ),
            pivot,
        )
        at_confirmation = strategy_candle(at(4), close="0.99")
        self.assertIsNone(
            latest_valid_supporting_swing_v2(sweep(), (at_confirmation,), (pivot,), at(5))
        )


class V2GovernanceTests(SimpleTestCase):
    V1_PINS = {
        "research/failed_break_detector.py": "26c1882d6af516b21684e23e18efca16d5e26e999eb830b9373536c2c2c22b34",
        "research/strategy.py": "2a2e80d4fc0ccb39441098e9b9ea22da354dac9b60a28f27e2bd5ce9f9cad07e",
        "research/signal_count.py": "376b3fa5fc1f064f560d0b352f49c90285bd0b2dd741c42813781ffb462ed7b5",
        "research/pre_s1_governance.py": "61d8180139cb18e1f04d87fcc54ffde5825c8e64664f6dc2873de65c7cfac32c",
        "docs/strategy/failed-break/v1/phase-1-freeze-manifest.json": "f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882",
        "docs/strategy/failed-break/v1/s2-exploratory-policy-freeze-v1.json": "4f70ea3c86569de5b54ad3f18d7c1021b6067532ba9fb42b62faf1a0b2676e8c",
    }

    def test_policy_is_hash_bound_and_runtime_authority_remains_blocked(self):
        policy = load_v2_policy()
        readiness = v2_readiness()
        self.assertEqual(policy["strategy"]["identity"], readiness["strategy_identity"])
        self.assertEqual(readiness["strategy_content_sha256"], governance.ARTIFACT_SHA256)
        self.assertEqual(
            readiness["detector_source_sha256"],
            policy["source_sha256"]["research/failed_break_detector_v2.py"],
        )
        self.assertEqual(readiness["status"], "BLOCKED_NO_V2_S0_ACCEPTANCE")
        self.assertFalse(readiness["persistent_runner_exposed"])
        self.assertFalse(readiness["return_execution_authorized"])

    def test_v1_sources_and_artifacts_remain_byte_identical(self):
        for relative_path, expected in self.V1_PINS.items():
            self.assertEqual(
                hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest(), expected
            )

    def test_v2_module_has_no_outcome_or_return_execution_dependencies(self):
        source = (ROOT / "research/failed_break_detector_v2.py").read_text()
        for forbidden in ("TradeReturn", "Backtest", "profit_loss", "drawdown", "outcome"):
            self.assertNotIn(forbidden, source)

    def test_unregistered_successor_fails_closed(self):
        dataset = SimpleNamespace(
            name=SUCCESSOR_DATA_IDENTITY,
            version=SUCCESSOR_DATASET_VERSION,
            manifest_sha256=SUCCESSOR_MANIFEST_SHA256,
            data_contract_sha256=SUCCESSOR_CONTRACT_SHA256,
        )
        contract = SimpleNamespace(
            identity=SUCCESSOR_DATA_IDENTITY,
            sha256=SUCCESSOR_CONTRACT_SHA256,
            global_semantic_inventory_sha256=SUCCESSOR_INVENTORY_SHA256,
        )
        query = mock.Mock()
        query.values.return_value.get.side_effect = DatasetRegistration.DoesNotExist
        with mock.patch(
            "research.failed_break_detector_v2.DatasetRegistration.objects.filter",
            return_value=query,
        ):
            with self.assertRaisesRegex(DetectorV2EvidenceError, "not registered"):
                validate_registered_successor(dataset, contract)

    def test_hash_consistent_semantic_mutation_still_fails_closed(self):
        policy = load_v2_policy()
        policy["admission"]["d_and_w_admission"] = "ONLY_WHEN_H1_COMPLETES"
        body = dict(policy)
        body.pop("v2_policy_sha256")
        changed_policy_sha = digest(body)
        policy["v2_policy_sha256"] = changed_policy_sha
        raw = canonical_bytes(policy) + b"\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mutated.json"
            path.write_bytes(raw)
            with (
                mock.patch.object(governance, "ARTIFACT_PATH", path),
                mock.patch.object(
                    governance,
                    "ARTIFACT_SHA256",
                    hashlib.sha256(raw).hexdigest(),
                ),
                mock.patch.object(governance, "POLICY_SHA256", changed_policy_sha),
                self.assertRaisesRegex(DetectorV2GovernanceRefusal, "admission semantics"),
            ):
                governance.load_v2_policy()
