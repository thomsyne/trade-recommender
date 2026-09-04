# Failed-break v2 final research binder

**Terminal status:** `COMPLETED_NEGATIVE_EXPLORATORY_RESULT`

**Archive date:** 2026-09-04

**Strategy:** `failed-break-phase-1-admission-correction-v2`

**Dataset:** `oanda-ba-ny17-friday-provider-observed-v2` / `phase-2b1r-v2`

**Scope:** exploratory research only; permanently ineligible for promotion or live trading

This is the authoritative human-readable record of the failed-break v2 programme. The
canonical machine-readable terminal boundary is
`failed-break-v2-terminal-freeze.json`. Existing source code, database evidence,
authorizations, and artifacts remain immutable for reproducibility. Nothing in this
binder authorizes another execution.

## A. Executive summary

The project attempted to build and govern a systematic foreign-exchange strategy that
trades failed breaks of daily and weekly structural levels. It began as a side project:
find a defensible, repeatable edge that could be researched and executed around a day
job, then determine what capital would be needed to support average monthly income of
CAD 800 to CAD 1,000.

CAD 10,000 was a useful reference account, not an immutable capital ceiling. The real
question was whether CAD 10,000, CAD 40,000, or some other amount could responsibly
support the income objective. Capital was always meant to be an output of a positive,
robust edge analysis, not a lever used to make weak economics look acceptable.

The answer for this strategy and this 2010-2018 cohort is negative. Across 82 unique
physical trades, gross expectancy was **-0.1804203810R per trade**, gross profit factor
was **0.7646015214**, and every one of the 15 governed commission-by-financing scenarios
was negative. Increasing capital would scale the historical loss; it cannot repair the
absence of an edge. There is therefore no finite positive capital amount that converts
this negative historical average into positive CAD 800 or CAD 1,000 average monthly
income.

The programme is complete and closed. The strategy must not be traded, promoted,
rerun, retuned, or rescued through favourable-result, pair-removal, direction-removal,
capital-scaling, or threshold-reinterpretation arguments. Any future research requires
a new strategy identity, a new preregistration, and genuinely untouched validation
evidence.

## B. Strategy description

### Concept

A failed break occurs when price moves through a previously available structural level
but does not sustain the break. The strategy derived levels from completed daily and
weekly candles, used hourly candles for decisions, and required the information used at
each decision to have been available at that time.

The detector tracked supporting daily swings and daily/weekly structural roles. A newer
same-type daily pivot superseded an older active pivot at the newer pivot's availability
time; terminal instances stayed terminal. Daily and weekly inventory members were
admitted independently of whether their completion coincided with an H1 completion.
Confirmation, theoretical entry, boundary censorship, and the ten-provider-D-session
horizon used the ordered sealed provider-observed inventory rather than synthetic
calendar bars.

At a high level, a candidate had to sweep or break a governed level, satisfy the frozen
session and confirmation conditions, retain valid supporting structure, and reach a
theoretical H1 entry. Stops and targets were constructed from the frozen S2 rules. When
both could be touched within one candle, the preregistered conservative ordering was
used. Missing or conflicting evidence failed closed instead of being silently omitted.
The maximum holding period used ten actual completed, sealed provider-D sessions and
then the corresponding next sealed H1 exit open.

### Market, execution, and risk conventions

The six instruments were `AUD_USD`, `EUR_GBP`, `EUR_USD`, `GBP_USD`, `USD_CAD`, and
`USD_JPY`. Decisions used registered D, W, and H1 inventory. The strategy applied its
frozen New York session restrictions and the six development-only absolute spread P99
ceilings accepted at S0.

Observed bid/ask spread was applied. Additional slippage was fixed at zero. The latter
is an optimistic limitation, not evidence that real execution has no slippage. The
15-cell sensitivity surface was exactly three round-turn commission assumptions
(`0`, `0.5`, and `1.0` pip) multiplied by five annual financing assumptions
(`-6%`, `-3%`, `0%`, `+3%`, and `+6%`). It was not a slippage grid.

Account reporting currency was CAD. Each conversion leg used the latest successfully
ingested, conflict-free, sealed, completed H1 midpoint close strictly before entry.
Fixed direct and inverse routes were used independently by leg. There was no live quote,
future quote, synthetic candle, forward fill, or entry-bar high/low/close substitution.
Legitimate provider-observed weekend or holiday closures did not make the latest sealed
member stale; missing or conflicting required evidence failed closed.

Results were normalized in R. Fixed-risk diagnostics used CAD 25, CAD 50, and CAD 100
per unique physical trade against a non-compounding CAD 10,000 reference account.
Aggregate and currency-direction exposure rules, simultaneous-signal ordering, and
conflict resolution were frozen before returns were inspected.

### Physical trades and books

One market event could belong to several descriptive strategy books. Those memberships
are attribution labels, not separate capital allocations. The final cohort contains
82 physical trades and 186 non-additive memberships. Treating 186 memberships as 186
independent trades would duplicate both evidence and risk.

### Excluded information

The strategy did not use economic-news releases, central-bank-event labels,
macroeconomic forecasts, sentiment, discretionary chart interpretation, or live broker
conditions. That omission does not explain away the observed result; it defines the
strategy that was actually preregistered and evaluated.

## C. Dataset and governance history

### Dataset

