"""Explicit retrospective event-clock projection; never a Phase4 PIT snapshot.

Acquisition clocks remain on every bar. Only this separately registered replay
type exposes simulated availability at interval completion. No production loader
or old persisted contract accepts this type as evidence of historical knowledge.
"""

import bisect
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal as D

from market.state import features, fvg, liquidity, structure
from market.state.canonical import identity_digest
from market.state.features import Bar, bars_are_consecutive
from market.strategy.contracts import arithmetic
from market.strategy.evaluate import evaluate

LOOKBACKS = {"W": 300, "D": 400, "H4": 300, "H1": 300, "M15": 500}


class RetrospectiveBar(Bar):
    @property
    def available_at(self):
        return self.end


class Series:
    @arithmetic
    def __init__(self, rows):
        self.rows = rows
        self.bars = tuple(
            RetrospectiveBar(
                datetime.fromisoformat(row["timestamp"]),
                *(
                    (D(row[f"bid_{name}"]) + D(row[f"ask_{name}"])) / 2
                    for name in ("open", "high", "low", "close")
                ),
                datetime.fromisoformat(row["end"]),
                D(row["ask_close"]) - D(row["bid_close"]),
                row["granularity"],
                datetime.fromisoformat(row["acquired_at"]),
                1,
                identity_digest(row),
            )
            for row in rows
        )
        self.ends = tuple(b.end for b in self.bars)
        self.by_start = {b.timestamp: (b, row) for b, row in zip(self.bars, rows, strict=True)}
        if len(self.by_start) != len(self.bars) or tuple(sorted(self.ends)) != self.ends:
            raise ValueError("replay_series_order")
        self.gaps = [0]
        for a, b in zip(self.bars, self.bars[1:]):
            self.gaps.append(self.gaps[-1] + (not bars_are_consecutive(a, b)))

    def before(self, cutoff, count, *, require_contiguous=False):
        stop = bisect.bisect_right(self.ends, cutoff)
        start = max(0, stop - count)
        if require_contiguous and stop > start and self.gaps[stop - 1] != self.gaps[start]:
            return ()
        return self.bars[start:stop]


@dataclass
class ReplayInput:
    instrument: str
    cutoff: datetime
    data: dict
    strategy: str
    _payload: dict | None = field(default=None, init=False)

    def __post_init__(self):
        if self.cutoff.utcoffset() is None or not (
            datetime(2019, 1, 7, tzinfo=UTC) <= self.cutoff < datetime(2025, 1, 6, tzinfo=UTC)
        ):
            raise ValueError("sealed_or_unregistered_decision_cutoff")

    def series(self, granularity, *, before=None, outcome=False):
        series = self.data.get(granularity)
        if series is None:
            return ()
        return series.before(
            min(self.cutoff, before) if before else self.cutoff,
            LOOKBACKS[granularity],
            require_contiguous=not outcome,
        )

    @property
    @arithmetic
    def payload(self):
        if self._payload is not None:
            return self._payload
        blocks = {}
        if self.strategy.startswith("pullback-"):
            for granularity in ("D", "H4"):
                bars = self.series(granularity)
                blocks[granularity] = {"higher_timeframe": {"trend": features.trend_feature(bars)}}
                if granularity == "H4":
                    blocks[granularity]["structure"] = {
                        "support_resistance_zones": structure.support_resistance_zones(
                            bars, features._current_atr(bars), self.instrument, granularity
                        )
                    }
        elif self.strategy.startswith("phase5-"):
            bars = self.series("H1")
            blocks["H1"] = {
                "liquidity": liquidity.liquidity_context(
                    bars, features._current_atr(bars), self.instrument, "H1"
                )
            }
            blocks["M15"] = {
                "higher_timeframe": {
                    "break_of_structure": features.break_of_structure_feature(self.series("M15"))
                }
            }
        elif self.strategy.startswith("orb-m15-fvg"):
            bars = self.series("M15")
            blocks["M15"] = {
                "fvg": fvg.find_fvgs(
                    bars, D("0.01") if self.instrument.endswith("_JPY") else D("0.0001")
                )
            }
        self._payload = {
            "schema": "phase55/retrospective-features-v1",
            "instrument": self.instrument,
            "granularities": blocks,
            "event_state": {"state": "unavailable", "reason": "genuine_vintages_missing"},
        }
        return self._payload


def decision(instrument, strategy, cutoff, data):
    inputs = ReplayInput(instrument, cutoff, data, strategy)
    return evaluate(inputs, strategy)
