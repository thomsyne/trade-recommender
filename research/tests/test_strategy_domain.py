import inspect
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import TestCase

from research.strategy import (
    Bias,
    Candle,
    Context,
    EntryOpen,
    LevelState,
    Lifecycle,
    Pivot,
    Role,
    Side,
    SweepEvent,
    atr14,
    breakout_flip_levels,
    confirm_sweep,
    daily_bias,
    daily_pivots,
    detect_failed_sweep,
    ema,
    entry_eligibility,
    evaluate_level,
    flip_level,
    make_level,
    nearest_opposing_target,
)

D = Decimal
START = datetime(2026, 1, 1, tzinfo=UTC)


def candle(index, close, *, high=None, low=None, spread="0", complete=True, hours=24):
    close = D(str(close))
    high = D(str(high)) if high is not None else close + 1
    low = D(str(low)) if low is not None else close - 1
    spread = D(str(spread))
    opened = START + timedelta(hours=index * hours)
    half = spread / 2
    return Candle(
        opened,
        opened + timedelta(hours=hours),
        close - half,
        high - half,
        low - half,
        close - half,
        close + half,
        high + half,
        low + half,
        close + half,
        complete,
    )


def context(at=None):
    return Context(at or START + timedelta(days=400), "strategy-1", "dataset-1")


def level(key="support", role=Role.SUPPORT, price="10", activated_at=START):
    return make_level(
        key,
        "PREVIOUS_WEEKLY_EXTREME",
        role,
        D(price),
        D("2"),
        activated_at,
        START,
        D("0.01"),
        context(),
    )


def active_states(levels):
    return {item.key: LevelState(Lifecycle.ACTIVE) for item in levels}


class IndicatorTests(TestCase):
    def test_point_in_time_is_deterministic_and_incomplete_or_future_candles_are_excluded(self):
        candles = [candle(i, i + 1) for i in range(4)]
        candles.append(candle(4, 100, complete=False))
        cutoff = candles[3].completed_at
        first = ema(candles, 3, context(cutoff))
        second = ema(tuple(reversed(candles)), 3, context(cutoff))
        self.assertEqual(first, second)
        self.assertEqual([point.value for point in first], [D("2"), D("3")])

    def test_atr_wilder_seed_starts_at_fourteenth_true_range(self):
        candles = [candle(i, 10, high=11, low=9) for i in range(14)]
        self.assertEqual(atr14(candles[:13], context()), ())
        self.assertEqual(atr14(candles, context())[0].value, D("2"))

    def test_strict_pivot_is_delayed_until_second_later_completion(self):
        candles = [candle(i, 5, high=v, low=1) for i, v in enumerate([2, 3, 9, 4, 3])]
        before = context(candles[3].completed_at)
        after = context(candles[4].completed_at)
        self.assertEqual(daily_pivots(candles, before), ())
        pivots = daily_pivots(candles, after)
        self.assertEqual(pivots[0].available_at, candles[4].completed_at)

    def test_bias_requires_ema_and_structure_and_h4_is_not_an_input(self):
        candles = [candle(i, 100 + i) for i in range(221)]
        pivots = (
            Pivot(candles[100].opened_at, candles[102].completed_at, D("180"), "high"),
            Pivot(candles[110].opened_at, candles[112].completed_at, D("160"), "low"),
            Pivot(candles[150].opened_at, candles[152].completed_at, D("230"), "high"),
            Pivot(candles[160].opened_at, candles[162].completed_at, D("200"), "low"),
        )
        self.assertEqual(daily_bias(candles, pivots, context()), Bias.BULLISH)
        self.assertNotIn("h4", inspect.signature(daily_bias).parameters)


