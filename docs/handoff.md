# Current handoff

## Completed

The Foundation and Market Truth slice is implemented. It includes PostgreSQL
setup, Django authentication, canonical instruments and source policy,
OANDA bid/ask ingestion, fail-closed quality validation, deterministic
technicals, append-only audit, durable scheduler/worker primitives, fixtures,
tests, and Today/Pair/Operations interfaces.

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

Implement only the Forecast Contract slice from `docs/project-map.md`:

1. close the exact five-day probability event and neutral-band decision with
   the owner;
2. create versioned immutable macro/tactical target contracts;
3. add forecast issuance cutoffs, parent dependencies, abstention, and expiry;
4. implement deterministic resolution against later executable data;
5. add declared mechanical baselines and proper scoring fixtures;
6. render locked fixture forecasts in Decision and Timeline surfaces.

Do not add Anthropic, broad web/news, paid providers, paper positions, or AWS in
that pass. Preserve every first-slice invariant in `docs/architecture.md`.

## Still OPEN

- real OANDA token/account availability;
- exact five-day target and neutral band;
- provider permission for external-model processing;
- paid economic-calendar/PIT provider trial;
- financing history/cost sensitivity parameters.
