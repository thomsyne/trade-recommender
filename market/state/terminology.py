"""Versioned SMC/ICT terminology registry (design §4.5).

Every adopted term the engine emits is registered here with its plain-language
description, formation/availability/expiry/invalidation semantics, a causal-test
pointer, its limitations and prohibited interpretation, and — because Phase 4 is
feature-only — the explicit statement that it defines no trade entry, exit or
risk. Snapshots and reports fail closed on any term version that is not
registered, and on the undefined free-form vocabulary the brief forbids, so an
unknown label can never be accepted as an authoritative fact.
"""

NOT_IN_PHASE_4 = "not defined in Phase 4"


def _term(name, description, *, formation, availability, expiry, invalidation, limitations):
    return {
        "name": name,
        "description": description,
        "inputs": "completed midpoint OHLC with registered start, completion and observation availability",
        "formula": description,
        "timeframe": ["M15", "H1", "H4", "D", "W", "M"],
        "causal_test": "market.tests.test_phase4_corrections",
        "formation": formation,
        "availability": availability,
        "expiry": expiry,
        "invalidation": invalidation,
        "limitations": limitations,
        "prohibited_interpretation": "descriptive proxy only; no directional conviction",
        "trade_entry": NOT_IN_PHASE_4,
        "trade_exit": NOT_IN_PHASE_4,
        "trade_risk": NOT_IN_PHASE_4,
    }


