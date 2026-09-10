# Phase 4.5 engineering acceptance matrix

Status: available engineering evidence complete; independent review required,
not self-accepted. Restore-dependent and deployment gates remain explicit below.
Base, local main and fetched origin/main: `62cf0a095407b1ec29d9c4999ccc56de38fee9d8`.
Initial worktree clean; fast-forward was a no-op. Working branch:
`phase4.5/architecture-stabilization`. No unrelated changes may be overwritten.

Authorization update: the owner subsequently permitted deployed-environment and
provider access when it materially improves proof. This task used only AWS
metadata/object reads and read-only SSM database inspection, then disposable local
restores. No deployed mutation, OANDA request, new instance or teardown was needed.
See [external action evidence](external-actions.md). This supersedes the original
blanket AWS/production-access restriction below only for the recorded actions.

The bounded independent-review correction pass is local-only: no deployed,
production or provider access. It closes RLS-hidden-row and materialized-view
bootstrap defects and pins the explicit waiver to six exact identities/source.
See [correction verification](verification.md#bounded-independent-review-corrections).

| Gate | Requirement / owner | Verification / completion gate | Non-goal |
|---|---|---|---|
| 1a | Test infrastructure: trustworthy ordinary current-state suite | Exact base/final failing identities; broad current-state suite green without skips or weakened assertions | Production behavior changes to satisfy tests |
| 1b | Historical migration fixtures: disposable schema ownership | Fresh historical graphs, irreversible boundaries, teardown isolation; no runtime SQL repair; exact unavoidable exclusions documented | Reversing irreversible history or faking certification |
| 2a | Market time boundary: canonical interval, observation and first-known API | Source time vs completion vs recording vs cutoff; equality, late evidence, caller migration | New ledgers or SQL formulas |
| 2b | Python/PostgreSQL ADR: pure calculation and semantic replay vs durable identity, relationships, immutability and synchronization | Behavior-preserving tests before removing enforcement; races and immutable snapshot identity retained | Broad refactoring or speculative abstractions |
| 2c | Migrations: prospective changes only | Fresh/populated/contradictory/concurrent cases; reversible reverse/reapply preservation | Rewriting Phase1–4 evidence |
| 3a | Operational certification: PostgreSQL 15.14 compatibility and 17.6 target | Exact-version test matrix and deterministic reproducible benchmark | Production capacity inferred from synthetic results |
| 3b | Operations: query count/plans, locks, throughput, RSS, WAL, heap/index/TOAST growth, backlog/restart and realistic history | Measured values, explicit deployment thresholds, alert/failure behavior and unmeasured limits | Production/provider calls or activation |
| 3c | Calendar policy: authoritative versioned exceptional closures and irregular sessions | Source-backed fixtures, absent attestation fails closed, interval and session boundary cases | Inventing universal FX exchange hours |
| 4a | Phase5 readiness ADR and complete acceptance matrix | Enumerate immutable Phase4 outputs, versions, availability, missingness, provenance, permitted derivations and forbidden reinterpretations | Phase5 strategy implementation |
| All | Protected behavior: technicals, schedules/prompts, forecasts/lifecycle/sizing, four decision-enabled pairs, M15 dormant | Semantic fingerprints and schedule/no-consumer checks | Activation or eligibility changes |
| All | Engineering hygiene and handoff | Focused then combined/broad/historical tests; make check, Ruff/format/compile/Django/makemigrations/diff and offline CI scripts; four coherent local commits; live remote refs; clean worktree | Push, PR, deployment, AWS/OANDA/.env.local or existing databases |

Resources must be uniquely named, disposable and task-owned. Retained evidence must
be compact and reproducible, without raw logs, machine paths or secrets. Each gate
must be mapped to evidence or an explicit unresolved limitation in the handoff.

## Final gate disposition

| Gates | Evidence / outcome | Remaining boundary |
|---|---|---|
| 1a, 1b | [Verification](verification.md): 1,464 available tests green on each exact version; real per-scenario historical databases and exact shared-head fingerprint checks | Exactly six source/identity-pinned accepted-fixture tests excluded from 1,470 discovered; default suite retains them and remains blocked by their setup |
| 2a, 2b | [Architecture ADR](architecture.md), asymmetric clock/DST checks, immutable identity races and unchanged descriptor digest | No SQL guard removed, no SQL formula duplicated |
| 2c | [Checkpoint 1](checkpoint-1.md) and [genuine restore](external-actions.md): fresh, negative, catalog-drift, recorder, contention, no-op and reverse/reapply proofs; review corrections cover forced RLS/hidden rows and empty/populated materialized views | Genuine accepted-success and already-applied-0027 restore/no-op proof still mandatory before rollout; deployed backup ends at 0023 |
| 3a, 3b | [Operations](operations.md): both-version measured query/RSS/WAL/heap/index/TOAST/race/backlog limits, clean restarts and full available-test matrix | Synthetic envelope is not deployment sizing; crash recovery, long outages, retained WAL and production queue recovery require rehearsal |
| 3c | Offline source-backed US Christmas closure and fail-closed half-open interval policy; five tests | No Canadian/provider-wide open-session attestation; absent coverage blocks readiness |
| 4a | [Phase5 readiness](phase5-readiness.md): immutable outputs/versions, clocks, missingness, provenance, allowed derivations and prohibited reinterpretations | Documentation only; no Phase5 strategy, schedule, consumer or activation |
| All | Final checks pass; four local checkpoint commits plus one bounded review-correction commit; task resources removed; live main ref unchanged | Independent review remains required; no push/PR/deployment performed |
