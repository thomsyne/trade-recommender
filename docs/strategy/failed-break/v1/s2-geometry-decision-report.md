# Return-blind S2 geometry — decision report

Recommendation: **B — a separately authorized exploratory-only backtest freeze
that can never authorize promotion, regardless of outcome.** This recommendation
is **not effective**. S2, return access and all partition unlocks remain blocked.
The 0.20R practical-effect target is unconditionally immutable after the
return-blind geometry became known. No additional acquisition is proposed as
this gate's action.

Candidate commit `cfe9d19eef2f76bec2328098be77f68bf3103320` and all its files are
unchanged. This gate adds a projector, a canonical artifact, tests and this report.
It does not rerun or amend S0/S1. The existing candidate readiness remains
unchanged; this projection is a separate review input, not activation authority.

## Exact population and geometry

The artifact's `events` array contains every one of the **90 physical events**:
immutable setup ID, full natural key (instrument, direction, sweep timestamp,
detector, dataset version), canonical physical-key hash, entry/confirmation times,
book memberships, level families and source evidence hashes. It contains no
candle price path or exit outcome. The **204** memberships are 90 combined,
43 weekly, 40 daily-swing and 31 breakout. There are 66 two-book and 24 three-book
events; books must not be pooled as independent trades.

The persisted unpurged ledger contains 91 eligible physical events / 206 book
evaluations. The already-accepted purge of setup **596** (two memberships) is
reconstructed from sealed timestamp metadata and excluded, without deleting it.
Included entries span `2010-02-08T15:00:00Z` to `2018-12-03T19:00:00Z`.

| Book | Eligible physical events | Entry dates | Entry weeks | Week Kish | Shared-factor clusters | Factor Kish | Fixed-equity capacity-positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| Combined | 90 | 81 | 73 | 59.5588 | 74 | 60.4478 | 86 |
| Weekly | 43 | 42 | 40 | 36.2549 | 40 | 36.2549 | 42 |
| Daily swing | 40 | 38 | 38 | 36.3636 | 38 | 36.3636 | 40 |
| Breakout | 31 | 30 | 29 | 25.9730 | 29 | 25.9730 | 31 |

Combined distributions, with all individual dates/weeks and sizes in the artifact:

- Entry dates: 73 singletons, seven size-2 dates, one size-3 date (81 / 90).
- Entry weeks: 60 singletons, eleven size-2 weeks, two size-4 weeks (73 / 90).
  Exact Kish: `90² / 136 = 2025/34`.
- Shared factors: 62 singletons, ten size-2 components, two size-4 components
  (74 / 90). Exact Kish: `90² / 134 = 4050/67`.
- Every combined-book entry has a distinct timestamp: 90 simultaneous groups of
  size one. Across books these are the same 90 events, not 204 independent entries.
- Maximum-horizon overlap: 45 combined-book event-pair edges, peak five concurrent
  requests. Weekly/daily/breakout peaks are four/two/three, reproducing accepted S1.

Shared-factor definition is exactly the proposed S2-04 definition: within each
**New York ISO entry week**, connect two physical events when either currency is
shared; take transitive connected components, ignoring direction and book. This
is count-based dependence geometry, not proof of cross-cluster independence.
The previous **408 singleton currency incidences are non-authoritative** and must
not be used as independence evidence. **Confirmed-setup Kish must never replace
eligible/allocated/resolved-trade effective sample size.**

## Capacity is a diagnostic, not resolved trading

Actual allocation depends on marked book equity and earlier stops, targets or
structure exits. These are forbidden here. Actual allocated count and **resolved
allocated physical-trade count are unknowable**, not zero and not 86.

The deterministic diagnostic holds each book's equity at C$10,000 and reserves
allocated initial risk until its maximum ten-provider-D-session horizon. It uses
the stored pre-entry CAD risk per unit, C$25 requested risk, C$100 aggregate cap,
C$50 gross currency-direction cap, largest common fraction, one-unit downward
rounding, no netting and no residual redistribution. New allocations precede
equal-time scheduled release. It inspects no prices and simulates no exit.

