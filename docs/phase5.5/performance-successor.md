# Bounded causal-input reuse, validation revision 4

The owner rejected waiting 10–12 hours for the full population. The four local
revision-3 workers were stopped with interrupts, preserving committed daily
checkpoints. The idle catalog contains 48,125 checkpoints and passes SQLite
integrity checking. It is incomplete, not an accepted or fully verified report
population. All revision-1/2/3 registrations and existing publications remain
unchanged; revision 4 explicitly supersedes revision 3 rather than reusing its ID.

Profiling one registered development day under unchanged revision 3 showed
8,785,790 calls, with most time rebuilding H1 liquidity and M15 structure inputs.
A separate three-day/two-strategy reference (576 opportunities) took 12.384 seconds
excluding data loading; its private canonical result is retained for comparison.
Those calculations preceded source changes and used only registered development
data. A synthetic red test demonstrated duplicate computation of identical inputs.

The successor caches only the existing pure H1 liquidity and M15 break-of-structure
descriptor outputs. Keys include instrument, descriptor granularity and the entire
causally selected immutable bar tuple, including acquisition/revision provenance.
The cache holds at most 4,096 entries, is process-local and disappears on restart.
Cached JSON is immutable; each evaluation decodes its own copy. Future candles are
excluded before lookup, and different prior revisions cannot reuse cached entries.

This shares descriptive inputs, not strategy decisions, positions, outcomes or
report populations. Sweep reversal and acceptance continuation retain separate
evaluations, scenarios, state, checkpoint identities and reports. Adjacent bounded
chunks for those two strategies can reuse inputs in the same process. Original
Phase 5 formulas, simulator digests, all periods, population, cost assumptions,
thresholds, report schema and evidence-first disposition rules are unchanged.
No production module, consumer, schedule or eligibility path is modified.

Semantic replay admission, complete-chain verification and report publication
boundaries remain unchanged. No on-disk proof or claimed end state replaces replay.
Freeze and commit the successor before any actual development benchmark with its
source. Compare a small fixed slice with the retained revision-3 reference and
measure end-to-end checkpoint cost before allocating another complete replay.
Do not infer a full-population speedup or pass from that small benchmark.

The historical holdout remains sealed. No cache, benchmark or work-allocation
option permits its access. Future financing and other mandatory-evidence gates
remain unchanged.
