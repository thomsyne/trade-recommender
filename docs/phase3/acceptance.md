# Phase 3 PM acceptance

**ACCEPT for opening a PR only.** Product behavior acceptance applies exactly to
`3ef40c1bf30d65c8633be07d393a137273945bbc`, on
`phase3/experiment-lifecycle-foundation`, based on
`16a27029f6f78af35adb040a8b70c98744f226c4`. This document adds no behavior changes.
Production activation is not authorized. Push, merge, deployment, production
access, schedule enablement, provider spending and promotion require separate
owner approval; this verdict performs none of them.

The PM read the complete supplied twenty-requirement brief, its role-specific
acceptance criteria and definition of done. Branch, HEAD, merge base and initially
clean worktree were verified directly. No applicable AGENTS.md exists in the
repository or ancestor paths. Review followed engineer implementation, independent
adversarial review, engineer corrections, independent correction acceptance, then
this PM review. The implementer did not approve their own work.

## Evidence and review scope

The following retained evidence supplies the traceability references below:

- **D:** `docs/phase3/design.md`, including the occurrence boundary, transition
  table, explicit contextual-information distinction and aggregation precision.
- **R:** `docs/phase3/runbook.md`, including registration preview, disabled jobs,
  recovery, integrity usage and separate activation authority.
- **E:** `docs/phase3/handoff.md`, `correction-handoff.md`, `f9-handoff.md` and
  `review-lessons.md`; implementation and correction provenance, not self-approval.
- **T0:** `/Users/oluwatomisintaiwo/trade-recommender-artifacts/phase3-tester-92q7/review.md`:
  initial independent matrix, original reproductions, migration and UI evidence.
- **T1:** `/Users/oluwatomisintaiwo/trade-recommender-artifacts/phase3-rereview-h72b/review.md`:
  F1–F8 closure and the complete initial adjacent-gap ledger. Its NO-SHIP verdict
  was correct at d02dc1 because F9 remained open.
- **T2:** `/Users/oluwatomisintaiwo/trade-recommender-artifacts/phase3-f9-review-k61m/review.md`:
  independent ACCEPT at 3ef40c1, closing F9 and its remaining evidence gaps.

This is product traceability review of those findings, discriminating evidence,
documentation and selected owning source paths. The PM did not rerun suites or
start a second broad code audit. Earlier findings and rejected evidence remain
visible in T0/T1; T2 closes F9 and does not retroactively turn earlier runs green.

## Requirements traceability

