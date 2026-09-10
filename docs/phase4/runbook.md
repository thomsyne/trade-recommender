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

The current descriptor definition is `market-state-descriptor@0.12.0`
(`compute.DESCRIPTOR_DEFINITION`); the version is bumped whenever the feature set,
a threshold or a lookback changes, so every snapshot binds the exact algorithm
versions. Bounded per-granularity lookbacks (`compute.LOOKBACKS`) are pinned in
the definition body so no computation scans unbounded history.

## Dry-run / read-only commands

All use the disposable test-DB or a read-only connection; none is scheduled.

The new mandatory surfaces are:

```bash
python manage.py preview_market_state_batch \
  EUR_USD@2026-01-05T10:00:00Z GBP_USD@2026-01-05T11:00:00Z \
  --granularities H1 H4
python manage.py validate_market_state_definition /tmp/definition-envelope.json
python manage.py market_state_coverage --instrument EUR_USD GBP_USD \
  --since 2026-01-05T08:00:00Z --cutoff 2026-01-05T12:00:00Z --granularities H1
python manage.py market_state_integrity --after-id 0
```

Batch: at most eight distinct selections and five distinct granularities; explicit
aware cutoffs, stable sorting and escaped JSON. Validation: at most 64 KiB, exact
envelope `{key, version, definition, definition_sha256}`, no database access or
registration; supported descriptor identity/body/hash must all match. Export an
envelope from reviewed source, not by invoking the registration command.

Coverage: explicit window at most seven elapsed days; default exit zero for a
successfully produced report, even with missing inputs/snapshots. Add
`--require-complete` to exit one on any selected row without complete registered
inputs and a fresh current-version snapshot. Empty registered ranges do not pass
strict coverage. Feature availability remains independent of input coverage;
unknown macro/events do not count as neutral. This report does not attest semantic
integrity. See design §20.1 for the exact freshness/range policy.

Integrity retains the 100-snapshot page/cursor and also scans at most 500 rows
each of relevant schedules and occurrences. Static codes flag any Phase4
schedule, malformed task identity/parameters, unexpected M15 activation, source
consumers and scan overflow; any violation exits one. Existing Phase2 H1/H4/D/W
schedules are not changed. Source scanning cannot certify external/dynamic
consumers. Run normal Phase2 schedule integrity separately for its full inventory.

Migration 0037 is prospective and row-preserving. On a disposable database only,
upgrade to 0037, reverse to 0036 and reapply 0037 to test a roundtrip. Reversal
retains 0.12.0 rows as unsupported historical evidence; it does not make older
code able to compute them. Do not reverse through 0036 with recorded observations:
its original refusal remains in force. No production migration is authorized by
these instructions. Acceptance remains superseded pending final PM verification.

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
- **0036 reversal** to `market 0035` preserves populated legacy rows but refuses
  if any observation has non-NULL `recorded_at`. Do not clear recording facts or
  disable the refusal to force a downgrade. Pair a permitted legacy-only downgrade
  with compatible code; older snapshots are not re-certified under another version.
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

See [verification](verification/README.md) for current checks and historical provenance.
The following performance measurements predate 0036 and are not current benchmarks.
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

## Final-boundary verification (0036)

Design §19 and the [current evidence](verification/README.md) govern 0.11.0.
Use the retained disposable-only script for focused, concurrent, affected,
research, broad, populated migration and historical→M15 parity checks. Baseline
comparisons must match exact test commands, identities, causes and multiplicities.

New candle evidence receives DB-owned `recorded_at` under the shared series lock;
NULL on legacy evidence means unknown, not zero or a fabricated historical time.
Cutoff eligibility uses both source observation and recording availability.
Late arrival is retained, not rejected or retroactively inserted into old snapshots.
Persisted cutoffs must not exceed database time after lock acquisition. Durable
future-cutoff work fails with `future_market_state_cutoff`; retry no earlier than
the requested time, without silently moving its cutoff. READ COMMITTED is required.
For multi-series transactions acquire the full sorted series set before writing.

Policy/series semantic fields are immutable from registration, including before
their first reference; register a new semantic identity rather than editing one.
Editorial/acquisition settings remain editable. No scheduling or activation follows
from passing tests. Acceptance remains superseded pending independent review.

## Historical eight-finding correction verification (0035)

Design §18 governs the 0.10.0 changes. New evidence lives in
[`verification/eight`](verification/eight/README.md); earlier measurements above
remain historical. Acceptance is superseded pending a fresh independent review.

Use only a newly initialized private UTF-8 PostgreSQL cluster, a unique Unix
socket/port and `env -i` with explicit `POSTGRES_HOST`, `POSTGRES_PORT`,
`POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_CONN_MAX_AGE=0`, PATH and HOME. Never
source `.env.local` or let an unset variable select a default database. The
documented bootstrap accommodation remains: normally migrate market 0026,
fake only the data-dependent 0027, then normally migrate the remaining graph.

Run `test_phase4_eight_findings` along with the existing Phase4/M15 modules.
Run the exact historical sequence separately:
`test_zzzzzzzz_live_observation_migration` then
`test_observation_lineage.SqlPythonParityTests`, without setup SQL repair.
Run the broader market/operations/forecasts suites on equivalently bootstrapped
exact-base and final databases and compare failure identities and causes.

For disposable migration verification, populate with the exact starting
implementation, fingerprint every application table, then migrate
`0034 → 0035 → 0034 → 0035`, comparing rows after each step. Reversing only 0035
removes its prospective guards and reinstalls 0034's frozen definition validators;
it does not rewrite/delete snapshots or research. This downgrade must be paired
with compatible code and does not certify historical 0.10.0 rows under 0.9.0.
It is not authorization for an operational rollback, nor for reversing 0032's
state tables. Never edit 0034 or use a runtime SQL repair as a migration test.

Consumed policy/series semantic edits now reject once referenced. Editorial
quality notes remain editable and do not change historical 0.10.0 replay.
Instrument code/currency contradictions reject prospectively. Investigate
historical contradictions read-only; do not repair immutable evidence in place.