The registered successor dataset used completed, provider-observed OANDA practice
bid/ask candles under the New York 17:00 Friday convention. It contains 365,055 accepted
candles across the six instruments and D/H1/W granularities, backed by 132 successful
attempt-1 acquisition chains and 132 manifests. The predecessor overlap of 364,953
candles was identical, and the successor added a governed 102-candle extension. The
six-instrument warm-up proof established 25 provider-observed sessions where the earlier
convention had only 14. The development cohort was 2010 through 2018; preceding data was
warm-up only.

The dataset was registered once as database dataset ID 3, name
`failed-break-provider-observed-historical`, version `phase-2b1r-v2`, with effective
identity `oanda-ba-ny17-friday-provider-observed-v2`. Registration configuration SHA was
`dc12d05ba149b01ec2f5ed4228d64622bc675b58c7d790fe676d2b46370d18e2`; registration
report SHA was `871ba55669da47577c6eb65c46bf8fb86ba6aef73fe7dd322ff37c67b3f280c2`.

### Gate and stage narrative

Gate 8E froze acquisition readiness. Gate 8F executed one canary. Gate 8G acquired the
remaining 131 governed chunks exactly once. Gate 8H independently accepted the result.
Gate 8I solved the large-snapshot JSONB limit using decomposed identities, bound the
365,055-candle successor and overlap/warm-up proof, and enabled the existing governed
registration path. The dataset was then registered and sealed without changing
production.

V1 S0 accepted return-blind coverage, warm-up, missingness, spread ceilings, and
distribution hashes. V1 S1 exposed timestamp/calendar and D/W admission defects. V1 S2
was frozen exploratory-only, but v1 evidence was not promoted or rewritten. V2 corrected
daily/weekly admission and supporting-swing lifetime semantics forward-only under a new
strategy identity.

V2 then passed a separately accepted S0, an optimized return-blind S1, S1 outcome
acceptance, geometry, and an exploratory-only S2 freeze. The code-only calculator and
runner were separately governed. Every execution authority was exactly once and
forward-only; consumed failures did not become permission to retry.

### Git-derived chronology

The following chronology was reconstructed from first-parent Git history. Commit IDs are
the reviewed branch heads; merge IDs are the plain two-parent merges on `main`.

| PR | Stage | Reviewed head | Merge commit | Result |
|---:|---|---|---|---|
| 31 | Gate 8E | `dac983655845` | `590b4f41a17b` | Acquisition readiness merged |
| 32 | Gate 8G | `ffeda51bec8e` | `51398bf6b074` | Governed acquisition wave code merged |
| 33 | Gate 8I | `df491d8452f9` | `dec7c8c15bac` | Dataset acceptance/registration governance merged |
| 34 | Pre-S1 corrections | `360c3ca765f4` | `7e34bdf9dbf5` | B1/B6/B7/D9/D4 and S0 acceptance merged |
| 35 | V1 exploratory S2 | `962fc747eb48` | `0a52192d6675` | Exploratory-only v1 S2 frozen |
| 36 | Detector v2 | `ca20dbcadcef` | `db7a774...` | Forward-only D/W and swing correction merged |
| 37 | V2 S0 preparation | `e04412327452` | `1506eea0dc78` | Code-only v2 S0 boundary merged |
| 38 | V2 S0 acceptance | `8e45c226934a` | `ea0c5d5d403c` | JobRun 4 accepted |
| 39 | V2 S1 runner | `644955cd13fe` | `badfaee13e63` | Optimized runner merged, execution blocked |
| 40 | V2 S1 authorization | `4f86c6c3fb8e` | `3b787839b149` | Exactly-once execution authority merged |
| 41 | V2 S1 acceptance | `20de3ce2ae08` | `f6b498b187d4` | JobRun 5 accepted |
| 42 | V2 geometry | `f40ec608d0bd` | `c1abe04199bd` | Return-blind geometry merged |
| 43 | V2 S2 policy | `890e0d0cf64e` | `139dff6a0dd0` | Effective exploratory-only policy merged |
| 44 | Return calculator | `2949c06667fd` | `efd125f1a5c6` | Code-only calculator merged |
| 45 | Return runner | `bd0316eefeed` | `b38a8918b18e` | Code-only persistent runner merged |
| 46 | First return authority | `fa1fdf5ef174` | `9a391a711669` | Exactly-once authority merged |
| 47 | macOS memory correction | `c8797a1d8541` | `d9a1c09df966` | RSS-watchdog successor merged |
| 48 | Lineage performance | `4f80dd93c6e5` | `71260ab4a379` | Timestamp-precompute successor merged |
| 49 | Rollover correction | `4127b64afd6f` | `567006533e42` | Financing-rollover successor merged; final run succeeded |

Abbreviations with ellipses are display-only; Git is authoritative for their complete
objects. The terminal archive starts from exact commit
`567006533e42428e2e103c9fa8edd304dbc859e5`, tree
`681d314bb15e8bfec1b76d29abf9b258edd24e69`. The final archival merge cannot be embedded
inside a file that is itself part of that merge without a self-reference cycle. The
annotated tag `failed-break-v2-terminal-negative-2026-09-04` resolves the final archival
commit and tree unambiguously.

## D. Execution history and engineering lessons

### V2 S1 launch

The first v2 S1 launch used a restricted `PATH` that hid the working native libpq and
exposed an x86_64 `psycopg_binary` extension to an arm64 interpreter. It failed before
Django initialized, issued zero database queries, and wrote nothing. A separately
authorized replacement used `.venv/bin/python`, the native arm64-compatible psycopg/libpq
runtime, the local PostgreSQL Unix socket, and external-network denial. It completed
atomically as JobRun 5.

