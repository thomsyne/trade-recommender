# Phase5 acceptance matrix — not acceptance

Owner of implementation/tests: Phase5 engineer. Owner of hypothesis acceptance,
holdout release, combination and rollout: project owner after independent review.
No row is self-accepted. Evidence must distinguish synthetic engineering checks
from economic validation. `pending` means incomplete, not waived.

Initial checkout: clean `main`; local HEAD, fetched `origin/main` and required base
all `131a2fc1cd6d2d849cb13a94ce5b937cf0fe8a44`. Read-only fetch completed; safe
fast-forward was a no-op. Work branch: `phase5/explicit-strategy-library`.
Remote: `https://github.com/thomsyne/trade-recommender`. Worktree: repository root.

The exact contracts in [design](design.md) and [ADR](architecture.md) are part of
every row. Tests will live in `market/tests/test_strategy_library*.py`; evidence
and exact command results will be retained in `verification.md`.

| ID / checkpoint | Requirement and owner | Exact contract | Discriminating test | Evidence / disposition | Non-goal / gate |
|---|---|---|---|---|---|
| A1 | Engineer: output types | Separate continuous, setup, intent, result, overlay schemas; unknown carries reason, never numeric zero | Cross-kind fields rejected; unavailable has no signal | pending | No recommendation adapter; review gate |
| A2 | Engineer: immutable dependencies | Exact 0.12.0 digest, snapshot identity, cutoff, both manifests, output hash; exact cited observations only | Bad digest, late revision/recording, future suffix | pending | No current Candle substitution |
| A3 | Engineer: pure boundary | Frozen scalar inputs → deterministic output; persistence and simulation separate | No DB during calculation; repeat bytes | pending | No SQL formula engine |
| A4 | Owner: preregistration | Definition/simulator/population/era/holdout/threshold hashes registered before outcomes | Changed era/holdout/definition refused | pending | No retrospective threshold fitting |
| B1 | Engineer: EWMAC | Design §2 exact pairs, EW variance, scalar, cap, affordable equal mean, FDM 1, buffer 1 | Asymmetric EMA/variance, warmup, zero vol, ±20, ±1 boundary | pending | No inferred profitability |
| B2 | Engineer: breakout | Design §3 10/20/40/80/160/320 D, EMA ceil(N/4), scalar 40, cap, independent combination | Flat range, smoothing, high/low asymmetry, cost exclusion | pending | Never pooled with EWMAC |
| C1 | Engineer: fast MR | Prior D EWMA5, H1 deviation, EWMAC16/64 alignment, vol ratio reduction | Daily completion equality, opposing trend, high-vol boundary | pending | No executable limit-fill claim |
| C2 | Engineer: simulation | Next registered interval, quote-unit costs, adverse dual hit/gap, financing/conversion evidence | Stop and target same bar, weekend, gaps, missing costs and conversion | pending | Gross ≠ net; evidence readiness gate |
| D1 | Engineer: ORB | London/NY first M15; separate wick/basic, close-confirmed and FVG identities | DST, weekend, missing open, wick versus close, strict equality | pending | No M1 interpolation/ingestion |
| D2 | Engineer: ORB geometry | Design §5 ATR/spread stop, 2R target, 8h exit, 2h entry expiry, one attempt/trade | No same-bar entry, FVG direction/equality/gaps, expiry | pending | FVG retained only after untouched net comparison |
| E1 | Engineer: pullback | D/H4 trend same sign; qualified H4 zone; M15 or H1 reclaim+continuation | Expired/unqualified zone; opposite trend; separate timeframe IDs | pending | No subjective confluence |
| E2 | Engineer: range MR | D sideways, H4 consolidation; outer 10% edge reclaim, next close continuation, center exit | Center entry refused; expansion or unknown event blocks readiness | pending | No trading during unknown-safe calendar |
| E3 | Engineer/owner: failed break | Sweep reversal and acceptance continuation separate; exact M15 structure, 0.25ATR invalidation | Pending sweep, invalidated/expired event, structure mismatch | pending | Preserve v1/v2 negative evidence; new prospective era |
| F1 | Engineer: carry readiness | Requires PIT forwards/financing/rollover/broad ranking; rates never substitute | Policy-rate-only → unavailable | pending | No carry direction or trend+carry before standalone proof |
| F2 | Engineer: event overlay | Named decisions/CPI/employment/GDP; inclusive ±1800s; pause/reduce/unchanged only on evidence | Later vintage/suppressor, date-only, missing consensus, empty ≠ safe | pending | Risk only; no production effect |
| F3 | Engineer: GARCH challenger | Fixed/EWMA/Student-t GARCH independently; multiplier ≤1 | Convergence/failure/nonfinite, cap, insufficient history | pending | Mature pinned solver; no directional forecast |
| F4 | Owner: exclusions | Equity/options/dilution, HP, triangular candles, acceleration, normalized-trend priority, subjective SMC/ICT, RL deferred/rejected | Registry contains none | pending | No silent future implementation |
| G1 | Engineer: attribution | Separate strategy/version/session/timeframe/population/era; dependent weeks/currencies not independent samples | Mixed IDs refused; duplicate/overlap units not inflated | pending | No silent pooling or unsupported profit claim |
| G2 | Engineer: persistence | Immutable definitions, evidence, results; FK/hash/unique locks, raw SQL update/delete/truncate refusal | ORM/raw SQL/concurrent retry; migration preservation | pending | New forward migrations only |
| G3 | Engineer: operations | Explicit bounded offline preview/report/integrity; idempotent task callable, unregistered | SELECT-only report, retry, overflow, no schedules/import consumers | pending | Four/eight eligibility and dormant M15 preserved |
| G4 | Engineer: verification | Focused then combined; exact base/final failures, unchanged six Phase4.5 exclusions; PG15.14/17.6 | Persistence/concurrency/migration on both; make check/offline CI | pending | No fake accepted restore or hidden exclusions |
| G5 | Engineer: handoff | Local A–G commits, fingerprints, clean owned resources/worktree, remote recheck | Diff/source hashes/ref evidence | pending | No self-accept, push, PR, merge, deploy or activation |
