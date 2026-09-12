# Phase5.5 validation protocol v1 — pre-outcome specification

No outcomes have been calculated. This specification fixes the model choices
before development; the executable registration must additionally bind verified
acquisition manifests, coverage audit, all source hashes and registration time.
Missing metadata cannot be replaced with invented manifests. Acquisition and
retrospective diagnostics are not broker-observed execution, historical PIT or
economic acceptance. The historical holdout remains sealed until explicitly
released after independent review; this engineering candidate has no release flag.

## Identity and persistence

Each validation identity is the hash of the protocol, original Phase5 revision-2
definition digest, unchanged formula implementation digest, unchanged simulator
definition digest, instrument population, exact immutable input manifests, periods,
cost/execution model, opportunities, missingness and report schema. Original
Phase5 definitions and their 2026-09-11/2027 prospective population remain intact.
The historical replay is a new validation revision, never an old StrategyEvaluation
or StrategySimulation. Every change to formulas, parameters, filters, sources,
population or modeled execution creates a new immutable revision.

Acquisition time, model registration time and historical interval time are separate
fields. Do not fabricate a historical `known_at` or manufacture Phase4 snapshots
that claim newly acquired bars were historically available. Retrospective feature
replay may use final candles completed by a simulated decision cutoff under the
new explicitly labeled replay contract; actual acquisition times remain attached.
Revision-prone macro/event/calendar/financing evidence still needs genuine vintages.

## Sources and cost model selected without strategy outcomes

Sources read 2026-09-11 (current documentation, not historical account evidence):

1. https://developer.oanda.com/rest-live-v20/instrument-df/ defines BA OHLC,
   interval-start timestamps, price-count volume and completeness. Bid/ask highs
   and lows need not occur simultaneously; their differences are not spread samples.
2. https://join.oanda.com/ca-en/core-spreads-q1-2025/ states
   “commissions of only CAD$1 per 10,000 units traded” with CAD$10K eligibility.
   This is a Canadian published pricing reference, not proof this practice
   account qualified or that the rate applied during 2017–2026.
3. https://www.oanda.com/ca-en/trading/our-pricing explains liquidity-provider
   pricing and separate spread-only/core-commission plans. Account-specific
   historical pricing is not established by instrument BA candles.
4. https://www.oanda.com/ca-en/trading/ states regular FX hours approximately
   Sunday 17:00 through Friday 17:00 New York, subject to DST/public holidays.
5. Existing Phase5 fixes separate costs, no favorable target-gap improvement,
   adverse stop-gap/dual-hit treatment, strict missingness and the MR limit model.

Baseline regular-session diagnostic model:
- **Observed spread:** at each modeled market entry/exit use BA open or BA close
  as applicable; accounting relative to the midpoint charges the corresponding
  half-spread once. For intrabar stop/target (no simultaneous quote known), charge
  half of max(open spread, close spread) for that candle as a labeled proxy.
  Never add the same spread again after using side-specific bid/ask prices.
- **Modeled commission reserve:** CAD 0.0001 per base unit per side, using the
  published CAD1/10000 reference. This is an incremental uncertainty reserve,
  not a second assertion of observed broker commission. It intentionally adds
  conservative cost even if the source BA spread embeds spread-only pricing.
  Report that ambiguity, do not relabel BA as a core spread or infer zero fees.
- **Modeled market slippage:** one observed/proxy spread per side. Adverse model
  doubles this to two spreads per side and doubles commission reserve to
  CAD 0.0002/base/side. These are explicit scenario magnitudes, not empirically
  established upper bounds on real slippage. No finite OHLC-derived slippage
  guarantee exists. A nonpositive/unavailable spread blocks the model.
- **Pair/session awareness:** use each pair's contemporaneous BA spread and
  preserve London/New York/other interval attribution. No pooled spread estimate,
  universal pip charge, held-out calibration or best-cost selection. Model values
  vary directly with each pair/session's observed BA data, not with strategy results.
- **Limit entries:** retain `adverse-limit-h1-v1` opening-through-limit only,
  limit price with no entry slippage/improvement; exit cost remains adverse.
  Intrabar touch, queue ambiguity and beyond-invalidation gap remain unavailable.
- **Financing:** no stress-rate substitution. Any modeled holding that touches
  or crosses NY17 rollover without genuine financing/rollover evidence is
  unavailable, including equality/ambiguous exit boundaries. Do not force-close
  positions early to evade missingness without creating another hypothesis.
- **Conversion:** CAD account; require contemporaneous complete BA conversion
  candle for quote→CAD, via USD where necessary. Use adverse side for conversion,
  separate conversion cost from gross/other costs, with no future interval.
  This is a retrospective conversion proxy, not account-observed conversion.
  Missing conversion or an inconsistent route is unavailable. CAD needs identity
  conversion, explicitly recorded rather than an inferred missing zero-cost source.
- **Calendar:** regular-session model only. Observed candle presence is not an
  exceptional-session attestation. Missing expected intervals make affected
  decisions/active trades unavailable; gaps after terminal exit do not invalidate
  the completed prefix. Missing exceptional-session/event vintages are a visible
  integrity limitation and **prevent retention regardless of diagnostic returns**.

