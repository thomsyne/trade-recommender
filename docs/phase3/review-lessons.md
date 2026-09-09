# Phase 3 review corrections and future verification obligations

These are concrete failures in the initial implementation, not accepted risks.
Independent review found eight blockers at `e74defa`. The correction log and tests
must establish fixes before acceptance; documentation alone is no evidence.

| Missed assumption | Required future counterexample |
|---|---|
| A decimal column and Decimal calculation imply the same midpoint | Ingest bid/ask whose midpoint ends in half a micro-unit on both even and odd ties. Verify real target AND endpoint writes, canonical digest and raw SQL. Explicit HALF_EVEN is preserved. |
| A row declaring v3 is historical | Register a future cutover; try v1/v2/v3 before and after effectiveness, spoof recorded_at and backdate generated_at. PostgreSQL owns insertion time. Preserve existing null-audit legacy rows without backfill. |
| The service's endpoint query protects every writer | ORM creation and bulk/raw insertion must reject immediately before successful endpoint availability and accept exactly at it. Also challenge incomplete/failed observations and endpoint shape. |
| A matching source id/state is semantic proof | Attempt expired-unobserved one microsecond before the real horizon, full coverage labelled missing, no-entry versus entered gaps, expired results before maturity, and cancellation/revocation after entry. Test source records themselves and canonical transitions. |
| A confidence helper works for any metric with the same range width | Test negative, zero and positive paired deltas with signed support and independent Hoeffding arithmetic. Preserve the unsigned Brier path. Lower must never exceed upper. |
| A schedule already marked invalid is safe to use downstream | Feed null/zero/bool/long/null-JSON and daily recurrence shapes before gcd/date arithmetic. Check bounded JSON, nonzero command status, safe seed rejection, and unequal-period eventual collisions. This repeats the Phase 2 malformed-diagnostic pitfall and must become a mandatory boundary test. |
| A report cutoff only applies to model samples | Save a later shared resolution, derived score, selection, closure and paper result; rerun the earlier report byte-for-byte at the same cutoff. Future facts must not change it. |
| A historical assertion can reverse the current installed graph | Run the exact integrated command at base and branch, compare identities AND causes, and exercise historical assertions in a permanent normally migrated isolated database. Never hide a new failure behind an external old-schema run. |

Further source gaps found while closing the review matrix: unsupported control
methods were insertable against an occurrence; weekly dependence could be forged
in SQL; a revocation source after entry could release capacity before the canonical
transition rejected it. Source boundaries must validate the invariant before any
projection or side effect observes the fact. Specific regression tests precede
acceptance of these adjacent corrections.

The historical harness declares market0030/research0014 because the Phase 2 test
changes instrument eligibility across market0029→0030 and needs the historical
research tables needed for normal fixture flushing at that boundary. These two
assertions create no research setup, entry eligibility or dataset acceptance
evidence. Research 0015 changes entry-boundary validation and depends on market
0027; those semantics are outside these instrument and schedule assertions.
Research 0014 therefore supplies their declared historical schema without pulling
in unrelated later evidence dependencies. The full current graph is still
normally installed in the original test database before this class runs. The original installed graph is never mutated;
all fixture writes, normal forward/backward migrations and unchanged assertions
execute in a UUID-owned test database. Only the existing documented market0027
bootstrap accommodation is used. The default connection is restored and the exact
owned historical database is dropped. The 19 pre-existing Gate8 assertions remain
unchanged; their different base/branch failure causes must remain explicit.

The tester observed base 222 tests / 5 failures / 23 errors versus branch 257 tests / 20 errors.
Those independent counts supersede any suggestion that the engineer's earlier
base 222 tests / 19 errors was the sole reproducible result. Disk-readiness failures are
separate observations: the unchanged threshold is 2 GiB and the host fell below it.
No assertion, runtime gate or unowned file may be changed to conceal that condition.