### Return execution failures and replacements

| Attempt | Authority | Outcome | Evidence preserved |
|---:|---|---|---|
| 1 | First exactly-once return authority | Exit 1 in 1.09 s: macOS `RLIMIT_AS` current-limit refusal | No transaction, calculation, result, or row; peak RSS 78,053,376 bytes |
| 2 | RSS-watchdog successor | Exit 1 after 901.421431 s at `lineage completed=0 total=82` | Atomic rollback; no result row; whether an OHLC query had begun was not provable |
| 3 | Timestamp-precompute successor | Exit 1 after 5.629354 s: governed rollover mismatch in 78/82 events | All 82 normalized; no result constructed or committed |
| 4 | Rollover-correction successor | Exit 0 after 7.82 s | One immutable JobRun 6; one result/idempotency row; no other application-table delta |

Each failed authorization was consumed and recorded. Each replacement required a new
forward-only authorization. No failed attempt was silently treated as a retry token.

### Performance root cause

The 15-minute timeout was not in the initial lineage verifier. The progress marker was
emitted after lineage verification and immediately before real normalization.
`DjangoSealedEvidenceAdapter._prior_start()` rebuilt and converted the full instrument
H1 completion list for every strict-prior lookup. The real return-blind profile measured
**19,878 calls** and **1,141,664,450 unnecessary timestamp conversions/scans**. It also
found 3,515 repeated lookups among 16,363 unique `(instrument, decision_time)` pairs.

Precomputing completion tuples once per `(instrument, granularity)`, bisecting the H1
tuple, and bisecting precomputed D completions preserved strict-prior semantics while
removing the quadratic work. Representative old-path 500-lookups took 13.340301 seconds;
corrected one-time preparation took 0.175477 seconds, registered inventory load took
2.430214 seconds, and evidence-key planning took 2.647610 seconds for 27,969 needed
candles. The corrected query budget was 16 total, with three pre-candle queries. Synthetic
end-to-end compute took 1.137667 seconds; the final real calculation completed in 7.82
seconds.

Earlier synthetic rehearsals deep-copied already normalized events. They therefore did
not exercise real inventory loading, strict-prior planning, conversion routes, actual
query shapes, or normalization. They were useful compute-floor tests, not production
runtime proofs.

### Rollover defect

The next real-data run found missing or extra governed financing rollovers in 78 of 82
events. The correction reconciled financing days to the frozen provider-session
convention, including DST, weekends, closures, and equality boundaries. It did not
change entries, stops, targets, terminal ordering, the 82-event cohort, 186 memberships,
cost grid, risk rules, bootstrap, or permanent non-promotion. The complete disposable
real-data rehearsal passed before the successor authority was merged and used.

### Future engineering controls

Future work should make synthetic rehearsals exercise the real adapter and query plan,
profile cardinality-dependent helpers on registered timestamp inventories, separate
compute-only from persistence timings, emit stage-level count-safe progress, and validate
provider-session calendars against whole cohorts before granting persistent authority.
Read-only real-data rehearsals should occur before building elaborate exactly-once
machinery, not after.

## E. Final evidence geometry

V2 S1 produced 344,817 H1 analyses, 17,935 levels, 17,901 lifecycle events,
868 setups, 1,213 level attributions, 1,620 setup transitions, and 752 book-level entry
evaluations. There were zero unresolved data-quality failures.

The 752 evaluations included 188 `ENTRY_PENDING` book memberships representing 83
physical setups before geometry. One physical setup was purged at the governed partition
boundary, leaving 82 geometry-eligible physical trades and 186 non-additive memberships.
The final physical events occupied 76 entry dates and 68 New York entry weeks.

Entry-week clustering had Kish effective count `1681/28 = 60.0357142857`. Shared-factor
clustering had 69 clusters and Kish effective count `3362/55 = 61.1272727273`. The
conservative effective sample was therefore approximately 60. The old 408-singleton
shared-currency statistic is non-authoritative, and a confirmed-setup Kish count cannot
substitute for trade-level effective sample size.

Return-blind geometry adequacy passed only at sigma `0.5R` and failed at `1.0R` and
`1.5R`; confirmatory adequacy was not established across the diagnostic scenarios.
The separate S2-03 hypothetical sensitivity grid remained `[0.5R, 1.0R, 2.0R]`.
Neither grid could authorize promotion. Thus the cohort was already exploratory-only
and permanently non-promotable before any return was read.

## F. Complete return results

### Gross result and terminals

| Measure | Governed result |
|---|---:|
| Physical trades | 82 |
| Non-additive memberships | 186 |
| Gross total | -14.7944712431R |
| Gross expectancy | -0.1804203810R |
| Gross profit factor | 0.7646015214 |
| Winners / losses | 18 / 64 |
| Win / loss rate | 21.9512% / 78.0488% |
| Median result | -0.9985745400R |
| Payoff ratio | 2.7185831871 |
| Longest winning / losing streak | 4 / 11 |
| Stationary-bootstrap mean | -0.1804203810R |
| 95% bootstrap interval | [-0.5400490611R, 0.2229967496R] |
| Preregistered practical-effect target | 0.20R |

Terminal classifications were 59 `STOP`, 13 `TARGET`, 6 `DAILY_STRUCTURE`, and
4 `HORIZON`. Every physical event received exactly one terminal classification.

### Commission by financing scenarios

