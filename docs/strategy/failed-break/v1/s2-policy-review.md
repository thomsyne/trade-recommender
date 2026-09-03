# S2 policy-freeze candidate — independent review

This is a code-only candidate, **not an effective S2 freeze or permission to
calculate returns**. All seven new-policy decisions below require owner
authorization. The candidate has no effective timestamp, all authority flags are
false, and `require_frozen_policy()` refuses. No strategy, dataset, S0 or S1
identity is replaced. No schema or migration is needed for this gate.

Baseline: `7e34bdf9dbf5b43e45f638acbd685a7070d1733e`.
Scope: one canonical JSON candidate, one standard-library-only loader/readiness
module, one bounded test module, and this review ledger. There is no executor,
simulation, performance calculator, database writer or policy-registration service.

## Evidence reconstruction and identity safety

The source is the verified post-S1 archive, SHA-256
`9b8bb6845fe1f8b9dcb0f340d13c0edfe09529564065095318781c89c7a677e0`.
Only its `research_jobrun` table was extracted to stdout with `pg_restore
--data-only --table=research_jobrun --file=-`; no connection or restore into a
database was made. Exactly jobs 1, 2 and 3 were present. Their configuration and
report objects are embedded in the candidate, and all six original hashes
reconstruct against independently pinned accepted constants. No candle, setup,
entry-price or outcome table was extracted. This verifies accepted archived
evidence, **not the current live database**.

The loader also checks the original specification, approval, freeze manifest,
accepted S0 artifact, reviewed pre-S1 source files and migration-0015 digests.
It checks canonical JSON bytes, external file digest and internal self-hash;
verifies inherited manifest sections, S0 ceilings and 24 distribution hashes;
and reconstructs the pre-S1 and CAD route-table identities without importing
the ORM or old signal-count runners. No path/environment/artifact override exists.

Effective data is dataset **3**, `phase-2b1r-v2`, contract **2**,
`oanda-ba-ny17-friday-provider-observed-v2`; strategy **1** remains
`failed-break-phase-1-freeze-v1`. The predecessor data label retained inside the
historical strategy/S0 manifest is archival compatibility, never active routing.
The accepted S0 artifact supplies the unchanged registration identities. The
365,055-candle count and underlying snapshot are accepted baseline assertions;
this gate deliberately does not recount live candles or recompute a database snapshot.

Material count distinction: **90 combined-book eligible physical events**, not
204 independent trades. The 204 evaluations include 40 daily-swing, 31 breakout,
43 weekly and 90 combined-book requests. The 316 included confirmed setups have
196 non-empty issuance weeks and exact Kish count `49928/331`. These are
**confirmed-setup** clusters, not eligible/resolved-trade clusters. The S1
book/time/direction currency grouping has 408 singleton incidences; this is not
proof of 408 independent currency factors.

## Rules reconstructed without new decisions

The authoritative source is `phase-1-specification.md`, its approved machine
manifest, and the independently approved pre-S1 successor conventions. Their
full source digests are in `source_sha256`; the candidate retains the manifest
sections verbatim as structured values in `reconstructed_manifest_rules`.

| Rule | Authority and current implementation | Frozen meaning |
|---|---|---|
| Entry and price | §§5,11,12.1; `strategy.entry_eligibility`, detector, research 0015 | First sealed H1 open at/after confirmation completion; long ask/short bid; effective open distinct from later admission; never delay a session block. |
| Stop and target | §§12.2–12.3; `strategy.entry_eligibility`, `nearest_opposing_target` | Buffer max(open spread, 0.10 completed H1 ATR14), outward stop rounding, nearest independently active opposing zone, weekly/daily/breakout then activation/stable-key ties, target frozen, minimum 1.5R. |
| Holding/purge | §13 and accepted B7; `signal_count._maximum_horizon_end` | Ten actual sealed D completions strictly after entry; entry-containing session counts only on later completion; first sealed H1 open at/after tenth completion; horizon must be strictly before partition boundary. |
| Spreads | §11.2 and accepted S0 | Six unchanged P99 ceilings plus spread/H1 ATR ≤ 0.10; 24 frozen distribution hashes; no outcome-conditioned refreeze. |
| CAD | §12.2 and approved D4 | Independent latest sealed H1 midpoint-close legs strictly before entry; no elapsed-clock staleness or missing-member fallback. CAD identity; USD via USD_CAD multiply; GBP via GBP_USD then USD_CAD multiply; JPY via USD_JPY divide then USD_CAD multiply. |
| Risk and allocation | §15 | Independent C$10,000 books; request 0.25% equity risk; 1% aggregate and 0.5% gross currency-direction caps; largest common fraction; no netting or redistribution; no pair preference. |
| Exit | §§5,13,14 | Side-aware stop/target touches; same-H1 stop first; worse adverse stop gap; no favorable target-gap fill; strict daily structure invalidation; no trailing, scaling, pyramiding or breakeven changes. |
| Costs | §16 | Spread once; primary commission unknown/excluded and financing unavailable/excluded, not net broker performance. All 3×5 cost scenarios preserved; signed financing, NY rollover and Wednesday multiplier; no profitable-cell selection. |
| Missingness and closures | §§4.5,10 and approved B6/B7/D9 | Expected missing/conflicting sealed member fails closed; DATA_INCOMPLETE / CANCELLED_DATA_QUALITY / UNRESOLVED_DATA by stage. Inventory omission is closure, not a synthesized candle. |
| Statistical design | §§17–19,21 | Combined book primary; separate family accounting and Holm secondary tests; all comparators; 10,000 stationary daily-bootstrap and NY-week clustered replicates; frozen block-length formula; chronological and untouched partitions remain locked. |
| Decision clock | §5 and pre-S1 | Admit completed evidence, previous-H1 stop/target, D/W lifecycle/structure, pending setup decisions, simultaneous entries, new sweeps, scheduled exits. No premature release of scheduled-exit risk. |

