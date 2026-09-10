# Phase 4 — Deterministic Market-State Engine: Runbook

Operational guide for the market-state engine (`market/state/`). Formulas,
thresholds and versions are defined in [design.md](design.md); this document is
how to run, verify, estimate and roll back. **Nothing here is scheduled or
activated** — every command is read-only or writes only immutable market-state
records, and none calls a provider.

## Components

| Module | Responsibility |
|---|---|
| `market/state/canonical.py` | Deterministic canonical JSON + SHA-256 (rejects float/Decimal/bad keys) |
| `market/state/definitions.py` | Register/load content-addressed `MarketStateDefinition` (fail-closed) |
| `market/state/manifest.py` | Causal input-manifest (eligible candle identities at a cutoff) |
| `market/state/snapshots.py` | Idempotent, determinism-checked snapshot persistence |
| `market/state/features.py` | Higher-timeframe: swings, trend, ATR, volatility, equilibrium, BOS/CHoCH |
| `market/state/structure.py` | S/R zones, equal levels, displacement candidates, consolidation, prior extremes |
| `market/state/liquidity.py` | Sweep and acceptance proxies |
| `market/state/fvg.py`, `sessions.py`, `orb.py` | FVG proxy and ORB (first M15 of London/NY sessions) |
| `market/state/context.py` | Point-in-time macro regime, scheduled-event state, spread |
| `market/state/compute.py` | Assembles the payload; `build_market_state` (no persist) and `compute_market_state` (persist) |
| `market/state/integrity.py` | Read-only semantic-integrity verification |
| `market/state/tasks.py` | Durable per-instrument calculation task (unscheduled) |

The current descriptor definition is `market-state-descriptor@0.9.0`
(`compute.DESCRIPTOR_DEFINITION`); the version is bumped whenever the feature set,
a threshold or a lookback changes, so every snapshot binds the exact algorithm
versions. Bounded per-granularity lookbacks (`compute.LOOKBACKS`) are pinned in
the definition body so no computation scans unbounded history.

## Dry-run / read-only commands

All use the disposable test-DB or a read-only connection; none is scheduled.

```bash
# Preview one snapshot payload WITHOUT persisting (read-only):
.venv/bin/python manage.py preview_market_state EUR_USD --cutoff 2026-01-05T13:00:00+00:00 --granularities M15 H1 H4 D W

# Verify semantic integrity of persisted snapshots (nonzero exit on violation):
.venv/bin/python manage.py market_state_integrity
.venv/bin/python manage.py market_state_integrity --instrument EUR_USD
# Continue a bounded report when has_more is true (use its next_after_id):
.venv/bin/python manage.py market_state_integrity --after-id 100

# Offline M15 acquisition + snapshot storage estimate (no DB/provider):
.venv/bin/python manage.py estimate_m15_cost --instruments 12
```

Computing a snapshot programmatically (durable task, one instrument, idempotent):

```python
from operations.tasks import execute_task

execute_task(
    "market.compute_market_state", {"instrument": "EUR_USD", "cutoff": "2026-01-05T13:00:00+00:00"}
)
```

The task is **not** registered as a `ScheduledJob`. Activating it later requires a
separate, explicit decision informed by `estimate_m15_cost` — do not seed a
schedule as a side effect.

## M15 prerequisite and non-activation

M15 is a supported ledger/calculation granularity (`quality.LIVE_GRANULARITIES`)
but is deliberately excluded from `quality.SCHEDULED_LIVE_GRANULARITIES`, so the
Phase 2 canonical job inventory is unchanged and **no M15 schedule exists**. The
`ingest_oanda` CLI and live schedules see only `H1/H4/D/W`; M15 ingestion is a
programmatic capability (`SUPPORTED_LIVE_INTERVALS`) used by tests and dry-runs.
Migration `0031` adds the M15 arm to the migration-0029 SQL mirrors in lockstep
with `quality.py`; it is reversible to the exact pre-M15 bodies.

## Availability and missingness

Every feature returns `state ∈ {available, unavailable, not_applicable}`. An
`unavailable` feature carries a stable `reason_code` (e.g. `insufficient_history`,
`insufficient_right_bars`, `atr_unavailable`, `opening_interval_missing`,
`no_established_structure`, `event_time_date_only`, `macro_vintage_unavailable`,
`spread_unavailable`) and is **never** collapsed into a neutral or false value.
The snapshot's `data_quality_status` is a coarse aggregate; per-feature
availability lives inside `output_payload`.

## Monthly aggregation

`prior_completed_month` aggregates completed daily candles into the latest fully
past New York-session month (`compute._prior_completed_month`). A partial current
month is never reported as a completed month; when no past month has candles the
result is `unavailable(incomplete_period)`.

## Macro / event / spread limitations (point-in-time honest)

