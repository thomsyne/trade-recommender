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

The Decision Evidence extension is implemented: five broader business/market
RSS feeds, S&P 500/VIX/Bitcoin/WTI/US 10-year/broad-USD context, a slower
explicitly labelled World Bank-derived gold series, official BoC/Fed/BoE/ECB
decision calendars, and four-hour immutable pair evidence snapshots. Pair
pages show evidence freshness, source count, pair macro, intermarket, calendar,
and news without creating or changing forecasts.

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

Build the first model-forecast contract against `PairEvidenceSnapshot`: pin the
Anthropic model and prompt, define strict output validation and spend caps, and
write a new prospective recommendation record without altering evidence or the
existing mechanical controls. Complete the source-by-source external-model
terms review before including anything beyond fields already marked model
eligible.

## Still OPEN

- provider permission for external-model processing;
- paid economic-calendar/PIT provider trial;
- remaining BLS/Census release-calendar automation;
- financing history/cost sensitivity parameters.