Every cell was negative. CAD results below use CAD 25 risk per physical event; CAD 50
and CAD 100 totals are exactly two and four times these values.

| Commission (pip) | Financing | Total R | Expectancy R | Profit factor | CAD 25 total |
|---:|---:|---:|---:|---:|---:|
| 0.0 | -6% | -23.1017653940 | -0.2817288463 | 0.6595295279 | -577.5441 |
| 0.0 | -3% | -18.9481183187 | -0.2310746136 | 0.7100542003 | -473.7030 |
| 0.0 | 0% | -14.7944712431 | -0.1804203810 | 0.7646015214 | -369.8618 |
| 0.0 | +3% | -10.6408241675 | -0.1297661484 | 0.8236718184 | -266.0206 |
| 0.0 | +6% | -6.4871770922 | -0.0791119158 | 0.8878519801 | -162.1794 |
| 0.5 | -6% | -24.1927946008 | -0.2950340805 | 0.6479858060 | -604.8199 |
| 0.5 | -3% | -20.0391475253 | -0.2443798479 | 0.6974073536 | -500.9787 |
| 0.5 | 0% | -15.8855004500 | -0.1937256152 | 0.7507097359 | -397.1375 |
| 0.5 | +3% | -11.7318533747 | -0.1430713826 | 0.8083687487 | -293.2963 |
| 0.5 | +6% | -7.5782062985 | -0.0924171500 | 0.8709412791 | -189.4552 |
| 1.0 | -6% | -25.2838238076 | -0.3083393147 | 0.6367320928 | -632.0956 |
| 1.0 | -3% | -21.1301767317 | -0.2576850821 | 0.6850900758 | -528.2544 |
| 1.0 | 0% | -16.9765296565 | -0.2070308495 | 0.7371939828 | -424.4132 |
| 1.0 | +3% | -12.8228825806 | -0.1563766168 | 0.7934966031 | -320.5721 |
| 1.0 | +6% | -8.6692355054 | -0.1057223842 | 0.8545267642 | -216.7309 |

The financing sign is the governed scenario axis, not a promise about realized broker
carry. The additional-slippage axis is absent by policy. Real execution slippage beyond
the registered bid/ask spread would make this already-negative result less favourable.

### Fixed-risk diagnostics

The fixed-capital figures below use the gross/zero-commission/zero-financing cell for the
governed reference diagnostic.

| Risk/trade | Total P&L | Average month | Ending CAD 10k | Max drawdown | MDD / initial | Best month | Worst month | Sharpe | Sortino |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CAD 25 | -369.8618 | -3.4246 | 9,630.1382 | 423.6398 | 4.2364% | 168.0118 | -75.0837 | -0.2868 | -0.3960 |
| CAD 50 | -739.7236 | -6.8493 | 9,260.2764 | 843.8780 | 8.4388% | 336.0236 | -150.1673 | -0.2796 | -0.3870 |
| CAD 100 | -1,479.4471 | -13.6986 | 8,520.5529 | 1,674.3119 | 16.7431% | 672.0473 | -300.3347 | -0.2644 | -0.3676 |

Sharpe and Sortino are descriptive only. They are not tuning, selection, acceptance, or
promotion gates.

Across all 108 calendar months, 15 were positive, 39 negative, and 54 unchanged. There
were entries in 55 months. Complete CAD 25 monthly P&L follows; multiply by two or four
for CAD 50 or CAD 100 under the fixed-risk, non-compounding diagnostic.

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2010 | 0 | -24.9397 | -50.0049 | -25.1504 | -25.0115 | -24.9511 | -71.2796 | -49.9284 | 0 | 24.1972 | -25.0000 | 0 |
| 2011 | -61.5951 | -25.0799 | 0 | 128.9252 | 0 | 0 | 58.8272 | 54.2900 | 0 | -25.0000 | -74.9996 | 168.0118 |
| 2012 | 60.3978 | -24.8984 | 0 | 0 | -50.0653 | 0 | 0 | -24.9147 | -25.0000 | 0 | -25.0456 | 0 |
| 2013 | -24.9792 | 0 | -2.6488 | 0 | -25.0832 | -50.0740 | 0 | 0 | -60.4371 | 0 | 0 | 5.9752 |
| 2014 | -25.0000 | -8.2927 | 0 | 0 | 0 | 0 | 0 | 0 | 125.2612 | 64.5824 | 0 | 73.7730 |
| 2015 | 0 | 26.0275 | 0 | -50.1978 | 0 | -25.0191 | 0 | -24.9267 | 0 | 0 | -25.0444 | 0 |
| 2016 | 0 | -24.9136 | 0 | -49.8585 | 0 | 0 | 0 | 0 | 0 | 0 | -25.0000 | -10.2733 |
| 2017 | 0 | 0 | -25.2263 | 56.7529 | 0 | 0 | 8.1925 | -50.0720 | -25.1005 | 0 | 0 | -75.0837 |
| 2018 | 0 | 89.3566 | 34.5023 | -58.7919 | 0 | 0 | -25.0474 | 0 | 0 | 0 | 0 | -25.0000 |

Annual gross results and CAD 25 equivalents were:

| Year | Gross R | CAD 25 |
|---:|---:|---:|
| 2010 | -10.8827366076 | -272.0684 |
| 2011 | 8.9351810659 | 223.3795 |
| 2012 | -3.5810464638 | -89.5262 |
| 2013 | -6.2898884421 | -157.2472 |
| 2014 | 9.2129570528 | 230.3239 |
| 2015 | -3.9664209898 | -99.1605 |
| 2016 | -4.4018167885 | -110.0454 |
| 2017 | -4.4214864497 | -110.5372 |
| 2018 | 0.6007863797 | 15.0197 |

