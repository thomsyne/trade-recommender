"""Pure offline dispatch. This is deliberately absent from operations dispatch."""

import json
from datetime import datetime
from decimal import Decimal as D
from decimal import localcontext
from zoneinfo import ZoneInfo

from market.state.sessions import SESSIONS
from market.strategy.contracts import (
    Component,
    ContinuousForecast,
    SetupCandidate,
    Unavailable,
    encoded,
)
from market.strategy.costs import CostEvidence
from market.strategy.definitions import STRATEGIES
from market.strategy.orb import opening_range
from market.strategy.risk import (
    carry_readiness,
    macro_overlay,
    surprise_readiness,
    volatility_overlay,
)
from market.strategy.setups import atr, fast_mean_reversion, mean_reversion_risk
from market.strategy.structure import failed_break, pullback, range_reversion
from market.strategy.trend import breakout, cap, ema, ewmac, sigma


def cost_from_payload(body):
    body = dict(body)
    for field in ("known_at", "valid_from", "valid_through"):
        body[field] = datetime.fromisoformat(body[field])
    for field in ("spread", "commission_per_side", "slippage_per_side", "financing_reserve"):
        body[field] = D(body[field]) if body[field] is not None else None
    return CostEvidence(**body)


def evaluate(inputs, strategy, *, costs=(), previous=D(0)):
    if strategy not in STRATEGIES:
        raise ValueError("unsupported_strategy")
    if len({c.component for c in costs}) != len(costs):
        raise ValueError("duplicate_component_cost")
    if any(c.quote_currency != inputs.payload["instrument"].split("_")[1] for c in costs):
        raise ValueError("cost_currency_mismatch")
    with localcontext() as ctx:
        ctx.prec = 34
        if strategy in ("ewmac-d-v1", "breakout-d-v1"):
            function = ewmac if strategy == "ewmac-d-v1" else breakout
            results = (
                function(
                    inputs.series("D"),
                    costs={c.component: c for c in costs},
                    cutoff=inputs.cutoff,
                    previous=previous,
                ),
            )
        elif strategy == "fast-mr-h1-v1":
            setup = fast_mean_reversion(inputs)
            results = [setup]
            hours = inputs.series("H1")
            daily = inputs.series("D", before=hours[-1].timestamp) if hours else ()
            closes = tuple(b.close for b in daily)
            reduction = mean_reversion_risk(sigma(closes), sigma(closes[:-1]))
            results.append(reduction)
            volatility = atr(hours)
            if not isinstance(setup, Unavailable) and volatility is not None:
                raw = 10 * (ema(closes, 5) - hours[-1].close) / volatility
                value = cap(raw) * reduction.multiplier
                results.append(
                    ContinuousForecast(
                        strategy, value, value, (Component("h1-deviation", raw, value, None),)
                    )
                )
        elif strategy.startswith("orb-"):
            variant, session = strategy.split(":")
            day = inputs.cutoff.astimezone(ZoneInfo(SESSIONS[session]["timezone"])).date()
            results = (opening_range(inputs, session=session, session_date=day, variant=variant),)
        elif strategy.startswith("pullback-"):
            results = (pullback(inputs, "M15" if "m15" in strategy else "H1"),)
        elif strategy == "range-m15-v1":
            results = (range_reversion(inputs),)
        elif strategy.startswith("phase5-"):
            results = (failed_break(inputs, continuation="acceptance" in strategy),)
        elif strategy == "carry-readiness-v1":
            results = (carry_readiness(inputs),)
        elif strategy == "macro-risk-v1":
            results = (macro_overlay(inputs), surprise_readiness(inputs))
        else:
            results = (volatility_overlay(inputs, strategy),)
    results = tuple(
        Unavailable(strategy, "snapshot_cutoff_after_entry")
        if isinstance(result, SetupCandidate) and result.entry_at < inputs.cutoff
        else result
        for result in results
    )
    return {
        "schema": "phase5/evaluation-v1",
        "strategy": strategy,
        "outputs": [json.loads(encoded(r)) for r in results],
        "activation": "forbidden",
    }
