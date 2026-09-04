# Failed-break v2 S1 runner: architecture and disposable benchmark

## Authorization boundary

This is code-only implementation and disposable verification. Persistent v2 S1 execution, returns, backtesting, promotion, and live trading remain unauthorized. The production command is readiness-only by default; `--execute` additionally requires a separately reviewed, fixed-path authorization artifact that is not present.

## Architecture map

The runner safely reuses the existing immutable S1 models, canonical `evidence_hash` builder, pure failed-break strategy functions, registered-inventory loader, v2 completion/admission primitives, sealed-D horizon, point-in-time CAD conversion policy, and accepted-v2-S0 verifier. The existing v1 `signal_count_s1` orchestration and row-at-a-time services are not reused: they pin v1 job/detector identities, repeatedly query history and lifecycle state per H1 member, and embody the superseded H1-coincident D/W admission path. The new path preloads all registered evidence, computes chronologically in memory, constructs every persisted field and hash explicitly, and writes once.

The exact write graph is `JobRun -> Level -> LevelLifecycleEvent -> SetupEvent -> SetupLevelAttribution -> SetupTransition (confirmation) -> EntryEligibilityEvaluation -> SetupTransition (entry decision) -> AnalysisRun`. All writes are enclosed by one outer transaction. A duplicate check runs before the first insert. There is no retry, resume, partial-success, or partial-commit path.

All written models inherit `ImmutableRecord`. Its only `save()` override refuses updates when a primary key already exists; it does not derive defaults or hashes. `bulk_create` bypasses that check, so the runner explicitly supplies stable keys, evidence hashes, transition decision times, execution/strategy/dataset lineage, and every decision-dependent nullable field.

The affected database triggers are `research_jobrun_append_only`, `research_level_append_only`, `research_levellifecycleevent_append_only`, `research_setupevent_append_only`, `research_setuplevelattribution_append_only`, `research_setuptransition_append_only`, `research_entryeligibilityevaluation_append_only`, `research_analysisrun_append_only`, `research_setup_attribution_validate`, `research_setup_transition_validate`, and `research_entry_target_validate` (the latter two call the migration-0015 sealed-inventory entry-boundary function). The named model constraints are `level_low_lte_central`, `level_central_lte_high`, `level_atr_positive`, `unique_level_lifecycle_event`, `unique_analysis_instrument_h1_detector_dataset`, `unique_physical_setup_event`, `unique_setup_level_attribution`, `unique_setup_outgoing_transition`, `valid_phase2a_setup_transition`, `unique_setup_book_eligibility`, and `eligibility_fields_match_decision`; primary keys, protected foreign keys, non-null fields, and the unique level stable-key and JobRun idempotency-key fields also apply.

The load budget outside accepted-S0 reconstruction is one registration identity query, one six-instrument metadata query, three snapshot queries per instrument (sealed inventory, registered candles with lineage, conflicts), and one global ingestion-manifest query. Detector computation itself contains no ORM or database-connection access; query count is independent of member count.

## Real-model disposable benchmark

Two independent restores of the verified post-v2-S0 backup were run in a local PostgreSQL 16 cluster listening only on a private Unix socket with TCP disabled. Each rehearsal used actual Django models, indexes, constraints, and triggers. The fixture was AUD_USD from 2017-01-01 through 2018-12-31 (2017 warm-up; 2018 persisted measurement), plus USD_CAD over the same interval solely for governed CAD conversion evidence. It read no post-entry outcome or return model.

Invocations:

```text
POSTGRES_DB=failed_break_v2_s1_benchmark_a POSTGRES_USER=oluwatomisintaiwo POSTGRES_HOST=/private/tmp/failed-break-v2-s1.nEog8H/socket POSTGRES_PORT=55441 .venv/bin/python -m research.benchmarks.failed_break_v2_s1_runner_benchmark --batch-size 500 --output /private/tmp/failed-break-v2-s1-benchmark-a-final4.json
POSTGRES_DB=failed_break_v2_s1_benchmark_b POSTGRES_USER=oluwatomisintaiwo POSTGRES_HOST=/private/tmp/failed-break-v2-s1.nEog8H/socket POSTGRES_PORT=55441 .venv/bin/python -m research.benchmarks.failed_break_v2_s1_runner_benchmark --batch-size 2000 --output /private/tmp/failed-break-v2-s1-benchmark-b-final4.json
```

Environment: macOS 26.5.2 arm64, Python 3.11.4, Django 5.2.17. Provider credential variables were removed for both invocations. Harness SHA-256: `50220560994df705b4754757714fb5797131b012c8168657e4405af12b1859c9`.

Both runs admitted AUD_USD D/H1/W counts 519/12,409/103 and USD_CAD 521/12,411/103. The persisted 2018 workload was 6,216 analyses, 584 levels, 577 lifecycle events, 11 setups, 20 attributions, 28 transitions, 17 entry evaluations, and one JobRun (7,454 rows in the transaction). Both batch sizes and both golden-reference/optimized projections produced projection SHA `e475a78ed5eb357e97d7aa62b58fa4b512fc9ae9eda4f521e2162944d4f374e2`, JobRun configuration SHA `cff541256f9d2138260e2b7ebe04d44ff3e2ddaa0ddeafd5f0058c69af13f08b`, and report SHA `05aa6d17af02a6bf1188eeb08d5f60dc5aa11347b79d3c923bd70a6e505f7b9a`.

| Stage | batch 500 | batch 2,000 |
|---|---:|---:|
| Accepted S0 reconstruction | 18.269 s | 18.222 s |
| Registration/lineage validation | 0.375 s | 0.381 s |
| H1/D/W plus conversion preload | 2.075 s | 2.063 s |
| Detector computation | 0.998 s | 1.003 s |
| Canonical evidence construction | 0.001 s | 0.001 s |
| Golden-reference equivalence check | 1.022 s | 1.028 s |
| Actual-model persistence and commit | 0.334 s | 0.334 s |
| Total | 23.282 s | 23.222 s |

For batch 500, writes measured: analyses 0.157 s; levels 0.026 s; lifecycle 0.017 s; setups 0.001 s; attributions 0.001 s; confirmation transitions 0.001 s; entry evaluations 0.003 s; entry transitions 0.008 s; JobRun 0.0005 s. PostgreSQL constraint and trigger execution is included in each insert-stage measurement and cannot be separated safely without disabling governance. The residual transaction/commit estimate was 0.118 s (0.117 s for batch 2,000).

Injected failure after entry-evaluation insertion rolled back to the exact pre-run counts on both restores. A second persistence call was refused before writes. V1 counts remained exactly unchanged on both restores: 344,667 analyses, 17,162 levels, 17,128 lifecycle events, 855 setups, 1,185 attributions, 1,616 transitions, 761 entry evaluations, and three JobRuns.

The machine-readable summary is `s1-runner-benchmark-results-v2.json`. It records batch/restore determinism and the measured timings without presenting compute-only timing as full S1 runtime.

## Full-run projection

Scaling the 6,216 measured analyses to the governed 344,817 H1 membership gives a direct compute/write estimate near two minutes after one-time validation and preloads. The conservative planning range is **2–6 minutes** on the measured host. This is a range, not an execution promise: six-instrument conversion lookups, different setup/level density, PostgreSQL index growth, JSON serialization, cache temperature, trigger costs, and one large transaction can scale nonlinearly. The range is below 30 minutes; persistent execution nevertheless remains closed pending separate review and authorization.