Pair-level gross contributions were:

| Pair | Trades | Gross R |
|---|---:|---:|
| AUD/USD | 12 | 3.7350186127 |
| EUR/GBP | 7 | 2.1822678385 |
| EUR/USD | 15 | -4.2916243177 |
| GBP/USD | 20 | -14.8238288209 |
| USD/CAD | 13 | -2.1787318275 |
| USD/JPY | 15 | 0.5824272718 |

Longs contributed -14.4087427587R across 45 trades; shorts contributed -0.3857284844R
across 37. GBP/USD accounted for 53.3348% of absolute pair-level net contribution, and
longs accounted for 97.3928% of absolute direction-level contribution. The largest
single event was 4.65% of total absolute event contribution, the top five were 18.41%,
and event-level HHI was 0.0176666. These concentrations reinforce, rather than rescue,
the negative aggregate result.

Removing GBP/USD after seeing the outcome leaves only about +0.0293575778R gross before
additional costs: approximately flat, not a validated edge. The positive AUD/USD and
EUR/GBP subsets have only 12 and 7 trades and were identified after outcomes were known.
Shorts were better than longs but still negative. None is a promotable strategy.

Because total and average P&L are negative, the governed capital fields for averaging
CAD 800 or CAD 1,000 monthly are null. Arithmetic scaling cannot turn a negative average
into a positive income target. Historical performance is not a forward guarantee.

## G. Repository and database final state

### Repository identity

The immutable pre-archive application baseline is commit
`567006533e42428e2e103c9fa8edd304dbc859e5`, tree
`681d314bb15e8bfec1b76d29abf9b258edd24e69`. The final archive identity is the annotated
tag `failed-break-v2-terminal-negative-2026-09-04`, which must point to the plain
two-parent archival merge. This indirection avoids embedding a merge hash in a file that
determines the merge tree itself.

Migration heads remained `market 0027` and `research 0015`. Production was not contacted.

### Persistent research state

| Model/table | Final count |
|---|---:|
| StrategyDefinition | 1 |
| StrategyVersion | 2 |
| StrategyParameterManifest | 2 |
| JobRun | 6 |
| AnalysisRun | 689,484 |
| Level | 35,097 |
| LevelLifecycleEvent | 35,029 |
| SetupEvent | 1,723 |
| SetupLevelAttribution | 2,398 |
| SetupTransition | 3,236 |
| EntryEligibilityEvaluation | 1,513 |
| Exploratory result rows | 1 |
| Exploratory idempotency-key rows | 1 |

Every other outcome, paper-trade, promotion, and backtest table remained empty. The
complete application-count snapshot SHA was
`11a017314eb55d75ecc096e53519310c87932af57de3ff73520cc47392ab1316`.

JobRun 6 was the single successful `failed-break-exploratory-returns-v2` run, bound to
StrategyVersion 2 and dataset 3. Its hashes were:

| Component | SHA-256 |
|---|---|
| Configuration | `3f90135bba1ef0cce20906e5f3799a4cf921a62c772c16466d40a21b832d1e93` |
| Complete evidence | `ebbbca6c5d9f63d5138bbcb0c3b44be7057d052aa116baee577e3adc1acae288` |
| Report | `a27d92e9408382258210d7f1b1d0e8f4eacb10b75d6ff43975c25611998485d9` |
| Event results | `da25f8cc33f02f17a235fd1b8b62c569bb090a6bd999e208672eb6e5cb2efe4e` |
| Cost scenarios | `774c1115685deb4bc9c62ce079ddfafa698361ef31e43c87afaa685ea294179a` |
| Cost summaries | `f77cd9644f665a2def4c6f6fa2646b519dbcebaddf714048c570190284d2bfb0` |
| Fixed-capital diagnostics | `f169bac33eb9aaed0f5a4cdb95dc756a0f1df9c7373f94eebfbc46612ffaa77f` |
| Statistical evidence | `9ef544570d8c808ab6f9a2d496d493279e86a3ae0861fddb9f4306434e52b1e3` |
| Metrics | `13c425773afc3d2b4e539c712db8bd2355fedc5a492d278232e2fccbc7860ea2` |
| Terminal counts | `1f27241096995bc26487adab648eeef7fa5948f05d3189612c73ae7f265bad44` |
| Event keys | `5ee92b1e528b91979a6835eb11285f4ca9d2e7025b27f42c93d9e28373c571bd` |
| Equity paths | `ccb197159e3cbbf0c02a61ba9d7f21ecc7ead9ee26a253c3a59ca87efde79031` |
| Inputs | `61ea5a276d5d528db56e17493e035a422bda3f5bcef5c0e9ad94730b9bec0368` |
| External canonical result file | `205f60f4f8bc73eb8984e5ac38f5c089a8035ae288fb2ff11000455e6b9fc718` |

Abbreviated component digests are display aids; the canonical JobRun evidence and result
file retain their complete values. The v1 preservation aggregate remained
`dc7df52c3502644dc850d6cec865db977a8604b6d871bc8e9f6ec8d477e91a45`.
Read-only readiness confirmed that a repeat execution is permanently refused.

### Backups and isolation