class LevelTests(TestCase):
    def test_level_never_activates_retroactively_and_zone_is_frozen(self):
        with self.assertRaises(ValueError):
            make_level(
                "future",
                "CONFIRMED_DAILY_SWING",
                Role.SUPPORT,
                D("10"),
                D("2"),
                START + timedelta(days=2),
                START,
                D("0.01"),
                context(START + timedelta(days=1)),
            )
        frozen = level()
        self.assertEqual((frozen.zone_lower, frozen.zone_upper), (D("9.85"), D("10.15")))
        with self.assertRaises(FrozenInstanceError):
            frozen.zone_lower = D("0")

    def test_role_flip_is_new_instance_with_new_frozen_zone(self):
        source = level()
        crossing = candle(2, "9.9", high="10", low="9.8")
        state = evaluate_level(source, [crossing], context())
        flipped = flip_level(source, crossing, D("4"), D("0.01"), context())
        self.assertEqual(state.state, Lifecycle.SUPERSEDED_BY_FLIP)
        self.assertEqual(flipped.role, Role.RESISTANCE)
        self.assertNotEqual(flipped.key, source.key)
        self.assertEqual((flipped.zone_lower, flipped.zone_upper), (D("9.70"), D("10.30")))

    def test_target_inventory_is_bias_independent_and_uses_boundary_and_tie_priority(self):
        weekly = level("w", Role.RESISTANCE, "13")
        swing = make_level(
            "s",
            "CONFIRMED_DAILY_SWING",
            Role.RESISTANCE,
            D("13"),
            D("2"),
            START,
            START,
            D("0.01"),
            context(),
        )
        levels = [swing, weekly]
        target = nearest_opposing_target(
            D("10"), Side.LONG, levels, context(), level_states=active_states(levels)
        )
        self.assertEqual(target.key, "w")
        self.assertEqual(target.zone_lower, D("12.85"))

    def test_target_inventory_excludes_every_inactive_lifecycle_state(self):
        targets = [
            level(state.value, Role.RESISTANCE, str(13 + index))
            for index, state in enumerate(Lifecycle)
        ]
        states = {item.key: LevelState(Lifecycle(item.key)) for item in targets}
        selected = nearest_opposing_target(
            D("10"), Side.LONG, targets, context(), level_states=states
        )
        self.assertEqual(selected.key, Lifecycle.ACTIVE.value)

    def test_breakout_activates_at_breakout_close_and_expires_after_twenty_subsequent_sessions(
        self,
    ):
        daily = [candle(i, "10", high="11", low="9") for i in range(20)]
        breakout = candle(20, "12", high="12.5", low="10")
        daily.append(breakout)
        created = breakout_flip_levels(daily, {breakout.completed_at: D("2")}, D("0.01"), context())
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].activated_at, breakout.completed_at)
        following = [candle(i, "11", high="11.5", low="10.5") for i in range(21, 41)]
        state = evaluate_level(created[0], [breakout, *following], context())
        self.assertEqual(
            (state.state, state.effective_at), (Lifecycle.EXPIRED, following[-1].completed_at)
        )

    def test_weekly_expiry_precedes_same_timestamp_role_flip(self):
        expiring = level()
        crossing = candle(2, "9.9", high="10", low="9.8")
        expiring = make_level(
            expiring.key,
            expiring.family,
            expiring.role,
            expiring.central_price,
            expiring.atr_at_activation,
            expiring.activated_at,
            expiring.source_at,
            D("0.01"),
            context(),
            expires_at=crossing.completed_at,
        )
        self.assertEqual(evaluate_level(expiring, [crossing], context()).state, Lifecycle.EXPIRED)


