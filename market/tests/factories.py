from datetime import UTC, datetime
from decimal import Decimal

from market.oanda import CandleData


def candle(timestamp=None, **changes):
    values = {
        "timestamp": timestamp or datetime(2026, 1, 5, tzinfo=UTC),
        "complete": True,
        "volume": 100,
        "bid_open": Decimal("1.1000"),
        "bid_high": Decimal("1.1020"),
        "bid_low": Decimal("1.0990"),
        "bid_close": Decimal("1.1010"),
        "ask_open": Decimal("1.1002"),
        "ask_high": Decimal("1.1022"),
        "ask_low": Decimal("1.0992"),
        "ask_close": Decimal("1.1012"),
    }
    values.update(changes)
    return CandleData(**values)
