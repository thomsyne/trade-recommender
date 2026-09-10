# Phase5 acceptance matrix — PM ACCEPT for PR review only

Status: **Final PM ACCEPT for opening a PR only — not economic acceptance or
rollout**, 2026-09-10. The final requirements-only decision and independent
closure evidence are recorded below. Historical preregistration and handoff
statements remain evidence of their stage, not outstanding engineering findings.

The independent review of the initial handoff requested six corrections.
[Correction contracts, reproduction evidence and review lessons](corrections.md)
supersede the original implementation claims for lineage, schemas, simulator
causality, outcome terms, MR execution and Decimal determinism. Independent
verification closed all six and the subsequent SQL evidence-admission P2 at the
reviewed head; the engineer's correction cycle did not self-accept them.

Owner of implementation/tests: Phase5 engineer. Owner of hypothesis acceptance,
holdout release, combination and rollout: project owner after independent review.
No row is self-accepted. Evidence must distinguish synthetic engineering checks
from economic validation. The matrix below records the initial preregistration
state: its `pending` markers are historical, not waivers. The disposition register
following it records the engineering handoff and remaining external gates.

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

## Disposition register

All test references below are under `market/tests/`; `library_*` abbreviates
`test_strategy_library_*`. [Verification](verification.md) records executed
commands, failures and limits. [Runbook](runbook.md) gives the operational gates.
“Implemented” means delivered for independent review, never owner acceptance.

