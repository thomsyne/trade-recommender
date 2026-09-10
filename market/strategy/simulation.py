"""Frozen, adverse OHLC model. Outputs are modeled results, never executable fills."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext

from market.calendar_policy import interval_readiness
from market.quality import NEW_YORK, registered_successor
from market.state.canonical import identity_digest
from market.strategy.contracts import ExecutionIntent, ExecutionResult, Unavailable, encoded
from market.strategy.definitions import simulator_definition


@dataclass(frozen=True)
class OutcomeTerms:
    """Explicit complete interval coverage, not an absent-rollover-means-zero guess."""

    source_sha256: str
    quote_currency: str
    account_currency: str
    from_at: datetime
    through_at: datetime
    known_at: datetime
    conversion_at: datetime
    conversion_rate: D
    # Every crossed NY17 rollover must appear, even when its documented cost is zero.
    rollovers: tuple[tuple[datetime, D], ...]


def simulate(setup, bars, *, cost, calendar, profile, terms):
    strategy = setup.strategy
    if cost is None:
        return Unavailable(strategy, "cost_unavailable")
    reason = cost.readiness(setup.available_at, component=strategy)
    if reason:
        return Unavailable(strategy, reason)
    # OHLC cannot locate a delayed intra-interval fill. Never round it backwards.
    if setup.available_at + timedelta(seconds=cost.latency_seconds) > setup.entry_at:
        return Unavailable(strategy, "latency_misses_next_open")
    selected = tuple(b for b in bars if setup.entry_at <= b.timestamp < setup.exit_at)
    if not selected or selected[0].timestamp != setup.entry_at:
        return Unavailable(strategy, "next_interval_missing")
    with localcontext() as ctx:
        ctx.prec = 34
        direction = setup.direction
        entry = selected[0].open
        entry_cost = cost.spread / 2 + cost.slippage_per_side
        modeled_entry = entry + direction * entry_cost
        if (
            direction * (modeled_entry - setup.stop) <= 0
            or direction * (setup.target - modeled_entry) <= 0
        ):
            return Unavailable(strategy, "entry_gap_outside_geometry")
        expected = setup.entry_at
        consumed = []
        for bar in selected:
            if bar.timestamp != expected or bar.granularity != setup.granularity:
                return Unavailable(strategy, "outcome_interval_gap")
            if (
                interval_readiness(
                    bar.timestamp,
                    bar.end,
                    profile=profile,
                    as_of=setup.available_at,
                    attestation=calendar,
                )
                != "attested_open"
            ):
                return Unavailable(strategy, "calendar_unavailable")
            consumed.append(bar.content_sha256)
            adverse, favorable = (bar.low, bar.high) if direction == 1 else (bar.high, bar.low)
            if direction * (bar.open - setup.stop) <= 0:
                exit_price, reason = bar.open, "stop_gap"
            elif direction * (adverse - setup.stop) <= 0:
                exit_price, reason = setup.stop, "stop_adverse_path"
            elif direction * (favorable - setup.target) >= 0:
                exit_price, reason = setup.target, "target_no_improvement"
            elif bar.end >= setup.exit_at:
                exit_price, reason = bar.close, "time_stop"
            else:
                expected = registered_successor(bar.timestamp, setup.granularity)
                continue
            # No tick time: conservative availability and rollover exposure at bar end.
            exited_at = bar.end
            if (
                terms is None
                or not terms.source_sha256
                or terms.quote_currency != cost.quote_currency
                or terms.from_at > setup.entry_at
                or terms.through_at < exited_at
                or terms.known_at > exited_at
                or terms.conversion_at != exited_at
                or not terms.conversion_rate.is_finite()
                or terms.conversion_rate <= 0
            ):
                return Unavailable(strategy, "outcome_terms_unavailable")
            if terms.account_currency == terms.quote_currency and terms.conversion_rate != 1:
                return Unavailable(strategy, "invalid_same_currency_conversion")
            day = setup.entry_at.astimezone(NEW_YORK).replace(
                hour=17, minute=0, second=0, microsecond=0
            )
            required = []
            while day <= exited_at.astimezone(NEW_YORK):
                if setup.entry_at < day <= exited_at:
                    required.append(day)
                day += timedelta(days=1)
            rates = dict(terms.rollovers)
            if len(rates) != len(terms.rollovers) or any(
                t not in rates or not rates[t].is_finite() for t in required
            ):
                return Unavailable(strategy, "rollover_evidence_missing")
            financing = sum((rates[t] for t in required), D(0))
            gross = direction * (exit_price - entry)
            costs = (
                cost.spread + 2 * (cost.slippage_per_side + cost.commission_per_side) + financing
            )
            net = gross - costs
            intent = ExecutionIntent(
                identity_digest(json.loads(encoded(setup))),
                identity_digest(simulator_definition()),
                identity_digest(json.loads(encoded(cost))),
                identity_digest(json.loads(encoded(calendar))),
            )
            return ExecutionResult(
                identity_digest(json.loads(encoded(intent))),
                setup.entry_at,
                exited_at,
                modeled_entry,
                exit_price - direction * entry_cost,
                gross,
                costs,
                net,
                net * terms.conversion_rate,
                tuple(consumed) + (terms.source_sha256,),
                reason,
            )
        return Unavailable(strategy, "time_stop_interval_missing")
