# Phase 4 — Engineer Handoff

Handoff for independent testing. Treat every claim below as a claim to verify,
not a fact.

## Branch / base / status

- Branch: `phase4/deterministic-market-state`
- HEAD: `ede9407f02dc060d53d5e556f06da9429ec110da`
- Base / merge-base with `main`: `a3fbe6ce7fc08895c5696a2a25744f46e5d6e284`
- `origin/main`: `a3fbe6ce7fc08895c5696a2a25744f46e5d6e284` (unchanged; verified by fetch)
- Branch is **not pushed** (`git ls-remote --heads origin phase4/…` is empty)
- Working tree: **clean**
- Nothing pushed, deployed, activated, scheduled, or run against production; no
  provider/AWS/OANDA/Anthropic call was made. Migration 0027 used only the
  documented fake-bootstrap accommodation in the disposable test DB.

## Commits (base..HEAD)

```
1afc8e0 docs(phase4): mandatory preliminary design record
f6a0b7d feat(market): add M15 live granularity contract and calendar (slice 1)
b7cf2aa feat(market): immutable market-state definition/snapshot persistence (slice 2)
d3e7b00 feat(market): higher-timeframe descriptive context (slice 3)
9a88fbe feat(market): support/resistance and structure context (slice 4)
23f19d5 feat(market): liquidity and price-action proxies (slice 5)
66b50ee feat(market): ORB and FVG features (slice 6)
d62f67b feat(market): macro/event/spread point-in-time context (slice 7)
ede9407 feat(market): durable task, integrity report and dry-run CLIs (slice 8)
```

36 files changed, +4683 / -22. New package `market/state/` (14 modules), 9 test
modules, 2 migrations (`0031`, `0032`), 3 management commands.

## Requirement → code → test traceability

| Requirement | Code | Test |
|---|---|---|
| M15 granularity, alignment, completion, weekend/DST | `market/quality.py`, `live_acquisition.py`, `services.py` | `test_m15_live_granularity`, `test_observation_lineage` (parity matrix incl. M15) |
| M15 non-activation (job inventory unchanged) | `quality.SCHEDULED_LIVE_GRANULARITIES`, `live_acquisition.LIVE_INTERVALS` pinned | `test_m15_live_granularity::M15ConstantsTests`, `test_schedule_integrity` |
| M15 SQL/Python parity | migration `0031` CREATE OR REPLACE | `test_observation_lineage::test_interval_alignment_matches_python_across_dst`, `…completion…` |
| Immutable versioned definition | `models.MarketStateDefinition`, `state/definitions.py` | `test_market_state_persistence::DefinitionRegistryTests` |
| Immutable idempotent snapshot | `models.MarketStateSnapshot`, `state/snapshots.py` | `…::SnapshotPersistenceTests` |
| Canonical serialization (no float/NaN) | `state/canonical.py` | `…::CanonicalSerializationTests` |
| Causal manifest (ended/available/latest-revision) | `state/manifest.py` | `…::ManifestCausalityTests` |
| Dual-layer immutability (ORM + DB triggers) | migration `0032` | `…::SnapshotPersistenceTests::test_raw_sql_update_delete_truncate_are_blocked` |
| Swings + confirmation delay | `features.confirmed_swings` | `test_market_state_features::SwingTests`, `CausalConfirmationDelayTests` |
| Trend / ATR / volatility percentile / BOS / CHoCH | `features.py` | `…::TrendTests/AtrTests/VolatilityPercentileTests/BreakOfStructureTests/ChangeOfCharacterTests` |
| S/R zones (deterministic id, age, test count) | `structure.py` | `test_market_state_structure::ZoneTests` |
| Equal levels / displacement / consolidation / prior extremes | `structure.py`, `compute.py` | `…::EqualLevelTests/DisplacementTests/ConsolidationTests/PriorExtremeTests` |
| Sweep vs acceptance proxies | `liquidity.py` | `test_market_state_liquidity` |
| FVG 3-candle proxy | `fvg.py` | `test_market_state_orb_fvg::FvgGeometryTests` |
| ORB (first M15, missing = unavailable) | `sessions.py`, `orb.py` | `…::SessionConversionTests/OpeningRangeTests/OrbEndToEndTests` |
| Macro/event/spread point-in-time | `context.py` | `test_market_state_context` |
| Durable task, integrity, dry-run CLIs | `state/tasks.py`, `integrity.py`, 3 commands | `test_market_state_ops` |

