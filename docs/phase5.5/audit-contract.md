# Return-blind coverage and prior-use audit v1

Run before importing a strategy evaluator or reading any strategy output.
The metadata audit may inspect the sealed period only for the columns listed
below; this is not permission to load candle values or strategy results.

Database connections must use read-only, repeatable-read transactions with
statement/lock timeouts. Queries are fixed SELECT statements, never caller SQL.
Allowlisted metadata: instrument/source/dataset identity, granularity,
timestamp/interval end, observed/recorded/captured/available/vintage clocks,
counts, revision and completeness, existence of bid/ask fields or required
evidence, definition identity and prior evaluation/simulation cutoff counts.
Never select OHLC values, output JSON, direction, setup result, forecasts,
positions, returns or realized costs. Do not load arbitrary manifests (they
can contain outcomes or provider credentials). No provider trading endpoint.

Price availability is not executable spread/slippage evidence. A count of
calendar events is not calendar coverage/empty-window attestation. Current terms
do not reconstruct historical commissions/financing. Counts of observations
do not prove revision-safe retrospective replay. Gaps without a vintage-aware
expected-open calendar are unclassified timestamp discontinuities, not missing
trading intervals. Preserve actual acquisition clocks; no backdating.

Persist audit metadata and its hash before registration/outcomes. Each source
must state inspected, inaccessible, absent or unknown. Missing tables are
explicit, not empty data. No global prior-use clearance follows merely from
zero local rows: record owner confirmation and prior-research scope separately.
Source identity and exact dataset/candle manifests must subsequently be frozen
in the registration; audit summary hashes alone are not evaluation manifests.

Holdout is provisionally [2025-01-06,2026-09-07), halves split 2025-11-10,
all UTC half-open (44 + 43 = 87 ISO weeks). Development and warm-up are as in
the acceptance matrix. Coverage/prior-use failure requires documented replacement
dates supported by actual evidence before outcomes. If no qualifying dates
can be established, remain blocked rather than manufacture an untouched sample.
