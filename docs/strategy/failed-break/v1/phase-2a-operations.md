# Phase 2A operations

Phase 2A stops at theoretical entry eligibility. It does not authorize historical return,
post-entry price, M1-window, alert, or order processing.

## Upgrade precondition

Before applying `research.0011_phase_2a_review_corrections`, the pre-correction
`EntryEligibilityEvaluation` table must contain no `ENTRY_PENDING` rows. The old schema does not
retain the registered point-in-time CAD conversion evidence required by the corrected schema, so
the migration aborts rather than inventing that evidence. Resolve this by deploying against an
empty Phase 2A research database; do not delete or synthesize records to bypass the preflight.

Migrations 0011–0013 keep affected tables append-only or write-guarded at every committed stage.

## Registered return-blind workflow

After an approved, complete six-instrument development dataset exists, register S0 first:

```text
python manage.py signal_count_s0 \
  --dataset-id DATASET_ID \
  --strategy-version-id STRATEGY_VERSION_ID \
  --as-of AS_OF \
  --max-observations MAXIMUM
```

S0 trims every declared W/D/H1 range to candles completing strictly before the development
boundary. Its row-count and lineage checks do not require post-boundary D/W records, and its spread
population excludes an H1 open when that H1 candle completes at or after the boundary. S0 fails
rather than truncating. Its output includes the immutable `JobRun` ID required by S1:

```text
python manage.py signal_count_s1 \
  --dataset-id DATASET_ID \
  --strategy-version-id STRATEGY_VERSION_ID \
  --s0-job-id S0_JOB_ID \
  --as-of AS_OF \
  --max-setups MAXIMUM
```

S1 first runs the bounded chronological detector, records one detector-scoped `AnalysisRun` for
every registered development H1 decision point, and registers an immutable detector `JobRun`.
The final return-blind report verifies that detector job and exact analysis coverage before it is
registered. Re-running an existing identity is an idempotent resume/revalidation of immutable
records; it is not an independent offline replay.

The detector reads H1 evidence chronologically. It resolves an entry through the restricted
timestamp/bid-open/ask-open projection after that H1 interval completes and before loading the
interval's full detection OHLC. At a shared H1/D/W close it then admits the completed candles,
applies D/W lifecycle and structure changes before pending confirmation, and detects a new sweep
using the updated bias while excluding levels activated at that sweep close.

`partition_boundary_censored` is a research-partition exclusion, not a strategy transition. A
development sweep is censored when its latest possible three-H1 confirmation window plus its
required entry-evidence H1 completion is not strictly before `2019-01-01 00:00
America/New_York`. The detector computes that horizon from timestamps and the registered H1
calendar (including Friday-to-Sunday alignment), without reading a 2019 candle. Its immutable
detector report records canonical, individually hashed evidence for every censored setup. The final
S1 audit reconstructs that evidence and fails if it is absent, forged, or attached to a setup with a
strategy transition. The censorship-rule identity is also included unconditionally in both detector
and final S1 audit configurations, including when no setup is censored.

Censored setups remain in raw sweep and attribution diagnostics but are excluded from confirmation,
eligibility, book, concurrency, proposed-M1-window, and later return populations. They are distinct
from `partition_boundary_purged`, which retains the frozen ten-session rule for resolved
confirmations, so the populations cannot overlap. S1 fails rather than registering any other
incomplete or truncated audit. These commands must not be run against complete historical data
until that run is separately authorized.