## Formulas and assumptions

All formulas, thresholds and versions are in [design.md](design.md) §7–§10.
Key assumptions worth adversarial attention:

- Features operate on **midpoint** bars (`(bid+ask)/2` per OHLC component).
- Confirmation delay is inherited from manifest eligibility, not re-implemented:
  a candle is eligible only when complete, its interval has ended
  (`live_candle_completion(start) <= cutoff`) and `observed_at <= cutoff`; the
  latest revision known by the cutoff is used. The DB enforces
  `observed_at >= interval_end`, so an eligible complete candle always satisfies
  `interval_end <= cutoff`.
- Zone identity = `sha256` of the versioned rounded `[low, high]` only.
- Macro regime is currently point-in-time policy-rate level + direction; other
  indicators deferred. Event severity is always `unavailable` (no trustworthy
  field). FVG spread-normalization is `unavailable` in this release (price facts
  retained) — a documented follow-up.

## Migration preservation

- Forward-only. `0031` (AlterField choices + CREATE OR REPLACE of two SQL
  mirrors) and `0032` (two new tables + immutability/no-truncate triggers) create
  no synthetic snapshots and rewrite no existing rows. Both are reversible
  (0031 restores exact pre-M15 SQL; 0032 drops its triggers/tables/functions).
- `0032`'s no-truncate trigger reuses migration 0028's test-flush escape hatch
  (`current_database() LIKE 'test\_%'` + auth_permission AccessExclusiveLock) so
  Django's flush works while ordinary TRUNCATE still fails.
- Fresh install verified via the disposable-DB bootstrap (0026 → 0027 --fake →
  migrate applies 0031/0032 cleanly). `makemigrations --check` reports no changes.
- **Not exhaustively verified this session**: a byte-equivalent populated upgrade
  from exact Phase-3 main, and raw-SQL constraint-bypass beyond the snapshot
  triggers. Flagged for the tester.

## Test results (disposable test DB, market0027 accommodation, --keepdb)

- Focused market-state suite (9 modules): **112 tests, 0 failures/errors**
  (`test_m15_live_granularity`, `test_market_state_{persistence,features,
  structure,liquidity,orb_fvg,context,ops}`).
- Cross-module regression incl. `test_observation_lineage`,
  `test_live_observations`, `test_schedule_integrity`, `operations.tests`:
  **all green** (largest single run 193 tests, 0 failures).
- `make check` equivalent (`ruff check .`, `ruff format --check .`,
  `manage.py check`, `makemigrations --check --dry-run`, `compileall`): **clean**.

## Baseline comparison

- The touched non-state modules (`observation_lineage`, `live_observations`,
  `schedule_integrity`) pass green on a fresh disposable DB. Early apparent
  "baseline errors" were traced to **concurrent test runs polluting one keepdb**,
  not real failures; on a clean single-process DB they pass.
- The **broad** `market` suite is known-not-green: it retains the pre-existing
  Gate8 migration-reversal failing identities (documented limitation). This
  branch does not touch those migrations. **An exhaustive full-`market`-suite
  identity diff (branch vs exact base) was not run this session** — flagged as a
  residual for the tester to confirm no new failing identity is introduced.

## Performance (local synthetic — not production capacity)

Measured locally on the disposable DB, single instrument. `compute_market_state`
uses bounded windows and a stable query count independent of history length;
`estimate_m15_cost` gives offline acquisition/storage estimates. See
`estimate_m15_cost` output for capacity estimates; all such numbers are estimates
from stated assumptions, not measurements. (A precise compute-latency figure was
being measured at handoff time and can be regenerated with the probe in the
scratchpad; the store path, not compute, dominates that probe.)

## Retained artifacts / cleanup

- Disposable databases: `p4_disp_mktstate` / `test_p4_disp_mktstate` (local
  Postgres). Drop with the scratchpad helper `p4_testdb.sh drop`. No production
  DB, backup, or restored data was used.
- Scratchpad (session-local): test logs and the `p4_testdb.sh` helper.
- No provider fixtures were fetched; all tests use synthetic candles and
  hand-built research fixtures.

## Explicit statement

Nothing was pushed, deployed, activated, scheduled, or run against production;
no live provider/AWS/OANDA/Anthropic call was made; `origin/main` is unchanged at
`a3fbe6c` and the branch is unpushed. `technicals.py`, prompts, forecasts,
lifecycle, sizing/cost, and the decision-enabled instrument set are untouched.
