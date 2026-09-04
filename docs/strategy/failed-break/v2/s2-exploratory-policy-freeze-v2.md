# Failed-break v2 effective exploratory-only S2 policy freeze

Status: `EFFECTIVE_EXPLORATORY_ONLY` as of 2026-09-04. The canonical JSON
artifact is authoritative. This gate freezes policy only and grants no return
implementation or execution authority.

## Governed identities

- Repository baseline: `c1abe04199bd7e12159c0ed933b0c5ea023e0c0c`
- V2 S1 acceptance artifact: `5760dd2dd60a2d6a6087b5116b085a8a3774db1512962af0622bc0e3eeed93d5`
- V2 geometry artifact: `b3bc76fa4ac226793a24f11a9a65f9b549e7231ace11e399f6d81c1599e41fdc`
- V2 geometry self-hash: `a3c2f7e3f3f7d722228233c158b51eaa296557daf0c19860c79848a788ffc140`
- Event set: `8abb97a0e658d7079b9cfffd66259609b00f7c57aba89209a01cb5673df9fbd8`
- Membership set: `7bf33678f10ddbb395757baf1cefd2e460ecd35cd76f28bab2d545ba504a2396`
- Effective v2 artifact SHA-256: `1d4b1f451a60d7c2ac37a2fe91849d463254b7751529324e52198003de1ae8dc`
- Effective v2 policy self-hash: `e2d2a4880e0d900a150a6e801d940b32b09b8cd1435f283a87fe16555e059d72`

## Permanent boundary

This strategy version and the registered 2010-2018 cohort are exploratory-only,
promotion-ineligible, and permanently prohibited from promotion or live-trading
authorization regardless of any future outcome. Owner, CLI, environment,
database, data-only, successful-outcome, and threshold-reinterpretation
overrides are prohibited. A future confirmatory study requires a separately
governed, genuinely untouched cohort.

Policy freeze is authorized and effective. Return-calculator implementation,
persistent return execution, backtesting, promotion, live trading, providers,
production, and deployment remain unauthorized.

## Reused v1 decisions

The loader reconstructs the merged effective v1 S2 policy before accepting this
v2 policy. S2-01 through S2-07 are reused with their exact governed hashes:

- S2-01 theoretical accounting, margin, unit granularity and point-in-time valuation;
- S2-02 additional-slippage and cash-flow timing conventions;
- S2-03 statistical and descriptive metric conventions;
- S2-04 minimum evidence and coverage floors;
- S2-05 practical-effect and joint evaluation rules;
- S2-06 concentration definitions and limits;
- S2-07 ambiguity, replay fidelity and optional-M1 conventions.

Entry, stop, target, ten-provider-D-session exit, conversion, spread, cost,
ordering, bootstrap, concentration, ambiguity, Sharpe and Sortino semantics are
unchanged. The v1 artifact remains independent and does not automatically
govern v2.

The only accounting overlay is explicitly owner-authorized for v2: one physical
event is one risk and return unit. Book memberships remain non-additive
attributions. The accepted common-fraction ordering is retained, but every
event's memberships are collapsed to one risk request before allocation. This
prevents duplicated capital or duplicated trade counts.

## Accepted v2 geometry and statistical policy

The effective policy binds 82 geometry-eligible physical events, 186 book
memberships, 76 entry dates, 68 entry weeks, week Kish `1681/28`
(`60.0357142857`), 69 shared-factor clusters, and shared-factor Kish `3362/55`
(`61.1272727273`). Week Kish is the conservative effective sample. Confirmed
setup Kish cannot substitute for trade-level effective sample size, and book
memberships cannot be represented as independent trades.

The primary result is normalized physical-event return in R. Every one of the
82 events requires a governed terminal classification; missing or ambiguous
evidence becomes `UNRESOLVED_DATA` and cannot be silently omitted.

The geometry/MDE diagnostic grid is `[0.5R, 1.0R, 1.5R]` at target effect
`0.20R`: adequate only at `0.5R`, and inadequate at `1.0R` and `1.5R`.
Confirmatory adequacy is absent across the grid. The separate v1 S2-03
hypothetical statistical-sensitivity grid remains `[0.5R, 1.0R, 2.0R]`.
Neither grid may substitute for the other or be selected or reinterpreted after
returns are observed.

Bootstrap conventions remain: 10,000 deterministic replicates, exact
SHA-256 counter-stream seeds, aligned New York calendar-week resampling,
stationary-bootstrap block rounding, two-sided 95% percentile intervals at
0.025 and 0.975 with the frozen linear quantile convention, and preservation of
simultaneous/cross-pair members. Sharpe and Sortino remain descriptive only.

## CAD 10,000 diagnostic

The diagnostic uses fixed CAD 10,000 reference capital and three fixed risks per
physical event: 0.25% = CAD 25, 0.50% = CAD 50, and 1.00% = CAD 100. It has no
compounding, deposits, withdrawals, retrospective resizing, or leveraged target
scenario. Same-event books share one risk budget. Concurrent physical events
retain their individual fixed risk and must report peak aggregate exposure.

Daily equity and drawdown use the v1 governed 17:00 New York side-aware mark.
Monthly P&L uses all 108 development months and consecutive governed month-end
equity changes; empty unchanged months are zero. Annual P&L uses New York
calendar years 2010 through 2018. The complete output set includes total and
ending equity, average/median monthly P&L, month signs and activity, best/worst
month, CAD and initial-capital drawdown, annual P&L, counts at CAD 800/CAD 1,000,
and the algebraic risk needed to average those targets. The latter is explicitly
a diagnostic, undefined for incomplete terminal evidence or non-positive total
net R, and never a sizing recommendation.

CAD 10,000 is not claimed sufficient for broker margin or minimum trade size.
The unconstrained-theoretical-notional and non-tradable classifications remain
applicable.

## Costs

Observed bid/ask spread remains governed. Additional slippage is exactly zero
and no separate slippage model or axis exists; this optimistic limitation is an
additional reason results cannot authorize promotion or live trading. The
sensitivity grid is exactly three commission assumptions `[0, 0.5, 1]` pips by
five annual financing assumptions `[-0.06, -0.03, 0, 0.03, 0.06]`, for 15 cells.
No cell may be selected after viewing results. Gross R and scenario-net R must
be reported separately.

## Freeze isolation

Construction and verification read committed governance artifacts only. No
database, candle payload, post-entry price, outcome, return, P&L, provider,
credential, production, or network path was used. No return calculator or
execution command exists in this gate.
