"""Bounded chronological detector runner for the registered Phase 2A S1 audit."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

from django.db import transaction

from market.models import Candle as MarketCandle
from market.models import DatasetVersion, Instrument
from market.quality import (
    expected_candle_timestamps,
    registered_candle_completion,
    registered_successor,
)
from market.services import (
    assert_dataset_window_usable,
    candle_completion,
    sealed_inventory_membership,
)
from research.failed_break_services import (
    books_for_setup,
    derive_expected_entry_timestamp,
    evidence_hash,
    persist_analysis,
    persist_confirmation,
    persist_entry_evaluation,
    persist_level,
    persist_setup,
)
from research.models import (
    AnalysisRun,
    EntryEligibilityEvaluation,
    JobRun,
    Level,
    LevelLifecycleEvent,
    SetupEvent,
    SetupLevelAttribution,
    SetupTransition,
    StrategyVersion,
)
from research.provider_observed import contract_for_dataset
from research.signal_count import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    FROZEN_INSTRUMENTS,
    PARTITION_BOUNDARY_CENSOR_RULE,
    PIPETTES,
    S1_DETECTOR_JOB_NAME,
    _validate_s1_contract,
    development_candle_range,
    expected_analysis_keys,
    partition_boundary_censorship,
    read_entry_projection,
    stable_hash,
)
from research.strategy import (
    Bias,
    Candle,
    Context,
    EntryOpen,
    LevelSpec,
    LevelState,
    Lifecycle,
    SweepEvent,
    atr14,
    breakout_flip_levels,
    confirm_sweep,
    confirmed_swing_levels,
    daily_bias,
    daily_pivots,
    detect_failed_sweep,
    entry_eligibility,
    evaluate_level,
    flip_level,
    previous_weekly_levels,
    supporting_swing,
)


@dataclass
class _LevelNode:
    spec: LevelSpec
    record: Level | None = None
    state: LevelState = LevelState(Lifecycle.ACTIVE)


@dataclass
class _PendingSetup:
    event: SweepEvent
    setup: SetupEvent


DETECTION_CANDLE_FIELDS = (
    "timestamp",
    "granularity",
    "complete",
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
)


def _strategy_candle(row, contract=None) -> Candle:
    return Candle(
        opened_at=row["timestamp"],
        completed_at=candle_completion(row["timestamp"], row["granularity"], contract),
        bid_open=row["bid_open"],
        bid_high=row["bid_high"],
        bid_low=row["bid_low"],
        bid_close=row["bid_close"],
        ask_open=row["ask_open"],
        ask_high=row["ask_high"],
        ask_low=row["ask_low"],
        ask_close=row["ask_close"],
        complete=row["complete"],
    )


def _read_candles(dataset, instrument, granularity, timestamps, contract=None):
    timestamps = tuple(timestamps)
    if not timestamps:
        return ()
    return tuple(
        _strategy_candle(row, contract)
        for row in MarketCandle.objects.filter(
            dataset_version=dataset,
            instrument=instrument,
            granularity=granularity,
            timestamp__in=timestamps,
        )
        .order_by("timestamp")
        .values(*DETECTION_CANDLE_FIELDS)
    )


def _range_timestamps(ranges, granularity, *, contract=None, instrument=None):
    required = next(required for required in ranges if required.granularity == granularity)
    if contract is not None:
        # Provider-observed v2: schedule membership comes only from the
        # sealed timestamp inventory, never the theoretical calendar.
        return sealed_inventory_membership(
            contract,
            getattr(instrument, "pk", instrument),
            granularity,
            required.start,
            required.end,
        )
    return expected_candle_timestamps(required.start, required.end, granularity)


def _admitted_before(dataset, instrument, ranges, granularity, boundary, *, contract=None):
    timestamps = tuple(
        timestamp
        for timestamp in _range_timestamps(
            ranges, granularity, contract=contract, instrument=instrument
        )
        if candle_completion(timestamp, granularity, contract) < boundary
    )
    return list(_read_candles(dataset, instrument, granularity, timestamps, contract))


def _candle_completing_at(dataset, instrument, schedules, granularity, boundary, contract=None):
    timestamp = schedules[granularity].get(boundary)
    if timestamp is None:
        return None
    rows = _read_candles(dataset, instrument, granularity, (timestamp,), contract)
    if len(rows) != 1:
        raise ValueError(f"registered {granularity} candle is missing at {boundary.isoformat()}")
    return rows[0]


def _context(at, strategy, dataset):
    return Context(at, strategy.content_hash, dataset.manifest_sha256)


def _serializable(value):
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serializable(item) for item in value]
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value


def _setup_evidence(event):
    return {
        "sweep": {
            "completed_at": event.at.isoformat(),
            "side": event.side.value,
            "extreme": str(event.sweep_extreme),
        },
        "bias": {"value": event.frozen_bias.value},
        "provisional_swing": {"price": str(event.provisional_swing)},
        "threshold": {"price": str(event.confirmation_threshold)},
    }


def _persist_lifecycle(node, state):
    evidence = {
        "source_level_key": node.record.stable_key,
        "state": state.state.value,
        "effective_at": state.effective_at.isoformat(),
    }
    event, created = LevelLifecycleEvent.objects.get_or_create(
        level=node.record,
        state=state.state.value,
        effective_at=state.effective_at,
        evidence_hash=evidence_hash(evidence),
        defaults={"evidence": evidence},
    )
    if not created and event.evidence != evidence:
        raise ValueError("level lifecycle key resolved to different immutable evidence")
    node.state = state


def _latest_pre_entry_close(dataset, instrument_code, entry_timestamp):
    row = (
        MarketCandle.objects.filter(
            dataset_version=dataset,
            instrument__code=instrument_code,
            granularity="H1",
            timestamp__lt=entry_timestamp,
        )
        .order_by("-timestamp")
        .first()
    )
    if not row or registered_candle_completion(row.timestamp, "H1") > entry_timestamp:
        return None
    return row.midpoint_close, registered_candle_completion(row.timestamp, "H1")


def _cad_conversion(dataset, instrument, entry_timestamp):
    quote = instrument.quote_currency
    if quote == "CAD":
        return Decimal(1), entry_timestamp, "CAD@identity"
    usd_cad = _latest_pre_entry_close(dataset, "USD_CAD", entry_timestamp)
    if not usd_cad:
        return None, None, ""
    usd_cad_rate, usd_cad_at = usd_cad
    if quote == "USD":
        return usd_cad_rate, usd_cad_at, f"USD_CAD@{usd_cad_at.isoformat()}"
    if quote == "GBP":
        quote_usd = _latest_pre_entry_close(dataset, "GBP_USD", entry_timestamp)
        if not quote_usd:
            return None, None, ""
        quote_usd_rate, quote_usd_at = quote_usd
        effective_at = min(quote_usd_at, usd_cad_at)
        return (
            quote_usd_rate * usd_cad_rate,
            effective_at,
            f"GBP_USD@{quote_usd_at.isoformat()}|USD_CAD@{usd_cad_at.isoformat()}",
        )
    if quote == "JPY":
        usd_jpy = _latest_pre_entry_close(dataset, "USD_JPY", entry_timestamp)
        if not usd_jpy or usd_jpy[0] <= 0:
            return None, None, ""
        usd_jpy_rate, usd_jpy_at = usd_jpy
        effective_at = min(usd_jpy_at, usd_cad_at)
        return (
            usd_cad_rate / usd_jpy_rate,
            effective_at,
            f"USD_JPY@{usd_jpy_at.isoformat()}|USD_CAD@{usd_cad_at.isoformat()}",
        )
    return None, None, ""


def _material_level_specs(weekly, daily, precision, strategy, dataset, as_of):
    context = _context(as_of, strategy, dataset)
    daily_atr = {point.at: point.value for point in atr14(daily, context)}
    pivots = daily_pivots(daily, context)
    specs = list(confirmed_swing_levels(pivots, daily_atr, precision, context))
    specs.extend(breakout_flip_levels(daily, daily_atr, precision, context))
    for week in weekly:
        atr_candidates = [
            (completed_at, value)
            for completed_at, value in daily_atr.items()
            if completed_at <= week.completed_at
        ]
        if not atr_candidates:
            continue
        atr = max(atr_candidates)[1]
        next_week = registered_successor(week.opened_at, "W")
        specs.extend(
            previous_weekly_levels(
                (week,),
                atr,
                precision,
                _context(week.completed_at, strategy, dataset),
                expires_at=registered_candle_completion(next_week, "W"),
            )
        )
    return specs, daily_atr, pivots


def _persist_material_levels(
    *, nodes, activation_index, daily_by_completion, instrument, strategy, dataset, ranges, as_of
):
    while activation_index < len(nodes) and nodes[activation_index].spec.activated_at <= as_of:
        node = nodes[activation_index]
        node.record = persist_level(
            instrument=instrument,
            strategy_version=strategy,
            dataset_version=dataset,
            spec=node.spec,
            required_ranges=ranges,
            as_of=as_of,
        )
        activation_index += 1

    added = True
    while added:
        added = False
        for node in tuple(nodes[:activation_index]):
            if node.state.state != Lifecycle.ACTIVE:
                continue
            state = evaluate_level(
                node.spec, daily_by_completion.values(), _context(as_of, strategy, dataset)
            )
            if state.state == Lifecycle.ACTIVE:
                continue
            _persist_lifecycle(node, state)
            if state.state == Lifecycle.SUPERSEDED_BY_FLIP:
                activating = daily_by_completion.get(state.effective_at)
                atr_points = atr14(
                    daily_by_completion.values(), _context(state.effective_at, strategy, dataset)
                )
                if activating is None or not atr_points:
                    raise ValueError("role flip lacks its registered activation candle or ATR")
                flipped = flip_level(
                    node.spec,
                    activating,
                    atr_points[-1].value,
                    PIPETTES[instrument.code],
                    _context(state.effective_at, strategy, dataset),
                )
                flipped_node = _LevelNode(flipped)
                flipped_node.record = persist_level(
                    instrument=instrument,
                    strategy_version=strategy,
                    dataset_version=dataset,
                    spec=flipped,
                    required_ranges=ranges,
                    as_of=as_of,
                )
                nodes.insert(activation_index, flipped_node)
                activation_index += 1
                added = True
    return activation_index


def _entry_event(pending):
    return pending.event


def _evaluate_entry(
    *, pending, opening, h1_atr, nodes, instrument, dataset, strategy, ceiling, ranges, as_of
):
    entry_at = derive_expected_entry_timestamp(pending.setup)
    active_specs = []
    states = {}
    records_by_key = {}
    for node in nodes:
        if not node.record or node.spec.activated_at > entry_at:
            continue
        stored_spec = replace(node.spec, key=node.record.stable_key)
        active_specs.append(stored_spec)
        states[stored_spec.key] = node.state
        records_by_key[stored_spec.key] = node.record
    conversion_rate, conversion_at, conversion_identity = _cad_conversion(
        dataset, instrument, entry_at
    )
    result = entry_eligibility(
        _entry_event(pending),
        opening,
        h1_atr,
        active_specs,
        _context(opening.timestamp if opening else entry_at, strategy, dataset),
        expected_entry_timestamp=entry_at,
        precision=PIPETTES[instrument.code],
        absolute_spread_ceiling=ceiling,
        level_states=states,
        cad_conversion_rate=conversion_rate,
        conversion_effective_at=conversion_at,
        conversion_identity=conversion_identity,
    )
    target = records_by_key.get(result.target_key)
    evidence = {
        "expected_entry_timestamp": entry_at.isoformat(),
        "decision": result.decision,
        "reason": result.reason,
        "entry_open_present": opening is not None,
    }
    for book in books_for_setup(pending.setup):
        persist_entry_evaluation(
            setup=pending.setup,
            book_identity=book,
            result=result,
            opening=opening,
            target_level=target,
            evidence=evidence,
            required_ranges=ranges,
            as_of=as_of,
            expected_entry_timestamp=entry_at,
        )


def _merge_material_specs(nodes, known_keys, specs):
    additions = sorted(
        (spec for spec in specs if spec.key not in known_keys),
        key=lambda item: (item.activated_at, item.key),
    )
    nodes.extend(_LevelNode(spec) for spec in additions)
    known_keys.update(spec.key for spec in additions)


def _seed_h1_atr(candles, context):
    ranges = []
    for index, candle in enumerate(candles):
        previous_close = candles[index - 1].close if index else candle.close
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    points = atr14(candles, context)
    return (points[-1].value, []) if points else (None, ranges)


def _instrument_detector(
    *, instrument, dataset, strategy, ranges, spread_ceiling, as_of, contract=None
):
    for required in ranges:
        assert_dataset_window_usable(
            dataset,
            instrument,
            (development_candle_range(required, contract=contract, instrument=instrument.code),),
            as_of,
        )
    development_start = DEVELOPMENT_START.astimezone(UTC)
    development_end = DEVELOPMENT_END.astimezone(UTC)
    schedules = {
        granularity: {
            candle_completion(timestamp, granularity, contract): timestamp
            for timestamp in _range_timestamps(
                ranges, granularity, contract=contract, instrument=instrument
            )
            if candle_completion(timestamp, granularity, contract) < development_end
        }
        for granularity in ("W", "D", "H1")
    }
    development_h1 = sorted(
        (completion, timestamp)
        for completion, timestamp in schedules["H1"].items()
        if development_start <= completion < development_end
    )
    weekly = _admitted_before(
        dataset, instrument, ranges, "W", development_start, contract=contract
    )
    daily = _admitted_before(dataset, instrument, ranges, "D", development_start, contract=contract)
    h1 = _admitted_before(dataset, instrument, ranges, "H1", development_start, contract=contract)
    nodes = []
    known_spec_keys = set()
    specs, _, pivots = _material_level_specs(
        weekly,
        daily,
        PIPETTES[instrument.code],
        strategy,
        dataset,
        development_start,
    )
    _merge_material_specs(nodes, known_spec_keys, specs)
    initial_context = _context(development_start, strategy, dataset)
    bias = daily_bias(daily, pivots, initial_context)
    swing = supporting_swing(pivots, bias, initial_context)
    h1_atr, unseeded_true_ranges = _seed_h1_atr(h1, initial_context)
    pending = []
    activation_index = 0
    levels_initialized = False
    previous = max(h1, key=lambda item: item.completed_at, default=None)
    consumed = set(
        SetupLevelAttribution.objects.filter(
            setup__instrument=instrument,
            setup__dataset_version=dataset,
            setup__strategy_version=strategy,
        ).values_list("level__stable_key", flat=True)
    )

    for completion, opened_at in development_h1:
        for candidate in tuple(pending):
            confirmed = candidate.setup.setuptransition_set.filter(
                from_state=SetupTransition.State.TRIGGER_PENDING,
                to_state=SetupTransition.State.CONFIRMED,
                book_identity="",
            ).exists()
            if confirmed and derive_expected_entry_timestamp(candidate.setup) == opened_at:
                projection = read_entry_projection(
                    dataset_id=dataset.pk,
                    instrument_id=instrument.pk,
                    theoretical_entry_timestamp=opened_at,
                    as_of=completion,
                )
                _evaluate_entry(
                    pending=candidate,
                    opening=EntryOpen(
                        projection.timestamp, projection.bid_open, projection.ask_open
                    ),
                    h1_atr=h1_atr,
                    nodes=nodes,
                    instrument=instrument,
                    dataset=dataset,
                    strategy=strategy,
                    ceiling=spread_ceiling,
                    ranges=ranges,
                    as_of=completion,
                )
                pending.remove(candidate)

        candle = _candle_completing_at(dataset, instrument, schedules, "H1", completion, contract)
        if candle is None or candle.opened_at != opened_at:
            raise ValueError(f"registered H1 candle is missing at {completion.isoformat()}")
        previous_close = h1[-1].close if h1 else candle.close
        true_range = max(
            candle.high - candle.low,
            abs(candle.high - previous_close),
            abs(candle.low - previous_close),
        )
        h1.append(candle)
        if h1_atr is None:
            unseeded_true_ranges.append(true_range)
            if len(unseeded_true_ranges) == 14:
                h1_atr = sum(unseeded_true_ranges, Decimal()) / 14
                unseeded_true_ranges = []
        else:
            h1_atr = (h1_atr * 13 + true_range) / 14

        structure_changed = False
        for granularity, admitted in (("W", weekly), ("D", daily)):
            completed_candle = _candle_completing_at(
                dataset, instrument, schedules, granularity, completion, contract
            )
            if completed_candle is not None:
                admitted.append(completed_candle)
                structure_changed = True

        if structure_changed:
            specs, _, pivots = _material_level_specs(
                weekly,
                daily,
                PIPETTES[instrument.code],
                strategy,
                dataset,
                completion,
            )
            _merge_material_specs(nodes, known_spec_keys, specs)
            boundary_context = _context(completion, strategy, dataset)
            bias = daily_bias(daily, pivots, boundary_context)
            swing = supporting_swing(pivots, bias, boundary_context)
        if structure_changed or not levels_initialized:
            daily_by_completion = {item.completed_at: item for item in daily}
            activation_index = _persist_material_levels(
                nodes=nodes,
                activation_index=activation_index,
                daily_by_completion=daily_by_completion,
                instrument=instrument,
                strategy=strategy,
                dataset=dataset,
                ranges=ranges,
                as_of=completion,
            )
            levels_initialized = True

        for candidate in tuple(pending):
            inactive = {
                key: next(
                    (
                        node.state.effective_at
                        for node in nodes
                        if node.record and node.record.stable_key == key
                    ),
                    None,
                )
                for key in candidate.event.level_keys
            }
            confirmation = confirm_sweep(
                candidate.event,
                h1,
                daily,
                _context(completion, strategy, dataset),
                attributed_level_inactive_at=inactive,
                supporting_swings=pivots,
            )
            if confirmation.state != SetupTransition.State.TRIGGER_PENDING:
                persist_confirmation(
                    setup=candidate.setup,
                    confirmation=confirmation,
                    evidence=_serializable(asdict(confirmation)),
                    required_ranges=ranges,
                    as_of=completion,
                )
                if confirmation.state != SetupTransition.State.CONFIRMED:
                    pending.remove(candidate)

        existing_setup_ids = list(
            SetupEvent.objects.filter(
                instrument=instrument,
                dataset_version=dataset,
                detector_version=strategy.detector_version,
                sweep_h1_timestamp=candle.completed_at,
            ).values_list("pk", flat=True)
        )
        created_setup = bool(existing_setup_ids)
        if previous is not None and not created_setup:
            context = _context(completion, strategy, dataset)
            active_nodes = [
                node
                for node in nodes[:activation_index]
                if node.record
                and node.state.state == Lifecycle.ACTIVE
                and node.record.stable_key not in consumed
            ]
            if swing and bias != Bias.NEUTRAL:
                detection_specs = [
                    replace(node.spec, key=node.record.stable_key) for node in active_nodes
                ]
                event = detect_failed_sweep(
                    previous,
                    candle,
                    detection_specs,
                    bias,
                    swing.price,
                    context,
                )
                if event:
                    levels_by_key = {node.record.stable_key: node.record for node in active_nodes}
                    setup = persist_setup(
                        instrument=instrument,
                        strategy_version=strategy,
                        dataset_version=dataset,
                        event=event,
                        level_attributions={key: levels_by_key[key] for key in event.level_keys},
                        evidence=_setup_evidence(event),
                        required_ranges=ranges,
                        as_of=completion,
                    )
                    consumed.update(event.level_keys)
                    if (
                        partition_boundary_censorship(
                            setup_id=setup.pk, sweep_timestamp=setup.sweep_h1_timestamp
                        )
                        is None
                    ):
                        pending.append(_PendingSetup(event, setup))
                    existing_setup_ids.append(setup.pk)
                    created_setup = True

        result = (
            AnalysisRun.Result.CANDIDATE_CREATED
            if created_setup
            else AnalysisRun.Result.LEVEL_ACTIVE
            if any(
                node.record and node.state.state == Lifecycle.ACTIVE
                for node in nodes[:activation_index]
            )
            else AnalysisRun.Result.NO_SETUP
        )
        persist_analysis(
            instrument=instrument,
            strategy_version=strategy,
            dataset_version=dataset,
            completed_h1_timestamp=candle.completed_at,
            result=result,
            evidence={
                "completed_h1_timestamp": candle.completed_at.isoformat(),
                "result": result,
                "setup_ids": existing_setup_ids,
            },
            required_ranges=ranges,
            as_of=completion,
        )
        previous = candle

    unresolved = [candidate.setup.pk for candidate in pending]
    if unresolved:
        raise ValueError(f"S1 detector left unresolved TRIGGER_PENDING setups: {unresolved}")


def _assert_complete_setup_lifecycle(dataset, strategy, censored_setup_ids=frozenset()):
    setups = SetupEvent.objects.filter(
        dataset_version=dataset,
        strategy_version=strategy,
        sweep_h1_timestamp__gte=DEVELOPMENT_START.astimezone(UTC),
        sweep_h1_timestamp__lt=DEVELOPMENT_END.astimezone(UTC),
    )
    for setup in setups:
        global_transition = setup.setuptransition_set.filter(book_identity="").first()
        if global_transition is None:
            if setup.pk in censored_setup_ids:
                continue
            raise ValueError("S1 detector lifecycle contains a TRIGGER_PENDING setup")
        if setup.pk in censored_setup_ids:
            raise ValueError("partition-censored setup has a strategy transition")
        if global_transition.to_state != SetupTransition.State.CONFIRMED:
            continue
        expected_books = set(books_for_setup(setup))
        evaluation_books = set(
            EntryEligibilityEvaluation.objects.filter(setup=setup).values_list(
                "book_identity", flat=True
            )
        )
        transition_books = set(
            SetupTransition.objects.filter(
                setup=setup,
                from_state=SetupTransition.State.CONFIRMED,
            ).values_list("book_identity", flat=True)
        )
        if evaluation_books != expected_books or transition_books != expected_books:
            raise ValueError("S1 detector confirmed setup has incomplete book eligibility")


@transaction.atomic
def run_s1_detector(*, dataset_id, strategy_version_id, s0_job_id, as_of):
    """Run every bounded development H1 decision and register its immutable coverage proof."""
    dataset = DatasetVersion.objects.get(pk=dataset_id)
    strategy = StrategyVersion.objects.get(pk=strategy_version_id)
    ranges_by_instrument, s0_output = _validate_s1_contract(dataset, strategy, as_of, s0_job_id)
    instruments = {
        instrument.code: instrument
        for instrument in Instrument.objects.filter(code__in=FROZEN_INSTRUMENTS)
    }
    if set(instruments) != FROZEN_INSTRUMENTS:
        raise ValueError("S1 detector requires all six registered instruments")
    contract = contract_for_dataset(dataset)
    for code in sorted(FROZEN_INSTRUMENTS):
        _instrument_detector(
            instrument=instruments[code],
            dataset=dataset,
            strategy=strategy,
            ranges=ranges_by_instrument[code],
            spread_ceiling=Decimal(s0_output.coverage["spread_ceilings"][code]),
            as_of=as_of,
            contract=contract,
        )

    expected = expected_analysis_keys(ranges_by_instrument, contract=contract)
    observed_rows = list(
        AnalysisRun.objects.filter(
            dataset_version=dataset,
            detector_version=strategy.detector_version,
            instrument__code__in=FROZEN_INSTRUMENTS,
            completed_h1_timestamp__gte=DEVELOPMENT_START.astimezone(UTC),
            completed_h1_timestamp__lt=DEVELOPMENT_END.astimezone(UTC),
        ).values_list("instrument__code", "completed_h1_timestamp", "result")
    )
    observed = tuple(sorted((code, timestamp.isoformat()) for code, timestamp, _ in observed_rows))
    if observed != expected or any(
        result == AnalysisRun.Result.DATA_INCOMPLETE for _, _, result in observed_rows
    ):
        missing = sorted(set(expected) - set(observed))[:3]
        unexpected = sorted(set(observed) - set(expected))[:3]
        raise ValueError(
            "S1 detector did not produce exact registered H1 analysis coverage: "
            f"expected={len(expected)} observed={len(observed)} "
            f"missing={missing} unexpected={unexpected}"
        )
    setup_rows = SetupEvent.objects.filter(
        dataset_version=dataset,
        strategy_version=strategy,
        sweep_h1_timestamp__gte=DEVELOPMENT_START.astimezone(UTC),
        sweep_h1_timestamp__lt=DEVELOPMENT_END.astimezone(UTC),
    ).values("pk", "sweep_h1_timestamp")
    censored_evidence = sorted(
        (
            evidence
            for row in setup_rows
            if (
                evidence := partition_boundary_censorship(
                    setup_id=row["pk"], sweep_timestamp=row["sweep_h1_timestamp"]
                )
            )
        ),
        key=lambda row: row["setup_id"],
    )
    censored_setup_ids = frozenset(row["setup_id"] for row in censored_evidence)
    _assert_complete_setup_lifecycle(dataset, strategy, censored_setup_ids)

    configuration = {
        "identity": S1_DETECTOR_JOB_NAME,
        "dataset_id": dataset.pk,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "strategy_version_id": strategy.pk,
        "strategy_content_hash": strategy.content_hash,
        "detector_version": strategy.detector_version,
        "partition_boundary_censor_rule": PARTITION_BOUNDARY_CENSOR_RULE,
        "s0_job_id": s0_job_id,
        "s0_report_sha256": s0_output.report_sha256,
        "as_of": as_of.isoformat(),
    }
    report_body = {
        "expected_analysis_count": len(expected),
        "expected_analysis_sha256": stable_hash(expected),
        "observed_analysis_count": len(observed),
        "observed_analysis_sha256": stable_hash(observed),
        "partition_boundary_censored": censored_evidence,
        "partition_boundary_censored_sha256": stable_hash(censored_evidence),
    }
    report = {**report_body, "report_sha256": stable_hash(report_body)}
    values = {
        "job_name": S1_DETECTOR_JOB_NAME,
        "strategy_version": strategy,
        "dataset_version": dataset,
        "config_hash": stable_hash(configuration),
        "as_of": as_of,
        "status": JobRun.Status.SUCCEEDED,
        "evidence": {"configuration": configuration, "report": report},
    }
    job, created = JobRun.objects.get_or_create(
        idempotency_key=(f"s1-detector:{strategy.pk}:{dataset.pk}:{stable_hash(configuration)}"),
        defaults=values,
    )
    if not created and any(getattr(job, key) != value for key, value in values.items()):
        raise ValueError("S1 detector run key resolved to different immutable content")
    return job
