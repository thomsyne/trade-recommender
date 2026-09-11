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

## Current gates

This matrix precedes outcomes and is not a frozen validation registration.
Dates remain provisional until A2/A3 are established. Unknown prior use or absent
required evidence cannot be waived by engineering. A blocked audit does not
constitute a development evaluation, candidate selection or review-ready engine.
