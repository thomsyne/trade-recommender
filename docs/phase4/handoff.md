# Phase 4 — correction handoff, not acceptance

## Current: final recording boundary, descriptor 0.11.0

**Acceptance remains superseded pending fresh independent review.** Migration
0036 and this continuation preserve the intentional prior worktree. The four
engineering dispositions are:

| Finding | Disposition and evidence |
|---|---|
| System first-known time | DB-owned nullable `recorded_at`; no legacy backfill. Caller backdating fails through ORM and raw SQL. Late evidence is retained for later cutoffs. |
| Ingestion/snapshot race and future cutoff | Shared per-series transaction locks; READ COMMITTED; non-future database cutoff. Both transaction orders, ORM reselection and stale SQL rejection pass with non-superuser connections and timeouts; committed snapshots pass integrity. |
| Research first-consumption race | Policy/series semantic identity is immutable from registration. Both concurrent orders reject semantic updates; editorial fields remain editable and committed evidence remains valid. |
| Liquidity/consolidation knowledge time | Full actual pivot/ATR/range/lifecycle prerequisites determine availability; physical times remain separate. Before/equality/after and irrelevant-prefix/suffix checks pass, including persisted integrity replay. |

The 187-test focused Phase4 suite and exact 10-test historical migration→M15
parity sequence pass on PostgreSQL15.5 UTF-8. Populated 0035→0036→0035→0036
preserves 549 rows across 110 tables; no system timestamp is fabricated. Reversal
refuses once new recording facts exist. All nine original baseline failing test
identities (eight failures/one missing-field error) now pass. The sweep baseline
expectation was corrected to the same-bar reclaim, not a later unused candle.

See [compact verification](verification/README.md) and its result manifest for
exact commands, broad/research differential, fingerprints, resource cleanup and
final Git checks. Broad suites are not green; inherited failures are not waived.
No activation, forecast consumer, external provider/production access or push is
part of this work. The older sections below are historical; their removed raw
artifacts remain in Git at the starting checkpoint, not in the current tree.

## Historical eight-finding response, descriptor 0.10.0

