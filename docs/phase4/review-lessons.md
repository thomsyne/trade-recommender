# Phase 4 — review lessons and remaining review boundaries

## Requirements-only omissions (0.12.0)

- Closing a bounded bug review does not complete omitted requirements. Trace
  operational commands, event policy and every lifecycle field separately.
- A `defined` label is not a window. Pin exact bounds, inclusivity, timezone,
  status eligibility and unknown/empty meaning in the definition hash.
- Report integrity, input coverage, snapshot freshness and feature availability
  independently. A complete input interval does not imply sufficient ATR history
  or an attested event calendar.
- Test read-only claims with both traced SQL and every table's count/content
  fingerprint, including populated snapshots and nonzero command exits.
- Canonical schema validation must distinguish JSON booleans from integers;
  Python dictionary equality alone does not.
- Lifecycle formation, confirmation, knowledge time and terminal state need
  separate fields. Normalize at the breach, cite actual prerequisites, and test
  both directions with unequal values and exact boundaries.
- A newly reversible migration can run before an older rollback refuses. Tests
  must restore their own migration graph through the executor in `finally`;
  do not repair installed SQL in unrelated parity-test setup.
- Static direct-consumer scans are bounded detection, not proof against arbitrary
  dynamic reflection or external consumers. Engineering tests are not acceptance.

## Final recording boundary (0.11.0)

- Source observation time is not database first-known time. Preserve unknown
  legacy recording times as NULL; require DB-owned time for new evidence and
  test caller backdating through both ORM and raw SQL.
- A successful INSERT is not proof of post-commit integrity. Hold one transaction
  open, observe the competing connection waiting on the shared lock, release it,
  then verify committed evidence. Test both orders and stale raw-SQL selection.
  State isolation-level and multi-series lock-order contracts explicitly.
- First-use immutability checks can race with first consumption. Registration-time
  semantic immutability removes that race; test concurrent orders and ensure
  editorial fields still update. Do not describe a sequential probe as a race.
- Availability must include actual pivot, ATR and lifecycle dependencies without
  inheriting unrelated prefix/suffix delay. Use asymmetric before/equality/after
  cases. A same-bar reclaim must not wait for an unused next candle.
- Reproduce Unicode failures on UTF-8 before assigning them to application code.
  Compare exact identities/causes, not counts or a different broad command.
- Keep concise results, checksums and reproducible scripts. Historical raw logs
  belong to their Git checkpoint, not duplicated into every correction. Record
  verification limitations and cleanup; engineering completion is not acceptance.

## Eight-finding follow-up

The subsequent [independent review](https://ampcode.com/threads/T-01a08985-818d-7698-aa9c-f843744479db)
still rejected the implementation. Descriptor 0.10.0 responds to its eight concrete
findings; acceptance remains superseded. Design §18 and the current handoff govern
the new behavior. The older lessons below describe the preceding correction.

- Cutoff eligibility applies to discovery queries as well as final selection.
  Test a future reschedule that changes only identity, not the displayed payload.
- Freezing ORM collections is not freezing facts. Freeze scalar relations too;
  separate semantic policy fields from editorial notes, and test historical replay
  after editing the latter. Test deletion/addition of unused evidence independently
  from a necessary predecessor or suppressor.
- A syntactically valid content digest proves nothing about the cited row. Test
  raw non-superuser INSERT with recomputed enclosing hashes, wrong content and
  valid-but-unrelated lineage. Independently select the actual latest candle.
- Lifecycle availability inherits prerequisites. Delay the opening candle beyond
  both breakout and failure; vary retest/failure timing before, at and after it.
  Zone dependency windows must exclude unrelated earlier observations.
- “Last available” is not “immediately preceding registered.” Missing an exact
  period must disclose its expected boundaries instead of returning a stale row.
- Independent compression and expansion flags do not establish a transition.
  Pin ordering, window, normalization and equality; preserve the completed fact's
  source identities and times under future suffixes.
- Keep exact-base/final failure identity/cause evidence. Retain reproduction
  evidence before fixes; distinguish engineering results from independent closure.

## Earlier correction lessons (historical)

Earlier acceptance claims are superseded. The latest independent review found
thirteen open findings after earlier reviews had reported acceptance. This
correction is an engineering response, **not an independent re-acceptance**.
See [acceptance](acceptance.md) and [handoff](handoff.md).

1. **Hash agreement is not semantic agreement.** The original guards accepted
   internally consistent false facts. Migration 0034 now validates a single
   explicit definition contract, canonical identities, scope, candle revisions,
   prerequisites and research availability. Integrity also replays classifications.
   Even replay can certify an omitted-input forgery: the correction therefore
   compares the claimed evidence with a separate bounded ledger selection. Full
   formula and selection enforcement still belongs to the application/integrity
   boundary, not solely to the SQL trigger.
2. **Freeze before computing.** A separately queried manifest is not evidence of
   what a computation consumed. Candle scalar tuples and eagerly loaded research
   vintages now precede feature computation. Exact observation, predecessor,
   retrieval, policy, source and series content is bound. Private research models
   are not deep immutable scalar objects; independently review this distinction
   and the conservative auxiliary/evidence supersets before closing finding 1.
3. **Formation, completion and availability are different timestamps.** A pivot
   needs confirming bars; ATR can itself arrive late. FVG, displacement, ORB and
   sweep availability must include normalization evidence. Later volatility must
   not requalify an old candidate. Adversaries must vary spread, ATR and retrieval
   timing independently, rather than using identical timestamps everywhere.
4. **Reachability needs a production-sized fixture.** A monthly trend that passes
   on hand-built monthly bars can still be unreachable through daily ingestion.
   The regression now exercises fourteen complete months through the actual
   400-D observation selection. Zone expiry is tested beyond 200 intervals.
5. **A weekend is not a missing registered interval.** Test Friday→Sunday and
   Thursday→Sunday daily succession alongside a missing weekday interval. Apply
   the same registered calendar to ATR, swings and lifecycle maturity.
6. **Threshold boundaries and terminal transitions deserve asymmetric tests.**
   FVG equality is tested at normalized minima in both directions. Breakout
   failures across the opposite boundary are terminal; later touches cannot
   retroactively make an invalid breakout a retest. Zone tests exclude formation
   and confirmation activity and use frozen confirmation-time margins.
7. **Parity setup must not install the implementation it is verifying.** The old
   setup concealed migration contamination. Runnable historical fixtures now own
   disposable databases; impossible older rollback plans fail before undoing
   M15. Their inherited failures remain errors, not skips. The exact historical
   sequence and broad failure identity comparison are separate required checks.
8. **LIMIT is not a scan bound.** Retain EXPLAIN ANALYZE evidence for old cutoffs
   and revision-rich research, not just output lengths. Time-window bounds and
   2,048-row fail-closed caps limit selection but do not guarantee constant work
   for every revision density. Process RSS including ingestion is not an isolated
   working-set measurement; shared-cluster WAL is not snapshot WAL.
9. **Documentation is part of the contract.** Pin versions without importing
   moving runtime code into migrations. Test the migration digest against the
   Python definition. Never describe destructive table reversal as a safe
   operational rollback. Never carry stale acceptance or test counts forward.

All thirteen finding dispositions and original §4.1–§4.5 traceability are in the
handoff. Passing this correction's focused tests does not replace independent
adversarial review or resolve its explicitly listed limitations.