| Backup | SHA-256 | Mode | Restore-list check |
|---|---|---:|---|
| `/Users/oluwatomisintaiwo/trade-recommender-backups/trade_recommender_research-pre-exploratory-return-rollover-successor-20260904T183431Z.dump` | `94404cea13af8587bfcd7704f577f3ec652cfccdfa4e5be5d9cc7e9923a84000` | 0600 | Passed |
| `/Users/oluwatomisintaiwo/trade-recommender-backups/trade_recommender_research-post-exploratory-return-rollover-successor-20260904T183853Z.dump` | `d304d57991453d174876d5c65b8641c63923e7e16fcbff13c031a948fb6e6735` | 0600 | Passed |

Both checksum sidecars were also mode 0600. Provider credentials were unset, external
networking was denied, PostgreSQL access was restricted to the local research Unix
socket, and no production, provider, deployment, promotion, or live-trading path was
used.

## H. Complete material artifact index

### Governing artifacts

| Stage | Artifact path | File SHA / self-hash | Operation and status |
|---|---|---|---|
| Gate 8F | `phase-2b1r-gate8f-successor-canary-outcome.json` | `2bc4db198c720f5d9b35b737d2cd2703688b86f4da68f88eba61f3b6932d1548` / `1abf67c7c0bf31441634285beb5e832766418c69eb026f59de7abbb47d1fe5d6` | One canary accepted; permanently closed |
| Gate 8I | `phase-2b1r-gate8i-final-dataset-acceptance.json` | `5ea57f6f2b8b1c487a9638652f1d6ec1568f8297604629f8d360471c6c45e297` / `ed68a01dc00d67b95de8720e0b8a85f1ee35603265daca1ec0cce28eac5b8905` | Migration 0027; dataset registered once |
| V1 S0 | `phase-2b1r-pre-s1-s0-acceptance.json` | `225c5365219bd7653c99d8f25e113df9c5f4ad24d95b35b36f7928479bee9583` / `aae04ad6c9794d4904e4bb177dab35a6cd02ca53a1ed4dbcdc3a7176da476f34` | JobRun 1 accepted |
| V1 S2 | `s2-exploratory-policy-freeze-v1.json` | `4f70ea3c86569de5b54ad3f18d7c1021b6067532ba9fb42b62faf1a0b2676e8c` / `c30896d2fcd943f647f93f53077e7d7d9163c455cca20aad91df8fbcd667e26f` | Exploratory-only, non-promotable |
| V1 geometry | `s2-geometry-projection-v1.json` | `4749633ac8c3f28e977e7697ba9f1b9d32425de84afde183a2d0fd98e4c7b27b` / `af2f0d6e2e865dcdc8d9825c039d5df650059e717cd09fad92b0f41ff72a8fb7`; report `f6f9df6a9b2c943171018a8674e659c5fd773a6ae1f4b4562ab097fd90096e8b` | Return-blind diagnostic |
| V2 detector | `detector-admission-correction-v2.json` | `3b9188749c10581d7518e25838a2cb65704d1329e7ebe3061cd7fe4b82115861` / policy `0946c470e82a458a0a626960cf20063ae42f183d59429a9d23dbf6f32ce59f4d` | Forward-only admission correction |
| V2 S0 preregistration | `s0-preregistration-v2.json` | `99b45b18b1345cd0d6f12863354e8aea7a39b62ab9b95651ed12db7836752d6f` / `336502cbdb8dbf9098891478b29ac90af39e7b7c1be3e02592edd2e2b36b984d` | One S0 execution authorized |
| V2 S0 acceptance | `s0-outcome-acceptance-v2.json` | `7c438598d6ad8f9b94aa1d264eaa57040f1d91bc1e4f758b1231dda5a9801548` / `4b6f6ac1f24c2a0fb0fb7f5a7246ae265e1c2b0504b06d7e30d1f7ef8cb64e31` | JobRun 4 accepted |
| V2 S1 runner | `s1-runner-preregistration-v2.json` | `051a5b26820b0f4da947353f3bcca13592b3fabe2b127383892a949610fccc75` / `7e7c1999301942f5724dc17148ad89a1676ad820d1f0ea1dfed8679e73913b3b` | Implementation only |
| V2 S1 authorization | `s1-execution-authorization-v2.json` | `9c9d0ed067447db74e33728aa77c5a925b80cc4793b5fadf69170c1dbd64a659` / `f548c819c6381e4531d8a3720e78e3ae2b96a6c5e7b512044ce7719c200922d5` | One execution consumed |
| V2 S1 acceptance | `s1-outcome-acceptance-v2.json` | `5760dd2dd60a2d6a6087b5116b085a8a3774db1512962af0622bc0e3eeed93d5` / `5f1497b7e47da958469d8b8c13d2608243e7a0f811eb30f54f4d5fe65f2bbcab` | JobRun 5 accepted |
| V2 geometry | `s1-geometry-v2.json` | `b3bc76fa4ac226793a24f11a9a65f9b549e7231ace11e399f6d81c1599e41fdc` / `a3c2f7e3f3f7d722228233c158b51eaa296557daf0c19860c79848a788ffc140` | 82 events / 186 memberships |
| V2 S2 | `s2-exploratory-policy-freeze-v2.json` | `1d4b1f451a60d7c2ac37a2fe91849d463254b7751529324e52198003de1ae8dc` / `e2d2a4880e0d900a150a6e801d940b32b09b8cd1435f283a87fe16555e059d72` | Effective exploratory-only freeze |
| Calculator | `exploratory-return-calculator-preregistration-v2.json` | `92acc23cc194e530f525c92243466aa87adc1933b8e659b560ccf9dae3a3ec1a` / `7fd25e8b1a660c6b0b087c4b40eca43588b0018d659c281374f5213a31400d77` | Code only |
| Runner | `exploratory-return-runner-preregistration-v2.json` | `3e465e56af7eb0bc5eef175618dc8c38d0e8fafcc7a867d6b31e70946de3a93a` / `b8877148c25b8982867e3df77314142b4b0d18924d820ea7777275292de4fca7` | Code only; later performance pin |
| Initial return authority | `exploratory-return-execution-authorization-v2.json` | `21c2a3ce7a8ae7eb46ca07a551160a1830f58b4938215491ab40d026f96c349c` / `e0904ae6885d55da3ad10d500018b35d6b48631334a98e342155e7eac859df9a` | Consumed by RLIMIT failure |
| RLIMIT failure | `exploratory-return-execution-failure-v2.json` | `47f76090cd933002067d3f48594c8fcd68fdb6e48d2f121089212b20ebd910b0` / `7a76a6c0249f9f5d5eece84f90175880d712624ed1c79eb7a4821ab1b4d8030e` | Immutable failure record |
| RSS successor | `exploratory-return-replacement-authorization-v2.json` | `e84b1b4b4a8b6b6c25ff4eefca21ab649b4a460a0b3db04b09c0433888407868` / `d6b3e312f80a8395418726e95e384463c29feb11352e0306e46f9398c5f833a5` | Consumed by timeout |
| Timeout failure | `exploratory-return-lineage-timeout-failure-v2.json` | `ca8436767223bc0dd5d954241a96fe01e75e630055912381635d9d371565b325` / `6e0ca64a7f26437936645e887afc5d379ec05b00b74ff072a7f0dbbe2c4aa6a6` | Immutable failure record |
| Performance preregistration | `exploratory-return-lineage-performance-preregistration-v2.json` | `786f727719c962948de1d6c330f6aa6e67af7ca22276ef80f6b6dc6b9b9d26b8` / `00dc9e580d3680fe3a7227b78b43d04908c2f51c97a0b68e31115cf69289f2bf` | Strict-prior optimization |
| Performance authority | `exploratory-return-lineage-performance-authorization-v2.json` | `d3c05c54a6fd0ec9af65f88489e30948f9ace072835756dd5c4b999f91de0b85` / `0e61b6bb07810dc579ef770d39a8144ae5e7f01ff6c1cc6dee9e24a4871c036a` | Consumed by rollover failure |
| Rollover failure | `exploratory-return-rollover-execution-failure-v2.json` | `425a75912ba991fb01f96d1eb88778c60e2c2a5c6874d954c2838d4f1c1b379b` / `c4de8dd992fb31e199b2015df49952fc116f0fee364ea64827062292a1d25732` | 78/82 mismatch record |
| Rollover preregistration | `exploratory-return-rollover-preregistration-v2.json` | `fa041f60701d089649fc4da57b35bdd38794e27b30d94166dca9442c548e0b32` / `bcd1f67b6e11c7fd5d8791058cdb1dfbe82b053a3828dd68dc0400d11c747157` | Provider-session correction |
| Final authority | `exploratory-return-rollover-authorization-v2.json` | `d77c1b5d69061a7bc80a99aacf82e92ed65287fc4a3029bc61f3853590ddb31a` / `6daed2315f2353ab62a3b00dd531a6566f9597b5933e1e819e412aa4314f7180` | Consumed by successful JobRun 6 |
| Rollover calculator | `exploratory-return-rollover-correction-v2.json` | `61896776164b05822dd6ccc45a0d3b61cd1995938742390732eeea066cf05d8b` / `6e51fb260def75344c335f7c1e3c40fd254fc5e34677073b99aa9565b20117e8`; source `9daa42e9bf7b4ac059c3ccb618aac3c96db0cba203985b7d2ad2d36be50f3a4c` | Final semantics, unchanged economics |
| Rollover report | `exploratory-return-rollover-correction-v2.md` | `9fec559a810eabfdb2c7cde6b6140b4bbd08f87c7791752a271bf1b5521d678d` | Reviewed correction narrative |
| Rollover rehearsal | `exploratory-return-rollover-rehearsal-v2.json` | `1b1e3c23641c99a26d18e3bdde3ab87fa0e338196385749517ab5cd3ab0acef1` / `51749b0daa69bf39bb2626c0f09e52c73f99bbe813deb1228645297d3096771f` | Disposable real-data success |
| Terminal archive | `failed-break-v2-terminal-freeze.json` | Loader-pinned canonical file / self-hash | Permanent closure |

