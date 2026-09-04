# V2 exploratory-return lineage performance correction

Status: code-only forward correction; no real return execution performed.

## Consumed attempt

The replacement authorization `e84b1b4b4a8b6b6c25ff4eefca21ab649b4a460a0b3db04b09c0433888407868` was consumed by one invocation. It exited 1 after 901.421431 seconds with `exploratory return execution exceeded 15-minute ceiling`. Its last progress was `stage=lineage completed=0 total=82`; no normalized marker appeared. The before/after application-count hash was unchanged at `5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097`, JobRuns remained 5, result and idempotency rows remained zero, and the application-table delta was zero.

The captured telemetry cannot prove whether the worker read any outcome rows before timeout because the old `load_normalized_events()` had no internal markers. It does prove that normalization did not complete, the calculator produced no result, nothing committed and nothing was disclosed.

## Phase map

The historical `lineage` marker was emitted only after authorization/environment checks, database and migration identity, pristine-state reconstruction, semantic dataset/registration/S0/S1/acquisition validation, cohort-key reconstruction and the duplicate check. The next marker followed all of `load_normalized_events()`: entry evidence, sealed D/H1 inventory materialization, evidence-key planning, outcome-candle loading, conflict validation and normalization. Calculation and persistence followed that next marker. The timeout was therefore inside `load_normalized_events()`, not `verify_return_blind_lineage()`.

The corrected count-only markers are `upstream_evidence`, `cohort_reconstruction`, `entry_evidence`, `sealed_inventory`, `evidence_plan`, `sealed_candles`, `normalization`, `normalized`, `calculation` and `commit`. They disclose no price, terminal, P&L or profitability information.

## Measured root cause

Local read-only profiling against the registered timestamp inventory measured 362,229 D/H1 members. The exact local planning geometry invoked `_prior_start()` 19,878 times: 16,363 unique `(pair, decision_time)` keys and 3,515 repeats. The old helper rebuilt and converted the full H1 completion list before each bisect, rescanning 1,141,664,450 elements. A bounded 500-call sample scanned 28,719,508 elements in 13.340301 seconds. Amp's remote estimate of approximately 46,000 calls correctly identified the algorithmic defect but is superseded by the local exact count.

The exact return-blind lineage verifier completed in 0.369547 seconds with 106 queries. Timestamp inventory loading took 2.430214 seconds, one-time completion precomputation took 0.175477 seconds and all 19,878 cached bisects took 0.012881 seconds. The corrected real timestamp-only preparation reached the 27,969-key candle plan in 2.647610 seconds with three queries before candle loading and zero candle-price queries.

Both old and corrected preprocessing use three queries before candle loading; the failed invocation's total query count remains unknown because it was not instrumented. The complete corrected adapter has a fixed 16-query budget: entry evidence, confirmations, inventory, twelve instrument/granularity candle groups and one conflict check. That count is independent of event and candle cardinality.

The correction precomputes completion tuples once for each instrument/granularity, bisects D completions rather than scanning D history repeatedly, and loads candles with twelve fixed instrument/granularity queries. A repeat-key cache was not added: only 3,515 of 19,878 lookups repeated, while all cached-tuple bisects already took 0.012881 seconds.

## Query-plan evidence

The old combined OR predicate had an estimated cost of 4,826,101.81. It was not executed against real outcome data. Twelve return-blind `EXPLAIN (ANALYZE, BUFFERS)` membership-only queries selected only candle ID and timestamp across the complete 362,229-member registered D/H1 inventory. They completed in 282.320 ms total, with a maximum group time of 117.589 ms, and used `unique_dataset_market_candle`, `market_candle_dataset_version_id_3b97cce0` and `market_instrument_code_29fcb23f_like`. This broader-than-required proof supports the fixed-group query shape; no index migration is warranted.

## Synthetic proof and preservation

The prior rehearsal returned deep-copied, already-normalized events and therefore bypassed inventory loading, `_prior_start()`, conversion planning, Django query construction and normalization. The new harness separately exercises production-cardinality lookup planning and runs the complete runner/calculator/bootstrap/atomic-store path twice with 82 events and 19,762 deterministic synthetic H1 rows. Both runs produced evidence hash `0b590b8ff666273599a2707ab1097fa15cc8456d032d2d04e4f668a1743ab744`. Maximum watchdog duration was 1.137667 seconds, worker RSS 103,825,408 bytes and the conservative process-tree bound 128,876,544 bytes—substantial headroom under 900 seconds and 1 GiB.

Calculator source, financial formulas, 82-event cohort identity, 186 memberships, S2 policy, terminal ordering, currency conversion, cost grid, atomic persistence, idempotency, timeout/memory watchdog and permanent non-promotion are unchanged. Golden tests cover strict-prior equality and adjacent boundaries; existing calculator/policy/geometry tests retain DST, weekend, CAD-route, missing/conflicting evidence, rollback, timeout, memory and concurrency coverage.

## Forward authority

Both earlier authorizations and both failure artifacts remain immutable consumed history. The new fixed-path successor authorization permits exactly one future invocation of the same command, requires a fresh verified backup, retains the 900-second and 1 GiB boundaries, prohibits retry/resume/further replacement without new explicit authority, and permanently prohibits promotion and live trading. It contains no expected return, outcome, terminal, P&L, equity or profitability hash.
