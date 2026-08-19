# First-slice architecture

```diagram
┌──────────────┐      ┌────────────────────┐
│ Private user │─────▶│ Django dashboard   │
└──────────────┘      │ Today/Pair/Ops     │
                      └─────────┬──────────┘
                                │
                    ┌───────────▼───────────┐
                    │ PostgreSQL            │
                    │ market truth + queue  │
                    └──────┬─────────┬──────┘
                           │         │
                  ┌────────▼───┐ ┌───▼────────┐
                  │ scheduler  │ │ worker     │
                  │ occurrences│ │ task claim │
                  └────────────┘ └─────┬──────┘
                                      │
                                ┌─────▼──────┐
                                │ OANDA v20 │
                                │ bid + ask │
                                └────────────┘
```

## Ownership boundaries

- `market.models` owns canonical instruments, rights-aware source records,
  retrieval manifests, candles, technical snapshots, and audit events.
- `market.oanda` owns the provider request/response contract. It has no database
  authority.
- `market.quality` owns acceptance of a batch before persistence.
- `market.services` owns idempotent persistence and technical snapshot updates.
- `market.technicals` is pure deterministic calculation code.
- `operations` owns durable occurrence generation, claims, retries, and task
  dispatch. Task implementations call the owning domain service.
- `dashboard` reads domain state. It cannot create evidence or forecasts.

## Invariants

1. Stored candles are completed bid/ask intervals with UTC interval-start
   timestamps.
2. `(instrument, granularity, timestamp)` is unique.
3. A retrieval is idempotent by a canonical SHA-256 manifest.
4. An invalid batch stores no candles and emits a rejection audit event.
5. Audit events reject updates/deletes in both Django and PostgreSQL.
6. Midpoints are display/feature values, never future execution prices.
7. Fixture sources are quarantined, visibly labelled, and never forecasts.
8. A scheduled occurrence has one durable idempotency key and one atomic claim.

## Deliberate first-slice choices

- A database-backed queue avoids Redis/Celery until workload proves the need.
- Canvas charting avoids a frontend build pipeline while giving the browser a
  real candlestick surface. A dedicated library remains replaceable.
- Local setup runs native PostgreSQL because Docker is not preinstalled in Amp
  orbs; Compose still records the web/worker/scheduler/database topology.
- The development owner and fixtures only seed when `DEBUG` is true.

## Forecast seam — implemented

Versioned immutable forecast/evidence contracts, mechanical baselines, and
proper scoring fixtures now sit above market truth. See
`docs/forecast-contract.md`. The next seam is rights-aware point-in-time
research ingestion; it may create evidence records but cannot issue forecasts
or alter contracts and scoring.
