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

S0 fails rather than truncating. Its output includes the immutable `JobRun` ID required by S1:

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
registered. Raw sweep and attribution diagnostics retain partition-boundary-purged confirmations;
confirmation, eligibility, and later populations exclude them. S1 fails rather than registering an
incomplete or truncated audit. These commands must not be run against complete historical data
until that run is separately authorized.
