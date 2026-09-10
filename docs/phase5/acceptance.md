# Phase5 acceptance matrix — not acceptance

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
| C1 | Implemented prior-D equilibrium, H1 alignment and separate high-vol reduction. `FormulaBoundaryTests.test_prior_daily_equilibrium_and_h1_alignment`, `library_structure.StructureTests.test_unavailable_is_not_sideways_or_safe`. | No limit-order fills or intrabar path claim. |
| C2 | Implemented adverse next-interval model. `library_simulation.SimulationTests` covers dual hits, delayed entry, missing costs, directional gaps, exact rollover equality, weekend reopening and PIT conversion. | Net unavailable without complete documented assumptions; synthetic checks are not broker evidence. |
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
