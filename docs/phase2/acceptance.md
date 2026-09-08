# Phase 2 independent PM acceptance

**ACCEPT for opening a PR**, assessed after the independent tester's final READY.
Accepted implementation: `56d31368fd91199e7f70ac0f6eb916a7fddd2ee6` on
`phase2/g10-ingestion-only`. This report is a later documentation-only commit.
Base/merge base: `61ff8bc021744b0b785843c994db422c9a742431` (`main`);
required Phase 1 `6cc1325d06538cefaf1cf25b49175fdcbfcb8a22` is included.
No stacked dependency is necessary. The PM performed acceptance independently of
implementation and only after tester correction re-verification. No implementation
was changed by the PM.

“Code and tests safely support twelve-pair live ingestion, while only the original
four pairs remain eligible for research recommendations and trading workflows.”

This accepts the scoped code and evidence under the owner's already accepted Phase 1
exceptions. It does not assert a green complete suite. It authorizes no push, merge,
deployment, production access, provider/account call, schedule activation, notification,
paper trade or strategy activation.

## Requirements traceability

Evidence references below are relative to the repository unless prefixed `external`.
External evidence is preserved at
`/Users/oluwatomisintaiwo/trade-recommender-artifacts/phase2-g10/`.

| Requirement | Implementation and evidence reviewed | PM result |
|---|---|---|
| Twelve canonical codes, explicit currencies/order; four decisions/eight data-only | `market/models.py`, `seed_canonical.py`; literal registry expectations in Phase 2 tests and independent contract probe; exact registry table in rollout | Accepted: EUR_USD, GBP_USD, EUR_GBP, USD_CAD remain decisions; USD_JPY, AUD_USD, USD_CHF, NZD_USD, EUR_JPY, GBP_JPY, AUD_JPY, AUD_CAD remain inactive |
| One acquisition owner and safe migration | `0030_ingestion_eligibility.py`; real 0029→0030 test with original six identities and unknown active/inactive rows | Accepted: migration preserves IDs/active states, canonical and active rows gain collection eligibility; unknown inactive rows remain disabled |
| Idempotent seed, no evidence/fixtures/users, deadline preservation | Conditional saves and advisory lock in seed; empty/existing/reseed/drift/concurrent tests and independent complete-job comparison | Accepted: twelve canonical rows, 48 job identities; explicit instrument collection disables survive reseed |
| Four supported granularities and load-safe scheduling | H1=3600, H4=14400, D=86400, W=604800; deterministic 48 distinct minute phases, interval bounds, latest-only catch-up and duplicate enqueue tests | Accepted: new deadlines stagger; old deadlines and operational missed-run policy retained; downtime bursts remain a rollout gate |
| Bid/ask, exact codes, smooth=false, complete UTC candles, New York 17:00/Friday, pagination | Actual HTTP MockTransport through task/storage for 8×4 combinations; independent exact request assertions and existing OANDA/quality tests | Accepted: JPY-scale and subunit six-decimal prices covered; D/W DST and includeFirst exercised |
| Append-only observations, revisions/conflicts, validation and technical lineage | Live manifest retrieval provenance and full request retention; every-pair A→B→A probe, exact-manifest replay test, complete live-observation/lineage suites | Accepted: invalid/crossed/gapped/duplicate/out-of-order data rejected under existing policy; frozen candle not replaced; exact source identities retained |
| Disabled scheduled/direct task fails closed | Eligibility/source gate in `operations/tasks.py`; queued-then-disabled independent cases before provider construction | Accepted: in-flight fetch requires drain for immediate cutoff; runbook discloses this |
| No downstream trading/research effects | H1/D active checks after fetch; direct recommendation, baseline and pair-evidence creation guards; all-eight direct and stale-object probes | Accepted: 32 ingestions leave forecasts-model census, pair evidence, budgets and outbox unchanged; four callbacks never called |
| Existing decisions, sizing, portfolio and dashboard unchanged | Existing active filters retained; original-four batch/navigation tests and independent inactive AUD_CAD conversion probe | Accepted: no onboarding recommendations enter downstream graphs; eligibility policy remains the original four |
| Terms use ingestion universe safely | `capture_oanda_terms`; exact twelve-code independent test, missing response instrument, missing token/account, empty universe cases | Accepted: terms do not confer decision eligibility |
| Read-only bounded health/integrity report | `report_fx_onboarding.py`; deterministic fixed-time 32-row probe, no-write SQL check, forbidden evidence injection/nonzero exit and state tests | Accepted: per-series missing/stale/failed/quarantined/disabled, success/interval/count, schedule, revisions/conflicts, technicals and forbidden roots/descendants exposed |
| Accurate Operations disable reasons | P2-01 reproduction → engineer regression/fix → tester verification at 56d3136; actual template/CSS synthetic component screenshot inspected by engineer/tester | Accepted: configuration, collection disable and schedule disable distinguished; no UI redesign |
| Scope and historical preservation | Complete changed-file diff; independent 78-file historical byte comparison and unchanged historical/discovery OANDA methods | Accepted: no strategy, prompt, model, historical universe, terminal binder or archived evidence expansion/rewrite |
| Capacity, reversible canary rollout, future work | `rollout.md` and independent arithmetic review | Accepted as a plan; all production measurements/activation remain pending owner approval |
| Reviewable evidence and local history | Four coherent implementation/correction/documentation commits, clean implementation worktree; exact command arrays, raw logs, residual-ID results | Accepted with explicitly retained complete-suite limitations below; PM adds only this acceptance record |

