# Current handoff

## Completed

The Foundation and Market Truth slice is implemented. It includes PostgreSQL
setup, Django authentication, canonical instruments and source policy,
OANDA bid/ask ingestion, fail-closed quality validation, deterministic
technicals, append-only audit, durable scheduler/worker primitives, fixtures,
tests, and Today/Pair/Operations interfaces.

The Forecast Contract slice is also implemented: immutable macro/tactical
target versions, exact market evidence snapshots, parent forecasts, explicit
abstention and conditional-entry fields, five/twenty-session resolution,
mechanical controls, mean multiclass Brier scoring, PostgreSQL mutation
triggers, and Decision/Timeline rendering.

The Research Ingestion slice is implemented: a safe allowlisted fetch boundary,
immutable raw RSS/API snapshots, official central-bank release feeds and
policy-rate series for CAD/USD/EUR/GBP, deterministic normalization,
publication/retrieval/vintage timestamps, deduplication, revisions/conflicts,
rights metadata, scheduled jobs, provider-comparison records, and a read-only
Research ledger. See `docs/research-ingestion.md`.

## Verification gate

Run:

```bash
./.agents/setup
./.agents/setup
./.agents/resume
make check
make test
make dev
```

Then authenticate through the portal and review Today, USD/CAD H4/Daily,
Research, and Operations at desktop and narrow viewport widths.

## Next pickup

Before synthesis, finish source qualification: verify current official CPI and
employment identifiers/revision semantics, run a bounded economic-calendar
candidate trial, and complete terms review for any evidence sent to an external
model. Preserve the strict research→forecast boundary; any later thesis model
must consume locked evidence snapshots and write a new prospective contract,
not alter this ledger.

## Still OPEN

- provider permission for external-model processing;
- paid economic-calendar/PIT provider trial;
- official CPI and employment release-time/revision contracts;
- financing history/cost sensitivity parameters.
