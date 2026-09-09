# Phase 4 — Deterministic Market-State Engine: Design Record

Status: **living design record** (mandatory preliminary artifact, authored before
implementation). Branch `phase4/deterministic-market-state`, based on
`origin/main` at `a3fbe6ce7fc08895c5696a2a25744f46e5d6e284`.

This document is the single authority for every implementation-defined term,
formula, threshold, availability rule and version in Phase 4. No vocabulary used
in code, snapshots, reports or the terminology registry may exist without a
definition here.

---

## 0. Product objective and non-goals

Build a **causal, deterministic, versioned, immutable and explainable** market-state
engine. For identical frozen inputs, a fixed definition version and a fixed
information cutoff, it must produce **byte-equivalent** canonical output.

It describes observable market facts and honestly-labelled proxies. It is
**feature-only**. In Phase 4 it MUST NOT, and this design does not define any of:

- recommend a trade; manufacture directional conviction; classify an "A+ setup";
- infer institutional intent; claim access to hidden liquidity or order books;
- select entry, stop, target, size or portfolio admission;
- alter Phase 3 lifecycle, target/control identity or experiment outcomes;
- feed existing model prompts or recommendation generation.

Explicit statement, repeated per §12 for each feature: **no Phase 4 feature has a
trade entry, exit or risk rule.** Phase 5 owns strategies; Phase 6 the trader
workflow; Phase 7 how AI consumes this evidence.

### Non-negotiable honesty rules

1. **Unavailable ≠ false/neutral/zero/ranging.** Every feature returns exactly one
   of `available` / `unavailable(reason_code)` / `not_applicable` /
   `experimental_deferred`.
2. **No future facts.** Only inputs whose availability is at or before the
   `information_cutoff` may influence a snapshot.
3. **Proxy language is mandatory** wherever hidden liquidity or order flow is not
   observed ("proxy", "candidate").
4. **Partial ≠ complete.** A partial current month/candle/session is exposed only
   as explicitly partial descriptive context, never as a completed classification.
5. **Decimal, not float.** All numerics are `Decimal` or exact integer units;
   never `NaN`, `inf`, locale-dependent or binary-float artifacts.

---

## 1. Canonical instruments and eligibility

All twelve canonical FX pairs are retained; eligibility is **unchanged** by Phase 4.

- Decision-enabled (unchanged): `EUR_USD`, `GBP_USD`, `EUR_GBP`, `USD_CAD`.
- Ingestion-only (unchanged): `USD_JPY`, `AUD_USD`, `USD_CHF`, `NZD_USD`,
  `EUR_JPY`, `GBP_JPY`, `AUD_JPY`, `AUD_CAD`.

Phase 4 market-state calculation MAY run for all twelve. It **does not** make any
ingestion-only pair decision-enabled: it touches no decision, sizing, portfolio,
or schedule-activation code. Decision-enablement remains a property of the
existing `Instrument` / recommendation path, untouched here.

---

## 2. Scope in this branch: adopted vs deferred

The brief is large. To keep design and implementation in lockstep (a PM acceptance
criterion), every concept is classified. **Deferred is a first-class, honest
state** and is surfaced as `experimental_deferred` at runtime, never as a silent
gap or a fabricated value.

| Group | Concept | State in this branch |
|---|---|---|
| Prereq | M15 live granularity + calendar | **adopted (implemented)** |
| Persistence | Definition + Snapshot immutable records, migration, triggers | **adopted** |
| 4.1 HTF | M/W/D/H4 trend, swings, ATR/true-range, volatility percentile, range/equilibrium, BOS, CHoCH, HH/HL & LH/LL, compression/expansion, persistence, distance-from-equilibrium | **adopted** |
| 4.1 HTF | macro regime, scheduled-event state | **adopted (point-in-time honest, §10)** |
| 4.2 Structure | confirmed swing H/L, prior-day/week/month H/L, session/overnight extremes, S/R zones (ATR-normalized), zone age/test-count, equal/clustered levels, consolidation, breakout/retest/failed-breakout, displacement supply/demand candidates, structural invalidation | **adopted** |
| 4.2 Structure | round-number interpretive state | **experimental_deferred** (distance computed; no interpretive/decision use — §4.2) |
| 4.3 Liquidity | wick-through+reclaim, acceptance close, clustered-liquidity proxy, prior-session extremes, sweep depth, reclaim distance/timing, displacement size, 3-candle imbalance proxy | **adopted** |
| 4.4 ORB | London & New York ORB (M15 open), range, breakout/retest/failure | **adopted** |
| 4.4 FVG | 3-candle FVG proxy (H4/H1/M15), fills, expiry, invalidation | **adopted** |
| 4.5 | SMC/ICT terminology registry | **adopted** |
| Ops | durable calculation/reconciliation tasks, integrity report, dry-run CLIs | **adopted** |