| IDs | Engineering disposition and exact evidence owner | Remaining gate / non-goal |
|---|---|---|
| A1, A3 | Implemented distinct frozen schemas and pure dispatch. `test_strategy_library.ContractTests`, `library_boundaries.FormulaBoundaryTests`, SELECT-only persistence checks; engineer owns replay. | No output adapter, scheduling or production consumer. |
| A2 | Implemented exact 0.12.0 manifest loader, source pin and immutable cutoff dependency. `library_provenance.ProvenanceTests.test_exact_old_revision_survives_later_candle_spread_revision`, `library_persistence.PersistenceTests`; inherited Phase4 suffix/vintage tests remain authoritative for upstream features. | No uncited revisions, current candles or new descriptor output. |
| A4 | Implemented frozen definition/population/holdout hashes and SQL pins; `ContractTests.test_definitions_are_fresh_and_distinct`, `PersistenceTests.test_definition_holdout_and_raw_mutations_are_refused`. | Owner controls holdout release; historical data never becomes untouched by relabeling. |
| B1 | Implemented independent EWMAC components, frozen scalars, EMA variance, cap, cost screen, FDM and buffer. `library_trend.TrendTests` covers asymmetric EMA, variance versus sample standard deviation, affordability equality, warmup and buffer boundaries. | EWMAC64/256 unavailable under D400; no profitability claim. |
| B2 | Implemented separately attributed completed-range breakout with quarter-ceil EMA. `TrendTests.test_breakout_completed_high_low_and_quarter_warmup`. | Breakout320 unavailable under D400; no EWMAC pooling. |
| C1 | Implemented prior-D equilibrium, H1 alignment and separate high-vol reduction. `FormulaBoundaryTests.test_prior_daily_equilibrium_and_h1_alignment`, `library_structure.StructureTests.test_unavailable_is_not_sideways_or_safe`. Correction revision 2 owns the separately attributed `adverse-limit-h1-v1` model; `PureCorrections.test_limit_fill_nonfill_gap_ambiguity_latency_and_quote` covers placement, expiry and adverse/unavailable outcomes. | Modeled opening limit fills only; no executable-fill or intrabar path claim. |
| C2 | Market-owning versions retain the adverse next-interval model; fast MR uses its separate limit model. `library_simulation.SimulationTests` covers dual hits, delayed entry, missing costs, directional gaps, exact rollover equality, weekend reopening and PIT conversion; correction tests cover strict terms and terminal-prefix causality through persistence. | Net unavailable without complete documented assumptions; synthetic checks are not broker evidence. |
| D1, D2 | Implemented six session/variant IDs with terminal first attempt; `library_orb.OrbTests`, `FormulaBoundaryTests.test_fvg_qualification_and_equality_use_real_phase4_geometry`, `library_simulation_storage.SimulationStorageTests`. | Approved M15-close assumptions only; M1 separate. FVG retention awaits untouched paired net evidence. |
| E1 | Implemented independently versioned M15/H1 qualified pullback. `StructureTests.test_qualified_zone_and_continuation_both_required`. | Requires available pre-rejection HTF evidence and non-invalidated qualified zone. |
| E2 | Implemented range edge/center formula and unavailable event-clearance contract. `FormulaBoundaryTests.test_range_is_edge_only_with_frozen_center_exit`, `StructureTests.test_unavailable_is_not_sideways_or_safe`. | Data-readiness blocked on attested event/expansion clearance; never infer safe. |
| E3 | Implemented separate H1 sweep reversal and acceptance continuation with subsequent M15 BOS. `StructureTests.test_h1_sweep_and_acceptance_require_later_m15_bos`, `test_prior_negative_evidence_remains_a_terminal_binder`. | All old negative evidence preserved; new prospective era and untouched holdout required. |
| F1 | Tested unavailable readiness contract in `library_risk.RiskTests.test_policy_rates_are_not_carry_and_empty_is_not_safe`. | Genuine PIT forwards/financing/rollover/ranking missing; trend+carry remains blocked. |
| F2 | Implemented risk-only named-window pause and spread protection; missing consensus/coverage unavailable. `RiskTests.test_named_vintage_endpoint_and_late_knowledge`, inherited Phase4 event revision/suppressor tests. | No directional surprise or production effect; absent events are not attested empty coverage. |
| F3 | Implemented separate fixed/EWMA/GARCH challengers. `RiskTests.test_risk_cannot_exceed_baseline_or_hide_solver_failure`, `FormulaBoundaryTests.test_garch_convergence_failure_is_not_an_ewma_fallback`; actual pinned solver repetition recorded in verification. | No exposure above baseline; absent/wrong solver or failed fit unavailable. |
| F4 | Explicitly deferred/rejected in design/runbook and absent from the exact 19-ID SQL-pinned registry. Engineer inventories; owner alone may authorize future versions. | No implementation or silent priority for any excluded family. |
| G1 | Implemented strict strategy/era/population attribution, duplicate refusal and cross-currency overlapping-week groups. `library_reports.AttributionTests`. | Reports are diagnostics, not automatic economic acceptance; no cross-family pooling. |
| G2 | Implemented append-only definitions/evaluations/simulations; `PersistenceTests`, `ConcurrencyTests`, `library_migrations.MigrationTests`, `SimulationStorageTests`. SQL protects identity; Python rejects semantically forged hash-consistent results. | Forward migrations only. Populated reversal refused; shared migration requires separate approval. |
| G3 | Implemented bounded SELECT-only CLI, integrity pagination and manual idempotent API. `PersistenceTests.test_reports_preview_and_integrity_are_select_only`, `test_all_definitions_are_sql_pinned_and_retries_are_exact`, `ProvenanceTests.test_dormant_consumers_and_readonly_definitions`. | No durable-job registration, schedule, M15 activation or four/eight policy change. |
| G4 | Verification results and exact inherited restore exclusions recorded separately by engineer in [verification](verification.md). | Unavailable genuine-restore fixture is not silently passed; no self-acceptance. |
| G5 | Local checkpoint history, protected fingerprints, remote refs and owned-resource cleanup recorded in verification; engineer prepares handoff. | Owner review remains open. No push, PR, merge, deploy, acceptance or activation. |

## Final PM requirements traceability decision