No broker executable-fill claim; no ticks, path, queue or actual order lifecycle
inferred from candles. Both baseline and adverse results are required; an absent
scenario is not zero. The regular-session model is a new immutable retrospective
execution revision referencing, not silently rewriting, the Phase5 simulator.

## Forecast-to-exposure and opportunity contracts

- EWMAC and breakout remain independent. Use their unchanged equal-available-
  affordable component combination and ±20 forecast cap, with buffer width 1.
  Desired exposure at the next eligible D opening is buffered forecast/20 times
  a baseline cap: min(1 account-notional equivalent, 0.5% account equity divided
  by one daily price-change sigma expressed in account currency). No leverage
  above one account-notional equivalent; no risk above that baseline; sizing
  uses prior completed observations only. Charge observed spread and modeled
  costs on absolute exposure change, not on every held bar or a fictitious trade.
  Never reset buffer inside a continued chunk. Daily holdings requiring absent
  financing remain unavailable, not zero-return daily observations.
- Setup versions use unchanged geometry, target, stop, expiry, first-attempt and
  entry timing. Planned stop risk cap is 0.5% account equity per instrument with
  notional capped at one account-equivalent. One active trade per identity/pair;
  opportunities while active remain counted as occupied, not separate trades.
- Each ORB identity gets one opportunity per weekday local session-day, including
  missing data/no setup/unavailable executions. Compare confirmed/FVG on the
  same pair/session/day grid, not each variant's selected trade days. A genuinely
  observed no-trade is zero exposure; unavailable is null and cannot be paired
  as zero. FVG needs positive paired weekly net increment over confirmed.
- Fast MR and H1 pullback: each regular H1 opening; M15 pullback, sweep reversal,
  acceptance continuation and range: each regular M15 opening. Continuous
  forecast: each regular daily opening. Warm-up never contributes scored returns.
  No selection on future completeness or whether a trade succeeds.
- Macro/fixed/EWMA/Student-t GARCH are paired risk-only overlays on identical
  baseline opportunities, separately by baseline identity. No directional macro
  returns or cross-family pooling. Multipliers remain [0,1]. Missing fit, baseline
  or macro vintage means unavailable, never neutral/safe or substitute solver.
- Carry has daily readiness opportunities but no carry direction without genuine
  PIT forwards/financing/rollover/broad ranking. Range and macro preserve mandatory
  event/regime/vintage gates. Prior failed-break negative evidence stays attached
  to its original era; historical reuse is not a fresh discovery population.

## Preregistered robustness and decisions

Evaluate baseline and adverse costs, one extra eligible interval latency, removal
of the best net instrument, removal of the best net UTC month, both chronological
halves, long/short, each session, high-volatility and event-period strata, missing
data, and adverse gap/dual-hit treatment. No parameter sweep. Event strata are
unavailable without vintage evidence. For extra latency, retain the same signal,
geometry/expiry; later information may not improve the decision.

Primary dependence unit is UTC ISO week across overlapping currency exposure;
merge linked weeks for positions crossing weeks. Raw trades are not independent.
Require ≥52 effective active weeks overall, ≥20 each half, ≥100 eligible
opportunities and ≥30 modeled trades for a directional identity. These are
minimum evidence gates, not statistical significance claims. Overlay comparisons
require the same matched opportunity set; report matched/unmatched counts.

Retain for Phase6 consideration only requires replay/integrity clean, positive
development and released holdout net overall/both halves, positive adverse-cost
net, positive net after removing best instrument/month, no >50% absolute-net
concentration in one instrument or UTC month, adequate dependence units and no
leakage/execution concern. Identity-level multi-instrument retention needs at least
three instruments with usable evidence; individual-instrument diagnostics do not
constitute a pooled pass. ORB session-specific identities do not pretend to prove
cross-session diversification. FVG additionally needs positive paired weekly
increment. No retention is possible while exceptional-session evidence is absent.

Negative/cost-consumed/fragile/concentrated/nonincremental complete diagnostic
evidence supports development rejection. Missing, insufficient or conflicting
evidence is inconclusive, never pass. Development may propose new hypotheses only
as separately registered revisions. Final candidate set, reports, thresholds and
exact holdout manifests must be frozen before explicit one-time release.

## Reporting and forward boundary

JSON and plain English must include all 19 identities, original and validation
versions, instrument/session and nonpooled attributable aggregates; opportunities,
trades, occupied/no-setup counts, exact unavailable reason counts, active/effective
UTC weeks, gross, observed spread, modeled commission/slippage, financing and
conversion separately, net CAD/account returns, turnover/holding duration,
drawdown/worst week/tails, long/short, concentration, halves, currency/concurrent
overlap, baseline/adverse scenarios and matched comparators. Unavailable numeric
metrics are null, not zero. Every row binds manifests and mode/integrity limitations.
Deterministic bytes, immutable identities, restart checkpoints and mismatch refusal
are engineering requirements, not promotion authority.

Forward shadow starts 2026-09-11 UTC, offline for 8–12 weeks (earliest complete
8 weeks 2026-11-06; 12 weeks 2026-12-04). Future intervals and unelapsed evidence
remain unavailable. No schedule, recommendation, sizing consumer, order or activation.