The strategy has no S2 execution/evaluation registration architecture to reuse.
Unrelated forecast/paper-trading portfolio code is not authority for this strategy.
This gate does not route through it or claim to protect unrelated historical commands.
Any future failed-break return command must separately implement and invoke a
hash-bound effective-policy authority check before opening outcome-bearing data.

## One bounded decision ledger — all pending authorization

Exact formulas, denominators, null rules and proposed numeric values live in the
canonical candidate's `decision_ledger` and `metrics`. The following is the
human-readable decision list, not additional policy.

| ID | Recommended default | Reason / remaining authority |
|---|---|---|
| S2-01 | Unconstrained theoretical notional: no broker leverage, margin constraint or liquidation simulation. One base-unit step; Decimal precision 38, half-even, ten stored decimal places. Quote-difference CAD cash accounting, extend independent strict-prior sealed conversion to each valuation/cash flow, NY 17:00 daily equity grid. Closure marks use only the last available sealed side-close, explicitly not a tradable bar. Nonpositive equity blocks new allocations and valid percentage-return inference. | Margin, venue unit step, post-entry CAD/valuation clocks and accounting precision were not governed. This is a proposed research convention, not broker realism. |
| S2-02 | No extra slippage model (0 additional pips, not evidence of zero historical slippage); keep adverse gaps/stop-first. Scenario commission at terminal exit. Rollover membership `entry < rollover <= exit`. Stop, target, structure, time priority; distinct physical signals remain independent gross requests, duplicate event/book is an error. | Completes unspecified cash-flow/tie/conflict details; preserves the §5 allocation-before-scheduled-exit sequence. |
| S2-03 | 95% two-sided percentile intervals; α=0.05; design power 80%; explicit SHA-counter seed and quantile rules. Calendar-day annualization 365.2425; daily reference rate and Sortino MAR 0. Sharpe/Sortino **descriptive only**, never tuning, selection or acceptance. Undefined denominators yield null/reason. | No historical risk-free rates are inferred or fetched. All formulas are text, not calculations on returns. Assumed dispersion is a design scenario, not estimated evidence. |
| S2-04 | Per promoted book/partition: ≥100 included confirmed setups, ≥50 eligible physical events, ≥50 resolved allocated trades, ≥30 paired events where genuinely paired, ≥40 entry dates, ≥30 raw and Kish entry weeks, ≥20 Kish shared-factor clusters, ≥1,095 calendar days, coverage 100%, unresolved evidence 0. | Proposed adequacy floors, not proof of power. Shared-factor grouping uses eligible events connected within NY week by either currency; the current aggregate S1 report cannot reconstruct that geometry. A later separately authorized return-blind projection may inspect existing immutable evidence, never rerun S1. Insufficiency is inconclusive, not permission to relax gates. |
| S2-05 | Mean primary effect ≥0.20R, lower 95% endpoint >0; positive comparator-difference lower endpoints; ≥95th random-timing percentile across all 100 replicates; all 15 cost cells fully resolved with mean ≥0R; Holm for three families. Owner-only non-activating promotion. Drawdown is reported relative to 0.25% planned risk, without an invented 10% retirement rule. | Strong proposed joint gates fixed before returns, not selected from results. Null-centered bootstrap p-values and pairing rules are explicit. |
| S2-06 | Initial-risk-weighted maxima: pair 40%, year 40%, direction 80%, session 80%, gross currency-direction 50%, combined-book family 60%. Split overlapping family weight equally; currency denominator is twice total risk. Family books exempt only from their definitional family concentration. | Explicit denominator and overlap treatment prevent falsely independent concentration claims. A breach retains evidence and blocks promotion; no subgroup deletion. |
| S2-07 | Ambiguous-primary-trade fraction ≤10%; replay mismatches 0; unresolved evidence 0. Optional separately authorized M1 refinement needs ≥30 pairs and reports all disagreements; unavailable M1 never deletes primary H1 trades. | H1 remains complete. No M1 retrieval or other acquisition is authorized by this policy candidate; no extra paired-data requirement silently reopens the closed historical-data phase. |

