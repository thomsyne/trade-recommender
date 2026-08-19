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

Then authenticate through the portal and review Today, USD/CAD H4/Daily, and
Operations at desktop and narrow viewport widths.

## Next pickup

Implement only the Research Ingestion slice from `docs/project-map.md`:

1. add official point-in-time macro observations/releases for Canada, the US,
   euro area, and UK;
2. add the isolated rights-aware RSS/web fetch boundary;
3. preserve provenance, release/vintage time, lineage, conflicts, and lawful
   retention metadata;
4. implement a recorded-fixture harness for the economic-calendar provider
   trial;
5. render research evidence without allowing it to create forecasts.

Do not add Anthropic synthesis, paper positions, or AWS in that pass. Preserve
every market-truth and forecast-contract invariant.

## Still OPEN

- provider permission for external-model processing;
- paid economic-calendar/PIT provider trial;
- financing history/cost sensitivity parameters.
