"""Pure candidate geometry, distinct from execution and continuous forecasts."""

from decimal import Decimal as D
from decimal import localcontext

from market.quality import registered_successor
from market.state.features import contiguous
from market.strategy.contracts import RiskOverlay, SetupCandidate, Unavailable
from market.strategy.trend import ema, sigma


def mean_reversion_risk(current, prior):
    if current is None or prior is None or current <= 0 or prior <= 0:
        return RiskOverlay("fast-mr-h1-v1", None, "daily_volatility_unavailable")
    multiplier = D("0.5") if current / prior > D("1.5") else D(1)
    return RiskOverlay("fast-mr-h1-v1", multiplier, "frozen_high_vol_reduction")


def atr(bars):
    if len(bars) < 15 or not contiguous(bars[-15:]):
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        value = (
            sum(
                (
                    max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                    for a, b in zip(bars[-15:], bars[-14:])
                ),
                D(0),
            )
            / 14
        )
        return value if value > 0 else None


def candidate(
    strategy,
    signal,
    direction,
    stop,
    *,
    target=None,
    available_at=None,
    periods=8,
    exit_at=None,
    evidence=(),
):
    available_at = max(signal.available_at, available_at or signal.available_at)
    entry = registered_successor(signal.timestamp, signal.granularity)
    if available_at > entry:
        return Unavailable(strategy, "confirmation_too_late_for_next_interval")
    end = entry
    for _ in range(periods):
        end = registered_successor(end, signal.granularity)
    risk = direction * (signal.close - stop)
    if risk <= 0:
        return Unavailable(strategy, "invalid_geometry")
    target = signal.close + direction * 2 * risk if target is None else target
    if direction * (target - signal.close) <= 0:
        return Unavailable(strategy, "target_not_ahead")
    return SetupCandidate(
        strategy,
        direction,
        available_at,
        signal.timestamp,
        signal.granularity,
        signal.close,
        stop,
        target,
        entry,
        entry,
        exit_at or end,
        tuple(evidence) + (signal.content_sha256,),
    )


def fast_mean_reversion(inputs):
    strategy = "fast-mr-h1-v1"
    hours = inputs.series("H1")
    if not hours:
        return Unavailable(strategy, "h1_unavailable")
    signal = hours[-1]
    daily = inputs.series("D", before=signal.timestamp)
    volatility = atr(hours)
    if len(daily) < 192 or volatility is None:
        return Unavailable(strategy, "warmup_or_gap")
    with localcontext() as ctx:
        ctx.prec = 34
        closes = tuple(b.close for b in daily)
        current, prior = sigma(closes), sigma(closes[:-1])
        if current is None or prior is None:
            return Unavailable(strategy, "daily_volatility_unavailable")
        equilibrium = ema(closes, 5)
        deviation = (equilibrium - signal.close) / volatility
        trend = ema(closes, 16) - ema(closes, 64)
        if abs(deviation) < 1 or deviation * trend <= 0:
            return Unavailable(strategy, "no_aligned_deviation")
        direction = 1 if deviation > 0 else -1
        return candidate(
            strategy,
            signal,
            direction,
            signal.close - direction * D("1.5") * volatility,
            target=equilibrium,
            periods=6,
            evidence=tuple(b.content_sha256 for b in daily)
            + ("high_vol_half" if current / prior > D("1.5") else "normal_vol",),
        )