#: term version -> contract. Keys must match the ``*_V`` version strings emitted
#: in snapshot payloads.
REGISTRY = {
    "compression-expansion-v1": _term(
        "compression before expansion",
        "ATR14 percentile <20 followed within 20 registered successors by percentile >80 "
        "and directional body >=1.5 preceding ATR14; percentiles use up to 100 prior ATRs, "
        "minimum 20; percentile equality does not qualify, body and window equality do.",
        formation="expansion interval completion after the latest pending compression",
        availability="maximum observation/completion of all compression and expansion ATR/population inputs",
        expiry="pending compression expires after 20 successors; completed facts retained in descriptor lookback",
        invalidation="missing registered interval resets pending state",
        limitations="bounded descriptive transition, not independent regime flags or a trading rule",
    ),
    "swing-v1": _term(
        "confirmed swing",
        "A pivot high/low confirmed by L=2 left and R=2 right strictly-lower/higher"
        " registered-consecutive candles.",
        formation="at the pivot bar",
        availability="after R right registered candles complete",
        expiry="none",
        invalidation="none (a fact once confirmed)",
        limitations="strict inequalities; equal levels are not swings",
    ),
    "trend-v1": _term(
        "trend classification",
        "uptrend (HH+HL) / downtrend (LH+LL) / range from the last two confirmed swings.",
        formation="on the latest confirmed swing pair",
        availability="when two highs and two lows are confirmed",
        expiry="superseded by the next classification",
        invalidation="a new confirmed swing pair",
        limitations="range is a defined value, not unavailability",
    ),
    "swing-sequence-v1": _term(
        "swing sequence",
        "HH/HL/LH/LL/equal labels over consecutive same-kind confirmed swings.",
        formation="per confirmed swing",
        availability="with the swing",
        expiry="none",
        invalidation="none",
        limitations="equal prices are labelled equal, not higher/lower",
    ),
    "atr-v1": _term(
        "average true range",
        "mean of the last 14 true ranges on midpoint OHLC.",
        formation="per bar with >= 15 bars",
        availability="contemporaneous with the bar",
        expiry="none",
        invalidation="none",
        limitations="insufficient history is unavailable",
    ),
    "volatility-v1": _term(
        "rolling volatility percentile",
        "percentile of the current ATR among only prior ATR observations.",
        formation="on the latest bar",
        availability="with >= 20 prior ATRs",
        expiry="superseded",
        invalidation="none",
        limitations="uses only prior observations",
    ),
    "vol-regime-v1": _term(
        "volatility regime",
        "compression (<20) / normal / expansion (>80) from the ATR percentile.",
        formation="on the latest bar",
        availability="when the percentile is available",
        expiry="superseded",
        invalidation="none",
        limitations="thresholds versioned",
    ),
    "equilibrium-v1": _term(
        "range equilibrium",
        "midpoint of the latest confirmed swing high/low, with distance in price and ATR.",
        formation="on the latest confirmed swing pair",
        availability="with a confirmed high and low",
        expiry="superseded",
        invalidation="none",
        limitations="ATR distance unavailable when ATR is",
    ),
    "persistence-v1": _term(
        "trend persistence",
        "consecutive bars one side of the equilibrium midpoint over a 20-bar window.",
        formation="on the latest bar",
        availability="when equilibrium is available",
        expiry="superseded",
        invalidation="none",
        limitations="bounded window",
    ),
    "bos-v1": _term(
        "break of structure",
        "a completed close beyond the latest swing extreme in an established trend.",
        formation="at the breaking close",
        availability="when a directional structure is established",
        expiry="superseded",
        invalidation="range has no established structure",
        limitations="wick-only penetration is not a break",
    ),
    "choch-v1": _term(
        "change of character",
        "a completed close beyond the opposing swing (first counter-trend break).",
        formation="at the breaking close",
        availability="when a directional structure is established",
        expiry="superseded",
        invalidation="an ordinary pullback is not a CHoCH",
        limitations="requires an established structure",
    ),
    "zone-v1": _term(
        "support/resistance zone",
        "same-kind swing clusters within both confirmation-time 0.25*ATR margins; a proxy band.",
        formation="at the earliest member swing",
        availability="with the member swings",
        expiry="age > 200 intervals",
        invalidation="a completed close beyond the band by >= 0.25*ATR",
        limitations="identity binds instrument/timeframe/boundaries and member candle content; new members create a new identity",
    ),
    "equal-levels-v1": _term(
        "equal/clustered levels",
        "local highs/lows within 0.1*ATR; a visible-liquidity proxy.",
        formation="at the local extrema",
        availability="with >= 3 bars",
        expiry="none",
        invalidation="none",
        limitations="non-strict extrema surface equal levels",
    ),
    "sd-candidate-v1": _term(
        "supply/demand candidate",
        "origin body of a displacement leg (>= 1.5*ATR + continuation); a proxy candidate.",
        formation="at the displacement origin",
        availability="after the continuation bar",
        expiry="none",
        invalidation="none",
        limitations="no claim of resting orders",
    ),
    "consolidation-v1": _term(
        "consolidation / breakout",
        "a bounded range (<= 1.5*ATR) with breakout / retest / failed-breakout state.",
        formation="over the base window",
        availability="with window + tail bars",
        expiry="superseded",
        invalidation="a completed close back inside (failed)",
        limitations="retest requires holding beyond the boundary",
    ),
    "prior-extreme-v1": _term(
        "prior-period extreme",
        "high/low of a completed prior day/week/month.",
        formation="at period close",
        availability="after the period completes",
        expiry="superseded by the next period",
        invalidation="none",
        limitations="a partial period is never completed",
    ),
    "sweep-v1": _term(
        "liquidity sweep proxy",
        "a wick through a level (>= 0.1*ATR) with a reclaim close on the origin side.",
        formation="at the breach candle",
        availability="on the reclaim close",
        expiry="none",
        invalidation="acceptance beyond the level",
        limitations="proxy for a rejection, not observed order flow",
    ),
    "acceptance-v1": _term(
        "acceptance proxy",
        "a completed close beyond a level not reclaimed within 3 intervals.",
        formation="at the accepting close",
        availability="after the 3-interval window matures",
        expiry="none",
        invalidation="a later reclaim",
        limitations="pending until the window elapses",
    ),
    "fvg-v1": _term(
        "three-candle imbalance (FVG) proxy",
        "a gap between candle 1 and candle 3 of three registered-consecutive candles.",
        formation="at candle 3 completion",
        availability="after all three candles and contemporaneous ATR inputs complete and become observed",
        expiry="unfilled after 50 candles",
        invalidation="full fill or internal-swing break",
        limitations="a proxy, not proof of institutional imbalance",
    ),
    "orb-v1": _term(
        "opening range (ORB)",
        "high/low of the first M15 candle of a session, with breakout/retest/failure.",
        formation="at the opening M15 completion",
        availability="when the opening M15 is available (never substituted)",
        expiry="end of session",
        invalidation="a completed close back inside after breakout",
        limitations="requires the exact opening M15 candle",
    ),
    "session-v1": _term(
        "session policy",
        "London/New York 08:00 opens and the overnight window, converted to UTC.",
        formation="from the session date",
        availability="always",
        expiry="none",
        invalidation="none",
        limitations="holidays not modelled",
    ),
    "spread-v1": _term(
        "spread",
        "observed ask-bid at the candle close; never backfilled.",
        formation="at the candle close",
        availability="when bid/ask are observed",
        expiry="superseded",
        invalidation="none",
        limitations="no historical spread => unavailable",
    ),
    "event-state-v1": _term(
        "scheduled-event state",
        "pair-currency events, vintage-correct, exact vs date-only, severity unavailable.",
        formation="at the event vintage",
        availability="when the vintage is known by the cutoff",
        expiry="past the display window",
        invalidation="a later vintage",
        limitations="no trustworthy severity field; date-only has no intraday window",
    ),
    "macro-regime-v1": _term(
        "macro regime",
        "point-in-time policy-rate level and direction per currency.",
        formation="at the observation vintage",
        availability="vintage known by the cutoff",
        expiry="superseded by a later vintage",
        invalidation="a later vintage",
        limitations="unknown macro state is unavailable, not neutral",
    ),
    "monthly-context-v1": _term(
        "monthly context",
        "trend over completed New York-session months aggregated from daily candles.",
        formation="at month close",
        availability="when every registered daily session is present",
        expiry="superseded",
        invalidation="none",
        limitations="a partial current month is excluded",
    ),
}