| Brief requirement | Accepted product behavior and evidence |
|---|---|
| 1. Separate definition and occurrence | `TargetContract` is reusable; immutable `TargetOccurrence` identifies the frozen scored event independently of model/issuance/row ID. D; T1 semantic registered variants, duplicate/concurrency, content/cutoff/hash and HALF_EVEN probes close F1. |
| 2. Shared resolution | One immutable resolution selects the fifth later registered daily session and supplies both derived outcomes. Missing/cancelled shapes are unscored; abstention receives Brier without directional hit. T0 shared resolution/asymmetric score tests; T1 holiday, endpoint-shape and before/at/after ingestion-availability cases close F3. |
| 3. Prospective exact controls | Exact tactical occurrence/control-method identity is required before reservation or provider call; late/mismatched controls reject at SQL boundaries. Failed provider calls retain valid controls. T0 original SQL/provider probes; T1 trusted cutover/downgrade and multiple-method checks close F2. Historical null links remain unpaired. |
| 4. Operational issuance | Completed D evidence drives prior resolution then current target/control; later generation requires the exact control. Four decision-enabled instruments only. R; T1 dedicated failed-control/retry, real stage order, unique issuance and schedule collision checks. |
| 5. New prospective era | Explicit future v4 method/era registration with policy v2 isolates changed semantics. No old sample reassignment or migration samples; preview does not register or activate schedules. D/R; T1 trusted audit-time, pre-effective legitimate legacy, downgrade rejection and era tests. |
| 6. Explicit populations | Assigned rows, distinct targets, immature/mature/scored/missing/cancelled, comparable/unpaired, direction/abstention and portfolio/paper populations remain separate. Primary coverage is scored mature distinct targets divided by all mature expected targets. D; T0 boundaries/UI and T1 persisted assessment evidence. |
| 7. Repeated issuance dependence | Predictions average within target before weekly cluster aggregation; one control cannot gain weight from repeated H4 rows. Canonical targets pair champion/challenger. Cutoffs exclude later facts. T0 independent repeated-target arithmetic/pairing; T1 future-fact and method/dependence SQL evidence. Weekly clusters are not claimed independent. |
| 8. Mechanical gates | Exact prospective paired shared outcomes, separately computed normalized Brier, target/cluster counts, signed uncertainty and missing/incompatible controls govern paired readiness. Uniform performance alone cannot authorize promotion. T1 closes F5 with independent signed oracle, persisted 50-target readiness, unmocked equality, stale/wrong-era owner rejection and threshold cases. No automatic active-policy mutation. |
| 9. Prediction versus execution | Probability forecasts include abstentions; directional hits exclude them. Admission, actual entry, nonactivation, gross pips, R and cost-adjusted R remain separate from Brier. T0 actual neutral-prediction/target-hit execution UI and protected-scope inspection; T1 real expiry evidence; T2 current-risk positives/terminals. Geometry and costs unchanged. |
| 10. Canonical state machine | D specifies roots, edges, facts, terminal states and forbidden reopening. No generic canonical pending. T1 exact sixteen legal edges plus two roots, each with real valid facts and invalid source/earlier-time probes; source semantics close F4. |
| 11. Append-only lifecycle | One authoritative v4 event chain, recommendation serialization and SQL source/predecessor/time validation; historical paper facts remain intact. T0 five-table UPDATE/DELETE/TRUNCATE and chain-race evidence; T1 full transition matrix and semantic source constraints. |
| 12. Complete disposition | Directional issuance atomically records durable assessment obligation, then membership or explicit reasoned disposition; operational failure remains retryable and expires explicitly. Abstentions cannot enter cohorts. D; T1 nine missing dispositions and membership/selection/admission/result integrity counterexamples, plus cutover rejection. |
| 13. Owner cohorts | Same-target batches cannot create competing open decisions. Fixed deadlines, whole-cohort material-target supersession, final member dispositions and empty selection are explicit. Current capacity is rechecked under lock. T0 empty-selection evidence; T1 actual supersession, displaced capacity and independent owner/reconciler races. |
| 14. Expiry reconciliation | All new recommendations reconcile; only active admitted setups monitor entry. Complete no-activation coverage differs from unobserved H1 and missing daily evidence; actual entries have distinct terminal outcomes. T1 real sources, maturity boundaries and all-state UI; T2 actual terminal exclusion. No non-admitted simulated execution. |
| 15. Shared projection | Today/Market, Inbox, Paper, Exposure, Reviews, Calibration and integrity use canonical lifecycle semantics. T0/T1 actual DOM/screenshots cover labels and controls. T2 closes F9: shared current-risk eligibility gives exactly the same two active IDs and C$250 in Paper/Exposure/portfolio, excluding three terminal rows while retaining history. |
| 16. Preserve evidence/migrations | Nullable legacy links; no manufactured controls, samples, decisions or events. Normal populated upgrades preserve original columns/IDs/hashes; contradictory prospective fixtures reject atomically. T0 independent populated/atomic probes; T1 original migrations unchanged and normal full upgrade; T2 genuine legacy admission/entry/result upgrades. |
| 17. Honest legacy | Ambiguous records stay legacy_unadjudicated; factual abstention, admission, entry and terminal history remain available; null controls remain unpaired_legacy. T1 normal upgrade preserves null audit time/all original columns; T2 real legacy admitted/entered C$125 and terminal zero-risk boundaries. E records synthetic dry-run classification counts, not production counts. |
| 18. Durable tasks | One canonical instrument task runs target/control, derived resolution, lifecycle/paper and health stages without model budget. Latest-only, retry/lease-safe, disabled deterministic schedules preserve existing deadlines. T1 actual downtime/failure/recovery/expired-lease and unequal-period collision cases; original four-pair restriction retained. |
| 19. Read-only integrity | Deterministic bounded JSON, static safe codes, nonzero prospective violations and separate legacy populations. T1 every named target/lifecycle/experiment code has positive and clean counterexamples; actual later facts preserve past reports, malformed recurrences remain safe and 61 violations cap details at 50. SQL trace establishes read-only behavior. |
| 20. Documentation | D/R/E cover occurrence, resolution, pairing, era, formulas, dependence, gates, transitions, cohorts, legacy, recovery, integrity and non-goals. This acceptance adds the prospective observation checklist below. Skill/profitability are unproven; no learning, new strategies, ingestion-only pair activation or automatic policy change is claimed. |

## Accepted semantics and evidence quality

Exact target equality means the same event, not identical information sets. The
target cutoff freezes daily/technical evidence; the model's later contextual
cutoff is separately audited. The registered tactical target v2 supplies the
frozen geometry to the existing version-1 mechanical method. Contract v4 and
evaluation policy v2 make that changed evaluation boundary explicit.

