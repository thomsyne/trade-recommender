# Phase 5.5 offline validation acceptance matrix

Engineering specification, not acceptance. Base: merged main
`b850c4ea618c34397e86fd8133b7255ff972f8ba` (PR #55). No original Phase 5
definition, simulator, population, migration or failed-break evidence may change.
An independent reviewer and then PM own review/traceability. One consolidated
correction cycle follows a stable candidate; engineering cannot self-accept.

| ID | Required behavior | Discriminating verification / evidence |
|---|---|---|
| A1 | Coverage/prior-use audit executes before any signal, return, trade, P&L, Sharpe, excursion or outcome calculation. Output only source/coverage/access metadata. | SELECT-only transaction, explicit column allowlist; no prices/results selected; persisted audit bytes/hash. |
| A2 | Audit all available sources, instruments, granularities, timestamps/counts, gaps, duplicates/revisions, BA/mid, acquisition clocks and cost/calendar/vintage readiness. | Empty, partial, revised and missing sources remain explicit; expected-open calendar absent means gaps unclassified, not market closures. |
| A3 | Explicitly establish no previous Phase 5 strategy-result access within proposed holdout. | Database metadata and research history plus owner attestation; absence of rows is not absence of human access. Unknown fails closed. |
| A4 | Freeze eligible dates before outcomes; replacements require coverage/prior-use reason. | UTC half-open warmup [2017-01-01,2019-01-07), development [2019-01-07,2025-01-06), holdout [2025-01-06,2026-09-07); split 2025-11-10. Exactly 87 complete ISO weeks, halves 44/43. No invented replacement coverage. |
| B1 | Immutable complete validation registration committed before outcomes, referencing unchanged 19 Phase 5 formula/simulator digests. | Source, periods, instruments, exact manifests, evidence sources, mapping, missingness, opportunities, dependence, adverse scenarios, thresholds and schema bound; mutation/refusal probes. |
| B2 | Original prospective population preserved; new population-bound validation revision where required. | SQL/Python admission agree; historical identities cannot masquerade as original prospective evidence. |
| B3 | Holdout sealed until explicit one-time release after independent review and final candidate/manifest freeze. | Boundary/equality/overlap/warmup spill tests; reject access before loading observations; no CLI force bypass. |
| C1 | Bounded deterministic offline batch with focused strategy/instrument/period chunks, immutable evaluations/simulations, safe resumable checkpoints. | Retry, interrupted write, concurrent workers, changed manifest/period/source, deterministic bytes and replay tests. |
| C2 | No recommendation, order, sizing, eligibility, schedule, production consumer or real trade. | Static consumer/import/command audit; no activation settings or dispatch entries; no production writes. |
| D1 | Separate EWMAC and breakout exposure maps frozen before outcomes: next eligible interval, baseline-capped risk, buffered turnover, financing/conversion. | Asymmetric long/short, latency, buffer boundaries, costs on actual turnover, cannot exceed baseline; no cross-family pooling. |
| D2 | Fast MR retains adverse-limit-h1-v1, never executable-fill claims. | Opening-through limit, gap, ambiguous intrabar/queue and expiry tests reuse exact simulator contracts. |
| D3 | Six London/NY wick/confirmed/FVG ORBs separate; matched session-day comparators. | Missing comparator not zero; FVG positive paired weekly net increment over same-session confirmed required. |
| D4 | M15/H1 pullbacks, sweep reversal, acceptance continuation separately attributed. | Earlier negative failed-break evidence/new-era boundaries preserved; no historical relabeling. |
| D5 | Range unavailable without genuine regime/event-expansion clearance; carry unavailable without PIT forwards, financing, rollover and broad ranking. | Empty evidence cannot mean safe; policy rates cannot substitute for carry. |
| D6 | Macro paired risk-only, fixed/EWMA/Student-t GARCH identical opportunities and capped at baseline. | Matching/unavailable propagation, solver failure, multiplier >1 refusal; no independent directional overlay returns. |
| E1 | PIT/leakage-safe decisions; true acquisition timestamps; final candles only labelled retrospective replay where revision semantics permit. | Late/revised inputs cannot become historical known-at; future evidence cannot change decisions. |
| E2 | Missing spread/commission/slippage/financing/conversion/calendar is unavailable, never zero/safe. Candle data not ticks/path/queue/fills. | Each omitted cost independently blocks net; adverse gap/dual-hit checks. |
| F1 | JSON and English reports by strategy/version/instrument/session and attributable aggregate. | Eligible opportunities, trades, exact unavailable reasons, active ISO weeks, gross, each cost, net account return, turnover/duration, drawdown/worst week/tails, sides, concentration, halves, currency/concurrent overlap, baseline/adverse and paired comparators; unavailable metrics null, not zero. |
| F2 | UTC ISO weeks across overlapping currency exposure primary dependence units; raw trades not independent. | Cross-year ISO and multiweek/concurrent exposure tests; adequate weeks/opportunities explicitly counted. |
| F3 | Preregister adverse costs, extra interval latency, remove best instrument/month, halves, sides, sessions, high-vol/events, missingness, adverse gaps/dual hits. | No outcome-driven search or thresholds; every material change new revision. |
| F4 | Retain requires integrity-clean replay, positive development and later holdout overall/both halves/adverse, adequate effective weeks/opportunities, no decisive concentration/leakage/execution defect. Reject negative, cost-consumed, fragile, concentrated or nonincremental; insufficient/conflicting evidence inconclusive, never pass. | Independent decision expectation fixtures; historical retain only Phase 6 consideration, never trading approval. |
| F5 | Development proposal includes all 19 identities, no success selection; final candidate/threshold/schema/holdout manifest frozen before release. | Completeness check; unavailable/loss variants retained in reporting; no holdout outcome before authorized continuation. |
| G1 | Forward shadow starts 2026-09-11, offline 8–12 weeks. | Future/unelapsed intervals unavailable; no invented elapsed evidence/schedule. |
| G2 | Focused synthetic/disposable tests while coding, consolidated stable PG15/17 and final available-evidence suite where practical. | Leakage/sealing/idempotency/determinism/missing-cost/pairing/SQL/Python/migration/reversal/preservation/concurrency; full logs and hashes, no interrupted-pass claims. |
| G3 | Clean committed local candidate, owned resources cleaned, complete independent-review handoff. | Exact files/commits, audit, dates, development dispositions, verification/limitations/blockers to coordinator; no push/PR/merge/deploy/activation. |

## Original pre-outcome gates

This matrix precedes outcomes and is not a frozen validation registration.
Dates remain provisional until A2/A3 are established. Unknown prior use or absent
required evidence cannot be waived by engineering. A blocked audit does not
constitute a development evaluation, candidate selection or review-ready engine.

## Final PM traceability gate — 2026-09-12

**ACCEPT for opening a PR and merge review only.** The reconciled dormant
development candidate is engineering-reviewable. This is not economic acceptance,
holdout release, strategy retention or promotion, Phase 6/6A eligibility,
deployment, activation, recommendation, execution, an order or trading approval.
No requirement or independent-review finding is waived.

Implementation candidate:

- branch `phase5.5/offline-validation`;
- implementation commit
  `63b36d590e0de24dabc3a1a8cda428ec153dc393`, tree
  `1a5cbe0de95fe214d8265c628ff511b4e4c8dd54`;
- reconciliation-tools commit
  `684ce6ab27f3cde6d77e24ae99bb2a57e018cae2`;
- merged Phase 5 base
  `b850c4ea618c34397e86fd8133b7255ff972f8ba`.

Git established a clean candidate before this PM document change. The complete
candidate delta from the Phase 5 base is 65 paths: `.gitignore`, Phase 5.5-only
documents, offline validation modules/tests and isolated worker infrastructure;
no production application, migration, strategy-definition or prospective
population path changed. The final reconciliation scope is exactly three
read-only reconciliation modules, one test module and
`revision6-reconciliation.md` across the tools and handoff commits.

Local `main` and `origin/main` both identify
`909abad4260cfca739224a268f7f424cfab011be`; their merge base with the candidate
is the Phase 5 base. Main is 14 commits ahead on its side and the candidate is 28
commits ahead on its side. A non-mutating merge-tree check reports one content
conflict, in `.gitignore`: main has the later broad `.candidate-data*` rule while
this candidate has `.candidate-data/phase55-v1/`. This is the only path changed on
both sides. Therefore a PR may be opened for review, but an explicit current-main
integration/conflict-resolution review is required before merge. No rebase,
integration update or conflict resolution is part of this acceptance.

### Requirement dispositions

| Requirement | Disposition and trace |
|---|---|
| A1 | **Met.** The outcome-blind audit preceded evaluation, used fixed metadata-only projections and preserved its digest. The corrected post-freeze cache audit denies blob reads and sanitizes failures. |
| A2 | **Met with mandatory limitations retained.** The registered acquisition covers 12 instruments, five granularities, 2,592 chunks and 240 groups. Gaps, acquisition clocks, BA limitations and absent genuine costs/calendars/vintages remain explicit rather than inferred safe. |
| A3 | **Met for the registered holdout gate.** Metadata/history checks and the owner's explicit no-prior-Phase-5-result-access attestation are preserved. This is not inferred from zero rows. |
| A4 | **Met.** Frozen UTC half-open periods are warmup `[2017-01-01,2019-01-07)`, development `[2019-01-07,2025-01-06)` split `2022-01-03`, and sealed holdout `[2025-01-06,2026-09-07)` split `2025-11-10`, exactly 87 ISO weeks (44/43). |
| B1 | **Met.** Revision 6 registration is `c64f5731ea8d0e77a9d6ae4889eaffec8135288881e75d039a58d30c7a566237`; 46 source hashes, exact manifests, costs, periods, scenarios, thresholds and 19 formula/simulator identities were independently checked. |
| B2 | **Met.** Six immutable registration identities and their supersession chain remain separate. Revision-specific checkpoints, reports and equivalence sets were not relabelled or pooled. |
| B3 | **Met; release still forbidden.** Sealed requests refuse before SQL/decompression, loaded intervals cannot cross the boundary, all catalogs contain zero holdout checkpoints, and no CLI release bypass exists. A later explicit owner instruction after this PM gate and merge decision is required before any holdout access. |
| C1 | **Met.** Checkpoint admission and resume derive decisions, results, accounting, occupancy and end state by replay over the bounded registered daily grid; stored hashes or caller ancestry are not trusted. Retry, mutation, fresh-resume and concurrency boundaries have focused coverage. |
| C2 | **Met.** The engine remains manual, offline and dormant. No consumer, eligibility path, schedule, production write, recommendation, order, sizing activation or real trade was added. |
| D1 | **Met as a mapping capability; historical returns remain blocked.** Separate EWMAC/breakout next-D mapping preserves prior buffered state, baseline risk/notional caps and costs on absolute unit change. Missing genuine financing remains unavailable. |
| D2 | **Met.** Fast MR retains `adverse-limit-h1-v1`, gap/intrabar/queue refusal semantics and no executable-fill claim. |
| D3 | **Met.** Six London/NY wick/confirmed/FVG identities remain separate and use exact same-session-day comparator keys. Missing or occupied outcomes are unmatched, not zero. |
| D4 | **Met.** Pullback M15/H1, sweep reversal and acceptance continuation remain separately attributed; earlier failed-break evidence and eras were not rewritten. |
| D5 | **Met by unavailability.** Range lacks genuine event/regime clearance; carry lacks PIT forwards, financing, rollover and broad ranking. Neither is treated as safe or complete. |
| D6 | **Met.** Fixed/EWMA/GARCH/macro are paired risk-only views of each baseline population, capped at baseline. Macro vintages and unavailable multipliers propagate; there is no directional overlay return. |
| E1 | **Met within the retrospective contract.** Acquisition clocks and retrospective labels remain distinct; completed-candle replay does not claim historical PIT knowledge. Reconciliation invoked no market replay or new outcome calculation. |
| E2 | **Met with model limitations retained.** Missing spread, conversion, financing, calendar or other required evidence is unavailable. Costs are separated; candle evidence is not represented as tick, path, queue or fill evidence. |
| F1 | **Met.** All 975 JSON/English report pairs cover every instrument and attributable aggregate with states/reasons, gross and separate costs, net/return, dependence, halves, strata, concentration, remove-best, tails, realized drawdown, currency/concurrency, scenarios and comparators. |
| F2 | **Met.** UTC ISO-week dependence, cross-week linkage and overlapping currency/concurrent exposure are reported; raw trades are not treated as independent. Aggregates represent 12 independent CAD 100,000 accounts, not a pooled portfolio. |
| F3 | **Met.** Baseline, adverse-cost, extra-latency, remove-best, halves, sides, sessions, volatility/events and missingness remain preregistered and fixed. No outcome-driven scenario or threshold was added. |
| F4 | **Met.** The evidence-first decision order leaves incomplete or conflicting evidence inconclusive, never a pass or a prose-waived reject. No development result is a retain. |
| F5 | **Met.** All 19 identities and all unavailable/losing views remain in the proposal and report grid; there was no success selection and no holdout outcome. |
| G1 | **Met as dormant capability only.** Forward shadow is manual/offline from 2026-09-11; no schedule was created and no unelapsed future evidence was invented. |
| G2 | **Met with broad-suite limitation retained.** Executed and preserved checks are distinguished below; the failed broad PG17 result is not called green. |
| G3 | **Met for engineering handoff.** The exact local candidate, evidence identities, limitations, resource state and independent closure are recorded. Private evidence remains Git-excluded; no push, PR, merge or activation occurred. |

### Independent correction closure R1–R5

Independent review of the exact implementation candidate closed every correction
with no P0–P3 blocker:

- **R1 closed:** sealed and malformed requests refuse before SQL; metadata is
  authenticated before blob selection; cache audit is metadata-only and blob-read
  denied. No holdout checkpoint or payload was found or opened.
- **R2 closed:** complete catalog admission/resume is replay-derived and validates
  fixed-grid ancestry, stored bytes, attribution, chronology, decisions, states,
  occupancy, end state and accounting rather than accepting self-consistent hashes.
- **R3 closed:** public report construction requires a verified `Catalog`; arbitrary
  rows cannot certify reports. The complete 975-cell population has no missing,
  duplicate, excluded or pooled cells.
- **R4 closed:** asymmetric mapping tests cover long/short, reversal, no-turnover,
  latency, continuation, caps and absolute-turnover costs. Financing remains null
  or unavailable rather than fabricated.
- **R5 closed:** scenario order is fixed by the registration. All 975 current
  English files round-trip against canonical JSON and reversed scenario mappings;
  all 975 historical revision-2 JSON/text pairs retain their indexed hashes.

### Completed evidence and arithmetic reconciliation

- Completed development archive SHA256:
  `ae99296cf07ccf3bbb9d7a97378d2517371c8f2f60aaea83ac207919173043d1`.
- `reconciliation-index-v2.json` SHA256:
  `35f8f2440fe2bed36bc743e27a71b88ef6a13929915a6010d9c0bb28d4bb309c`;
  all 22 indexed sizes and hashes match. The earlier index remains preserved.
- Revision-5 partial archive SHA256:
  `9baaa50ddc3159b4da69fe3499e0e32c3f31725a28c3592fad40e780cac86347`.
- Complete grid: 15 baseline/readiness identities × five views × 13 scopes =
  975 reports (900 instrument, 75 aggregate), covering all 19 Phase 5 identities.
  The catalogs contain 394,380 checkpoints, 180 complete chains and 2,191 days
  per chain. Checks cover 2,925 scenario views, 2,418 paired scenario views and
  75,120 ORB keys.
- Leaf/aggregate arithmetic reconciles complete state and unavailable-reason
  populations, gross-cost-net/account return, duration, weeks, halves, side and
  volatility strata, concentration/remove-best, tails, realized drawdown and
  currency/concurrency. Decimal34 operation-count/magnitude bounds preserve 725
  nonzero leaf-sum deltas, maximum `9.49E-24 CAD`; no cent-scale tolerance or
  discrepancy is waived.
- FVG net increment is exactly zero in every scenario. London has 368 matched and
  18,412 unavailable/unmatched opportunities per scenario; New York has 185 and
  18,595. Missing and occupied opportunities remain unmatched, never safe zero.
  There is no positive FVG incremental evidence.

### Revision and runtime reconciliation

| Revision | Main checkpoints | Complete / partial / absent chains | Reports |
|---|---:|---:|---:|
| 1 | 21,921 | 10 / 1 / 169 | 0 |
| 2 | 394,380 | 180 / 0 / 0 | 975 |
| 3 | 48,125 | 20 / 4 / 156 | 0 |
| 4 | 64 | 0 / 2 / 178 | 0 |
| 5 | 4,012 | 0 / 5 / 175 | 0 |
| 6 | 394,380 | 180 / 0 / 0 | 975 |

The separate 64-checkpoint revision-5 equivalence catalog is not pooled into its
main run. Revision 2 and revision 6 are the only complete 975-report publications.
All 975 disposition transitions are `inconclusive → inconclusive`: 909 report
metric views are unchanged; 66 GARCH views changed (57 instrument, nine aggregate),
with eight changed gate sets and 9,355 nested deltas.

Revision 1–5 setup totals are 775 / 35,827 / 6,233 / 15 / 213; changes versus
revision 6 are 330 / 5,425 / 144 / 0 / 0 and are confined to saved GARCH
multiplier/nonconvergence state. Revision 2 → 6 has 4,606 available multiplier
changes, 398 availability gains and 421 losses; among modeled opportunities, 559
changed, 51 lost availability and 51 gained it. Material adverse and latency
examples remain in the handoff, including GARCH/fast-MR latency worsening from
`-138534.1315` to `-140392.0160 CAD` (842 to 838 trades) and GARCH/acceptance
adverse-cost changing from `-76807.4371` to `-73705.2295 CAD`.

The registered transition from Darwin/Python 3.11.4 to Linux/Python 3.11.16 is
correlated with these changes. It is not proof of a particular numerical-backend
cause or cross-runtime bitwise equivalence. No solver rerun, refit or tuning was
performed to force agreement, and selective agreement is not an acceptance basis.

### Scientific result, limitations and verification boundary

Formal development result: **19 inconclusive identities, zero qualifying
candidates, zero formal rejects and zero retains**. Incomplete adverse evidence is
neither a pass nor a formal reject. No identity may populate Phase 6A eligibility
from this result.

Unresolved prerequisites and limitations remain genuine financing and historical
terms, forwards and carry rollovers/ranking, exceptional-session calendars/events,
macro vintages, range clearance, thin samples, candle-only execution evidence,
realized rather than mark-to-market drawdown, adverse/latency failures and
cross-runtime GARCH sensitivity. These limitations are dispositions, not waived
findings.

New engineering verification executed 75 focused tests: 69 passed and six explicit
disposable-PostgreSQL skips. Preserved targeted correction evidence records 116
passes on each of PG15 and PG17. Independent review directly executed nine new
reconciliation tests (nine passed) and complete read-only artifact/hash, archive,
registration/source/seal, checkpoint/grid/state/pairing, report-metric,
revision-delta and coverage/cutoff checks. Those saved-evidence checks are not a
fresh market replay.

The prior broad PG17 run completed 1,580 tests with two errors and remains not
green. The discovery-plan error reproduced on the merged base; the future-timestamp
error did not. Measured clock skew is consistent with but does not prove the latter
error's cause. No new broad suite, PG service, scientific replay or solver was run
for this PM gate.

### Seal, operations and authority

No holdout prices, outcomes, derived labels or tuning were accessed; zero holdout
checkpoints exist. The holdout remains physically present behind the sealed loader,
not released or claimed deleted. **This acceptance does not permit inspecting the
holdout.** Any holdout release requires a later, separate, explicit owner instruction
after this PM gate and the merge decision.

The dedicated EC2 instance is preserved as stopped-state evidence; compute billing
ended and retained storage only remains. No EC2, PostgreSQL, provider, market-data
or trading resource was started or called for this gate. No schedule, deployment,
activation, promotion, recommendation, order or trade was made. Phase 6A and Phase
7 worktrees were not touched. Private candidate evidence remains excluded from Git,
was not copied or rewritten by this gate, and no secret was exposed.

Authorization is limited to opening a PR and conducting merge review of this
dormant candidate. It does not authorize push by this gate, merge, deployment,
strategy approval, Phase 6/6A eligibility, holdout release, scientific rerun,
activation, recommendation, execution or trading.