This produces 86 positive/4 zero-unit combined requests (zero-unit setups 472,
17, 633 and 577); weekly loses setup 17, other family requests remain positive.
It is **not a lower or upper bound on actual allocation survival** when marked
equity and earlier exits are unknown. Its trace matches an independent exact-
rational reference for every book. Diagnostic survivors have combined week Kish
`1849/30` and factor Kish `3698/59`; the increase after clustered capacity blocks
is not permission to substitute this sample or claim improved confirmatory power.

Each horizon uses the first ten actual sealed D completions strictly after entry,
including the entry-containing D only if it completes later, and the first sealed
H1 open at/after the tenth completion. Compact witnesses retain those D starts
and neighbouring entry/horizon H1 timestamps; whole-series timestamp hashes bind
the preloaded inventory. Holiday omissions are never replaced by calendar bars.

## Concentration — no return weighting

Combined eligible-request ratios (all requests have equal pre-allocation risk):

| Dimension | Counts / shares |
|---|---|
| Pair | AUD_USD 14/90; EUR_GBP 9/90; EUR_USD 16/90; GBP_USD 22/90; USD_CAD 13/90; USD_JPY 16/90 |
| Entry year, 2010–2018 | 19, 13, 9, 10, 7, 7, 5, 11, 9 out of 90 |
| Direction | Long 48/90; short 42/90 |
| Session | London only 23/90; NY only 37/90; overlap 30/90 |
| Combined-family fractional shares | Weekly 16/45; daily swing 19/60; breakout 59/180 |
| Largest gross currency-direction share | Long USD 1/4; denominator is twice total requested risk |

Maximum pair/year/direction/session/family/currency shares are respectively
24.44% / 21.11% / 53.33% / 41.11% / 35.56% / 25.00%, below the proposed
40% / 40% / 80% / 80% / 60% / 50% limits **for this eligible-request diagnostic**.
Family weight is split equally across attributed families, not duplicated.
Exact fractions and fixed-equity diagnostic risk-weighted ratios are in the
artifact for each book. Actual resolved-trade risk-weighted concentration remains
unknowable; no S2 concentration acceptance gate is declared passed.

## Detectable effect, not observed performance

Using the candidate's 95% two-sided confidence and 80% target power:
`MDE = (z_0.975 + z_0.80) × assumed_sigma / sqrt(n_eff)`.
The newly requested dispersion grid is **0.5R, 1.0R, 1.5R**; the prior candidate
artifact is not changed. These are normal-design sensitivities with assumed
dispersion and cluster independence, not measured power or return estimates.

| Combined sample basis | n / Kish | σ=0.5R | σ=1.0R | σ=1.5R |
|---|---:|---:|---:|---:|
| Raw eligible physical count | 90 | 0.1477R | 0.2953R | 0.4430R |
| Actual eligible entry-week geometry | 59.5588 | 0.1815R | 0.3630R | 0.5445R |
| Actual eligible shared-factor geometry | 60.4478 | 0.1802R | 0.3603R | 0.5405R |

At the proposed practical effect **0.20R**, adequacy is not established across
the preregistered dispersion scenarios: σ=1.0R and 1.5R require much larger
effects even before actual allocation/resolution uncertainty. Residual serial
dependence can further reduce information. All per-book and separately labelled
capacity-diagnostic MDEs are included; none is a claim about resolved-trade n_eff.

## Every S2-04 numeric floor

S = satisfied on the stated return-blind population; F = failed on that cohort;
U = unknowable without unauthorized evidence. No promotion assessment is made.

| Proposed floor | Combined | Weekly | Daily | Breakout |
|---|---|---|---|---|
| Included confirmed setups ≥100 | S:316 | S:146 | S:141 | S:156 |
| Eligible physical events ≥50 | S:90 | F:43 | F:40 | F:31 |
| Resolved allocated trades ≥50 | U | F:upper bound 43 | F:upper bound 40 | F:upper bound 31 |
| Genuinely paired events ≥30 | U | U | U | U |
| Nonempty entry dates ≥40 | S:81 | S:42 | F:38 | F:30 |
| Nonempty entry weeks ≥30 | S:73 | S:40 | S:38 | F:29 |
| Kish entry weeks ≥30 | S:59.56 | S:36.25 | S:36.36 | F:25.97 |
| Kish shared factors ≥20 | S:60.45 | S:36.25 | S:36.36 | S:25.97 |
| Observation period ≥1,095 days | S:3,287 | S:3,287 | S:3,287 | S:3,287 |
| Registered coverage 100% | S:S0/S1 only | S:S0/S1 only | S:S0/S1 only | S:S0/S1 only |
| Unresolved data count 0 | U:exit evidence | U:exit evidence | U:exit evidence | U:exit evidence |