**Acceptance remains superseded pending fresh independent re-review.** The
following engineering dispositions replace the historical 0.9.0 residuals below.
The starting checkout was clean `phase4/deterministic-market-state` at
[`0188ee5`](https://github.com/thomsyne/trade-recommender/commit/0188ee51f1d4c44664db195ed005aca9243d9800),
including correction
[`160681b`](https://github.com/thomsyne/trade-recommender/commit/160681bf280c5e82fabfe9ac4ac3520cf17be774).
Local main, merge base and cached origin/main remained
[`a3fbe6c`](https://github.com/thomsyne/trade-recommender/commit/a3fbe6ce7fc08895c5696a2a25744f46e5d6e284).

| Review finding | Engineering disposition (not independent closure) |
|---|---|
| 1 Event candidate cutoff | Candidate discovery applies observation/retrieval eligibility; latest eligible suppressor precedes display filtering. Unknown coverage stays unavailable. |
| 2 Instrument metadata identity | Macro currencies and pip sizing use validated canonical code; Python/integrity/DB reject or report contradictory columns. |
| 3 SQL semantic forgeries | Forward 0035 validates research content digests, ordered FK lineage, and actual latest eligible manifest/payload candle/revision. Non-superuser probes reject both original forgeries and accept valid evidence. |
| 4 Consumed-only research | Immutable scalar bundle; identity includes consumed rate periods and event witnesses/suppressors across context cutoffs. Editorial notes do not invalidate replay; consumed policy/series semantic edits reject. Frozen builds issue zero queries. |
| 5 ORB availability | Failure/retest knowledge times propagate opening/ATR/breakout/lifecycle availability; physical completion remains separately disclosed. Both sessions and integrity chronology are tested. |
| 6 Zone availability | Availability uses actual member confirmation and ATR inputs, not the full earlier prefix. Unrelated delay preserves the zone and tests; late confirmation delays it. |
| 7 Exact prior periods | Exact preceding registered day/week/month/session, disclosed source periods and interval identities; no fallback to older available evidence. Friday weekly registration and weekend daily succession remain unchanged. |
| 8 Compression before expansion | Bounded causal transition with strict percentile thresholds, inclusive normalized body/window minima, source identities, formation/availability, pending/unavailable states and future-suffix invariance. Policy is pinned in design §18 and the descriptor. |

Reproduction, focused/affected checks, migration preservation, exact historical
parity, broad differential identities/causes, source fingerprints and performance
plans are retained in [`verification/eight`](verification/eight/README.md).
All ten new regression tests failed against the starting implementation for the
reported defects before passing the corrected implementation. The original
reproduction log is retained, including both session subcases.

Limitations: no production capacity, PostgreSQL 17, exceptional-holiday calendar,
isolated feature RSS or WAL certification. SQL does not duplicate market formulas;
Python integrity independently replays them. Unsupported historical definitions
are reported safely, never rewritten or certified under the new version. These
changes authorize no forecast consumption, push, PR, deployment or activation.
The private resources and final branch/worktree checks are recorded with the new
evidence; unrelated databases, source configuration and services were not used.

## Historical 0.9.0 handoff (superseded where it conflicts above)

**Not ready for acceptance.** This replaces the stale accepted/clean handoff.
The correction preserves the interrupted implementation and adds adversarial
checks, migration isolation and retained evidence. All thirteen findings remain
subject to independent review; the residuals below are not waived.

Starting implementation:
[`064f98a`](https://github.com/thomsyne/trade-recommender/commit/064f98ac565b6d071eac0030ff477f9919333cde).
Exact comparison base, local `main`, cached `origin/main`, and live remote main:
[`a3fbe6c`](https://github.com/thomsyne/trade-recommender/commit/a3fbe6ce7fc08895c5696a2a25744f46e5d6e284).
Branch: `phase4/deterministic-market-state`. The correction is local only; use
[`160681b`](https://github.com/thomsyne/trade-recommender/commit/160681bf280c5e82fabfe9ac4ac3520cf17be774)
for the code checkpoint and the verification file inventory for changed paths.
Remote inspection found other unrelated branches, but no remote Phase 4 branch.
No refs were fetched or changed, and nothing was pushed, deployed, activated,
scheduled, or run against production, AWS, OANDA, or `.env.local`.

## Thirteen finding dispositions

“Tested” below describes engineering evidence, not independent closure.

| # | Finding | Correction and discriminating evidence | Residual |
|---|---|---|---|
| 1 | Exact frozen identity | One materialized candle set feeds manifest/features; research freezes before computation. Exact observation/predecessor/retrieval/policy/source/series hashes bind research. Existing identity race tests and trigger-vintage/no-query regression pass. | **Incomplete minimal-consumption contract:** auxiliary M15/D/W and research selection remain bounded conservative supersets, not a proven consumed-only set. Private eager research model instances are not deep immutable scalar records. |
| 2 | Definition/terminology | Only descriptor 0.9.0 key/version/body/digest is supported. Runtime parameters, lookbacks, session policy and terminology are bound. Unknown identity, bad digest, changed constants and arbitrary classification tests reject. Migration digest agreement is tested. | New versions require a forward migration; this is deliberately not an extensible registry accepting arbitrary bodies. |
| 3 | Semantic forgeries/integrity | 0034 rejects hash-valid scope/instrument/prerequisite/revision/availability forgeries. Non-superuser mutation and exact TRUNCATE refusal pass. Integrity safely handles malformed historical values, replays price/research, and independently compares eligible evidence sets; omission regression passes. Pages are bounded to 100 with continuation cursor. | SQL alone does not reconstruct every formula or reject every omitted-input forgery; application/integrity rejects those. Historical unsupported definitions report `unsupported_definition`, not retrospective certification. |
| 4 | Monthly reachability | 400 D lookback retains fourteen complete months in the production-path regression. Missing registered months cannot become complete or bridge trend continuity. | Registered FX calendar does not model exceptional holidays. |
| 5 | Formation/availability/context | Bars retain observation/completion/revision/content lineage. Formation and availability are distinct; ATR-input availability propagates. Displacement/sweep use historical ATR, ORB uses breakout spread. Frozen macro/event vintage and reschedule tests distinguish historical from final-cutoff context. | Full adversarial coverage of every late revision × trigger × lifecycle combination is not established by these tests. |
| 6 | FVG normalization | Inclusive raw/ATR/pip/spread minima are pinned; equality and rejection in both directions, absent ATR, first-following gaps and late ATR availability are tested. | No production calibration or trading interpretation is claimed. |
| 7 | Registered succession | Weekend H1/D succession differs from true missing intervals. ATR, swings, FVG, acceptance, zones and candidate paths use registered continuity. | Independent audit of every contiguous-feature window remains required. |
| 8 | Zone chronology/expiry | Confirmation-time ATR margins, directional kinds, member identities, post-availability tests, terminal invalidation and age >200 expiry. Tests distinguish pre-confirmation activity, later volatility and reachable expiry. | New members produce a new clustered identity; no persistent cross-snapshot zone ledger is introduced. |
| 9 | Breakout failure/retest | Opposite-boundary failure works in both directions and is terminal. A later touch cannot become a retest of an already failed breakout. | Earlier valid retests can remain historical facts before a later failure. |
| 10 | Complete sessions | Overnight and prior London/NY eight-hour extremes require full registered M15 coverage. ORB carries session/local/UTC boundaries and breakout context. | Eight-hour descriptive session windows are explicitly chosen policy, not exchange hours. |
| 11 | SQL bounds/performance | Indexed cutoff horizon plus DISTINCT/LIMIT; research cap 2,048 fail-closed. 200/3,501 observations, old-cutoff and dense research EXPLAIN evidence retained. | LIMIT does not promise constant scan work for arbitrary revision density. Isolated RSS/WAL and production capacity remain unmeasured. |
| 12 | Historical isolation/parity | Parity setup SQL repair removed. Runnable historical fixtures own disposable DBs; preflight raises unchanged irreversible-operation errors before partial rollback. Exact historical→parity sequence passes both DST checks. | Older historical fixtures still fail at unchanged irreversible forecasts0031; this does not make those fixtures runnable. Exact broad differential is retained. |
| 13 | Honest documentation | Acceptance explicitly superseded. Design §17 governs corrections; runbook gives correct reversal targets and evidence warnings; this handoff and lessons replace stale claims. | No independent re-acceptance has occurred. |

## Original §4.1–§4.5 traceability

| Requirement | Implementation | Verification modules |
|---|---|---|
| §4.1 completed M/W/D/H4 context, swings/trend/ATR/volatility/structure | `state/features.py`, `compute.py`, `manifest.py` | `test_market_state_features`, `test_market_state_review_fixes`, `test_phase4_corrections` |
| §4.2 zones/equal levels/displacement/consolidation/breakout lifecycle | `state/structure.py` | `test_market_state_structure`, correction tests |
| §4.3 sweep/reclaim versus acceptance, normalized observable proxies | `state/liquidity.py` | `test_market_state_liquidity`, correction tests |
| §4.4 M15 ORB, DST, FVG geometry/normalization/fill/expiry/internal break/context | `state/sessions.py`, `orb.py`, `fvg.py`, `context.py` | `test_market_state_orb_fvg`, `test_market_state_context`, correction and semantic-boundary tests |
| §4.5 versioned terminology/formula/timeframe/formation/availability/expiry/invalidation | `state/terminology.py`, `definitions.py`, migration0034 | persistence, review-fix and semantic-boundary tests |
| Persistence, idempotency, raw SQL, safe integrity, unscheduled tasks/CLIs | `state/snapshots.py`, `integrity.py`, `tasks.py`, management commands | persistence/ops/semantic-boundary tests and six-writer probe |
| M15 contract without activation; SQL/Python parity | existing migration0031 and M15/observation code | M15 tests; exact historical-migration→parity run; schedule-integrity tests in broad run |

Protected technicals, forecasts, settings, canonical production seed and live
schedule source files match both starting implementation and exact base.
`verification/protected.json` includes the asymmetric 28-candle technical output
fingerprint, not just file diffs. No strategy, risk, sizing, cost, prompt,
decision-enabled-instrument or schedule change is part of this correction.

## Verification and preservation

See [verification/README.md](verification/README.md), `checks.txt` and the JSON
artifacts for exact results, commands, failure identities and measurements.

- Focused Phase 4/M15: **163 tests pass**, including fourteen semantic-boundary
  tests. Assertions check actual semantics; TRUNCATE specifically requires the
  existing `must not be truncated` refusal, not an unrelated “immutable” message.
- Exact live-observation historical migration→SQL/Python parity: **10 pass**;
  no setup SQL installation. The separate impossible-plan test checks migration
  state and installed M15 definitions remain byte-identical.
- Broad comparison executes all `market operations forecasts`, not a selected
  passing subset. Both sides use separate fresh schemas, UTF-8/template0 and the
  same 0027 accommodation. `differential.json` retains every failing identity,
  normalized terminal exception cause and repeated teardown occurrence.
  Base: **838 tests, 2 failures/244 errors, 241 unique failing identities**.
  Correction: **1,002 tests, 2 failures/238 errors, 235 unique failing identities**.
  **No new failures or changed causes; six live-observation historical failures
  removed.** The remaining 233 irreversible-error identities hit unchanged
  forecasts0031. The two shared assertions are Gate5 installed-function MD5
  `e7d028c9a27596a1b9fba65bd7015cb6` versus expected
  `5ef0117c6a32cca8a81322a7766d8f52`, and the disposable connection role's
  `on` versus `off` superuser expectation. Normal-role semantic probes pass
  separately; neither inherited assertion is suppressed or weakened.
- `make check`: Ruff, formatting, Django system checks, no pending migrations
  and compileall pass. CI's offline IAM/bootstrap/remote/backup/infra/Compose/
  Terraform-format/production-settings checks were exercised. Hosted CI and
  deployment stages were not run; the unrelated full-repository Django suite
  remains outside this focused broad comparison. Local PostgreSQL was 15.5,
  not the CI service image's 17.6; cross-version execution is unverified.
- An unaccommodated fresh graph fails at the unchanged data-dependent market0027.
  Only that migration was faked in disposable bootstraps; the rest of the graph
  installs normally, including M15 and 0034. This is **not** an unqualified fresh
  install pass.
- Starting-code populated upgrade: **110 tables, 549 rows**, including two
  observations and one existing snapshot, byte-identical after 0034. Its reversal
  to0033 and reapplication also preserved those rows. No synthetic snapshots were
  migration-created. Existing unsupported evidence is reported safely.
- Six non-superuser concurrent writers: **one snapshot, one created result,
  identical output**. Temporary probe role was removed.

## Measured cost, not production capacity

| H1 observations | Build queries / seconds | Compute + persist + verify queries / seconds | Manifest entries / bytes | Payload bytes |
|---|---|---|---|---|
| 200 | 6 / 0.0643 | 19 / 0.2166 | 200 / 33,001 | 9,265 |
| 3,501 | 6 / 0.0819 | 20 / 0.3142 | 300 / 49,501 | 11,745 |

Plans include SQL, LIMIT, actual rows, buffers and old cutoff. At 3,501 the
current H1 selection uses the existing series/revision index, reads300 rows,
filters0; the old-cutoff query returns0. The 200-row planner can choose a small
sequential scan. Dense research adds 201 event vintages and 200 macro observations:
7 build queries, 0.2000s, 193,259 payload bytes and 231,163 evidence bytes. The
rescheduled-out event is absent and macro direction is checked as tightening.

PostgreSQL heap/index/TOAST and compressed column sizes are recorded. Process peak
RSS was about69/94 MB, **including ingestion**, not isolated feature working set.
WAL is unmeasured because the disposable cluster served concurrent test databases.
Production load, scheduler cadence, multi-instrument throughput and retention
capacity are unmeasured. No rollout follows from these probes.

## Remaining work and cleanup boundary

The strict consumed-only/deep-immutable evidence requirement in finding1 is not
fully closed. SQL is not a full independent formula engine; broader adversarial
temporal/revision review remains necessary. Do not label the correction ready,
self-accept, or activate it based on the passing focused suite.

Owned disposable resources are the private PostgreSQL cluster under
`/tmp/p4-correction-7yufFa`, its databases, its `base`/`starting` worktrees, and
`/tmp/p4-resume-x0R8N8`. Their removal and final Git/remote/worktree verification
are recorded in `verification/checks.txt`. Unrelated local databases, worktrees,
branches and services must remain untouched. Retained artifacts contain synthetic
data only; temporary scripts and superseded logs are not operational dependencies.