Formula coverage includes side-aware quote/CAD P&L and fixed initial-risk R,
expectancy, descriptive win rate/payoff/profit factor, daily/cumulative/annualized
equity returns, drawdown and planned-risk normalization, Sharpe, Sortino, Kish,
paired differences, empirical quantiles, coverage and ambiguity. **None was
calculated on a trade, price path or portfolio in this gate.**

Count-only diagnostic: at the proposed 0.20R effect, 95% confidence and 80%
power, a hypothetical independent normal approximation needs 50, 197 or 785
independent units for assumed standard deviations 0.5, 1 or 2R. No empirical
dispersion was read, no returns were generated, and no attained-power claim is
made. The 90 combined eligible events do not establish effective independence.
The exact eligible/week/shared-factor power design remains prerequisite to an
effective freeze; this candidate cannot substitute confirmed-setup Kish for it.

## Readiness, efficiency and anti-lookahead boundary

Run offline, with an empty environment and the repository interpreter:

```bash
env -i PATH=/usr/bin:/bin .venv/bin/python -m research.s2_policy
env -i PATH=/usr/bin:/bin .venv/bin/python -m research.s2_policy --require-frozen
```

The first verifies candidate integrity and reports `REVIEW_REQUIRED`; it does
not run S2. The second exits 2 (expected refusal). There is no `--execute`, path,
dataset, arbitrary artifact or outcome-input argument. No approval status or
effective timestamp is invented. A subsequent authorized reviewed change is
needed to publish an effective freeze; operational return access remains separate.

The timestamp-only `SealedMetadataIndex` preloads expected inventory separately
from admitted references. Binary-search selection never falls back around a
missing expected member. Conversion strictness, entry-open field restrictions,
holiday adjacency and ten-D horizon equality are pinned by small tests. Horizon
selection returns only timestamps and is not an exit-evidence resolver.
`require_projection` authorizes fields only; callers must also validate admitted
membership and adjacency. Neither helper can return a price or an outcome.

Future execution requirements are hashed, but **not implemented**: preload bounded
series projections, no per-row ORM queries, independent reference equivalence,
append-only transactional batched writes, stable complete timestamp batches,
deterministic progress counters and stop-on-failure semantics. No executable
write/return path is introduced here. A future integration must demonstrate its
own throughput and golden equivalence before activation.

Representative disposable in-memory benchmark: 200 sealed metadata members,
50 indexed/reference comparisons, **0.002304 seconds**, all equal. Expected
focused-suite runtime before starting: **under 5 seconds**. No operation expected
to exceed 30 minutes was launched. No database restore/rehearsal was necessary.

## Verification scope

Focused tests: `python -m unittest research.tests.test_s2_policy -v` (26 tests).
They cover canonical/source/self hashes, accepted-job reconstruction and forgery
refusals, all-pending authority, source drift, successor routing, no overrides,
count-population distinctions, stdlib-only imports, offline read-only operation,
entry/conversion field and time boundaries, holidays/unusual timestamps,
missing/conflicting/failed/predecessor evidence, ten-D boundaries, and indexed
equality with an independent linear metadata reference.

Final-commit verification also runs Ruff check/format check on the new Python
files, Django system checks with a dummy database and explicit connection denial,
migration autodetection `--check --dry-run` under the same denial, compileall on
new Python files, candidate readiness and expected authority refusal, and git
diff checks. No full suite. Exact final-commit results and file hashes are reported
in the external implementation receipt rather than modifying an already-tested commit.

Isolation: no live persistent database connection, provider, credential lookup,
S0/S1 rerun, candle/outcome read, metric calculation, migration application,
strategy signal, deployment, PR or push. The only historical evidence inspected
was the accepted return-blind JobRun export in the existing verified backup.
