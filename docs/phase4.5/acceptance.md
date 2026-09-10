# Phase 4.5 engineering acceptance matrix

Status: **Final PM ACCEPT for opening a PR only — not rollout**, 2026-09-10.
Independent review and final requirements traceability are complete for the
reviewed engineering head. Restore-dependent and deployment gates remain below.
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
| All | Final checks pass; initial acceptance record, four local checkpoint commits and one bounded review-correction commit; task resources removed; live main ref unchanged | Independent review reconciled below; PM acceptance adds only a local documentation commit; no push/PR/deployment performed |

## Final PM traceability decision

Reviewed engineering head: `4ad4c081ee2b35882afd383bb4ee6156dc32a754`.
Direct checks confirmed the clean named branch, six unpushed commits, no upstream
or remote Phase4.5 branch, and local main/origin/main/live remote main at the base
above. This decision covers the complete base-to-head diff, all Phase4.5 documents,
the engineer handoff and both independent reviews; it is not a new code audit.

| Checkpoint | PM verdict | Acceptance basis and retained limit |
|---|---|---|
| 1 — test/migration harness | ACCEPT for PR | Singleton 0027 replacement; fresh empty PG15.14/17.6 installation; per-scenario historical isolation; exact installed catalog, reversal, recorder and contention evidence; genuine populated-negative restore preserves original refusal. Only six unchanged, source/identity-pinned fixture methods are restore-required. Default suite remains non-green. Genuine accepted-success and already-applied-0027 restore/no-op proofs remain mandatory before rollout. |
| 2 — architecture boundary | ACCEPT for PR | Canonical completion/first-known/availability calculations preserve distinct clocks and historical contracts. Python/DB ownership is explicit; published SQL guards, descriptor identity and protected Phase1–4 behavior remain unchanged. |
| 3 — operations | ACCEPT for PR | Exact PG15.14 compatibility and PG17.6 local certification, reproducible measurements and thresholds, bounded backlog/reconnect and clean-restart evidence, and source-backed exceptional-calendar fail-closed policy are documented. This is not production-capacity, crash/queue-recovery, deployed-alerting or provider-wide calendar certification. |
| 4 — Phase5 readiness | ACCEPT, documentation only | The consumption matrix pins immutable outputs, versions, causality, missingness and provenance, with explicit allowed derivations and forbidden reinterpretations. No Phase5 strategy, schedule, consumer, eligibility change or activation is introduced. |

The [initial independent review](https://ampcode.com/threads/T-01a08bc9-27f3-755f-912f-95aa4def329a)
rejected forced-RLS visibility (P1), materialized-view locking (P2) and an overbroad
runner waiver (P3). The [bounded correction review](https://ampcode.com/threads/T-01a08c1d-c163-7277-9169-3382150d6c1a)
verified all three closed at the reviewed head: uncertain visibility/unsupported
relations delegate unchanged, and the exact waiver fails closed on pin drift or
missing identities while retaining an unlisted regression. Its 53/53 checks passed
on each exact version. No concrete unmet matrix requirement or remaining P0–P3
finding remains within this PR acceptance scope.

Engineering records 1,464 available tests passing on each version out of 1,470
discovered. The independent correction review did not rerun that full partition;
deleted broad-run logs lacked retained hashes. Default fixture runs discover six,
execute zero and report a setup error, not passes or skips. The six restore-required
methods and two unavailable genuine rollout proofs are **honest pre-rollout gates
compatible with this PR acceptance**, not completed proofs or a waiver of rollout
requirements. The available backup ends at 0023 without accepted registration;
its genuine negative result cannot substitute for either successful restore path.

The owner's external-access authorization and [action ledger](external-actions.md)
support the recorded AWS metadata/backup reads and read-only deployed SQL, followed
by disposable local restores. No activation, provider API call, deployed application
or database mutation occurred according to that evidence; SSM audit records and
ambient scheduled ingestion are explicitly distinguished. The private archive and
restore digest were not independently reacquired for this PM decision. Public
provider documentation is not provider acquisition. This review made no AWS,
production, provider, `.env.local` or existing-database access.

Cheap direct verification passed: clean/ref checks, full-diff inspection,
`git diff --check`, exact six waiver/source hashes, unchanged fixture source and
published migrations, and unchanged protected runtime directories. No database
suite was rerun for this documentation decision. This acceptance permits opening
a PR as a subsequent action; it performs or authorizes no push, merge, deployment,
rollout, Phase5 implementation or activation. All documented operational and
restore gates still apply before those separately authorized steps.
