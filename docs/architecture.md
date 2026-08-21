# System architecture

```diagram
┌──────────────┐      ┌────────────────────────┐
│ Private user │─────▶│ Django dashboard       │
└──────────────┘      │ Today/Pair/Research/Ops│
                      └───────────┬────────────┘
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
                         ┌────────────▼────────────┐
                         │ bounded provider edges │
                         │ OANDA + official macro │
                         └─────────────────────────┘
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
- `forecasts.recommendations` owns the provider-neutral recommendation contract,
  bounded Claude adapter, semantic validation, idempotency, spend gates,
  prospective resolution, and calibration metrics.
- `forecasts.paper` owns deterministic post-recommendation hourly bid/ask setup
  activation, conservative exit ordering, expiry, and immutable paper results.
- `research.fetch` owns the HTTPS allowlist, DNS/redirect/size/content-type
  safety boundary. It is not exposed as a generic fetch endpoint.
- `research.services` owns immutable raw research, normalization, vintages,
  deduplication, discrepancies, and audit lineage. It has no forecast write
  authority.
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
9. Research payloads normalize only after a fail-closed parse; rejected payloads
   remain quarantined raw evidence.
10. A changed macro value appends a vintage and discrepancy; it never rewrites
    an earlier observation.
11. Research cannot issue, mutate, resolve, or score a forecast.
12. A model recommendation cites only records in its immutable input snapshot,
    remains separate from the mechanical control, and has no execution authority.
13. Only recommendations with a frozen probabilistic outcome contract are
    resolved; vague legacy confidence is never reinterpreted after the fact.
14. Paper execution starts strictly after recommendation generation, uses
    executable bid/ask sides, and remains separate from thesis calibration.

## Deliberate first-slice choices

- A database-backed queue avoids Redis/Celery until workload proves the need.
- Canvas charting avoids a frontend build pipeline while giving the browser a
  real candlestick surface. A dedicated library remains replaceable.
- Local setup runs native PostgreSQL because Docker is not preinstalled in Amp
  orbs; Compose still records the web/worker/scheduler/database topology.
- The development owner and fixtures only seed when `DEBUG` is true.

## Forecast and research seams — implemented

Versioned immutable forecast/evidence contracts, mechanical baselines, governed
model recommendations, and proper scoring fixtures now sit above market truth.
Rights-aware, point-in-time official research sits beside them as a separate
evidence ledger. See `docs/forecast-contract.md`,
`docs/recommendation-contract.md`, and `docs/research-ingestion.md`.

Experiment health is a separate prospective ledger. Immutable method and policy
identities open champion or owner-authorized challenger eras before evidence is
collected. Recommendations are assigned at issuance, outcomes remain subject to
their original contracts, and daily assessments weight each UTC week as one
dependence cluster. Promotion records authorize review only; they cannot change
the active method, prompt, sizing, execution, or risk policy.