REGISTERED_TERMS = frozenset(REGISTRY)

REGISTRY["fvg-v1"]["timeframe"] = ["M15", "H1", "H4"]
REGISTRY["fvg-v1"]["formula"] = (
    "strict three-bar gap; directional middle body >= 1 ATR14; gap >= 0.000001 price, "
    ">= 0.1 ATR14, >= 1 pip, >= 1 candle-3 spread; equality at a minimum qualifies; "
    "absent ATR/spread leaves qualification unavailable"
)
REGISTRY["orb-v1"]["timeframe"] = ["M15"]
REGISTRY["monthly-context-v1"]["timeframe"] = ["D", "M"]
REGISTRY["event-state-v1"]["inputs"] = (
    "EconomicEvent vintage, RawRetrieval, SourcePolicy, source and optional series"
)
REGISTRY["event-state-v1"]["timeframe"] = ["point-in-time"]
REGISTRY["macro-regime-v1"]["inputs"] = (
    "latest and predecessor policy-rate MacroObservation periods, retrievals, source, policy and series"
)
REGISTRY["macro-regime-v1"]["timeframe"] = ["point-in-time"]
REGISTRY["spread-v1"]["inputs"] = "exact candle observation bid/ask close and contemporaneous ATR14"
REGISTRY["session-v1"]["inputs"] = "explicit cutoff and IANA London/New York calendar"

# These fields are authoritative classifications, never provider free text.
CLASSIFICATIONS = {
    "classification": frozenset({"uptrend", "downtrend", "range"}),
    "regime": frozenset({"compression", "normal", "expansion"}),
    "label": frozenset(
        {
            "first_high",
            "first_low",
            "equal_high",
            "equal_low",
            "higher_high",
            "higher_low",
            "lower_high",
            "lower_low",
        }
    ),
    "kind": frozenset({"high", "low", "demand_candidate", "supply_candidate"}),
    "direction": frozenset(
        {"up", "down", "bullish", "bearish", "tightening", "easing", "steady", "unknown"}
    ),
    "side": frozenset({"above", "below", "at"}),
}

#: Undefined labels the brief forbids from persisted snapshots and reports.
BANNED_VOCABULARY = (
    "A+ setup",
    "strong level",
    "clear draw on liquidity",
    "smart money entered",
    "institutional order block",
    "session bias",
    "obvious support",
    "high-probability FVG",
)


def _walk_values(value):
    """Yield every scalar and every ``version`` value in a nested structure."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in CLASSIFICATIONS and (
                not isinstance(item, str) or item not in CLASSIFICATIONS[key]
            ):
                yield ("invalid_classification", "")
            if key == "version":
                if isinstance(item, str):
                    yield ("version", item)
                else:
                    yield ("invalid_classification", "")
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    elif isinstance(value, str):
        yield ("scalar", value)


def terminology_violations(payload):
    """Return bounded reason codes for any unregistered term version or banned
    vocabulary in ``payload``. Empty means canonical."""
    violations = set()
    for kind, value in _walk_values(payload):
        if kind == "invalid_classification":
            violations.add("noncanonical_terminology")
        if kind == "version" and value not in REGISTERED_TERMS:
            violations.add("noncanonical_terminology")
        if kind == "scalar" and value in BANNED_VOCABULARY:
            violations.add("banned_vocabulary")
    return sorted(violations)
