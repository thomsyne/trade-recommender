# Phase 4 — final PM ACCEPT for opening a PR

2026-09-10: **ACCEPT for opening a PR only.** No concrete P0–P3 or missing
original mandatory requirement remains in this bounded requirements review.
This is not authorization to push, create a PR in this task, merge, deploy,
activate schedules, backfill, access providers/production, or consume features
in strategies or forecasts. Those actions require separate authorization.

Reviewed clean branch `phase4/deterministic-market-state` at
[`97ca615`](https://github.com/thomsyne/trade-recommender/commit/97ca6153bcac059471de28500e7c928a19b125a0),
with tested code
[`398feb3`](https://github.com/thomsyne/trade-recommender/commit/398feb35accff746574b8959f73aaecc46a2cecd),
descriptor 0.12.0 and prospective migration 0037. Local main, cached origin/main
and live remote main all equal
[`a3fbe6c`](https://github.com/thomsyne/trade-recommender/commit/a3fbe6ce7fc08895c5696a2a25744f46e5d6e284).
The reviewed HEAD was 24 unpushed commits ahead, with no remote Phase4 branch.
Only omission-verification documentation changed after the tested code commit.

## Authority and review chain

The [original brief and expanded prompt](https://ampcode.com/threads/T-01a0678e-9ea5-722f-99ad-8099c7ec5f76)
(messages 1274, 1281 and deferral clarification 1285) govern this verdict.
Thread summaries are accepted evidence, distinguished from direct PM execution.
The [prior PM rejection](https://ampcode.com/threads/T-01a08a5b-5aad-742e-bbd8-fb95fcd85e2f)
identified exactly three mandatory omissions, closed below.

The [bounded independent acceptance](https://ampcode.com/threads/T-01a08a4d-4732-730a-89b3-5536fa37db7a)
applies to
[`bc4469b`](https://github.com/thomsyne/trade-recommender/commit/bc4469b37d7cc0511f55061085b78bb5f8ec4d60),
not to the later omission commit. It independently closed research first-consumption
immutability, latest-eligible candle/ingestion concurrency, liquidity prerequisite
knowledge times, and consolidation prerequisite knowledge times. The final diff
does not regress those boundaries; this review does not reopen them.

The prior PM trace records the independent closure chain: initial findings
12–14/16; thirteen-finding cycle 2/4/6/7/10–13; six of the eight-finding cycle;
remaining identity/SQL/chronology residuals resolved through the final four above.
The current PM review directly checks the three omissions against source, tests,
design §20 and [retained execution evidence](verification/omissions.md). It is not
a claim of a new broad independent audit of the omission commit.

Acceptance was explicitly superseded before this verdict. This document now
supersedes pending-acceptance language in the historical handoff, design, runbook
and verification records; those records remain unchanged evidence of their dates.

## All original requirement rows reconcile

| Original mandatory scope | Closing implementation and evidence |
|---|---|
| §4.1 monthly/weekly/D1 trend; H4 trend/structure; HH/HL/LH/LL; swings, BOS/CHoCH; persistence and sideways/ranging | `features.py`, `compute.py`, `manifest.py`; feature/review-fix/correction tests and prior independent closures. Monthly uses complete registered daily aggregation; incomplete months cannot bridge continuity. Completed-close structure remains distinct from wick movement. |
| §4.1 volatility/percentile, compression/expansion, distance from equilibrium | Versioned ATR/prior-only population, thresholds, trend/range and equilibrium contracts; `features.py`, `structure.py`; correction/eight-finding tests. Compression-before-expansion is an ordered causal transition, not independent flags. |
| §4.1 scheduled-event and macro regime | `context.py`, exact frozen research identities and vintage/rate/missing-side tests; prior closures plus the event-window omission closure below. Unknown is not neutral. |
| §4.2 swings; normalized S/R zones, age/tests; prior day/week/month and overnight/session extremes | `structure.py`, `sessions.py`, `compute.py`; structure/correction/eight-finding tests and prior closures of zone chronology, distinct approaches, exact preceding periods and complete sessions. Eight-hour descriptive session policy is explicit. |
| §4.2 equal/clustered highs/lows; consolidation; breakout/retest/failed-breakout zones; displacement/origin candidates; structure invalidation | `structure.py`; deterministic identities, linkage/overlap, historical ATR, expiry and terminal failure contracts; structure/correction/final-boundary tests and independent closure of full consolidation dependencies. Candidates imply no resting orders. |
| §4.2 round-number context when empirically justified | Deterministic pip-distance context only; interpretive significance remains experimental/unpromoted without held-out evidence. This is an expressly permitted limit, not a missing mandatory strategy. |
| §4.3 wick breach/reclaim versus completed-close acceptance; clustered-level proxies and prior-session extremes | `liquidity.py`, `structure.py`, `sessions.py`; liquidity/correction/final-boundary tests and omission closure below. Physical breach/confirmation and causal knowledge times remain distinct. |
| §4.3 compression before expansion; ATR-normalized sweep depth; reclaim distance/timing; displacement size; gap/imbalance state | `structure.py`, `liquidity.py`, `fvg.py`; eight-finding, liquidity and ORB/FVG tests. Exact per-event level/source dependencies, normalized acceptance and terminal lifecycle now complete the expanded §4.3 contract. |
| §4.4 London/NY first-15-minute ORH/ORL; completed-close versus wick breach; reclaim/retest/failure | `sessions.py`, `orb.py`; actual required opening M15, local/UTC/DST boundaries, no later-candle substitution, normalization and event-availability context. ORB/FVG and chronology tests plus prior independent closure. |
| §4.4 bullish/bearish strict three-candle FVG; middle direction/displacement; raw/ATR/pip/spread minima; creation/partial/full fill/expiry/invalidation; internal swing break | `fvg.py` supports H4/H1/M15 with registered succession and no cross-timeframe mixing; ORB/FVG and correction tests, normalized equality boundaries and prior independent closures. Missing spread retains price facts without zero substitution. |
| §4.4 event-risk and spread at trigger time | `compute.py`, `context.py`, `orb.py`; frozen trigger-time vintage and contemporaneous bid/ask selection, prior chronology closure and versioned event-window completion. |
| §4.5 terminology inputs/formula/timeframe/formation/availability/expiry/invalidation/causal test; entry/exit/risk | `terminology.py` and exact descriptor validation bind the registry, reject undefined labels, and explicitly state trade entry/exit/risk are not defined in Phase4. Sweep/acceptance v2 terminology matches their implemented lifecycle. |
| Shared deterministic immutable snapshot/definition, causal cutoff/revisions, provenance, missingness, identity, concurrency | `canonical.py`, `definitions.py`, `manifest.py`, `snapshots.py`, forward guards and frozen research; persistence/semantic/final-boundary tests and the independent review chain. No reopening absent a direct regression. |
| M15 prerequisite, all 12 canonical pairs with four decision-enabled, preserved Phase1–3, durable tasks and operational reporting | Existing M15 parity/calendar/ingestion coverage, unscheduled leased/idempotent bounded tasks, cost estimates and completed operational surfaces below. H1/H4/D/W scheduled inventory and decision eligibility remain unchanged. |
| Migrations, adversarial/regression/cost evidence, design/runbook/handoff/lessons and acceptance sequence | Prior independent preservation/parity checks plus final omission evidence and this requirements-only PM decision; stated environment/capacity limits remain nonblocking for PR review only. |

## The three mandatory omissions are closed

1. **Operations:** batch preview is bounded to eight explicit sorted selections;
   standalone validation checks an exact ≤64-KiB definition envelope without DB
   access. Coverage has its own registered-input/current-snapshot policy and
   `--require-complete` exit rule; missing features are separately disclosed.
   Integrity retains bounded snapshot pages and adds task/schedule/M15/direct-source
   consumer drift checks, overflow violations and nonzero exits. Source paths
   perform no registration or mutation. Empty/populated tests trace SELECT-only SQL
   and fingerprint all tables; coverage absence does not become an integrity error.
2. **Events:** descriptor 0.12.0 binds exact UTC inclusive ±1,800 seconds,
   eligible scheduled/released statuses, currency mapping, latest eligible vintages
   and suppressors. Active overlaps form a union of vintage identities; no active
   window means unknown. Date-only events cannot activate intraday windows and
   severity is never inferred. Snapshot and trigger contexts consume the policy.
3. **Liquidity:** exact five-candle level identity, breach ATR14 plus previous-close
   dependencies and breach/confirmation candle identities are emitted. Acceptance
   magnitude uses breach ATR; pending confirmation is not accepted. Physical and
   knowledge times include actual prerequisites. Strict reclaim/close invalidation,
   expiry strictly after 50 registered successors, and gap-first terminal tracking
   match design §20.3 and terminology. Historical facts remain descriptive, not
   entry/exit/risk rules or an unbounded event ledger.

Migration 0037 adds prospective guards and evolves the supported descriptor;
it contains no row rewrite/backfill or schedule creation. “Forward-only” means a
new forward correction, not an irreversible migration: its disposable tested
0036→0037→0036→0037 roundtrip preserves rows and restores prior guards. The 0036
recording-fact reversal refusal remains. Forecasts, settings and technicals are
byte-identical to the original base; the omission diff changes no protected
inventory, decision eligibility, prompt, forecast, dispatch or activation source.

## Verification and honest limits

- Retained omission evidence: **18 new adversarial tests red→green** (checkpoint
  reported 3 failing subtests/16 errors), **205 focused passes**, **10 historical
  parity passes**, and **549 rows/110 tables preserved** with identical within-run
  fingerprints. Test methods and discriminating assertions were inspected directly.
- Broad evidence at the tested code commit: **1,044 tests, 2 failures/238 errors**;
  exact identity/cause/occurrence digest matches the independently accepted
  checkpoint (`bff7b147a631249e2fc36f278dc9a5afc664fb387032e999dd1da8e1dfc3b6ee`).
  This is not green. Research's retained 348-test/22-error result was not rerun for
  the omission task. Hashes of deleted raw logs identify reported runs; they are
  not independently replayable logs or substitute proof of passing tests.
- Direct PM checks: five database-free liquidity lifecycle tests pass, including
  descriptor/SQL digest equality; standalone validation accepts the exact envelope
  and rejects six malformed variants with DB execution forbidden; frozen-event
  endpoint/overlap/status/date-only/suppressor probes pass without DB access.
  Runtime scheduled inventory is exactly H1/H4/D/W. `git diff --check` passes.
- All seven historical artifact checksums/byte counts match, including the
  results manifest cited by the omission record. Current verification artifacts
  total **31,730 bytes across nine files**, including the older checksum manifest
  and later omission record. No raw logs/DB archives remain; secret/machine-path
  pattern checks pass. A direct 148-file protected source/migration comparison
  against the checkpoint passes; the retained engineering inventory reports 164.
  These are different inventory scopes, not a new reproduction of that digest.
- No database was opened in this PM review. Full DB suites, migration preservation
  and red/broad runs rely on the requested retained summaries; they were not rerun.
  PostgreSQL15.5/synthetic evidence and the unchanged data-dependent market0027
  fake-bootstrap accommodation are not fresh-install or PostgreSQL17 certification.
  Production capacity, isolated RSS/WAL, exceptional calendars and exhaustive
  multi-series concurrency remain unverified. Direct-source consumer scanning is
  not dynamic/external information-flow proof. SQL guards do not duplicate every
  formula; Python integrity supplies replay. Superuser trigger bypass remains
  outside ordinary-writer enforcement. These limits authorize no rollout.

The validator's task-owned temporary directory was removed; this PM review created
no cluster, DB, role, archive, worktree or persistent scratch script. Engineering
cleanup of its private cluster is retained evidence. Four pre-existing other
worktrees remain untouched. The only authorized local change is this acceptance
record and its documentation-only commit; no push, PR, deployment, activation,
provider/production/AWS/OANDA, `.env.local` or existing-DB access occurred.