class SetupTests(TestCase):
    def test_spread_only_movement_cannot_sweep_and_overlap_is_one_event(self):
        levels = [level("a"), level("b")]
        previous = candle(0, "10.1", high="10.2", low="10", hours=1)
        spread_only = candle(1, "10", high="10.1", low="9.9", spread="0.4", hours=1)
        self.assertIsNone(
            detect_failed_sweep(previous, spread_only, levels, Bias.BULLISH, D("9"), context())
        )
        swept = candle(1, "10", high="10.4", low="9.8", hours=1)
        event = detect_failed_sweep(previous, swept, levels, Bias.BULLISH, D("9"), context())
        self.assertEqual(event.level_keys, ("a", "b"))
        self.assertEqual(event.confirmation_threshold, swept.high)

    def test_neutral_sweep_never_becomes_retroactive_setup(self):
        previous = candle(0, "10.1", hours=1)
        swept = candle(1, "10", high="10.4", low="9.8", hours=1)
        self.assertIsNone(
            detect_failed_sweep(previous, swept, [level()], Bias.NEUTRAL, D("9"), context())
        )

    def test_three_h1_window_is_exact_and_frozen_threshold_is_used(self):
        event = SweepEvent(START, Side.LONG, ("a",), D("11"), D("9"), Bias.BULLISH, D("8"))
        bars = [candle(i, "10.9", high="20", low="9", hours=1) for i in range(4)]
        result = confirm_sweep(event, bars, [], context(), attributed_level_inactive_at={"a": None})
        self.assertEqual((result.state, result.at), ("EXPIRED", bars[2].completed_at))

    def test_sweep_bias_is_frozen_and_daily_invalidation_precedes_confirmation(self):
        event = SweepEvent(START, Side.LONG, ("a",), D("11"), D("9"), Bias.BULLISH, D("8"))
        confirmation = candle(0, "11.1", high="12", low="9", hours=1)
        invalidating_daily = candle(0, "7.9", high="9", low="7", hours=1)
        self.assertEqual(event.frozen_bias, Bias.BULLISH)
        result = confirm_sweep(
            event,
            [confirmation],
            [invalidating_daily],
            context(),
            attributed_level_inactive_at={"a": None},
        )
        self.assertEqual(result.state, "INVALIDATED")

    def test_confirmation_freezes_latest_still_valid_supporting_swing(self):
        event = SweepEvent(START, Side.LONG, ("a",), D("11"), D("9"), Bias.BULLISH, D("8"))
        confirmation = candle(0, "11.1", high="12", low="9", hours=1)
        new_swing = Pivot(START, START + timedelta(hours=1), D("8.5"), "low")
        result = confirm_sweep(
            event,
            [confirmation],
            [],
            context(),
            attributed_level_inactive_at={"a": None},
            supporting_swings=[new_swing],
        )
        self.assertEqual((result.state, result.supporting_swing), ("CONFIRMED", D("8.5")))

    def test_pending_setup_invalidates_only_when_every_attributed_level_is_inactive(self):
        event = SweepEvent(START, Side.LONG, ("a", "b"), D("11"), D("9"), Bias.BULLISH, D("8"))
        confirmation = candle(0, "11.1", high="12", low="9", hours=1)
        still_active = confirm_sweep(
            event,
            [confirmation],
            [],
            context(),
            attributed_level_inactive_at={"a": START + timedelta(hours=1), "b": None},
        )
        inactive = confirm_sweep(
            event,
            [confirmation],
            [],
            context(),
            attributed_level_inactive_at={
                "a": START + timedelta(hours=1),
                "b": START + timedelta(hours=1),
            },
        )
        self.assertEqual(still_active.state, "CONFIRMED")
        self.assertEqual(inactive.state, "INVALIDATED")

    def test_confirmation_fails_closed_for_missing_level_state_or_h1_gap(self):
        event = SweepEvent(START, Side.LONG, ("a", "b"), D("11"), D("9"), Bias.BULLISH, D("8"))
        next_bar = candle(0, "11.1", hours=1)
        missing_level = confirm_sweep(
            event,
            [next_bar],
            [],
            context(),
            attributed_level_inactive_at={"a": None},
        )
        gap = confirm_sweep(
            event,
            [candle(1, "11.1", hours=1)],
            [],
            context(),
            attributed_level_inactive_at={"a": None, "b": None},
        )
        self.assertEqual(missing_level.state, "CANCELLED_DATA_QUALITY")
        self.assertEqual(gap.state, "CANCELLED_DATA_QUALITY")


