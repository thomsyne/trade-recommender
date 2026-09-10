# Frozen deterministic library, correction revision 2

Status: return-blind engineering specification. Constants below are hypotheses,
not calibrated claims or reproductions of any author's published track record.
All strategies are offline. No observed outcomes have been inspected to select
these parameters. Corrected contracts have new immutable definition digests;
the 19 strategy IDs are retained for this unaccepted engineering correction.
Revision-1 records are never rewritten or silently reused. See
[correction contracts and review lessons](corrections.md).

## 1. Shared arithmetic, evidence and evaluation

Fresh local Decimal context: precision 34, half-even, fixed exponent bounds and
traps, independent of ambient context; compare before rounding, serialize outputs to
six decimals. Input costs, financing and conversion evidence retain exact decimal
strings, without quantization, so replay cannot move an affordability boundary.
Prices are midpoint quote currency/base unit. EUR/GBP/CAD/USD pairs use 0.0001
pip (JPY 0.01 if separately admitted; no eligibility expansion). No implied
executable quote. Registered consecutive completed observations only. Missing
intervals interrupt history, not forward-fill. EMA span n: alpha=2/(n+1), seed
first observation; require 3n observations unless specifically stated otherwise.
Only exact observations in the governing Phase4 manifest may be consumed. D
lookback is 400; larger warmups are unavailable, never uncited backfills.

Cost evidence must identify source/version, known-at, currency and horizon and
explicitly cover spread, commission, slippage/latency and financing. Unknown is
not zero. Cost affordability: conservative round-trip quote cost divided by
daily price standard deviation ≤0.1; equality affordable. This is a frozen
screen, not annual turnover or proven net value. Forecast components with absent
cost evidence remain raw descriptive calculations but excluded from combination.
Costs used in a decision must be known by its cutoff. Outcome-period financing
and conversion require separately cited outcome evidence; never feed them back.
An emitted setup's entry must be at or after its governing snapshot cutoff;
a late snapshot cannot authorize a historical fill. A missed entry is unavailable,
not silently backdated or resimulated with later feature information.

Preregistration era `phase5-prospective-2026-09-11-v1`: exploratory material ends
2026-09-11T00:00Z; development [2026-09-11,2027-01-01); untouched holdout
[2027-01-01,2028-01-01), UTC. Freeze before any outcomes; unavailable future
observations are not backfilled. Population: 12 canonical instruments, four
decision-enabled policy unchanged; report all by instrument, never trade eight
ingestion-only. Dependence unit: UTC ISO week across all currencies, union of
overlapping positions; at most one independent unit/week even across pairs.
No significance claim before 52 untouched weeks, no missing required costs or
calendar attestations, positive net mean, and positive net in each half-holdout.
These necessary thresholds do not automatically accept. FVG additionally needs
positive paired weekly net increment versus its same-session close comparator
on the same untouched population. No repeated holdout tuning or cross-era pooling.

## 2. EWMAC (`ewmac-d-v1`)

Daily fast/slow/scalar tuples: (2,8,10.6), (4,16,7.5), (8,32,5.3),
(16,64,3.75), (32,128,2.65), (64,256,1.875). Variance is EMA span32 of
squared one-day price differences, seeded with the first squared difference;
sigma=sqrt(variance); require 96 differences. Raw forecast is scalar ×
(EMA_fast(close)−EMA_slow(close))/sigma. Cap each speed at ±20. Require
max(3slow,97) closes. Zero sigma unavailable. Equal mean of affordable available
capped speeds, frozen diversification multiplier 1, cap again. No dynamic
correlation estimate. Buffer: starting previous forecast 0, retain previous when
absolute difference ≤1; otherwise move to target−sign(target−previous)×1.
Previous value must be explicitly supplied from same-version prior evidence;
offline default is initialization, not an invented position. Verify the complete
bounded ancestor chain (maximum256 records including the current evaluation),
all hashes and semantic replay before consuming a buffer. Cycles, missing or
invalid ancestors, cross-definition/instrument links and unordered cutoffs fail.