Historical abbreviations are deliberately labelled historical. They are not current
identity claims; complete values remain in the committed source artifacts and Git.

### Persistent operations

| Operation | Command/service | Result |
|---|---|---|
| Gate 8G successor acquisition | `run_successor_acquisition_wave --max-chunks 131 --execute` | 131/131 succeeded; no retry |
| Gate 8I migration | `python manage.py migrate market 0027_gate8i_final_dataset_acceptance --noinput` | Applied to research only |
| Dataset registration | Existing `register_failed_break_dataset` governed service | One successor registration/seal |
| V1 S0 | Existing committed S0 command | JobRun 1 accepted |
| V1 S1 | Existing committed staged S1 commands | JobRuns 2 and 3 accepted, then closed |
| V2 S0 | `python manage.py signal_count_s0_v2 --execute` | JobRun 4 succeeded |
| V2 S1 | `.venv/bin/python manage.py signal_count_s1_v2 --execute` | JobRun 5 succeeded |
| V2 exploratory return | `.venv/bin/python manage.py calculate_exploratory_returns_v2 --execute` | Three consumed failures; final successor created JobRun 6 |

## I. Lessons and corrected future approach

The programme over-invested in governance and production-grade machinery before cheaply
establishing signal density and economics. The governance did protect the record from
outcome-driven rewriting, but much of the engineering should have followed rather than
preceded an inexpensive economic screen.