class EntryTests(TestCase):
    def event(self, side=Side.LONG):
        sweep_extreme = D("9") if side == Side.LONG else D("11")
        return SweepEvent(START, side, ("a",), D("11"), sweep_extreme, Bias.BULLISH, D("8"))

    def target(self, role=Role.RESISTANCE, price="13"):
        return level("target", role, price)

    def eligibility_kwargs(self, levels, expected_entry_timestamp):
        return {
            "expected_entry_timestamp": expected_entry_timestamp,
            "precision": D("0.01"),
            "absolute_spread_ceiling": D("0.2"),
            "level_states": active_states(levels),
            "cad_conversion_rate": D("1.35"),
            "conversion_effective_at": expected_entry_timestamp,
            "conversion_identity": "USD_CAD@entry",
        }

    def test_correct_side_aware_next_open_and_frozen_prices(self):
        opening = EntryOpen(START + timedelta(hours=1), D("10"), D("10.1"))
        targets = [self.target()]
        result = entry_eligibility(
            self.event(),
            opening,
            D("1"),
            targets,
            context(),
            **self.eligibility_kwargs(targets, opening.timestamp),
            session_eligible=True,
        )
        self.assertEqual(result.decision, "ENTRY_PENDING")
        self.assertEqual(
            (result.entry, result.stop, result.target), (D("10.1"), D("8.9"), D("12.85"))
        )
        self.assertEqual(result.risk_per_unit_quote, D("1.2"))
        self.assertEqual(result.risk_per_unit_cad, D("1.620"))

    def test_terminal_guard_precedence_and_blocked_results_hide_prices(self):
        opening = EntryOpen(START + timedelta(hours=1), D("10"), D("10.5"))
        result = entry_eligibility(
            self.event(),
            opening,
            D("1"),
            [],
            context(),
            **self.eligibility_kwargs([], opening.timestamp),
            data_complete=False,
            session_eligible=False,
        )
        self.assertEqual(result.decision, "CANCELLED_DATA_QUALITY")
        self.assertIsNone(result.entry)

    def test_short_entry_uses_bid_open(self):
        opening = EntryOpen(START + timedelta(hours=1), D("10"), D("10.1"))
        targets = [self.target(Role.SUPPORT, "7")]
        result = entry_eligibility(
            self.event(Side.SHORT),
            opening,
            D("1"),
            targets,
            context(),
            **self.eligibility_kwargs(targets, opening.timestamp),
            session_eligible=True,
        )
        self.assertEqual((result.decision, result.entry), ("ENTRY_PENDING", D("10")))

    def test_session_precedes_missing_fill_and_spread_precedes_target(self):
        kwargs = dict(
            h1_atr=D("1"),
            levels=[],
            context=context(),
            **self.eligibility_kwargs([], START + timedelta(hours=1)),
        )
        self.assertEqual(
            entry_eligibility(self.event(), None, session_eligible=False, **kwargs).decision,
            "BLOCKED_SESSION",
        )
        opening = EntryOpen(START + timedelta(hours=1), D("10"), D("10.2"))
        self.assertEqual(
            entry_eligibility(self.event(), opening, session_eligible=True, **kwargs).decision,
            "BLOCKED_SPREAD",
        )

    def test_expected_timestamp_session_precedes_missing_quote_without_override(self):
        result = entry_eligibility(
            self.event(),
            None,
            D("1"),
            [],
            context(),
            **self.eligibility_kwargs([], START + timedelta(hours=1)),
        )
        self.assertEqual(result.decision, "BLOCKED_SESSION")

    def test_missing_or_future_conversion_fails_closed(self):
        opening = EntryOpen(START + timedelta(hours=1), D("10"), D("10.1"))
        targets = [self.target()]
        kwargs = self.eligibility_kwargs(targets, opening.timestamp)
        kwargs["cad_conversion_rate"] = None
        result = entry_eligibility(
            self.event(), opening, D("1"), targets, context(), **kwargs, session_eligible=True
        )
        self.assertEqual(result.decision, "CANCELLED_DATA_QUALITY")