## 3. Breakout (`breakout-d-v1`)

N=10/20/40/80/160/320. Each completed D endpoint includes that day's high/low:
H=max(high last N), L=min(low last N), x=40×(close−(H+L)/2)/(H−L).
Zero range unavailable. Smooth x with EMA span ceil(N/4) (`quarter-ceil-v1`),
seed first x; require 3span range observations (N+3span−1 closes). Cap smoothed
value ±20. Same sigma/cost screen and equal mean/FDM1/cap/buffer as EWMAC.
Unavailable long horizons are disclosed. Evaluate independently from EWMAC.

## 4. Safer H1 mean reversion (`fast-mr-h1-v1`)

Use D observations completed at/before the H1 signal interval start; require
15 closes for EWMA5 equilibrium and 192 for raw EWMAC16/64 alignment. H1
ATR14 is mean true range of last14 intervals plus preceding close. Deviation
z=(equilibrium−H1 close)/H1 ATR; require |z|≥1 and sign(z)=sign(EWMAC16/64).
Forecast clip(10z,±20); volatility reduction: multiply by 0.5 when latest
daily sigma/prior daily sigma >1.5, otherwise 1 (prior sigma required).
Candidate stop=signal close−direction×1.5ATR; target=frozen equilibrium;
entry expires after one H1 successor; time stop six H1 intervals.
`adverse-limit-h1-v1` alone owns MR simulation: limit=completed signal close,
placement at next eligible H1 opening after availability and latency, validity
[entry,next registered H1 opening). Candidate expiry bounds latest placement,
not order lifetime; delayed recording must not collapse order validity to zero.
Only an opening ask/bid through the limit models a fill at the
limit, with no favorable gap improvement or adverse entry slippage. Intrabar
touches are unavailable (queue/path unknown); an opening beyond invalidation is
unavailable. Stop-first after an opening fill; exit spread/slippage, two-sided
commission and documented financing/conversion remain explicit. This is a
conservative modeled limit hypothesis, never a realistic executable-fill claim.

## 5. ORB, M15 confirmation and next interval

Separate session suffixes london/new_york, Phase4 session-v1 08:00 local and
first M15 ORH/ORL. No weekend or replacement opening bar. Require complete
consecutive M15 history from open through confirmation, opening ATR14 and
confirmation spread. Opening range/ATR between 0.25 and 2 inclusive; spread/ATR
≤0.1. Basic `orb-m15-wick-v1`: first later high>ORH or low<ORL, dual breach
unavailable, known only on completion. Approved `orb-m15-confirmed-v1`: first
later completed close strictly beyond ORH/ORL. `orb-m15-fvg-v1`: close confirmation
plus same-direction three-M15 strict gap ending on confirmation; consume qualified
Phase4 fvg-v1 with its contemporaneous ATR/spread/minimum/displacement and no
cross-timeframe substitution. Equality is not a gap. Every variant has own ID.

Confirmation must complete ≤open+2h. One attempt and at most one modeled trade
per strategy/session/day; stop searching after first attempted confirmation,
including an unavailable geometry result. Stop beyond opposite OR edge by
max(0.25×opening ATR,2×confirmation spread); target=entry reference+direction×2R,
reference=confirmation close. Target/stop freeze then; next-interval entry gap
does not improve target or widen stop. Earliest entry is first registered M15
opening ≥actual information availability; allow at most one additional registered
interval after the opening at confirmation completion. This accounts for actual
recording delay without backdating a fill. The same bound applies to H1/M15
candidates below: expiry is the second registered successor of the signal start.
No same-interval fill; exit by session open+8h.
No M1 inference, tick acquisition, breakeven rule or recent-performance sizing.

## 6. Pullback, range and failed-break

