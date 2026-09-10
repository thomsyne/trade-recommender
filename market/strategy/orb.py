"""Three separately attributable M15-only ORB variants; no M1 interpolation."""

from datetime import datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext

from market.state.features import contiguous
from market.state.sessions import session_open_utc
from market.strategy.contracts import Unavailable, arithmetic, iso
from market.strategy.setups import atr, candidate


@arithmetic
def opening_range(inputs, *, session, session_date, variant):
    if session not in ("london", "new_york") or variant not in (
        "orb-m15-wick-v1",
        "orb-m15-confirmed-v1",
        "orb-m15-fvg-v1",
    ):
        raise ValueError("unsupported_orb_variant")
    strategy = f"{variant}:{session}"
    if session_date.weekday() >= 5:
        return Unavailable(strategy, "weekend_session")
    start, _, _ = session_open_utc(session_date, session)
    bars = inputs.series("M15")
    opening_index = next((i for i, b in enumerate(bars) if b.timestamp == start), None)
    if opening_index is None:
        return Unavailable(strategy, "opening_interval_missing")
    opening = bars[opening_index]
    volatility = atr(bars[: opening_index + 1])
    if volatility is None:
        return Unavailable(strategy, "opening_atr_unavailable")
    with localcontext() as ctx:
        ctx.prec = 34
        if not D("0.25") <= (opening.high - opening.low) / volatility <= 2:
            return Unavailable(strategy, "opening_range_geometry")
        for i in range(opening_index + 1, len(bars)):
            signal = bars[i]
            if signal.end > start + timedelta(hours=2):
                break
            if not contiguous(bars[opening_index : i + 1]):
                return Unavailable(strategy, "session_gap")
            if variant == "orb-m15-wick-v1":
                above, below = signal.high > opening.high, signal.low < opening.low
                if above and below:
                    return Unavailable(strategy, "ambiguous_dual_breach")
            else:
                above, below = signal.close > opening.high, signal.close < opening.low
            if not above and not below:
                continue
            direction = 1 if above else -1
            # First attempt is terminal even when geometry/data is unavailable.
            if signal.spread is None or signal.spread <= 0 or signal.spread / volatility > D("0.1"):
                return Unavailable(strategy, "confirmation_spread_unavailable_or_wide")
            available = max(b.available_at for b in bars[max(0, opening_index - 14) : i + 1])
            evidence = [b.content_sha256 for b in bars[max(0, opening_index - 14) : i + 1]]
            if variant == "orb-m15-fvg-v1":
                block = inputs.payload.get("granularities", {}).get("M15", {}).get("fvg", {})
                gaps = [
                    g
                    for g in block.get("fvgs", ())
                    if g.get("created_at") == iso(signal.end)
                    and g.get("direction") == ("bullish" if direction == 1 else "bearish")
                    and g.get("qualification", {}).get("state") == "available"
                ]
                if block.get("version") != "fvg-v1" or len(gaps) != 1:
                    return Unavailable(strategy, "same_direction_fvg_unavailable")
                gap = gaps[0]
                if i < 2 or gap["formation_start"] != iso(bars[i - 2].timestamp):
                    return Unavailable(strategy, "fvg_interval_mismatch")
                available = max(available, datetime.fromisoformat(gap["available_at"]))
            margin = max(D("0.25") * volatility, 2 * signal.spread)
            stop = opening.low - margin if direction == 1 else opening.high + margin
            return candidate(
                strategy,
                signal,
                direction,
                stop,
                available_at=available,
                exit_at=start + timedelta(hours=8),
                evidence=tuple(evidence),
            )
        return Unavailable(strategy, "no_confirmation_before_expiry")