Reviewed engineering head:
[`fb47dfb`](https://github.com/thomsyne/trade-recommender/commit/fb47dfb07baab8059c1b9fd4079fa60cdc0d659d).
The checkout was clean on `phase5/explicit-strategy-library`, with nine local
unpushed commits over local main, origin/main and live remote main, all at
`131a2fc1cd6d2d849cb13a94ce5b937cf0fe8a44`. No remote Phase5 branch existed.
This documentation decision adds one local commit; it changes no implementation.

Scope reviewed: the original Phase5 roadmap and implementation brief in the
[owner/coordination thread](https://ampcode.com/threads/T-01a0678e-9ea5-722f-99ad-8099c7ec5f76),
the [Phase4.5 readiness ADR](../phase4.5/phase5-readiness.md) and acceptance gates,
all six Phase5 documents, the full 44-file base-to-head diff, the
[engineer handoff and corrections](https://ampcode.com/threads/T-01a08c84-d2ca-7089-9c06-05e9425b1180),
and the [independent review and closure evidence](https://ampcode.com/threads/T-01a08d29-e259-74ca-bf3d-728cf5195d4b).
This is requirements traceability, not a new broad code audit.

The original ORB requirement used completed M1 confirmation after an M15 opening
range. The owner was explicitly asked, “Proceed with M15-confirmed ORB for Phase 5,
while treating M1 confirmation and executable-quote simulation as a future data
prerequisite?” After the M15-close/next-M15/wick-separate/FVG interpretation was
explained, the human replied “ok approved.” This approval permits only that ORB
substitution. It does not waive fast-MR limit simulation: the independently verified
correction supplies its own versioned conservative limit hypothesis.

| Original area / matrix IDs | Final PM disposition for PR review | Retained boundary |
|---|---|---|
| Separate immutable contracts and attribution / A1–A4, G1–G3 | ACCEPT: exact descriptor 0.12.0 dependencies, cutoffs/manifests, distinct forecast/setup/intent/result/risk schemas, pinned definitions and pure Python replay; bounded offline reports and explicit idempotent persistence. | Hashes and SQL admission do not certify formula truth. No cross-strategy pooling or automatic acceptance. |
| EWMAC / B1 | ACCEPT: six named speeds, volatility normalization, frozen scalars/cap/FDM, affordable within-family mean and verified buffer lineage. | D400 cannot warm EWMAC64/256; missing history/costs excludes components rather than inventing inputs. |
| Breakout / B2 | ACCEPT: six completed-D horizons, versioned quarter-ceil smoothing, scaling/cap/cost exclusion, independent EWMAC attribution. | Breakout320 warmup unavailable under D400; no pooled result. |
| Fast MR and simulation / C1–C2 | ACCEPT: prior-D EWMA5, H1 deviation, slower-trend alignment and high-vol reduction; separately pinned `adverse-limit-h1-v1`, with explicit costs, latency, calendar, financing and conversion. | Opening-through-limit modeled fill only; no favorable gap improvement. Intrabar touch/queue ambiguity and missing evidence are unavailable. No executable-fill or realistic tick-path claim. |
| ORB / D1–D2 | ACCEPT under explicit owner approval: six distinct London/NY wick, completed-close and M15 FVG IDs; frozen geometry, next-interval entry and terminal first attempt. | M15 is not M1. No inferred ticks/quotes; FVG retention still requires untouched paired net evidence. |
| Pullback / E1 | ACCEPT: qualified HTF trend/zone and separately versioned M15/H1 rejection/continuation with invalidation/expiry. | Unavailable or late HTF evidence cannot authorize entry. |
| Range MR / E2 | ACCEPT: edge-only reclaim/continuation and frozen center exit; breakout/regime and event-expansion readiness fail closed. | Current descriptor cannot attest event clearance, so no trading-ready range result is claimed. |
| Failed breakout / E3 | ACCEPT: H1 sweep reversal and acceptance continuation require subsequent M15 structure; distinct new prospective era. | Historical v1/v2 negative evidence and terminal binder remain unchanged; no relabeling as untouched data. |
| Carry / F1 | ACCEPT as required readiness-only capability: tested unavailable contract. | Genuine PIT forwards, financing, rollover and broad ranking are absent; policy rates never substitute. Carry direction and trend+carry await standalone validation. |
| Macro / F2 | ACCEPT: named PIT event windows and spread pause/reduction, risk only. | Missing consensus/release pairs and unattested coverage remain unavailable, never safe or directional alpha. |
| Fixed/EWMA/GARCH / F3 | ACCEPT: isolated risk challengers, pinned Student-t solver, non-increasing multipliers and explicit failures. | Optional dependency/version/fit failure is unavailable, not an EWMA fallback; synthetic fits prove no predictive value. |
| Deferred/rejected families / F4 | ACCEPT explicit exclusion of equity/options/dilution, HP momentum, candle triangular arbitrage, acceleration, normalized-trend priority, subjective SMC/ICT confluence and RL. | None is silently implemented or promoted. |
| Verification and handoff / G4–G5 | ACCEPT the documented evidence and independent closure, with the precise limitations below. | PR readiness only; economic acceptance and rollout remain separate owner decisions. |

## Independent closure reconciles six findings and the final SQL P2

| Finding | Independent closure evidence |
|---|---|
| P1 prior-buffer ancestry | Forged parents/grandparents propagate integrity failure; valid chains replay oldest first; 256 records reach replay, 257 fail before query 257; cycles, missing ancestors and mismatched attribution/cutoffs fail closed. |
| P2 terminal-prefix causality | Pre-entry/active gaps block; post-terminal gaps preserve stop, target and time-stop results, including persisted ORB and a later gapped outcome snapshot. |
| P2 closed output contracts | Hash-consistent non-superuser SQL probes verify exact shapes/types, strategy-to-kind compatibility, missingness, bounds and Python/SQL parity. The evidence-object hole remained open at 0040 and was not accepted prematurely. |
| P2 strict outcome evidence | Normal simulation rejects invalid currencies, SHA, provenance, units, times and conversion values. Final 0041 closes the remaining raw-SQL evidence admission path, as described below. |
| P2 missing MR limit hypothesis | Separate limit attribution and placement/lifetime/latency/expiry/fill/ambiguity checks; independent asymmetric long/short accounting produced net quote 3.57 and converted long net 4.4074073673. No executable-fill overclaim. |
| P3 Decimal determinism | Hostile ambient precision, rounding, traps and exponent contexts leave canonical outputs stable under fresh Decimal34/ROUND_HALF_EVEN boundaries. |
| Final SQL P2 / 0041 | Independent probes on exact PG15.14 and PG17.6 reject 182 malformed available-evidence cases per version and four unavailable gross/cost/net injections; admit genuine available, lossless decimals and documented null-evidence unavailable records with clean replay. |

Migrations 0038–0041 are prospective and preserving. 0038 adds only library
records; 0039 adds immutable identity/admission guards. 0040 closes output
contracts and pins correction revision 2 without rewriting revision-1 evidence;
independent probes preserve all 19 old definitions byte-for-byte and refuse
revision conflicts and populated reversal. Empty reverse/reapply is covered.
0041 adds conditional structural/type/validity admission only: populated valid
rows and clean replay survive forward/reverse/reapply; old malformed rows remain
unchanged and visibly fail integrity. SQL does not calculate forecasts, fills or
returns. These tests authorize no shared migration or rollout.

## Limitations are gates, not hidden completion claims

The implementation brief expressly requires a tested fail-closed readiness
contract when data is missing. Carry data, M1/ticks, executable quotes, complete
cost/calendar/conversion/rollover evidence, event clearance and long-horizon
history therefore have honest permitted dispositions for this offline PR. This
does not declare those capabilities economically usable or their data acquired.
The original limit-order requirement is represented by the conservative versioned
MR simulator, not waived via ORB approval or a fictitious broker-fill assertion.

Engineer evidence at the pre-0041 correction head records 1,520 available tests
passing on each exact PostgreSQL version. Independent review ran 56 focused tests
and 72 inherited tests per version there; after 0041 it ran 56 focused tests per
version and separate strengthened SQL integration probes (7.447s/7.373s), plus
`make check`, pin and protected-file checks. The full 1,520-test partition was not
rerun after 0041. PM did not rerun database, solver or deployment suites.

Exactly six unchanged restore-dependent tests remain excluded by the explicit
available-evidence runner. Default runs discover six and execute zero because
`DetectorV2QueryBudgetTests.setUpClass` raises `discovery plan conflicts with
canonical contract`; they are not passing tests. Their exact IDs and source hashes
remain those in [verification](verification.md). Phase4.5 genuine accepted-success
and already-applied-0027 restore/no-op proofs remain mandatory before rollout;
the deployed backup ending at 0023 proves refusal only. Provider-specific calendar
attestation, deployment-sized capacity/alerts and crash/outage/queue-recovery
rehearsals remain separate operational gates.

No observed economic outcome population or untouched holdout result is certified.
The return-blind prospective era starts 2026-09-11 UTC; calendar-2027 holdout access,
52 independent-week evidence, split-period net results and FVG paired incremental
net evidence remain owner-controlled gates. No holdout tuning/leakage or strategy
pooling is evidenced by this delivery; within-family component combination is
explicitly frozen. Reports remain diagnostics, not promotion or economic pass/fail.

Cheap PM direct checks passed: clean branch/base/live refs and nine-commit count,
full-diff inspection, `git diff --check`, all 598 protected files and their canonical
fingerprint, preserved original models prefix, implementation/design pins, exact
six restore IDs/source hashes, and absent consumer imports. Prior migrations,
failed-break evidence, Phase4/4.5 behavior, schedules and four-enabled/eight-ingestion
policy are unchanged. No source edit, provider/production/`.env.local`/existing-DB
access, push, PR creation, merge, deployment or activation occurred in this review.

**No concrete unmet mandatory requirement or remaining P0–P3 finding remains in
this PR-review scope. PM ACCEPT permits opening a PR as a subsequent action only;
it is not economic acceptance, holdout release, pooling, promotion, sizing,
decision-eligibility change, scheduling, deployment, rollout or activation approval.**
