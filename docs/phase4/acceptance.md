# Phase 4 — Acceptance

> **RE-ACCEPTED after slice 10.** The earlier acceptance (recorded at `ec1bdaf`,
> preserved below) was reopened when a deeper independent review found sixteen
> substantive findings (no P0) — snapshot identity not binding all consumed
> inputs, the definition not governing computation, a missing terminology
> registry, an unbounded SQL scan, registered-interval and contemporaneous-ATR
> gaps, and more. All sixteen were corrected in **slice 10** (commit `d01b138`),
> each with a discriminating test (`test_market_state_review_fixes`). A **round-4
> independent re-verification** then confirmed all sixteen RESOLVED with no new
> P0–P3, and a **fresh PM pass** checked all seven rejection criteria against the
> source — every one PASS. This acceptance stands at HEAD `3d89b59`. See
> [review-lessons.md](review-lessons.md) round 3 and the round-4/PM records below.

Recorded **after** two independent-tester passes and two PM passes. Branch
`phase4/deterministic-market-state`, HEAD `3d89b59` (the slice-10 corrections
`d01b138` plus their doc commits). Base / `origin/main`:
`a3fbe6ce7fc08895c5696a2a25744f46e5d6e284` (unchanged; branch unpushed).

## Process

1. Mandatory design record ([design.md](design.md)) authored before implementation.
2. Slices 1–8 implemented, each validated (focused tests + `make check`) and
   committed separately:
   1. M15 live granularity contract + calendar (+ SQL parity migration).
   2. Immutable definition/snapshot persistence + migration + triggers.
   3. Higher-timeframe context.
   4. Support/resistance and structure.
   5. Liquidity proxies.
   6. ORB and FVG.
   7. Macro/event/spread point-in-time context.
   8. Durable task, integrity report, dry-run CLIs.
3. Engineer [runbook.md](runbook.md) + [handoff.md](handoff.md).
4. **Independent tester (round 1)** — no P0; one P1, two P2, three P3.
5. **Engineer corrections (slice 9)** + bounded-scan follow-up; see
   [review-lessons.md](review-lessons.md).
6. **Independent tester (re-review)** — all six round-1 findings RESOLVED, no new
   P0–P3: **ACCEPT for PM review**.
7. **PM acceptance (first)** — recorded at `ec1bdaf`; later reopened (below).
8. **Independent tester (round 3, deeper)** — sixteen findings, no P0; all
   corrected in slice 10 (`d01b138`) with discriminating tests.
9. **Independent tester (round 4, re-verification)** — all sixteen RESOLVED, no
   new P0–P3, both parity identities now green: **ACCEPT for PM review**.
10. **PM acceptance (final)** — all seven rejection criteria checked against the
    source, every one PASS.

## Accepted documented limitations

- FVG spread-normalization reported `unavailable` (price facts retained);
  deterministic internal-swing-break invalidation deferred (full-fill + expiry
  implemented and claimed).
- Macro regime is point-in-time policy-rate level + direction only; event
  severity always `unavailable` (no trustworthy field); round-number
  interpretation `experimental_deferred`.
- `data_quality_status` is a coarse family-level aggregate; per-feature
  availability lives in the payload.
- The `market0027` fake-bootstrap and runtime-superuser trigger-bypass test
  limitations remain as documented and were not broadened.
- The pre-existing Gate8 migration-reversal failing identities in the broad
  `market` suite are untouched; an exhaustive full-suite identity diff was not
  re-run this session (low residual for PR review — protected diffs empty, focused
  suite green).

## Verification at final acceptance (HEAD `3d89b59`)

- `git diff main..HEAD -- market/technicals.py forecasts/`: **empty** (protected).
- Focused market-state suite: **129 tests, 0 failures**; both
  `SqlPythonParityTests` identities green; `make check` clean (ruff check/format,
  `manage.py check`, `makemigrations --check`).
- Broad-suite failures: **11, all the documented pre-existing `forecasts.0031`
  `IrreversibleError`** (`Phase2BMigrationSafetyTests` reversal setUp); no new
  failing identity. `forecasts/migrations/0031` is unmodified on this branch.
- `origin/main` == `a3fbe6c`; branch unpushed (`git branch -r --contains HEAD`
  empty); no provider/AWS/OANDA/Anthropic call; M15 present as an on-demand
  granularity but excluded from `SCHEDULED_LIVE_GRANULARITIES` — nothing
  scheduled, activated, deployed or backfilled.

## PM verdict (final)

> ACCEPT Phase 4 for opening a PR under the documented limitations. All seven
> rejection criteria PASS (protected diff empty; no prohibition violated; no
> trades/directional conviction/hidden-liquidity intent; determinism/causality/
> immutability intact; the spot-checked slice-9/10 fixes genuinely implemented;
> docs match code; broad-suite failures are the pre-existing `forecasts.0031`
> only). This does not authorize deployment, schedule/M15 activation, provider
> spending, strategy use, promotion, or production backfill.

## What this authorizes / does not

Authorizes **opening a PR** for Phase 4 under the limitations above. Does **not**
authorize deployment, schedule/M15 activation, provider spending, strategy use
(Phase 5 owns strategies and consumes these snapshots read-only), promotion, or
production backfill. Opening/merging the PR and pushing remain a human action.