Readiness retains 180 observation days, 24 effective weekly clusters, 50 samples,
90% mature-target coverage and calibration guardrails. Target-balanced scores and
signed intervals support descriptive research; neither readiness nor an owner
record automatically activates or promotes a method. Existing evidence does not
establish predictive skill, and paper results do not establish profitability.

Tests challenge plausible wrong implementations: semantic fields change before
hashing; asymmetric Brier and signed intervals have independent arithmetic;
rounding ties use real target/endpoint writes; every legal lifecycle edge has
source/time challenges; raw SQL attempts bypasses; concurrent issuance,
resolution, chain and owner/reconciler races exercise owning boundaries. Migration
proof uses normally upgraded populated records and atomic rejection, with later
real legacy execution fixtures. Forbidden stored states are simulated at report
read boundaries without disabling constraints. Actual app screenshots/DOM support
all requested states, and T2 compares active IDs and cash totals as well as labels.

T1 independently ran the corrected 301-test broad command and original probes.
T2 independently passed 49 affected tests in 17.248 seconds, reproduced genuine
legacy upgrades and captured the real Paper/Exposure UI. T2 also inspected and
normalized the final engineer broad run: **310 tests, 0 failures, 19 errors in
191.861 seconds**. The retained independently executed base run had **222 tests,
5 failures, 23 errors**. There are zero branch-only failing identities, nine
base-only and nineteen shared. The shared causes differ: base market0027 reverse
validator rejection versus branch irreversible forecasts0030. **The broad suite
is not green; these are not identical errors.** The Phase2 historical assertion
bodies remain unchanged in a UUID-isolated normal historical database; the original
connection and installed history are restored. Only the previously documented
market0027 bootstrap accommodation is used. No new skips or weakened assertions
are used to conceal these errors.

## Missing requirements and retained risks

No blocking missing requirement or unresolved F1–F9 finding remains in the
reviewed evidence. The initial T0/T1 evidence gaps are closed by their explicit
closure ledger and T2, rather than inferred from test totals. This assessment
does not include production observation, which is prohibited in this task.

Runtime PostgreSQL superuser remains the accepted/deferred bypass risk. The
historical migration-suite limitation above remains visible for PR reviewers;
acceptance does not claim general rollback support or a green CI suite. Weekly
dependence clusters remain conservative proxies. Local synthetic fixtures prove
contract behavior, not provider reliability, live data quality or trading skill.
Existing prompt/model, setup geometry, cost/risk limits, historical research,
NAS100 and the eight ingestion-only pairs remain outside the changed scope.

## Prospective rollout checklist — separate owner approval required

1. Obtain explicit deployment and production-operation authority. Review backup,
   migration preflight and readiness evidence under the existing runbooks before
   any authorized installation. Never rewrite historical evidence to pass checks.
2. Preview a future v4 era/cutover, verify method/policy identity and the original
   four decision pairs, and preserve historical unpaired classifications. Record
   registration only under explicit authority; it does not enable schedules.
3. Inspect schedule identities, disabled status, stagger/collision diagnostics
   and preserved deadlines. Separately authorize any schedule enablement and
   provider spending. Eight ingestion-only pairs must remain excluded.
4. Observe prospectively issued controls before relying on new assessments:
   confirm completed D ingestion, prior mature resolution, unique current tactical
   control, frozen exact target/cutoff and control time preceding every model
   issuance. Confirm blocked issuance when that control is unavailable. Observe
   retry/recovery without duplicate controls or repair-related model spending.
5. Retain read-only integrity output and verify new target/control/outcome links,
   historical unpaired counts, complete dispositions, cohort deadlines and
   Paper/Exposure/current-capacity agreement. Investigate violations at their
   owning boundary; never backfill a control as prospective evidence.
6. Observe real mature shared outcomes and audit population/cutoff accounting
   before using assessments. Keep immature outcomes outside coverage denominators
   and repeated rows outside effective evidence counts. Missing/incompatible
   controls block paired claims regardless of uniform-baseline performance.
7. Continue collecting until all registered days, samples, clusters, coverage,
   calibration and paired-comparison gates pass. Any subsequent promotion is a
   separate governed owner decision; this PR acceptance authorizes none.

The implementation, corrections and independent acceptance are locally committed.
The PM adds only this acceptance document. No push, PR creation, merge, deployment,
production access, real provider/email call or activation was performed in this
PM stage. Reviewed engineer/tester cleanup records retain evidence and remove only
their owned disposable resources. Final verdict: **ACCEPT for opening a PR only**.