Pullback D and H4 `trend-v1` must agree (up/down). H4 `zone-v1` support/resistance
with ≥2 tests, not invalidated, age≤200; long low touches upper edge and close
strictly above it, short mirror. Next M15 (or independently versioned H1) close
must exceed rejection high / fall below rejection low. Stop beyond zone outer
edge by 0.25 signal ATR14; 2R target, one-successor entry expiry, eight signal-bar
time stop. Zones are qualified evidence, not order inventory.

Range: D sideways plus current H4 consolidation; lower/upper 10% of range only.
Long excursion into lower edge then close above that edge; short mirrored.
Following M15 close must exceed rejection high / fall below low. Stop outside
range by 0.25ATR, exit frozen center, one-successor entry expiry, eight M15 time
stop. Known expansion/breakout disables; unknown event coverage cannot establish
trading readiness. No opposite-boundary discretionary exit.

Failed-break reversal: active confirmed H1 `sweep-v2`, direction opposite breach,
and subsequent lower-timeframe M15 `bos-v1`; continuation: active H1
`acceptance-v2`, same breach direction and subsequent same-direction BOS. Level,
breach, reclaim/confirmation and BOS availability ≤cutoff. Stop beyond maximum
excursion (reversal) or established level (continuation) by 0.25ATR; target2R,
expiry one successor/time stop8. No pending/expired/invalidated lifecycle accepted.
IDs use `phase5` prefix; do not revise failed-break v1/v2 or their terminal binder.

## 7. Simulation and overlays

Intent is not an order. Non-MR versions own `adverse-next-interval-v1` only.
Exact next eligible registered interval required, with
calendar profile/version known at decision. Entry uses next open midpoint plus
directional half spread and slippage; commission charged on both sides. Price
gap through stop closes at adverse open; otherwise stop wins a same-bar dual hit.
Target gap receives target (no favorable price improvement). Entry beyond target
or stop is unavailable. Missing required intervals/quotes/financing/conversion
leaves net unavailable, never zero-cost. Financing in quote currency per unit
for each crossed rollover; conversion at exit from exact PIT evidence, not current
FX rates. Rollover coverage includes entry and exit equality. Costs are signed
(negative means credit). A rollover exactly at entry or at/after the exit bar's
start charges max(cost,0): ambiguous ordering cannot award an unearned credit.
Rollovers strictly between entry and the exit bar's start retain their documented
signed amounts. Gross price P&L and modeled costs stay separate.
Outcome series retain exact sorted cited bars; continuity checks stop at terminal
exit. Missing pre-entry/active intervals fail closed; post-exit gaps cannot erase
the result. Required outcome terms include canonical base/quote/account currency
IDs, quote-per-base costs, account-per-quote conversion, nonempty provenance,
lowercase SHA256, aware ordered times and finite Decimal values.

Macro `macro-risk-v1`: risk only. Named central-bank decisions and CPI/employment/
GDP exact-time vintages; latest known wins before filtering, cancellations and
reschedules suppress old records. Inclusive ±1800s windows: pause multiplier0.
Outside active windows: spread/ATR>0.1 pause, >0.05 reduce0.5; otherwise unchanged1
only with attested complete event calendar. Unknown → unavailable. Surprise is
(actual−consensus) in same units only with PIT consensus and release; no implied
direction and otherwise unavailable. Current Phase4 coverage is unattested.

Risk challengers are separate fixed1, EWMA sigma ratio min(1,baseline/current),
Student-t GARCH(1,1) zero-mean daily returns fit with mature `arch==7.2.0`,
rescale=False, at least 250 returns, fit last≤399, deterministic solver options
maxiter1000/ftol1e-9; one-step variance, ratio min(1,baseline/sqrt(variance)).
Nonconvergence, dependency absence, nonfinite/zero variance → unavailable. No
fallback disguised as GARCH and no multiplier above baseline.

Carry is readiness only: genuine PIT forward discounts, broker financing,
rollover and broad cross-sectional ranking required. Policy rates never qualify.
No carry output or trend+carry without a later standalone validated definition.
Deferred/rejected families remain outside the executable registry.