A better future process is:

1. Start with lightweight vectorized screening.
2. Prefer systematic H1/H4 strategies compatible with a day job, not discretionary
   scalping.
3. Compare trend pullback, session/volatility breakout, and regime-filtered mean
   reversion candidates.
4. Begin with the existing pairs; add 6-12 liquid pairs only after a candidate shows
   promise.
5. Require approximately 300 physical trades before deep engineering.
6. Include realistic spread, commission, financing, and adverse-slippage sensitivity
   from the beginning.
7. Use walk-forward analysis and genuinely untouched validation evidence.
8. Reject results concentrated in one pair, year, or small set of trades.
9. Model capital as an output. CAD 40,000 would require 2-2.5% per month to produce
   CAD 800-1,000; that remains ambitious and is not guaranteed.
10. Limit initial research to 15-20 hours or two weeks before a go/no-go decision.
11. Do not build immutable database machinery until a strategy passes economic screening.

These are recommendations for a new research programme. They do not create a successor
strategy, loosen the terminal boundary, or authorize any implementation.

## J. Appendices

### J1. Exact successful commands

```text
run_successor_acquisition_wave --max-chunks 131 --execute
python manage.py migrate market 0027_gate8i_final_dataset_acceptance --noinput
python manage.py signal_count_s0_v2 --execute
.venv/bin/python manage.py signal_count_s1_v2 --execute
.venv/bin/python manage.py calculate_exploratory_returns_v2 --execute
```

The dataset registration used the existing `register_failed_break_dataset` service
exactly once. Its surrounding invocation is preserved in operational logs; this binder
does not invent command-line arguments that were not part of the governed interface.

### J2. Failed launches and exit status

| Failure | Command/launch | Exit | Persistent effect |
|---|---|---:|---|
| S1 architecture mismatch | Restricted-PATH S1 launch using wrong runtime resolution | Non-zero before Django | Zero queries and writes |
| Return RLIMIT | `.venv/bin/python manage.py calculate_exploratory_returns_v2 --execute` | 1 | None |
| Return timeout | Same exact command under RSS successor authority | 1 after watchdog timeout | Atomic rollback, none |
| Return rollover mismatch | Same exact command under performance successor authority | 1 | Atomic rollback, none |

### J3. Backup inventory

The two authoritative final-operation backups are listed in section G. Earlier stage
backups remain in `/Users/oluwatomisintaiwo/trade-recommender-backups/` with their
mode-0600 SHA sidecars. Disposable validation databases were removed after use.

### J4. Hash glossary

- **Artifact SHA:** SHA-256 of the exact committed file bytes.
- **Self-hash:** SHA-256 of canonical structured content with its self-hash field removed.
- **Configuration SHA:** canonical identity of frozen execution inputs and policy.
- **Evidence SHA:** canonical aggregate of the complete persisted result evidence.
- **Report SHA:** canonical hash of the governed report payload, not a screenshot.
- **Application-count SHA:** deterministic hash of application-table counts used to prove
  the expected persistent state.
- **Preservation aggregate:** combined digest proving earlier governed evidence remained
  unchanged.

### J5. Terminology glossary

- **Physical trade:** one unique market event and one risk allocation.
- **Book membership:** a non-additive label assigning a physical trade to an analysis
  family.
- **Sealed inventory:** registered successfully ingested provider observations eligible
  for governed selection.
- **Strict prior:** evidence completed before, never at or after, the decision timestamp.
- **R:** result normalized by the frozen initial risk of one physical trade.
- **Kish effective count:** concentration-adjusted sample size; not raw membership count.
- **Exploratory-only:** results may describe this closed cohort but can never authorize
  promotion or live trading.
- **Consumed authorization:** a one-shot authority that cannot be reused after its launch,
  whether the launch succeeds or fails.

### J6. Read-only reproduction

1. Check out the annotated terminal tag.
2. Verify the terminal artifact with the fixed-path loader:
   `python -c 'from research.failed_break_v2_terminal_archive import readiness; print(readiness())'`.
3. Verify artifact and binder sidecars with `shasum -a 256 -c`.
4. Inspect JobRun 6 only inside an explicit PostgreSQL read-only transaction against
   `trade_recommender_research`; select identities, statuses, counts, and stored canonical
   hashes. Do not invoke a management command with `--execute`.
5. Compare the canonical result-file SHA and stored evidence SHA to section G.
6. Confirm read-only readiness refuses another return execution. Do not test refusal by
   launching it.
7. Verify the pre/post dump checksums and inspect their catalogs with
   `pg_restore --list`; do not restore over a persistent database.

No reproduction step requires a provider, production database, credential, deployment,
new return calculation, or write. Historical performance is not a forward guarantee.
This closed negative exploratory experiment is permanently ineligible for promotion or
live trading.