No concept in the brief is silently dropped: anything not in the "adopted" rows is
explicitly `experimental_deferred` with a reason code and appears in the
terminology registry (§9) with that state.

---

## 3. M15 prerequisite (first isolated slice)

The live candle contract today supports only `H1`, `H4`, `D`, `W`
(`market/quality.py:LIVE_GRANULARITIES`, `market/models.py:GRANULARITIES`). A
first-15-minute ORB cannot be reconstructed from H1, so M15 is a hard prerequisite
and is implemented first, in isolation.

**Granularity semantics.** M15 is an **absolute-duration** interval of
`timedelta(minutes=15)` on the New York FX trading week.

- Alignment: a timestamp opens an M15 candle iff, in `America/New_York` wall clock,
  its second and microsecond are zero and its minute is a multiple of 15
  (`{0,15,30,45}`). Because `America/New_York`'s UTC offset is always a whole
  number of hours, the NY 15-minute grid coincides with the UTC 15-minute grid;
  DST shifts the grid by a whole hour and never fractures a 15-minute boundary.
- Completion: `start + 15 minutes` (pure UTC step, like H1/H4). DST is a whole-hour
  wall-clock event and never merges or splits an M15 interval.
- Weekend closure and DST: identical convention to the existing live calendar
  (`market/quality._market_is_open`, `registered_successor`). No holiday modelling
  (consistent with the documented existing limitation in `market/freshness.py`).

**Non-activation (critical).** Adding M15 as a *supported* granularity must not
silently change the Phase 2 **canonical job inventory** or add an enabled schedule.
The existing `market/live_schedules.py` and `market/live_acquisition.LIVE_INTERVALS`
enumerate exactly one ingestion job per `(instrument, granularity)` over the live
granularities. To keep that inventory byte-identical:

- `market/quality.py` gains `SCHEDULED_LIVE_GRANULARITIES = frozenset({"H1","H4","D","W"})`
  — the Phase 2 canonical scheduled set (M15 **excluded**).
- `LIVE_GRANULARITIES` gains `M15` — the set the observation **ledger** and
  alignment/completion rules support.