## Accepted product behavior and scope

Collection is broader prospectively, with an explicit acquisition permission independent
of decision eligibility. The eight onboarding pairs can receive only permitted market,
technical, terms and operational artifacts through the supported paths. Direct decision
creation rejects them before evidence/provider work, including stale in-memory eligibility.
Existing active-pair success callbacks and decision enumeration are retained. This is an
application workflow boundary, not a claim that privileged arbitrary database writes are
impossible; runtime superuser remains the owner's deferred Phase 1 exception.

The data universe includes more non-USD crosses. This establishes neither portfolio
diversification nor predictive skill. Future currency-level risk aggregation remains
required before trading expansion. Multi-timeframe setup/thesis/abstention work, M15/M1,
all named strategies, mechanical controls, lifecycle/deduplication repairs and model
learning remain separate future phases. No strategy activation is authorized.

## Missing or ambiguous criteria

No unmet code acceptance criterion or open relevant P2 was identified in this scoped
acceptance. The following limits are explicit rather than implicitly marked passed:

- “Tests pass” is assessed using scoped and differential evidence under the two
  owner-accepted Phase 1 exceptions, not as a claim that the complete suite passes.
- Deterministic/bounded diagnostics means stable ordering and bounded output for the
  fixed universe at a given time/state; `as_of` changes over time and database COUNT
  cost still depends on retained history. Production report latency is unmeasured.
- Existing explicit job disable can be reset by canonical reseeding, as documented.
  The persistent operator collection-off control is `ingestion_enabled=False`; missed-run
  policy and existing deadlines are preserved. Operators must use the documented control.
- Migration preserves pre-existing active values; canonical seeding establishes the
  specified four/eight split. Rollout must verify that split before dispatch resumes.
- Numeric worker/API/disk/memory alert thresholds await an approved instance baseline.
  Seven-day observation, weekly completion and seasonal DST observations are pending.
  Existing market-closure policy is reused; no comprehensive holiday calendar is claimed.

These are disclosed operational prerequisites or already authorized exclusions, not
newly waived implementation defects.

## Engineer and tester evidence assessment

The PM read the full brief, all changed implementation/test files, design, rollout,
engineering verification, both engineer handoffs, tester first/final reports and selected
raw evidence including the final failure summary and all 32 per-ID residual results.
The PM did not rerun the independent test role or initiate a broad new audit.

