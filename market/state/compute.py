"""Assemble and persist a market-state snapshot from causal inputs.

The payload is a per-granularity block of observable facts at the cutoff: the
eligible-candle count and latest midpoint close, plus the higher-timeframe
descriptive context (swings, trend, HH/HL sequence, ATR, rolling volatility
percentile and regime, range/equilibrium, persistence, break-of-structure and
change-of-character). Every feature carries an explicit availability state; an
unavailable feature is never reported as a neutral or false value. No threshold
here selects a trade — these are descriptive facts (docs/phase4/design.md §7.1).
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

from django.db import transaction

from market.quality import NEW_YORK
from market.state import context, features, fvg, liquidity, orb, sessions, structure
from market.state import manifest as input_policy
from market.state.canonical import format_decimal
from market.state.definitions import register_definition
from market.state.manifest import FrozenObservation, _iso, eligible_observations, manifest_from_rows
from market.state.snapshots import persist_snapshot, synchronize_inputs
from market.state.terminology import REGISTRY

DESCRIPTOR_KEY = "market-state-descriptor"
DESCRIPTOR_VERSION = "0.11.0"

FVG_GRANULARITIES = frozenset({"M15", "H1", "H4"})
ORB_SESSION_WINDOW_HOURS = 12
PRIOR_SESSION_HOURS = 8

#: Explicit bounded lookback (candles) per granularity. Every eligible-candle
#: fetch and the input manifest use these, so a snapshot never scans or embeds
#: unbounded history (design §14). The windows comfortably cover the deepest
#: feature (volatility percentile: ~14 + 100 prior ATRs ≈ 214 bars).
LOOKBACKS = {"M15": 500, "H1": 300, "H4": 300, "D": 400, "W": 300}
#: Bounded daily history permits approximately eighteen complete calendar months.
PRIOR_MONTH_LOOKBACK = 400
#: Most recent candle(s) needed for a prior-period extreme.
PRIOR_EXTREME_LOOKBACK = 2


def _runtime_parameters():
    """Every scalar algorithm constant is part of this single supported contract."""
    return {
        module.__name__: {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in vars(module).items()
            if key.isupper() and isinstance(value, (str, int, Decimal))
        }
        for module in (features, structure, liquidity, fvg, orb, sessions, context, input_policy)
    }


#: The canonical body of the descriptor definition. Observable facts only; the
#: feature list and thresholds are pinned so a snapshot binds the exact
#: algorithm versions that produced it.
DESCRIPTOR_DEFINITION = {
    "algorithms": {
        "input_manifest": "causal-eligibility-v1",
        "descriptor": "latest-eligible-candle-v1",
        "higher_timeframe": "htf-context-v1",
        "structure": "structure-context-v1",
        "monthly_context": "monthly-context-v1",
        "evidence_manifest": "vintage-evidence-v1",
        "corrections": "system-recording-prerequisite-chronology-v5",
    },
    "features": [
        "eligible_candle_count",
        "latest_eligible_candle",
        features.SWING_V,
        features.TREND_V,
        features.SEQUENCE_V,
        features.ATR_V,
        features.VOLATILITY_V,
        features.VOL_REGIME_V,
        features.COMPRESSION_EXPANSION_V,
        features.EQUILIBRIUM_V,
        features.PERSISTENCE_V,
        features.BOS_V,
        features.CHOCH_V,
        structure.ZONE_V,
        structure.EQUAL_LEVELS_V,
        structure.SD_CANDIDATE_V,
        structure.CONSOLIDATION_V,
        structure.PRIOR_EXTREME_V,
        liquidity.SWEEP_V,
        liquidity.ACCEPTANCE_V,
        fvg.FVG_V,
        orb.ORB_V,
        sessions.SESSION_V,
        context.SPREAD_V,
        context.EVENT_STATE_V,
        context.MACRO_REGIME_V,
    ],
    "runtime_parameters": _runtime_parameters(),
    "price_basis": "midpoint",
    "rounding": {"quantum": "0.000001", "mode": "ROUND_HALF_EVEN"},
    "calendar_policy": "ny-fx-week-v1",
    "missing_data_policy": "explicit-unavailable-v1",
    "lookbacks": {"M15": 500, "H1": 300, "H4": 300, "D": 400, "W": 300},
    "thresholds": {
        "swing_left": features.SWING_LEFT,
        "swing_right": features.SWING_RIGHT,
        "atr_period": features.ATR_PERIOD,
        "volatility_population": features.VOL_POPULATION,
        "volatility_min_population": features.VOL_MIN_POPULATION,
        "compression_percentile": str(features.COMPRESSION_PCTL),
        "expansion_percentile": str(features.EXPANSION_PCTL),
        "persistence_window": features.PERSISTENCE_WINDOW,
        "zone_cluster_atr": str(structure.ZONE_CLUSTER_ATR),
        "equal_level_atr": str(structure.EQUAL_LEVEL_ATR),
        "displacement_atr": str(structure.DISPLACEMENT_ATR),
        "consolidation_atr": str(structure.CONSOLIDATION_ATR),
        "consolidation_window": structure.CONSOLIDATION_WINDOW,
        "failed_breakout_bars": structure.FAILED_BREAKOUT_BARS,
        "sweep_depth_atr": str(liquidity.SWEEP_DEPTH_ATR),
        "reclaim_window": liquidity.RECLAIM_WINDOW,
        "fvg_displacement_atr": str(fvg.FVG_DISPLACEMENT_ATR),
        "orb_minutes": sessions.ORB_MINUTES,
        "zone_expiry_intervals": structure.ZONE_EXPIRY_INTERVALS,
        "fvg_expiry_bars": fvg.FVG_EXPIRY_BARS,
        "fvg_min_raw": str(fvg.FVG_MIN_RAW),
        "fvg_min_atr": str(fvg.FVG_MIN_ATR),
        "fvg_min_pips": str(fvg.FVG_MIN_PIPS),
        "fvg_min_spread": str(fvg.FVG_MIN_SPREAD),
    },
    "terminology": REGISTRY,
    "session_policy": {
        name: {"timezone": data["timezone"], "open": data["open"].isoformat()}
        for name, data in sessions.SESSIONS.items()
    },
    "context_policy": {
        "canonical_pair": "validated-Instrument.Code/base_quote-v1",
        "currency_country": context.CURRENCY_COUNTRY,
        "event_lookback_days": context.EVENT_LOOKBACK_DAYS,
        "event_horizon_days": context.EVENT_HORIZON_DAYS,
        "orb_window_hours": ORB_SESSION_WINDOW_HOURS,
        "prior_session_hours": PRIOR_SESSION_HOURS,
        "monthly_daily_lookback": PRIOR_MONTH_LOOKBACK,
        "pip_size": {"JPY": "0.01", "default": "0.0001"},
        "macro": "policy-rate/latest-two-periods/raw-percent/difference-sign/code-order-v1",
        "missing_side": "explicit-unavailable-not-neutral",
    },
}


def ensure_descriptor_definition():
    """Register (idempotently) and return the descriptor definition."""
    return register_definition(DESCRIPTOR_KEY, DESCRIPTOR_VERSION, DESCRIPTOR_DEFINITION)


def _midpoint(bid, ask):
    return (bid + ask) / 2


def _pip_size(instrument):
    return Decimal("0.01") if context.pair_currencies(instrument)[1] == "JPY" else Decimal("0.0001")


def _bars_from_observations(rows):
    return [
        features.Bar(
            timestamp=row.timestamp,
            open=_midpoint(row.bid_open, row.ask_open),
            high=_midpoint(row.bid_high, row.ask_high),
            low=_midpoint(row.bid_low, row.ask_low),
            close=_midpoint(row.bid_close, row.ask_close),
            end=row.interval_end,
            spread=row.ask_close - row.bid_close,
            granularity=row.granularity,
            observed_at=row.observed_at,
            revision=row.revision,
            content_sha256=row.content_sha256,
        )
        for row in rows
    ]


def _granularity_descriptor(instrument, granularity, rows):
    if not rows:
        return {"state": "unavailable", "reason_code": "insufficient_history"}
    latest = rows[-1]
    bars = _bars_from_observations(rows)
    atr = features._current_atr(bars)
    if granularity in FVG_GRANULARITIES:
        # No single atr: find_fvgs qualifies each gap with the ATR contemporaneous
        # to its candle 3, and uses each candle's own spread for normalization.
        fvg_block = fvg.find_fvgs(bars, _pip_size(instrument))
    else:
        fvg_block = {"state": "not_applicable", "reason_code": "unsupported_granularity"}
    return {
        "state": "available",
        "eligible_candle_count": len(rows),
        "latest_eligible_candle": {
            "timestamp": _iso(latest.timestamp),
            "revision": latest.revision,
            "midpoint_close": format_decimal(bars[-1].close),
        },
        "higher_timeframe": features.higher_timeframe_context(bars),
        "structure": structure.structure_context(bars, atr, instrument.code, granularity),
        "liquidity": liquidity.liquidity_context(bars, atr, instrument.code, granularity),
        "fvg": fvg_block,
        "spread": context.spread_context(latest, atr),
    }


def _orb_block(instrument, information_cutoff, rows):
    out = {}
    if not rows:
        for name in sessions.SESSIONS:
            out[name] = orb.orb_unavailable("insufficient_history", session_name=name)
        return out
    bars = _bars_from_observations(rows)
    index_by_ts = {row.timestamp: i for i, row in enumerate(rows)}
    bar_by_ts = {row.timestamp: bar for row, bar in zip(rows, bars)}
    for name in sessions.SESSIONS:
        found = sessions.most_recent_completed_orb_open(information_cutoff, name)
        if found is None:
            out[name] = orb.orb_unavailable("session_market_closed", session_name=name)
            continue
        utc_open, local_open, tz = found
        if utc_open not in index_by_ts:
            out[name] = orb.orb_unavailable("opening_interval_missing", session_name=name)
            continue
        opening_bar = bar_by_ts[utc_open]
        window_end = utc_open + timedelta(hours=ORB_SESSION_WINDOW_HOURS)
        session_bars = [
            bar_by_ts[row.timestamp] for row in rows if utc_open < row.timestamp < window_end
        ]
        # ATR contemporaneous with the opening interval, spread from the opening
        # candle itself — the ORB facts must not be requalified by later bars.
        atr = features.atr_at_index(bars, index_by_ts[utc_open])
        out[name] = orb.opening_range(
            opening_bar,
            session_bars,
            atr,
            opening_bar.spread,
            session_name=name,
            local_open=local_open,
            tzinfo=tz,
        )
        if out[name]["state"] == "available":
            index = index_by_ts[utc_open]
            available_at = max(
                b.available_at for b in bars[max(0, index - features.ATR_PERIOD) : index + 1]
            )
            out[name]["available_at"] = _iso(available_at)
            for field in ("breakout_available_at", "retest_at", "failed_at"):
                if field in out[name]:
                    out[name][field] = _iso(
                        max(available_at, datetime.fromisoformat(out[name][field]))
                    )
    return out


def _overnight_extreme(instrument, information_cutoff, rows):
    """High/low of the most recent completed overnight window: the previous New
    York 17:00 session open through the London 08:00 open (design §7.4)."""
    found = sessions.most_recent_completed_orb_open(information_cutoff, "london")
    if found is None:
        return {
            "state": "unavailable",
            "version": structure.PRIOR_EXTREME_V,
            "reason_code": "session_market_closed",
        }
    london_open, _local_open, _tz = found
    ny = london_open.astimezone(NEW_YORK)
    start_local = ny.replace(hour=17, minute=0, second=0, microsecond=0)
    if start_local >= ny:
        start_local -= timedelta(days=1)
    overnight_start = start_local.astimezone(UTC)
    window = [r for r in rows if overnight_start <= r.timestamp < london_open]
    from market.live_acquisition import complete_live_intervals

    expected = complete_live_intervals(overnight_start, london_open, "M15")
    if not expected or {r.timestamp for r in window} != set(expected):
        return {
            "state": "unavailable",
            "version": structure.PRIOR_EXTREME_V,
            "reason_code": "incomplete_period",
            "utc_start": _iso(overnight_start),
            "utc_end": _iso(london_open),
        }
    result = structure.prior_period_extreme(_bars_from_observations(window))
    result.update(
        utc_start=_iso(overnight_start),
        utc_end=_iso(london_open),
        timezone="America/New_York",
        session_date=start_local.date().isoformat(),
        available_at=_iso(max(max(r.observed_at, r.interval_end) for r in window)),
        source_intervals=manifest_from_rows({"M15": window})[0],
    )
    return result


def _prior_extreme(rows, information_cutoff, granularity):
    from market.live_acquisition import canonical_live_start, complete_live_intervals
    from market.services import live_candle_completion

    opens = complete_live_intervals(
        canonical_live_start(information_cutoff - timedelta(days=21), granularity),
        information_cutoff,
        granularity,
    )
    expected = max(opens)
    source = {
        "utc_start": _iso(expected),
        "utc_end": _iso(live_candle_completion(expected, granularity)),
    }
    selected = [r for r in rows if r.timestamp == expected]
    if not selected:
        return {
            "state": "unavailable",
            "version": structure.PRIOR_EXTREME_V,
            "reason_code": "missing_exact_prior_period",
            **source,
        }
    return {
        **structure.prior_period_extreme(_bars_from_observations(selected)),
        **source,
        "available_at": _iso(max(r.observed_at for r in selected)),
        "source_intervals": manifest_from_rows({granularity: selected})[0],
    }


def _prior_session_extreme(information_cutoff, rows, name):
    from market.live_acquisition import complete_live_intervals

    found = sessions.most_recent_completed_orb_open(
        information_cutoff - timedelta(hours=PRIOR_SESSION_HOURS, minutes=-sessions.ORB_MINUTES),
        name,
    )
    if found is None:
        return {
            "state": "unavailable",
            "version": structure.PRIOR_EXTREME_V,
            "reason_code": "session_market_closed",
        }
    start, local, tz = found
    end = start + timedelta(hours=PRIOR_SESSION_HOURS)
    window = [r for r in rows if start <= r.timestamp < end]
    expected = complete_live_intervals(start, end, "M15")
    boundaries = {
        "utc_start": _iso(start),
        "utc_end": _iso(end),
        "timezone": str(tz),
        "session_date": local.date().isoformat(),
        "local_start": local.isoformat(),
    }
    if not expected or {r.timestamp for r in window} != set(expected):
        return {
            "state": "unavailable",
            "version": structure.PRIOR_EXTREME_V,
            "reason_code": "incomplete_period",
            **boundaries,
        }
    return {
        **structure.prior_period_extreme(_bars_from_observations(window)),
        **boundaries,
        "available_at": _iso(max(max(r.observed_at, r.interval_end) for r in window)),
        "source_intervals": manifest_from_rows({"M15": window})[0],
    }


def _expected_daily_opens(year, month):
    """UTC open instants of every registered daily session in a NY calendar month
    (weekday Sun-Thu 17:00). Holidays are not modelled, so a month missing one of
    these is treated as incomplete rather than silently complete."""
    from calendar import monthrange
    from datetime import date, datetime, time

    from market.quality import DAILY_SESSION_WEEKDAYS

    opens = set()
    for day in range(1, monthrange(year, month)[1] + 1):
        d = date(year, month, day)
        if d.weekday() in DAILY_SESSION_WEEKDAYS:
            opens.add(datetime.combine(d, time(17), NEW_YORK).astimezone(UTC))
    return opens


def _completed_months(instrument, information_cutoff, rows=None):
    """Ordered ``[(‘YYYY-MM’, monthly_Bar)]`` for every fully-past NY month whose
    registered daily sessions are all present. A partial current month, or a past
    month missing any registered daily session, is excluded (never completed)."""
    if rows is None:
        rows = eligible_observations(
            instrument, "D", information_cutoff, lookback=PRIOR_MONTH_LOOKBACK
        )
    if not rows:
        return []
    cutoff_local = information_cutoff.astimezone(NEW_YORK)
    cutoff_month = (cutoff_local.year, cutoff_local.month)
    months = defaultdict(list)
    for bar, row in zip(_bars_from_observations(rows), rows):
        local = row.timestamp.astimezone(NEW_YORK)
        months[(local.year, local.month)].append((row.timestamp, bar))
    completed = []
    for key in sorted(m for m in months if m < cutoff_month):
        present = {ts for ts, _ in months[key]}
        if not _expected_daily_opens(*key) <= present:
            continue  # a registered daily session is missing -> not complete
        ordered = [bar for _, bar in sorted(months[key])]
        monthly = features.Bar(
            timestamp=ordered[0].timestamp,
            open=ordered[0].open,
            high=max(b.high for b in ordered),
            low=min(b.low for b in ordered),
            close=ordered[-1].close,
            end=ordered[-1].end,
            observed_at=max(b.available_at for b in ordered),
            granularity="M",
        )
        completed.append((f"{key[0]:04d}-{key[1]:02d}", monthly))
    return completed


def _prior_completed_month(instrument, information_cutoff, rows=None):
    if rows is None:
        rows = eligible_observations(
            instrument, "D", information_cutoff, lookback=PRIOR_MONTH_LOOKBACK
        )
    completed = _completed_months(instrument, information_cutoff, rows)
    local = information_cutoff.astimezone(NEW_YORK)
    previous = local.replace(day=1) - timedelta(days=1)
    expected = f"{previous.year:04d}-{previous.month:02d}"
    completed = [(label, bar) for label, bar in completed if label == expected]
    if not completed:
        return {
            "state": "unavailable",
            "version": structure.PRIOR_EXTREME_V,
            "reason_code": "incomplete_period",
            "month": expected,
        }
    label, monthly = completed[-1]
    result = structure.prior_period_extreme([monthly])
    result["month"] = label
    result["available_at"] = _iso(monthly.available_at)
    expected_opens = _expected_daily_opens(previous.year, previous.month)
    result["source_intervals"] = manifest_from_rows(
        {"D": [r for r in rows if r.timestamp in expected_opens]}
    )[0]
    return result


def _monthly_context(instrument, information_cutoff, rows=None):
    """Monthly trend over completed NY-session months (aggregated daily candles)."""
    completed = _completed_months(instrument, information_cutoff, rows)
    if not completed:
        return {
            "state": "unavailable",
            "version": features.TREND_V,
            "reason_code": "incomplete_period",
        }
    monthly_bars = [bar for _, bar in completed]
    return {
        "state": "available",
        "completed_months": [label for label, _ in completed],
        "trend": features.trend_feature(monthly_bars),
    }


#: Granularities the computation always consumes beyond the requested set: M15
#: (opening range) and D/W (prior-period and monthly context). The manifest binds
#: all of them so any consumed candle is part of the snapshot identity.
AUXILIARY_GRANULARITIES = frozenset({"M15", "D", "W"})


def _require_governing_definition(definition):
    """Fail closed unless the supplied definition is the contract this code
    computes. A definition whose body does not match the pinned descriptor cannot
    govern computation, so it is rejected rather than silently ignored."""
    from market.state.canonical import identity_digest
    from market.state.definitions import DefinitionError

    digest = identity_digest(definition.definition)
    if (
        (definition.key, definition.version) != (DESCRIPTOR_KEY, DESCRIPTOR_VERSION)
        or definition.definition_sha256 != digest
        or digest != identity_digest(DESCRIPTOR_DEFINITION)
        or definition.definition.get("runtime_parameters") != _runtime_parameters()
        or definition.definition["lookbacks"] != LOOKBACKS
        or definition.definition["context_policy"]["monthly_daily_lookback"] != PRIOR_MONTH_LOOKBACK
        or definition.definition["context_policy"]["orb_window_hours"] != ORB_SESSION_WINDOW_HOURS
        or definition.definition["context_policy"]["prior_session_hours"] != PRIOR_SESSION_HOURS
    ):
        raise DefinitionError(
            f"definition {definition.key}@{definition.version} does not match the "
            "descriptor contract this implementation computes"
        )


def build_market_state(
    instrument, definition, information_cutoff, granularities, *, frozen_inputs=None
):
    """Build the canonical payload, input manifest and evidence manifest without
    persisting. Returns ``(payload, scope, manifest, manifest_sha256,
    evidence_manifest, evidence_sha256, data_quality_status)``."""
    from market.state.canonical import identity_digest

    _require_governing_definition(definition)
    scope = sorted(set(granularities))
    if not scope or not set(scope) <= set(LOOKBACKS):
        raise ValueError("unsupported_granularity")
    consumed = sorted(set(scope) | AUXILIARY_GRANULARITIES)
    # Materialize once; manifests and every price feature share these exact rows.
    if frozen_inputs is None:
        frozen_rows = {
            g: tuple(
                FrozenObservation.from_row(row)
                for row in eligible_observations(
                    instrument,
                    g,
                    information_cutoff,
                    lookback=definition.definition["lookbacks"][g],
                )
            )
            for g in consumed
        }
        earliest = min(
            (r.observed_at for g in scope + ["M15"] for r in frozen_rows[g]),
            default=information_cutoff,
        )
        research = context.freeze_research(instrument, earliest, information_cutoff)
    else:
        frozen_rows, research = frozen_inputs
    research = MappingProxyType(
        {key: tuple(context.freeze_record(r) for r in values) for key, values in research.items()}
    )
    frozen_rows = MappingProxyType(
        {g: tuple(FrozenObservation.from_row(r) for r in rows) for g, rows in frozen_rows.items()}
    )
    manifest, manifest_sha256 = manifest_from_rows(frozen_rows)
    event_block = context.event_state(instrument, information_cutoff, frozen=research)
    macro_block = context.macro_regime(instrument, information_cutoff, frozen=research)
    per_granularity = {
        granularity: _granularity_descriptor(instrument, granularity, frozen_rows[granularity])
        for granularity in scope
    }
    output_payload = {
        "schema": "market-state/descriptor-v0",
        "definition": [definition.key, definition.version],
        "instrument": instrument.code,
        "information_cutoff": _iso(information_cutoff),
        "requested_granularities": scope,
        "granularities": per_granularity,
        "prior_extremes": {
            "prior_day": _prior_extreme(frozen_rows["D"], information_cutoff, "D"),
            "prior_week": _prior_extreme(frozen_rows["W"], information_cutoff, "W"),
            "prior_completed_month": _prior_completed_month(
                instrument, information_cutoff, frozen_rows["D"]
            ),
            "overnight_session": _overnight_extreme(
                instrument, information_cutoff, frozen_rows["M15"]
            ),
            "prior_london_session": _prior_session_extreme(
                information_cutoff, frozen_rows["M15"], "london"
            ),
            "prior_new_york_session": _prior_session_extreme(
                information_cutoff, frozen_rows["M15"], "new_york"
            ),
        },
        "monthly_context": _monthly_context(instrument, information_cutoff, frozen_rows["D"]),
        "opening_range": _orb_block(instrument, information_cutoff, frozen_rows["M15"]),
        "event_state": event_block,
        "macro_regime": macro_block,
    }

    # Attach historical context only from the already frozen vintage collection.
    # No feature can requery research after the candle bundle has been computed.
    context_cutoffs = {information_cutoff}

    def attach(value):
        if isinstance(value, dict):
            for child in tuple(value.values()):
                attach(child)
            for field in ("available_at", "breakout_available_at"):
                if field in value:
                    at = datetime.fromisoformat(value[field])
                    context_cutoffs.add(at)
                    value[field + "_context"] = {
                        "event_state": context.event_state(instrument, at, frozen=research),
                        "macro_regime": context.macro_regime(instrument, at, frozen=research),
                    }
        elif isinstance(value, list):
            for child in value:
                attach(child)

    attach(output_payload["opening_range"])
    for block in per_granularity.values():
        if "fvg" in block:
            attach(block["fvg"])
        if "liquidity" in block:
            attach(block["liquidity"])
    consumed_rates = set()

    def collect(value):
        if isinstance(value, dict):
            if value.get("model") == "research.macroobservation":
                consumed_rates.add(value["id"])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(output_payload)
    consumed_events = set()
    for at in context_cutoffs:
        eligible = [
            e for e in research["events"] if max(e.first_observed_at, e.retrieval.fetched_at) <= at
        ]
        candidates = {
            e.provider_event_key
            for e in eligible
            if at - timedelta(days=context.EVENT_LOOKBACK_DAYS)
            <= e.event_at
            <= at + timedelta(days=context.EVENT_HORIZON_DAYS)
        }
        for key in candidates:
            vintages = [e for e in eligible if e.provider_event_key == key]
            latest = max(vintages, key=lambda e: (e.first_observed_at, e.payload_fingerprint))
            consumed_events.add(latest.pk)
            # An in-window witness is necessary to explain an out-of-window suppressor.
            witness = max(
                (
                    e
                    for e in vintages
                    if at - timedelta(days=context.EVENT_LOOKBACK_DAYS)
                    <= e.event_at
                    <= at + timedelta(days=context.EVENT_HORIZON_DAYS)
                ),
                key=lambda e: (e.first_observed_at, e.payload_fingerprint),
            )
            consumed_events.add(witness.pk)
    evidence_manifest = {
        "events": [
            context.research_lineage(e) for e in research["events"] if e.pk in consumed_events
        ],
        "macro": {
            str(r.pk): context.research_lineage(r)
            for r in research["rates"]
            if r.pk in consumed_rates
        },
    }
    from market.state import terminology

    bad_terms = terminology.terminology_violations(output_payload)
    if bad_terms:
        raise ValueError(f"payload contains noncanonical terminology: {bad_terms}")
    all_available = all(g["state"] == "available" for g in per_granularity.values())
    data_quality_status = "complete" if all_available else "partial"
    return (
        output_payload,
        scope,
        manifest,
        manifest_sha256,
        evidence_manifest,
        identity_digest(evidence_manifest),
        data_quality_status,
    )


@transaction.atomic
def compute_market_state(instrument, definition, information_cutoff, granularities):
    """Compute and persist the descriptive snapshot for ``instrument`` at cutoff.

    Returns ``(snapshot, created)``. Idempotent: recomputing the same identity
    returns the existing snapshot.
    """
    granularities = tuple(granularities)
    synchronize_inputs(instrument, granularities, information_cutoff)
    payload, scope, manifest, manifest_sha256, evidence, evidence_sha, quality = build_market_state(
        instrument, definition, information_cutoff, granularities
    )
    return persist_snapshot(
        instrument,
        definition,
        information_cutoff,
        manifest,
        manifest_sha256,
        payload,
        scope=scope,
        evidence_manifest=evidence,
        evidence_sha256=evidence_sha,
        data_quality_status=quality,
    )
