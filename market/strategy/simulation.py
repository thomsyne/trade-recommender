"""Frozen, adverse OHLC model. Outputs are modeled results, never executable fills."""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext

from market.calendar_policy import interval_readiness
from market.quality import NEW_YORK, registered_successor
from market.state.canonical import identity_digest
from market.strategy.contracts import (
    ExecutionIntent,
    ExecutionResult,
    Unavailable,
    arithmetic,
    encoded,
)
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
    base_currency: str = ""
    provenance: str = ""
    cost_unit: str = ""
    conversion_unit: str = ""

    def valid(self):
        currencies = {"USD", "CAD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "NOK", "SEK"}
        times = (self.from_at, self.through_at, self.known_at, self.conversion_at)
        return (
            all(
                isinstance(c, str) and c in currencies
                for c in (self.base_currency, self.quote_currency, self.account_currency)
            )
            and self.base_currency != self.quote_currency
            and isinstance(self.source_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is not None
            and isinstance(self.provenance, str)
            and bool(self.provenance.strip())
            and self.cost_unit == "quote_per_base"
            and self.conversion_unit == "account_per_quote"
            and all(isinstance(t, datetime) and t.utcoffset() is not None for t in times)
            and self.from_at <= self.conversion_at <= self.through_at
            and self.known_at <= self.conversion_at
            and isinstance(self.conversion_rate, D)
            and self.conversion_rate.is_finite()
            and self.conversion_rate > 0
            and isinstance(self.rollovers, tuple)
            and all(
                isinstance(t, datetime)
                and t.utcoffset() is not None
                and self.from_at <= t <= self.through_at
                and isinstance(rate, D)
                and rate.is_finite()
                for t, rate in self.rollovers
            )
        )


@arithmetic
def simulate(setup, bars, *, cost, calendar, profile, terms):
    if setup.strategy == "fast-mr-h1-v1":
        return simulate_limit(
            setup, bars, cost=cost, calendar=calendar, profile=profile, terms=terms
        )
    return _simulate(
        setup, bars, cost=cost, calendar=calendar, profile=profile, terms=terms, limit=False
    )


@arithmetic
def simulate_limit(setup, bars, *, cost, calendar, profile, terms):
    if setup.strategy != "fast-mr-h1-v1" or setup.granularity != "H1":
        raise ValueError("limit_strategy_attribution")
    return _simulate(
        setup, bars, cost=cost, calendar=calendar, profile=profile, terms=terms, limit=True
    )


def _simulate(setup, bars, *, cost, calendar, profile, terms, limit):
    strategy = setup.strategy
    if cost is None:
        return Unavailable(strategy, "cost_unavailable")
    reason = cost.readiness(setup.available_at, component=strategy)
    if reason:
        return Unavailable(strategy, reason)
    # OHLC cannot locate a delayed intra-interval fill. Never round it backwards.
    if setup.available_at + timedelta(seconds=cost.latency_seconds) > setup.entry_at:
        return Unavailable(strategy, "latency_misses_next_open")
    # The decision owns its signal bar; intervening prerequisite intervals must
    # be present even when the outcome snapshot has a later, longer suffix.
    expected = registered_successor(setup.signal_start, setup.granularity)
    prerequisites = {b.timestamp: b for b in bars if expected <= b.timestamp < setup.entry_at}
    while expected < setup.entry_at:
        if expected not in prerequisites:
            return Unavailable(strategy, "pre_entry_interval_gap")
        expected = registered_successor(expected, setup.granularity)
    selected = tuple(b for b in bars if setup.entry_at <= b.timestamp < setup.exit_at)
    if not selected or selected[0].timestamp != setup.entry_at:
        return Unavailable(strategy, "next_interval_missing")
    with localcontext() as ctx:
        ctx.prec = 34
        direction = setup.direction
        entry = selected[0].open
        entry_cost = cost.spread / 2 + cost.slippage_per_side
        modeled_entry = entry + direction * entry_cost
        if not limit and (
            direction * (modeled_entry - setup.stop) <= 0
            or direction * (setup.target - modeled_entry) <= 0
        ):
            return Unavailable(strategy, "entry_gap_outside_geometry")
        expected = setup.entry_at
        consumed = []
        entered_at = None if limit else setup.entry_at
        # Candidate expiry bounds placement, not order lifetime. Recording delay
        # can move placement to that boundary; retain one eligible H1 of validity.
        order_expires = registered_successor(setup.entry_at, setup.granularity)
        for bar in selected:
            if bar.timestamp != expected or bar.granularity != setup.granularity:
                return Unavailable(strategy, "outcome_interval_gap")
            if bar.end is None or bar.end > cost.valid_through:
                return Unavailable(strategy, "cost_horizon_unavailable")
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
            if entered_at is None:
                if bar.timestamp >= order_expires:
                    return Unavailable(strategy, "limit_expired_unfilled")
                quote_open = bar.open + direction * cost.spread / 2
                quote_edge = (bar.low if direction == 1 else bar.high) + direction * cost.spread / 2
                if direction * (quote_open - setup.reference) <= 0:
                    if direction * (bar.open - setup.stop) <= 0:
                        return Unavailable(strategy, "limit_gap_beyond_invalidation")
                    entered_at = bar.timestamp
                    modeled_entry = setup.reference
                    entry = setup.reference - direction * cost.spread / 2
                elif direction * (quote_edge - setup.reference) <= 0:
                    return Unavailable(strategy, "limit_intrabar_fill_unavailable")
                else:
                    expected = registered_successor(bar.timestamp, setup.granularity)
                    if expected >= order_expires:
                        return Unavailable(strategy, "limit_expired_unfilled")
                    continue
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
                not isinstance(terms, OutcomeTerms)
                or not terms.valid()
                or terms.quote_currency != cost.quote_currency
                or terms.from_at > entered_at
                or terms.through_at < exited_at
                or terms.known_at > exited_at
                or terms.conversion_at != exited_at
                or not terms.conversion_rate.is_finite()
                or terms.conversion_rate <= 0
            ):
                return Unavailable(strategy, "outcome_terms_unavailable")
            if terms.account_currency == terms.quote_currency and terms.conversion_rate != 1:
                return Unavailable(strategy, "invalid_same_currency_conversion")
            day = entered_at.astimezone(NEW_YORK).replace(
                hour=17, minute=0, second=0, microsecond=0
            )
            required = []
            while day <= exited_at.astimezone(NEW_YORK):
                if entered_at <= day <= exited_at:
                    required.append(day)
                day += timedelta(days=1)
            rates = dict(terms.rollovers)
            if len(rates) != len(terms.rollovers) or any(
                t not in rates or not rates[t].is_finite() for t in required
            ):
                return Unavailable(strategy, "rollover_evidence_missing")
            # At entry or within the exit interval, rollover ordering is unknown:
            # charge adverse fees, but never award a possibly unearned credit.
            financing = sum(
                (
                    rates[t] if entered_at < t < bar.timestamp else max(D(0), rates[t])
                    for t in required
                ),
                D(0),
            )
            gross = direction * (exit_price - entry)
            costs = (
                cost.spread
                + (1 if limit else 2) * cost.slippage_per_side
                + 2 * cost.commission_per_side
                + financing
            )
            net = gross - costs
            intent = ExecutionIntent(
                identity_digest(json.loads(encoded(setup, exact=True))),
                identity_digest(simulator_definition(strategy)),
                identity_digest(json.loads(encoded(cost, exact=True))),
                identity_digest(json.loads(encoded(calendar, exact=True))),
            )
            return ExecutionResult(
                identity_digest(json.loads(encoded(intent))),
                entered_at,
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
