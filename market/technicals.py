from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TechnicalValues:
    atr_14: Decimal | None
    ewma_20: Decimal | None
    prior_high: Decimal | None
    prior_low: Decimal | None
    support: Decimal | None
    resistance: Decimal | None


def calculate_technicals(candles):
    candles = list(candles)
    if not candles:
        return TechnicalValues(None, None, None, None, None, None)

    closes = [_midpoint_close(candle) for candle in candles]
    true_ranges = []
    for index, candle in enumerate(candles):
        high = (candle.bid_high + candle.ask_high) / 2
        low = (candle.bid_low + candle.ask_low) / 2
        previous_close = closes[index - 1] if index else closes[index]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr = sum(true_ranges[-14:]) / min(len(true_ranges), 14)

    alpha = Decimal(2) / Decimal(21)
    ewma = closes[0]
    for close in closes[1:]:
        ewma = alpha * close + (Decimal(1) - alpha) * ewma

    previous = candles[-2] if len(candles) > 1 else None
    supports, resistances = _pivots(candles)
    latest = closes[-1]
    support_candidates = [value for value in supports if value < latest]
    resistance_candidates = [value for value in resistances if value > latest]
    return TechnicalValues(
        atr_14=_price(atr),
        ewma_20=_price(ewma),
        prior_high=_price((previous.bid_high + previous.ask_high) / 2) if previous else None,
        prior_low=_price((previous.bid_low + previous.ask_low) / 2) if previous else None,
        support=_price(max(support_candidates)) if support_candidates else None,
        resistance=_price(min(resistance_candidates)) if resistance_candidates else None,
    )


def _pivots(candles, window=2):
    supports, resistances = [], []
    for index in range(window, len(candles) - window):
        group = candles[index - window : index + window + 1]
        current = candles[index]
        low = (current.bid_low + current.ask_low) / 2
        high = (current.bid_high + current.ask_high) / 2
        if low == min((candle.bid_low + candle.ask_low) / 2 for candle in group):
            supports.append(low)
        if high == max((candle.bid_high + candle.ask_high) / 2 for candle in group):
            resistances.append(high)
    return supports, resistances


def _midpoint_close(candle):
    return (candle.bid_close + candle.ask_close) / 2


def _price(value):
    return value.quantize(Decimal("0.000001"))