- `market/live_acquisition.LIVE_INTERVALS` is pinned to
  `SCHEDULED_LIVE_GRANULARITIES` (byte-identical to today's value), so
  `live_schedules.py`, seeding and freshness defaults are unchanged and no `OANDA
  {code} M15` job is expected or created.
- A separate `SUPPORTED_LIVE_INTERVALS` (includes M15) gates the ingest/calc/ledger
  paths only (`operations.tasks.ingest_oanda` validation, provider request step).

**SQL parity.** Migration `0029` mirrors the Python alignment/completion rules in
two PL/pgSQL functions bound to `market/quality.py` by
`market/tests/test_observation_lineage.py`. A new forward migration
(`market/migrations/0031_m15_live_granularity`) `CREATE OR REPLACE`s both functions
to add the M15 arm, in lockstep with the Python change; the parity test is extended
to span M15 across a multi-year DST matrix. No M1 support is authorized or added.

**Existing negative tests.** Tests that assert "M15 is rejected as unsupported"
are updated to assert the *intent* (a genuinely unsupported granularity such as
`M1`/`M5` is rejected) rather than a now-false fact. No assertion is weakened; the
rejection behavior for truly-unsupported granularities is preserved and still
tested.

**Capacity / activation gating.** M15 acquisition and snapshot cost are *estimated*
offline (`estimate_m15_cost` dry-run, §11) before any activation is ever proposed.
This branch adds **no** enabled M15 schedule and makes **no** provider call.

---

## 4. Time and causality contract

Every computation is a pure function of `(frozen inputs, definition_version,
information_cutoff)` where `information_cutoff` is an explicit aware-UTC instant.

**Candle eligibility.** A candle is an eligible input only when all hold:

1. it is `complete`;
2. its registered interval has ended (`completion(start) <= information_cutoff`);
3. its recorded availability is `<= information_cutoff`
   (`CandleObservation.observed_at`, the first-accepted frozen observation);
4. its frozen content identity (`content_sha256`) is included in the snapshot's
   input manifest;
5. its provenance permits the claimed calculation (`observed` live, governed
   dataset, or fixture in tests — never `legacy_unknown` for point-in-time claims).

For live candles, the **first accepted frozen** `CandleObservation` (revision 1) is
authoritative for a snapshot; later provider revisions (`late_arrival`, `revision`,
`conflict`) create a *new* snapshot at a later cutoff and never rewrite an earlier
one. Governed historical data distinguishes genuine point-in-time evidence from
research-only data whose original availability is unknown; unknown availability is
never invented.

**Required causal properties (each has a test, §13):**

- *Prefix invariance*: appending future candles cannot change an earlier snapshot's
  output hash.
- *Cutoff invariance*: facts available after the cutoff are excluded; moving a
  candle's availability across the cutoff flips only eligibility, deterministically.
- *Confirmation delay*: a centered swing is `unavailable(insufficient_right_bars)`
  until all required right-hand candles complete and become available.
- *Calendar correctness* across DST, weekends, month ends, year ends, leap day.
- *No partial current candle*; *no "sixth observed candle" substitution* for a
  missing registered interval; *late arrivals* create a later snapshot only.

---

## 5. Immutable definition and snapshot contracts

Follows the repository's existing immutable-record convention: the `ImmutableModel`
base (`forecasts/models.py`), a unique `*_sha256` identity, `(key, version)`
uniqueness, `Decimal` columns, canonical-JSON hashing, and DB `BEFORE
UPDATE/DELETE/TRUNCATE` triggers installed by migration (patterns from
`forecasts/migrations/0002`, `0019`). New app-local module `market/state/` owns
this; it does **not** duplicate the candle ledger, calendar, scheduler, macro
store, lifecycle projection or evidence system.

### 5.1 `MarketStateDefinition` (immutable, versioned)

Binds: `key`, semantic `version`, canonical JSON `definition`, algorithm
identifiers, feature names, lookbacks/thresholds, calendar/session policy id, price
basis, rounding policy, missing-data policy, `definition_sha256` (SHA-256 of the
canonical JSON). Unique `(key, version)` and unique `definition_sha256`. Malformed
or unknown versions **fail closed** (rejected at read and at snapshot creation).

### 5.2 `MarketStateSnapshot` (immutable, append-only, idempotent)

Binds: `instrument`, `definition` (FK, hence version), `information_cutoff`,
`created_at`, exact candle identities + content hashes (the **input manifest**),
macro/event retrieval or vintage identities when used, `input_manifest_sha256`,
canonical `output_payload`, `output_sha256`, `data_quality_status`, and an
`idempotency_key`.

- **Idempotency key** =
  `identity_digest([definition_sha256, instrument, information_cutoff_iso,
  input_manifest_sha256])`. A duplicate concurrent calculation resolves to **one**
  canonical snapshot (unique constraint + get-or-create under advisory lock).
- **Canonical serialization**: `json.dumps(payload, sort_keys=True,
  separators=(",",":"), ensure_ascii=False)` with all numerics pre-formatted as
  `format(Decimal.quantize(QUANTUM, ROUND_HALF_EVEN), "f")` and integer units where
  exact. This matches `forecasts/targets.identity_digest`.
- **Determinism**: output hash is independent of query order, insertion order,
  process restart and Python/PostgreSQL rounding (parity tests, §13).
- **Immutability**: Python `ImmutableModel` + DB triggers; UPDATE/DELETE/TRUNCATE
  raise; no migration ever rewrites an existing snapshot; no synthetic snapshots
  are created for historical recommendations.

### 5.3 Rounding, units, precision

- Prices: `Decimal`, 6 dp, quantum `Decimal("0.000001")`, `ROUND_HALF_EVEN`
  (matches `market/technicals._price`).
- ATR-normalized and percentile values: `Decimal`, 6 dp, same rounding.
- Pip units: integer tenths-of-pip where exact; pip size is per-instrument
  (`0.0001` for non-JPY, `0.01` for JPY quote) and is recorded in the definition.
- Time: aware UTC ISO-8601 with explicit offset; NY-session local dates recorded
  alongside for session features.

---

## 6. Missingness and data-quality

Every feature result carries `{state, reason_code?, value?, units?, version}` where
`state ∈ {available, unavailable, not_applicable, experimental_deferred}`.

Stable reason codes (closed vocabulary, extended only via this document):
`insufficient_history`, `missing_registered_interval`, `incomplete_period`,
`evidence_after_cutoff`, `provenance_unavailable`, `spread_unavailable`,
`macro_vintage_unavailable`, `event_time_date_only`, `unsupported_granularity`,
`stale_source`, `contradictory_input`, `definition_mismatch`,
`insufficient_right_bars`, `no_established_structure`, `session_market_closed`,
`opening_interval_missing`, `atr_unavailable`.

Diagnostics are bounded and deterministic: stable IDs and reason codes only, never
raw arbitrary payloads or unbounded values. A snapshot's `data_quality_status`
aggregates feature states without collapsing `unavailable` into a value.

---

## 7. Feature definitions (adopted)

Each adopted feature is specified with the mandatory attributes: canonical name and
reason code · input granularity · price basis · lookback/min-obs · formula/thresholds
· tie-break/rounding · formation time · first-availability · cutoff · expiry ·
invalidation · missing-data behavior · output type/units/precision · definition
version · causal test · descriptive/experimental/deferred · **no Phase-4 entry/exit/
risk rule**. The registry (§9) persists a machine-readable copy.

Common conventions for §7–8:
- **Swing algorithm** (`swing-v1`): a *confirmed swing high* at index `i` requires
  `L` completed left bars and `R` completed right bars whose highs are all strictly
  less than bar `i`'s high; symmetric for lows on lows. Defaults `L=R=2`. Ties
  (equal highs within the window) do **not** confirm a swing (strict inequality),
  and are surfaced separately as *equal highs*. A swing is `unavailable
  (insufficient_right_bars)` until all `R` right bars complete and are available at
  the cutoff — this is the confirmation-delay rule.
- **Price basis**: swings, structure and zones use **midpoint** OHLC
  (`(bid+ask)/2`, matching `Candle.midpoint_*`) unless a feature explicitly needs
  bid/ask; spread-normalized qualifiers use observed bid/ask and are
  `unavailable(spread_unavailable)` when spread is absent (never assumed zero).
- **True range / ATR** (`atr-v1`): `TR = max(high-low, |high-prev_close|,
  |low-prev_close|)` on midpoint; `ATR_n` = simple mean of the last `n` completed
  TRs (`n=14` default). `unavailable(insufficient_history)` with `<n+1` bars;
  `unavailable(atr_unavailable)` propagates to normalized features.

### 7.1 Higher-timeframe trend and structure

- **Monthly context** (`month-context-v1`): aggregate **completed registered D**
  candles into a New York-session month (a month closes at the D close of its last
  session day). A completed monthly period is available only after month close and
  presence of all required registered D intervals; otherwise `unavailable
  (incomplete_period)`. A partial current month is exposed only as
  `partial_month_context` (explicitly partial), never a completed monthly trend. No
  ingested monthly candle is invented.
- **Trend classification** (`trend-v1`, per timeframe M/W/D/H4): from the last `k`
  confirmed swings (`k=2` pairs default), classify `uptrend` (higher-high **and**
  higher-low most recent pair), `downtrend` (lower-high and lower-low), else
  `range` (neither), else `unavailable(insufficient_history)`. Tie/mixed → `range`
  (a defined, available value distinct from `unavailable`).
- **HH/HL, LH/LL sequences** (`swing-sequence-v1`): the ordered classification of
  consecutive confirmed swings; output is a bounded, versioned list of
  `{type, level, formed_at, available_at}`.
- **Break of structure (BOS)** (`bos-v1`): requires a *previously established*
  swing extreme of the prevailing structure (`no_established_structure` reason if
  absent) and a **completed close** (named basis = midpoint close) beyond that
  extreme in the trend direction. Wick-only penetration is **not** BOS and is
  recorded distinctly. Every new high is *not* automatically a BOS.
- **Change of character (CHoCH)** (`choch-v1`): requires an established directional
  structure and a completed close beyond the most recent opposing confirmed swing
  (i.e. the first counter-trend structural break). An ordinary pullback that does
  not close beyond the opposing swing is **not** CHoCH.
- **Range / equilibrium** (`equilibrium-v1`): range = [most recent confirmed
  swing-low, swing-high] bounding the current consolidation; `midpoint =
  (low+high)/2`; *distance from equilibrium* = `(price - midpoint)` in price and in
  ATR units. `unavailable(insufficient_history)` without both bounds.
- **Trend persistence** (`persistence-v1`): count of consecutive completed bars on
  the same side of the equilibrium midpoint over a bounded window (`w=20`),
  reported as an integer with the window recorded.
- **Volatility** (`volatility-v1`): current `ATR_14`; **rolling volatility
  percentile** = rank of current `ATR_14` within the prior `P` eligible `ATR_14`
  observations (`P=100`, min 20), percentile by the *fraction of strictly-smaller
  prior values* (deterministic tie method: strict-less-than), population size and
  window recorded. Percentiles use **only prior** eligible observations.
- **Compression / expansion** (`vol-regime-v1`): `compression` when current
  `ATR_14` percentile `< 20`; `expansion` when `> 80`; else `normal`. Thresholds
  are versioned; `unavailable` when the percentile is unavailable.

### 7.2 Support, resistance and structure zones

- **Confirmed swing highs/lows** (`swing-v1`, above), midpoint basis.
- **Prior-period extremes** (`prior-extremes-v1`): prior-day / prior-week /
  prior-**completed**-month high and low from completed registered candles;
  overnight/session highs and lows from the session windows in §8. Each carries its
  source candle identities and `formed_at`/`available_at`.
- **S/R zones** (`zone-v1`): cluster confirmed swing levels whose pairwise distance
  `<= c * ATR_14` (`c=0.25` default, single-linkage) into a zone
  `[min_level, max_level]`; **zone id** = `identity_digest([definition_version,
  instrument, timeframe, round(min_level), round(max_level)])` — **never** a DB row
  id or calculation order. **Zone age** = number of completed intervals since the
  earliest member swing formed (units: intervals of the zone's timeframe).
  **Distinct test count** = number of *separate approaches*: a new test is counted
  only after price has left the zone by `>= c*ATR_14` and returned; consecutive
  candles resting inside the zone count as **one** test. Overlapping zones merge by
  single-linkage before id assignment (deterministic). Expiry: `unavailable` after
  `age > A` intervals (`A=500`) or after structural invalidation. Invalidation: a
  completed close beyond the zone by `>= c*ATR_14` on the zone timeframe.
- **Consolidation boundaries / breakout / retest / failed-breakout**
  (`consolidation-v1`): consolidation = a bounded window whose high-low range
  `<= r*ATR_14` (`r=1.5`); breakout = completed close beyond a boundary; retest =
  subsequent touch of the broken boundary from the far side without a completed
  close back inside; failed breakout = completed close back inside within `f`
  intervals (`f=3`). Wick vs close are distinct.
- **Displacement supply/demand candidates** (`sd-candidate-v1`): a *candidate*
  supply (demand) zone is the origin candle body of a displacement leg (a completed
  bar whose body `>= d*ATR_14`, `d=1.5`, followed by continuation). Named
  explicitly as a **proxy candidate**; no claim of resting orders.
- **Structural invalidation facts** (`invalidation-v1`): the completed-close
  condition that voids a zone/level, recorded as a fact with its triggering candle.

### 7.3 Liquidity and price-action proxies

- **Wick-through-and-reclaim (sweep proxy)** (`sweep-v1`): a bar whose wick
  penetrates a referenced level/zone by `>= s*ATR_14` (`s=0.1`) but whose body does
  **not** close beyond it, followed within `t` intervals (`t=3`) by a completed
  close back on the origin side (reclaim). Records: referenced level/zone id, event
  direction, first-breach time, confirming-close (reclaim) time, availability time,
  ATR-normalized **sweep depth**, **reclaim distance**, **reclaim timing**
  (intervals), source candle identities, expiry, invalidation.
- **Acceptance close** (`acceptance-v1`): a completed close through a level that is
  **not** reclaimed within `t` — distinct from a sweep. Wick breach and close
  acceptance are always mutually distinguishable.
- **Clustered-liquidity proxy** (`equal-levels-v1`): equal/clustered highs or lows
  (within `e*ATR_14`, `e=0.1`) as a *visible-liquidity proxy* (honest label).
- **Displacement size** (`displacement-v1`): ATR-normalized body size of a
  displacement bar, direction, source candle.
- **3-candle imbalance proxy** — see 7.4 FVG.

### 7.4 ORB and FVG

- **Session policy** (`session-v1`, versioned): London ORB `08:00–08:15`
  `Europe/London`; New York FX ORB `08:00–08:15` `America/New_York`; overnight
  context = previous NY `17:00` session open through London `08:00`. Boundaries are
  converted to UTC via IANA rules; each ORB records local session date, timezone,
  UTC start/end, DST offset, market-open flag, and the required M15 candle identity.
  A missing opening M15 candle yields `unavailable(opening_interval_missing)` — the
  **next** M15 candle is never substituted.
- **ORB outputs** (`orb-v1`): `ORH`/`ORL` from the completed first M15 candle; range
  size; range normalized by `ATR_14` and by spread (spread-normalized is
  `unavailable(spread_unavailable)` if spread absent); completed close outside the
  range (breakout, with time); wick-only breach (distinct); reclaim; retest;
  failure/invalidation; event-risk and spread state at the ORB's availability time.
  An ORB does not exist until the first M15 interval completes and is available.
- **FVG (3-candle imbalance proxy)** (`fvg-v1`), granularities H4/H1/M15 (no
  cross-granularity mixing): three consecutive registered completed candles;
  **bullish** iff candle-1 high `<` candle-3 low; **bearish** iff candle-1 low `>`
  candle-3 high; equality = **no gap** (strict inequality). Requires: explicit price
  basis (midpoint for gap geometry; bid/ask only for spread-normalized qualifier);
  middle-candle direction rule (must displace in the gap direction); middle-candle
  displacement threshold (`body >= g*ATR_14`, `g=1.0`); minimum raw gap (`> 0`);
  ATR-normalized gap; pip-normalized gap; spread-normalized gap when spread
  available (else `unavailable(spread_unavailable)`, price facts retained); created
  at candle-3 completion/availability; deterministic zone boundaries `[gap_low,
  gap_high]`; **partial-fill percentage** = fraction of the gap traversed by
  subsequent completed candles; **full fill** when price closes through the far
  boundary; expiry after `A_fvg` intervals; invalidation on full fill or on a
  deterministic internal-swing break. Named a three-candle imbalance/FVG **proxy**,
  not proof of institutional imbalance.

---

## 8. Session and calendar policy (versioned)

`session-v1`:

| Session | Local window | TZ | Notes |
|---|---|---|---|
| London ORB | 08:00–08:15 | Europe/London | first M15 |
| New York FX ORB | 08:00–08:15 | America/New_York | first M15 |
| Overnight context | prev 17:00 → 08:00 | NY open → London open | crosses UTC date |

All conversions use IANA zones (`zoneinfo`). Weekend closure and DST follow the
existing NY FX week (`market/quality`). Repeated and nonexistent local clock times
(spring-forward / fall-back) resolve via `zoneinfo` fold rules and are covered by
calendar tests (§13). Holidays are not modelled (documented existing limitation);
a session whose opening candle is absent is `unavailable`, never substituted.

---

## 9. Terminology registry (SMC/ICT)

`market/state/terminology.py` defines a **versioned** registry. For each adopted
term: canonical name, plain-language description, observable inputs, formula,
timeframe, formation time, availability time, expiry, invalidation, causal test id,
limitations, prohibited interpretation, and — because Phase 4 is feature-only —
`trade_entry: "not defined in Phase 4"`, `trade_exit: "not defined in Phase 4"`,
`trade_risk: "not defined in Phase 4"`. No strategy rule is invented to populate
those. Terms not adopted are recorded with state `experimental_deferred`.

**Fail-closed vocabulary.** Snapshots and reports reject any term not in the
registry: unknown/free-form labels (e.g. "A+ setup", "strong level", "clear draw on
liquidity", "smart money entered", "institutional order block", "session bias",
"obvious support", "high-probability FVG") are **never** accepted as authoritative
facts. Every persisted label is a registry key at a pinned version.

---

## 10. Scheduled events, macro regime and spread (point-in-time honest)

Consumes only existing attested research records and their true vintages
(`research/models.py`, `research/services.capture_pair_evidence(instrument,
now=cutoff)`); no parallel macro store is created.

- **Scheduled-event state** (`event-state-v1`): events mapped to base/quote
  currencies via the explicit policy `{"USD":"US","CAD":"CA","GBP":"GB","EUR":"EU"}`
  (extended per instrument as needed; recorded in the definition). Distinguishes
  exact-time vs date-only (`EconomicEvent.time_precision`), scheduled / cancelled /
  postponed / released, stale/revised vintages (`first_observed_at <= cutoff`). A
  date-only event is **never** rendered as an exact intraday risk window
  (`event_time_date_only`). **Severity**: no trustworthy impact field exists on
  `EconomicEvent`; severity is therefore taken from a versioned event-type→class
  policy or marked `unavailable` — "high impact" is never invented.
- **Macro regime** (`macro-regime-v1`): deterministic transforms of point-in-time
  `MacroObservation`s selected with `available_at <= cutoff`, `vintage_at <=
  cutoff`, `retrieval.fetched_at <= cutoff`, honoring `revision_sequence` (latest
  vintage known by the cutoff only — a later revision is never used in an earlier
  snapshot) and `availability_precision` (PROVIDER genuine vs RETRIEVAL
  first-seen). Records series/vintage identities, availability precision,
  normalization, lookback, regime thresholds, currency→pair composition, and
  missing-side behavior. Unknown macro state is `unavailable`, **not** neutral.
- **Spread** (`spread-v1`): observed bid/ask at the applicable candle/event cutoff;
  spread = `ask - bid` at close, units recorded, ATR-normalized where used. If no
  historically attested spread exists at the requested time,
  `unavailable(spread_unavailable)` — never backfilled from a current or future
  quote.

---

## 11. Tasks, integrity report, dry-run CLIs

- **Durable tasks** (`operations/tasks.execute_task` dispatch + a seeded but
  **disabled** `ScheduledJob` only if operational registration is later approved):
  deterministic idempotency keys, persistent leases, bounded retries, latest-only
  where appropriate, crash-safe, bounded runtime/batch, explicit failure reason
  codes (`operations/diagnostics.classify_failure`). One failed instrument does not
  block others; global definition/integrity failure fails closed. No model/provider
  budget; no automatic production registration; no silent schedule repair.
- **Integrity report** (`market/state/integrity.py`, read-only, bounded JSON,
  nonzero exit on violation): checks the full brief list (unknown/mismatched
  definition versions and hashes, malformed payload/schema, output/input-manifest
  hash mismatch, missing/contradictory candle identities, input-after-cutoff,
  incomplete-candle usage, missing registered intervals, silent revision
  substitution, duplicate snapshot identity, multiple outputs per idempotency key,
  noncausal swing availability, BOS/CHoCH without prerequisites, malformed/
  overlapping/impossible zone identity or chronology, invalid ORB session
  boundaries, ORB without exact opening M15, FVG on nonconsecutive candles, invalid
  fill chronology, macro vintage after cutoff, date-only event treated as exact,
  unavailable spread treated as zero, noncanonical terminology, unsupported
  granularity, unbounded/unsafe diagnostics, task/schedule identity drift,
  accidental consumption by recommendation/execution paths). Availability,
  freshness, coverage and semantic integrity are reported as separate axes.
- **Dry-run CLIs**: `compute one snapshot`, `preview a batch`, `validate
  definitions`, `validate snapshot integrity`, `estimate M15 acquisition + snapshot
  storage cost`, `report coverage` — all read-only / disposable, none mutate
  production, none call the provider, none register schedules.

---

## 12. Non-goals restated per feature

For **every** feature above and in the registry: it defines **no** trade entry,
**no** trade exit and **no** trade risk in Phase 4. It does not feed prompts,
probability generation, sizing, execution, costs or portfolio limits, and does not
alter Phase 3 target/control identity, Brier scoring, experiment gates, lifecycle,
paper execution, the four decision-enabled or eight ingestion-only instruments, or
existing schedule activation. `market/technicals.calculate_technicals` and the
`TechnicalSnapshot` it feeds are **not** changed (fingerprinted before/after, §13).

---

## 13. Test strategy (adversarial, independent oracles)

Expected values are derived independently (hand-calculated fixtures / independent
arithmetic and calendar oracles), never imported from the implementation under
test. Families: **determinism** (order/restart/concurrency/canonical-hash/
Python↔SQL rounding parity), **causality** (future-append, cutoff boundary, late
arrival, revision, partial candle, missing interval, swing right-hand boundary,
event/macro revision leakage, spread-unavailable-at-trigger), **calendar** (NY & London
DST, offset-change weeks, Friday close / Sunday reopen, month/year boundaries, leap
day, missing session candle, overnight UTC-date crossing, repeated/nonexistent
local times), **structural** (asymmetric fixtures for confirmed/unconfirmed swings,
equal levels, HH/HL & LH/LL, range vs trend, wick vs close, BOS vs none, CHoCH vs
pullback, zone merge/non-merge, repeated-candle single test, breakout/retest/failed,
sweep depth & reclaim timing, compression→expansion, displacement),
**ORB/FVG** (both sessions, both directions, wick-only, close-outside, equality
boundaries, missing opening M15, wrong middle direction, insufficient displacement,
min-gap equality, partial/full fill, expiry, invalidation, nonconsecutive candles,
spread missing/excessive, ATR unavailable, internal swing unconfirmed at cutoff),
**missingness** (available / insufficient / missing-interval / after-cutoff /
unsupported-provenance / malformed / valid-neutral-distinct-from-unavailable per
family), and **metamorphic/property** (price translation & positive scaling
preserve normalized classifications; instrument pip precision invariance; insertion
reversal invariance; future-suffix invariance; deterministic ids independent of DB
PKs).

**Regression protection**: fingerprint `calculate_technicals` output, the v4
target/control identity, prompt/output schema, Brier/experiment gates, lifecycle,
paper execution, sizing/cost, portfolio capacity, the 4 decision-enabled and 8
ingestion-only instruments, and the Phase 2 canonical schedule inventory, before
implementation and compare after.

**Baseline comparison** uses exact failing-test *identities* and causes, never
aggregate counts. The documented `market0027` fake test-bootstrap accommodation and
the runtime-superuser trigger-bypass limitation remain as-is and are **not**
broadened.

---

## 14. Performance and capacity (to be measured, not claimed)

Measured locally on representative synthetic data and reported in
`docs/phase4/runbook.md`: snapshot computation time per instrument/timeframe, query
count, peak RSS, payload/index size, batch duration, snapshots/day, M15 records/day,
storage growth/week & month, estimated WAL growth, scheduler load. Calculations use
explicit bounded windows and indexed access paths (no unbounded full-history scans).
Unmeasured quantities are labelled unmeasured; unit tests are never presented as
production capacity.

---

## 15. Migration plan

Forward migrations only; merged migrations are never edited. New migrations
preserve every existing row and historical hash; create no synthetic market-state
snapshots and no strategy/recommendation/lifecycle/experiment records; preserve
nullable legacy relationships honestly; install constraints/triggers atomically and
roll back atomically on failure; reject contradictory prospective fixtures in
preflight; and avoid operations requiring PostgreSQL superuser. Tested on fresh
install, populated upgrade from exact Phase 3 main, byte-equivalent preservation,
contradictory-data rejection, raw-SQL constraint-bypass attempts, and migration-
executor isolation, without concealing the known migration-suite limitations.

---

## 16.5 Corrections from independent review (slice 9)

The independent tester (no P0) surfaced contract gaps, corrected here:

- **Bounded windows (was P1).** `compute` now applies explicit per-granularity
  lookbacks (`LOOKBACKS`, pinned in the definition body) to every eligible-candle
  fetch and to the input manifest, so a snapshot never scans or embeds unbounded
  history. Definition version bumped to `0.7.0`.
- **Zone identity (was P2).** `structure._zone_id` now binds
  `[version, instrument, timeframe, low, high]` as §7.2 requires; the liquidity
  level id uses the same helper.
- **Consolidation (was P2).** `consolidation_state` now emits `breakout`,
  `retest` and `failed` over a `failed_bars` tail window (the parameter is live).
- **FVG (P3).** Adds an `expired` flag (unfilled after `FVG_EXPIRY_BARS`).
  **Deterministic internal-swing-break invalidation remains a documented
  deferral** — full-fill and expiry invalidation are implemented; internal-swing
  break is not yet, and is not claimed by the code.
- **Liquidity (P3).** Sweep/acceptance are tested only against bars at or after
  the reference level's formation.
- **Integrity (P3).** Adds `malformed_payload_schema` and `unsupported_granularity`
  checks; the docstring now states honestly that it covers the core semantic-
  integrity conditions verifiable from persisted state, with the remainder
  structurally precluded by immutability/uniqueness or by determinism.

## 16. Commit plan

1. M15 contract + calendar support (+ SQL parity migration).
2. Definition/snapshot persistence + migration + triggers.
3. Higher-timeframe context.
4. Structure and zones.
5. Liquidity proxies.
6. ORB/FVG.
7. Macro/event/spread context.
8. Tasks, integrity reporting, docs.
9. Corrections from independent review.

Each commit is behaviorally coherent and non-empty. Nothing is pushed, deployed,
activated, or run against production; no provider or AWS/OANDA call is made.