The observation period is the registered development calendar 2010–2018, not
3,287 active trading days. S1 unresolved quality count remains zero; execution
coverage/resolution is not examined. Paired comparator geometry/resolution is
not present in this S1 cohort. M1 remains unavailable and separately unauthorized.
S2-05 positive effect, confidence-bound, comparator and cost-grid outcome gates
remain entirely unknowable in this projection. This supports recommendation B,
not confirmation of A and not an effective change to the current policy.

## Verification and isolation

Before capture: exact candidate HEAD, clean worktree, and 90-event synthetic
benchmark **0.005047 seconds**; estimated live run under 30 seconds, six bounded
SELECTs, each capped at 60 seconds, below the 15-minute authorization limit.
Successful projection took **2.183749 seconds**. No large fixture or backtest.

Two read-only passes occurred. The first transaction was rolled back and the
projector exited 1 because it incorrectly required a confirmation JobRun FK of 2.
Source inspection showed the accepted detector calls `persist_confirmation`
without `job_run`, so those fields are legitimately null. Only the new projector
was corrected to require that exact existing behaviour. The second pass exited
0 and produced this one projection; no S1 row or candidate file was altered.

Both passes used a fixed local Unix-socket research target, empty child
environment, password lookup disabled via `/dev/null`, `REPEATABLE READ READ ONLY`,
and explicit rollback. The harmless libpq warning about `/dev/null` not being a
plain password file did not cause a credential lookup. Database name/read-only
mode/isolation/socket were checked before any evidence SELECT. No production or
provider connection, write, migration, discovery, acquisition or S0/S1 execution.

Six fixed query shapes have exact ordered field allowlists; extra fields, extra
rows or altered result descriptions fail closed. No query references the candle
table, any BA price/volume, stop/target/entry price, or any outcome table. Only
pre-entry CAD risk per unit is read as numeric sizing geometry. Timestamps after
entry come solely from the already-sealed discovery inventory, with no prices.

The source retains allowed S1 row projections and their existing evidence hashes;
it does not claim to reconstruct full S1 evidence payloads that were deliberately
not read. Offline verification reconstructs every projected identity, membership,
horizon witness and report hash. Whole-inventory adjacency was established during
capture and bound by series hashes; offline verification does not query it again.

Focused tests cover field refusal, lineage, DST/holiday metadata, factor
transitivity, boundary ordering, exact rational allocation equivalence,
concentration denominators, actual-cohort hashes and unknowable-count semantics.
Final checks use only the committed artifact, never another database projection:

```bash
env -i PATH=/usr/bin:/bin .venv/bin/python -m research.s2_geometry --verify-committed
env -i PATH=/usr/bin:/bin .venv/bin/python -m unittest research.tests.test_s2_geometry research.tests.test_s2_policy
```

Projection SHA: `022cc786e9c6ea98a0631115b98c9ce9562234dbc5e60a3beb203559de6d47dc`

Artifact file SHA: `04fdd37beb0bffb39b29b21a65e1af6bdfd1ae18eb515538d70e3a5c9a5fed35`

Report SHA: `84c53bd85255e7ac6a38dedbfce37dd87ac1a2618d5ae535557a8e06ed283266`

Event set SHA: `bcaa65ec285f491c4bbb543591f77f2ae6eaa73e37899728ccc538a2e00eb273`

Source projection SHA: `97d597b5b00fcabe6dc460974c25e3b5aa532040c212d24f4600ff80bed52dff`

Stop at the additive local review commit. No push, PR, merge, policy activation,
return calculation or backtest is authorized by this artifact or recommendation.