- **Events** carry no trustworthy severity field, so severity is reported
  `unavailable(severity_unavailable)` — never a fabricated "high impact".
  Date-only events expose no intraday risk window (`event_time_date_only`).
- **Macro** reads honor availability, vintage and retrieval time; a revision
  whose vintage is after the cutoff is never used. The regime is currently the
  point-in-time policy-rate level and direction per currency; other indicators
  are a later extension.
- **Spread** is the observed bid/ask at the candle close, never backfilled. FVG
  spread-normalization uses the candle-3 spread when available, else is reported
  `unavailable(spread_unavailable)` with the price facts retained.

## Integrity report

`market_state_integrity` recomputes the definition, output and input-manifest
hashes and the idempotency key, checks payload/definition agreement, and per
manifest candle checks interval-ended-by-cutoff, that the cited observation still
exists, and that its content hash is unchanged (silent-revision detection).
It independently reconstructs price and research classifications from exact
cited records; it does not trust the stored classification as an oracle.
Diagnostics are bounded ids and reason codes. Each page checks at most 100
snapshots and returns `has_more` and `next_after_id`; a clean page does not certify
the unchecked tail. Continue with `--after-id` until `has_more` is false. This is
the **semantic-integrity** axis only — availability/freshness/coverage are
separate. Exit code is nonzero when `violation_count > 0`.

## Test / verification (disposable database)

The market test database cannot migrate from scratch (migration 0027 requires
production data state), so use the documented **market0027 fake-bootstrap
accommodation**, then `--keepdb`:

```bash
# One-time bootstrap of a uniquely-named disposable test DB:
createdb <disp> && createdb test_<disp>
POSTGRES_DB=test_<disp> manage.py migrate market 0026
POSTGRES_DB=test_<disp> manage.py migrate market 0027 --fake
POSTGRES_DB=test_<disp> manage.py migrate
# Run tests (one process per keepdb at a time):
POSTGRES_DB=<disp> manage.py test market.tests.test_market_state_persistence ... --keepdb --noinput
```

Never source `.env` (it contains space-bearing secret values); export only the
Postgres credentials. Only one test process may use a keepdb at a time.

## Rollback / recovery

- **Recovery default**: leave immutable evidence in place and deploy a separately
  approved forward correction. Never migrate a populated production database
  backward merely to disable the feature.
- **0034 reversal** removes only its prospective semantic triggers/functions;
  `migrate market 0033` retains every definition/snapshot and the M15 SQL mirrors.
- **0031 reversal** occurs only when targeting `market 0030`, not `0031`.
  Reversing through 0032 drops the market-state tables and destroys their evidence.
  That is a disposable-database test operation, not an authorized production
  recovery procedure. Existing irreversible downstream migrations may also block
  a historical target. Do not fake those reversals.
- **Snapshots/definitions** are immutable (ORM + DB triggers) and append-only;
  recovery is by computing a new snapshot at a later cutoff, never by editing.
- **Task recovery**: the durable task is idempotent — re-running the same
  (definition, instrument, cutoff, manifest) returns the existing snapshot; a
  crash mid-batch loses nothing and re-runs safely.

## Non-goals and Phase 5 boundary

Feature-only: no trade entry/exit/risk, no strategy, no directional conviction,
no A+ classification, no institutional-intent or hidden-liquidity claims, no
change to `technicals.py`, prompts, forecasts, lifecycle, sizing, costs or the
decision-enabled instrument set. Phase 5 will own named strategies; it consumes
these snapshots read-only and must not modify the definition/snapshot contract.

## Capacity

Run `estimate_m15_cost` for the current offline estimates (records/day, storage/
week and month). These are estimates from stated assumptions, not measurements,
and authorize nothing. Local synthetic performance numbers are in
[handoff.md](handoff.md); they are not production capacity claims.

## Correction verification and limitations

See [verification](verification/README.md) for measured SQL plans and storage.
The 200/3,501-observation probes include build, persisted replay/verification,
payload/manifest bytes, old-cutoff plans and PostgreSQL relation sizes. A separate
probe includes 201 event vintages and 200 macro observations. Process RSS includes
ingestion; isolated working set and WAL are unmeasured. None establishes capacity
for a production cadence or authorizes scheduling.

Historical migration fixtures that can run use separate temporary databases.
Older fixtures blocked by irreversible forecasts 0031 use a preflight executor
that raises the same error **before** undoing any M15 function. Their failures
remain visible. Parity tests contain no SQL installation or repair. A broad
failure count must be compared by identity and exception cause, not waved away as
"baseline"; the current differential is retained with the verification artifacts.

Acceptance remains explicitly superseded pending independent review. SQL enforces
the supported definition, canonical identities, candle eligibility/revisions,
basic prerequisites and research existence/availability. Full formula replay is
an application/integrity check, not a duplicate SQL implementation. The existing
superuser trigger-bypass caveat remains; no new production privilege is required.