Engineer evidence contains tests failing under old coupling, malformed-response and
exact-window behavior before corrections. Final clean regression: **76 passed**,
including all 20 Phase 2 tests and all 32 differential error IDs. P2-01 then reproduced
independently, failed a new regression in 32 subcases before its owner fix, and passed
55 adjacent engineer tests. The existing fixture edits preserve assertions and use
historical schema correctly; they do not skip or suppress the deferred 0027 limitation.

Independent tester correction run at the accepted implementation: **174 tests, 173
passed, one failed, zero errors/skips**. The one failure is the explicitly accepted
runtime-superuser assertion (`test_connection_role_is_not_a_superuser`). All **10
independent probes** and **32 independently derived residual error IDs** passed. These
probe expectations include literal universe values and actual mocked ingestion/artifact
censuses, providing evidence beyond merely counting engineer-authored passing tests.
The tester's initial overstrict SQL-update assumption was corrected transparently; its
original log remains preserved and no implementation issue was erased.

The complete suite is **not green**: base **1,078 tests / 7 failures / 330 errors**;
implementation b0a4ed3 **1,097 / 1 failure / 353 errors**. These are not identical
failures. New missing-column manifestations follow failed backward migrations leaving
old schema; every one of the 32 error-only differential IDs independently passes on
clean current schema. No branch-only assertion failure remains in that comparison.
The full suite predates the final narrow correction; its owning, adjacent and residual
surfaces were reverified at 56d3136. This supports scoped acceptance without asserting
that every inherited error shares one cause or has been repaired.

Reproducibility: see `engineering-verification.md`, external
`independent/correction-verification-command.json`, `correction-verification.log`,
`full-suite-independent-differential.json`, `residual32-independent-ids.json`, and
`residual32-independent-results.json`. Runs were serial on disposable local PostgreSQL
with sanitized `env -i` and mocked HTTP. Only documented disposable migration 0027
bootstrap was recorded fake; later migrations ran. No new skips, assertion weakening,
secret/production access or real provider calls are reported. Static/Django/migration/
compile/diff checks are recorded as passed. Evidence is sufficient for PR review under
the accepted exceptions, not production readiness certification.

## Later owner-approved rollout checklist — all pending

- [ ] Obtain separate approval for deployment, production access and each activation.
- [ ] Establish queue/duration/API/RSS/swap/disk/WAL/backup and report-latency baselines
  and numeric limits before any wave. Budget +24 job identities, +32 enabled jobs,
  about +249 candle runs/day, repeated 14/14/90/730-day windows and about +178 unique
  intervals/day. Validate the runbook's illustrative storage estimates on the instance.
- [ ] Pause dispatch before migration/seed; stage all eight collection flags and their
  32 schedules disabled before resuming. Verify original four decisions, exact registry,
  metadata, schedules and no forbidden artifacts. Seed with a configured token can
  otherwise enable all eligible jobs; this must not be mistaken for safe activation.
- [ ] Activate only the approved wave, keeping `active=False`: USD_JPY/AUD_USD,
  then USD_CHF/NZD_USD, then EUR_JPY/GBP_JPY, then AUD_JPY/AUD_CAD.
- [ ] For each wave verify initial H1/H4/D/W success and exact D/W alignment, investigate
  unexpected gaps, and require no unexplained quarantine/conflict accumulation.
  Confirm zero evidence packets, forecasts, recommendations, sizing, portfolio,
  paper/review, model-budget or opportunity-notification artifacts for onboarding pairs.
- [ ] Observe at least seven calendar days including W completion/weekend before the
  next wave; record DST seasonal observation separately if not spanned. Check bounded
  queue/worker/API/memory/disk pressure and failure recovery by exact schedule identity.
  Account for a possible 48-job overdue recovery burst despite initial staggering.
- [ ] Exercise the approved rollback: disable affected schedules and collection flags,
  drain in-flight work for immediate cutoff, retain `active=False`, preserve all evidence,
  occurrences and lineage, and rerun read-only diagnostics before restart.

PM recommendation: **ACCEPT for opening a PR only**. New pairs are not declared live,
production schedules are not declared enabled, no edge is established, and the future
multi-timeframe strategy does not exist as a result of this phase.
