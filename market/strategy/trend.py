"""Continuous forecasts only. All arithmetic is pure, causal and return-blind."""

from decimal import Decimal as D
from decimal import localcontext

from market.state.features import contiguous
from market.strategy.contracts import Component, ContinuousForecast
from market.strategy.definitions import HORIZONS, SPEEDS


def ema(values, span):
    if not values or span < 1:
        raise ValueError("ema_inputs")
    with localcontext() as ctx:
        ctx.prec = 34
        alpha = D(2) / (span + 1)
        value = values[0]
        for observation in values[1:]:
            value += alpha * (observation - value)
        return +value


def sigma(closes):
    if len(closes) < 97:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        variance = ema(tuple((b - a) ** 2 for a, b in zip(closes, closes[1:])), 32)
        return variance.sqrt() if variance > 0 else None


def cap(value):
    return max(D(-20), min(D(20), value))


def buffer(target, previous=D(0)):
    if not previous.is_finite() or abs(previous) > 20:
        raise ValueError("invalid_previous_forecast")
    difference = target - previous
    return previous if abs(difference) <= 1 else target - (1 if difference > 0 else -1)


def combine(strategy, components, previous=D(0)):
    included = [c.capped for c in components if c.exclusion is None]
    with localcontext() as ctx:
        ctx.prec = 34
        value = cap(sum(included, D(0)) / len(included)) if included else None
        return ContinuousForecast(
            strategy,
            value,
            buffer(value, previous) if value is not None else None,
            tuple(components),
            None if included else "no_affordable_available_components",
        )


def _component(name, raw, volatility, costs, cutoff):
    if raw is None:
        return Component(name, None, None, "warmup_or_zero_range")
    cost = costs.get(name)
    reason = "volatility_unavailable" if volatility is None else "cost_unavailable"
    if volatility is not None and cost is not None:
        reason = cost.readiness(cutoff, component=name)
        if reason is None and cost.roundtrip / volatility > D("0.1"):
            reason = "unaffordable"
    return Component(name, raw, cap(raw), reason)


def ewmac(bars, *, costs, cutoff, previous=D(0)):
    """Each speed retains raw/capped value and its exact exclusion independently."""
    with localcontext() as ctx:
        ctx.prec = 34
        closes = tuple(b.close for b in bars) if contiguous(bars) else ()
        volatility = sigma(closes)
        components = []
        for fast, slow, scalar in SPEEDS:
            raw = None
            if len(closes) >= max(3 * slow, 97) and volatility is not None:
                raw = D(scalar) * (ema(closes, fast) - ema(closes, slow)) / volatility
            components.append(_component(f"ewmac-{fast}-{slow}", raw, volatility, costs, cutoff))
        return combine("ewmac-d-v1", components, previous)


def breakout(bars, *, costs, cutoff, previous=D(0)):
    with localcontext() as ctx:
        ctx.prec = 34
        bars = bars if contiguous(bars) else ()
        volatility = sigma(tuple(b.close for b in bars))
        components = []
        for horizon in HORIZONS:
            span = (horizon + 3) // 4
            values = []
            for end in range(horizon, len(bars) + 1):
                window = bars[end - horizon : end]
                high, low = max(b.high for b in window), min(b.low for b in window)
                if high == low:
                    values = []
                    continue
                values.append(40 * (window[-1].close - (high + low) / 2) / (high - low))
            raw = ema(values, span) if len(values) >= 3 * span else None
            components.append(_component(f"breakout-{horizon}", raw, volatility, costs, cutoff))
        return combine("breakout-d-v1", components, previous)
