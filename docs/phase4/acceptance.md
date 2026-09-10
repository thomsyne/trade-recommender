# Phase 4 — Acceptance

> **SUPERSEDED (reopened).** After the acceptance below, a deeper independent
> review found sixteen substantive findings (no P0) that the earlier tester/PM
> passes missed — snapshot identity not binding all consumed inputs, the
> definition not governing computation, a missing terminology registry, an
> unbounded SQL scan, registered-interval and contemporaneous-ATR gaps, and
> more. All sixteen were corrected in **slice 10** (commit `d01b138`) with
> discriminating tests, and re-verification is in progress. This acceptance does
> **not** stand until that re-review completes. See
> [review-lessons.md](review-lessons.md).

Recorded **after** independent-tester and PM acceptance. Branch
`phase4/deterministic-market-state`, HEAD `ec1bdaf` (this file adds one more
commit). Base / `origin/main`: `a3fbe6ce7fc08895c5696a2a25744f46e5d6e284`
(unchanged; branch unpushed).

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
6. **Independent tester (re-review)** — all six findings RESOLVED, no new P0–P3:
   **ACCEPT for PM review**.
7. **PM acceptance** — every rejection criterion checked, none holds.

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

## Verification at acceptance

- `git diff main..HEAD -- market/technicals.py forecasts/`: **empty** (protected).
- Focused market-state suite: **113 tests, 0 failures**; `make check` clean.
- `origin/main` == `a3fbe6c`; branch unpushed; no provider/AWS/OANDA/Anthropic
  call; nothing scheduled, activated, deployed or backfilled.

## PM verdict

> ACCEPT Phase 4 for opening a PR under the documented limitations. This does not
> authorize deployment, schedule activation, provider spending, strategy use,
> promotion, or production backfill.

## What this authorizes / does not

Authorizes **opening a PR** for Phase 4 under the limitations above. Does **not**
authorize deployment, schedule/M15 activation, provider spending, strategy use
(Phase 5 owns strategies and consumes these snapshots read-only), promotion, or
production backfill. Opening/merging the PR and pushing remain a human action.
