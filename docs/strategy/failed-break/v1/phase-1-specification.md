# Frozen Phase 1 Strategy and Data Specification

## Top-Down Failed-Break Continuation Trading Assistant v1

**Status:** Strategy and data contract frozen for review  
**Source baseline:** `thomsyne/trade-recommender` GitHub `main` at `354a5e75c0a69ab22fce88b81ca56028ea7fe897`  
**Predecessor:** Phase 0 Repository and Data Audit, accepted by the owner  
**Scope:** Specification only. No migrations, implementation, dataset download, signal count or return calculation is authorized by this document.

Any change to a frozen rule below creates a new strategy, data, execution, cost or portfolio-policy identity. Numeric evaluation thresholds are intentionally excluded until the return-blind signal-count procedure in §18 is complete.

## 1. Registered hypothesis

> In an established daily trend, an H1 failed break and reclaim of a pre-existing higher-timeframe level may provide a continuation entry toward the nearest objective opposing higher-timeframe level.

This is a research hypothesis, not a claim of profitability.

## 2. Registered identities

### 2.1 Strategy books

The following books are independent registered research identities with separate accounting:

1. `failed-break-weekly-extreme-v1`
2. `failed-break-daily-swing-v1`
3. `failed-break-breakout-flip-v1`
4. `failed-break-any-level-deduplicated-v1`

The three family books may each evaluate a physical event when it carries their attribution. Their returns must never be added as if they were independent opportunities. The deduplicated book creates at most one trade from one physical `SetupEvent`, irrespective of attribution count.

### 2.2 Supporting identities

- Market data: `oanda-ba-ny17-friday-v1`
- Shared physical-event detector: `failed-break-detector-v1`
- Historical event policy: `event-policy-none-v1`
- Primary execution: `execution-h1-stop-first-v1`
- Paired execution refinement: `execution-m1-windowed-v1`
- Primary cost view: `cost-observed-spread-only-v1`
- Cost sensitivity: `cost-commission-financing-grid-v1`
- Historical portfolio: `portfolio-common-fraction-025-100-050-v1`
- Signal count: `failed-break-signal-count-v1`
- Evaluation policy: `failed-break-evaluation-policy-v1`, numeric addendum pending signal counts

## 3. Universe and timeframes

### 3.1 Instruments

The registered universe is fixed:

1. `EUR_USD`
2. `GBP_USD`
3. `EUR_GBP`
4. `USD_CAD`
5. `USD_JPY`
6. `AUD_USD`

All six must be represented explicitly in source and in the dataset manifest. Missing instruments fail the dataset contract; the universe cannot shrink opportunistically.

### 3.2 Granularities

- `W`: completed context and levels.
- `D`: bias, ATR, swings, levels, structure invalidation and time counting.
- `H4`: stored/displayed context only; it cannot affect eligibility, entry, exit, sizing or evaluation.
- `H1`: setup detection, confirmation, primary execution and primary exit evidence.
- `M1`: separately identified paired execution refinement only.
- `S5`: deferred and absent from every v1 identity.

## 4. Canonical market-data contract

### 4.1 OANDA request contract

For `W`, `D`, `H4`, `H1` and approved M1 windows:

- provider: OANDA v20;
- price: bid and ask (`BA`);
- smoothing: false;
- completed candles only;
- stored timestamps: UTC interval starts;
- alignment timezone: `America/New_York`;
- daily alignment: 17:00;
- weekly alignment: Friday;
- volume: OANDA activity/tick volume, not centralized traded volume.

A weekly candle begins at Friday 17:00 New York and becomes available only when the following aligned Friday 17:00 boundary has passed and OANDA marks it complete. Daily candles use the analogous 17:00-to-17:00 boundary. IANA timezone conversion governs DST.

### 4.2 Price representation

One canonical candle stores bid and ask OHLC together. Midpoint is derived component-wise:

```text
mid_open  = (bid_open  + ask_open)  / 2
mid_high  = (bid_high  + ask_high)  / 2
mid_low   = (bid_low   + ask_low)   / 2
mid_close = (bid_close + ask_close) / 2
```

Midpoint drives indicators, swings, levels, sweeps and confirmations. Side-aware bid/ask drives execution and returns. A spread-only movement cannot create a midpoint sweep.

### 4.3 Dataset identity

Every immutable dataset version records:

- provider and environment;
- all six instruments;
- included granularities;
- requested and actual time ranges;
- BA/unsmoothed/alignment parameters;
- retrieval manifests and request statuses;
- schema/parser versions;
- row count and earliest/latest timestamp per series;
- per-series content hashes;
- duplicate, gap, completeness, volume and bid/ask quality summaries;
- creation time and parent dataset, if any.

The active dataset is referenced by immutable ID/hash in every analysis, level, setup and simulation.

### 4.4 Same-key conflicts and corrections

The canonical key remains `(instrument, granularity, timestamp)` within one dataset version.

For incoming data:

1. No existing key: validate and append.
2. Existing key with identical normalized BA OHLC, volume and completeness: idempotent no-op with lineage retained.
3. Existing key with any differing normalized value: append an immutable conflict record containing existing/incoming hashes, source manifests, differing fields and detection time; quarantine the incoming row/batch.

The active candle is never silently ignored, overwritten or retrospectively mutated. A correction requires an explicitly created child dataset version with its own manifest and hashes. Existing analyses continue referencing their original dataset version.

### 4.5 Quality gate

Before analysis, verify:

- all required history and warm-up candles exist;
- candles are complete, UTC, ordered and unique;
- timestamp phase matches registered alignment and DST semantics;
- OHLC is valid and bid does not exceed ask;
- gaps are explained by a registered FX session calendar or explicitly quarantined;
- ATR/EMA/swing warm-up is sufficient;
- instrument precision and pip location are known;
- no unresolved conflict affects the as-of window.

Failure produces `DATA_INCOMPLETE` for an H1 analysis or `CANCELLED_DATA_QUALITY` for an existing setup. Values are never imputed.

## 5. Point-in-time and as-of rules

All deterministic domain functions accept `as_of` and dataset identity.

A candle is usable only when:

1. its aligned interval has ended at or before `as_of`;
2. OANDA marked it complete;
3. it belongs to the registered dataset version; and
4. its ingestion manifest completed successfully.

Historical replay treats a valid market candle as available at its aligned close, while preserving that it was retrieved later. No macro/event data is used under `event-policy-none-v1`.

Additional rules:

- EMA/ATR at time `t` include only candles completed by `t`.
- A five-candle pivot centered at `t` is unavailable until `t+2` completes.
- A level activates at the close that satisfies its activation rule, never at its source candle timestamp.
- An entry level is pre-existing only if `activated_at <= sweep_h1_interval_start`; a level activated at the sweep candle's close cannot explain that sweep.
- An H1 sweep is visible only at sweep-candle completion.
- Confirmation is visible only at confirmation-candle completion.
- The primary theoretical entry is the next H1 interval open after confirmation.
- Dataset generation, spread-threshold generation, signal counting, P&L and evaluation each record separate cutoffs and hashes.

Historical H1 execution is resolved only after the entry H1 candle has completed and entered the frozen dataset. The resolver records the open's original effective timestamp separately from its later resolution timestamp. At return-blind signal count, a restricted projection may read only that candle's bid/ask open and timestamp; high, low, close, volume and every later field remain inaccessible. This execution-evidence exception never makes an incomplete candle available to strategy logic.

At a timestamp where H1, D or W intervals complete together, process in this order:

1. validate and admit all completed candles for the frozen dataset;
2. resolve stop/target evidence occurring inside the just-completed H1 candle for already-open trades;
3. Apply D/W level expiry, invalidation, supersession and activation globally, then update daily bias and structure. Updated level and structure status may affect pending setups, target inventory and open trades; recalculated EMA entry bias applies only to detection of new sweeps.
4. Apply pending-setup invalidation, confirmation or expiry using frozen sweep-time bias evidence without re-evaluating EMA eligibility. Same-timestamp level or provisional-structure invalidation takes precedence over confirmation.
5. evaluate newly confirmed entries at the new H1 open;
6. detect new sweeps using the updated bias but only levels that pre-date the sweep interval;
7. apply scheduled structure/time exits at the new H1 open if no earlier stop/target controls that boundary.

Stable IDs and rule priority resolve remaining ties; database insertion order never does.

Daily and weekly level-lifecycle and structure updates affect every relevant level, pending setup, target and open trade. Recalculated EMA entry bias governs only the detection of new sweeps. An existing `TRIGGER_PENDING` setup continues to use the bias snapshot captured at sweep completion.

## 6. Daily bias and structure

### 6.1 Indicators

Use midpoint daily closes.

Bullish EMA condition:

```text
EMA50[t] > EMA200[t]
EMA50[t] > EMA50[t-20]
```

Bearish EMA condition reverses both inequalities. EMA uses the standard recursive multiplier `2/(n+1)` and is seeded with the arithmetic mean of the first `n` available closes. No entry bias exists until both EMA50 and EMA200 are fully initialized and a 20-session EMA50 slope comparison exists.

Daily ATR(14) uses Wilder true range and Wilder recursive smoothing, seeded by the arithmetic mean of the first 14 true ranges. H1 ATR(14) uses the same rule on H1 midpoint candles.

### 6.2 Confirmed swings

A pivot high centered at daily candle `t` requires strict midpoint-high inequalities:

```text
high[t] > high[t-2]
high[t] > high[t-1]
high[t] > high[t+1]
high[t] > high[t+2]
```

A pivot low reverses them. Equal values fail. Confirmation occurs only after `t+2` completes.

### 6.3 Structure

Bullish structure requires:

- latest confirmed pivot high > preceding confirmed pivot high;
- latest confirmed pivot low > preceding confirmed pivot low;
- latest completed daily close > latest confirmed pivot low.

Bearish structure reverses the comparisons. Insufficient pivots produce neutral structure.

### 6.4 Entry bias

- Long: bullish EMA condition and bullish structure.
- Short: bearish EMA condition and bearish structure.
- Otherwise: abstain.

The supporting swing reference is frozen when a setup confirms.

### 6.5 Post-entry structure invalidation

- Long exits after a completed daily close strictly below the frozen supporting daily swing low.
- Short exits after a completed daily close strictly above the frozen supporting daily swing high.

Execution occurs at the next primary execution-adapter open. Equality does not invalidate.

## 7. Level and zone contract

### 7.1 Level roles

Levels are generated independently of current entry bias and carry one directional role:

- `SUPPORT`
- `RESISTANCE`

The complete active inventory is available for targets even when current bias prevents entry against that level.

### 7.2 Zone width

At activation:

```text
total_width = 0.15 × Daily_ATR14_at_activation
zone_lower  = central_price - total_width / 2
zone_upper  = central_price + total_width / 2
```

Round outward to instrument precision so the stored zone is never narrower than the formula. Width and boundaries never change during the level instance. Spread never resizes a zone.

### 7.3 Previous weekly extremes

During each aligned week:

- prior completed weekly low activates as support;
- prior completed weekly high activates as resistance;
- each expires when the current weekly candle completes.

After a completed daily close strictly above the prior weekly high's central price, create a new long flip-support instance centered on that price. After a close strictly below the prior weekly low's central price, create the corresponding short flip-resistance. Retire the original directional instance as `SUPERSEDED_BY_FLIP`; the flip receives new activation ATR/bounds and retains source lineage. Flip expiry remains the current weekly completion.

### 7.4 Confirmed daily swings

- A newly confirmed pivot low activates as support.
- A newly confirmed pivot high activates as resistance.
- A newer same-type confirmed pivot supersedes the older same-role instance.

A daily close strictly through the source swing's central price creates an opposite-role flip instance centered at that price with newly frozen activation ATR/bounds and retires the original role as `SUPERSEDED_BY_FLIP`. Confirmation of a newer same-type swing supersedes every still-active role instance derived from the older same-type swing.

### 7.5 Twenty-session breakout flips

For completed daily candle `t`:

```text
prior_high = max(mid_high[t-20:t-1])
prior_low  = min(mid_low[t-20:t-1])
```

- Close strictly above `prior_high`: activate long flip-support centered at `prior_high`.
- Close strictly below `prior_low`: activate short flip-resistance centered at `prior_low`.

The level expires after 20 subsequently completed daily sessions or invalidates earlier on a strict daily close through its distal boundary.

### 7.6 Universal lifecycle

Level states are append-only events:

```text
ACTIVE → INVALIDATED
ACTIVE → EXPIRED
ACTIVE → SUPERSEDED
ACTIVE → SUPERSEDED_BY_FLIP
```

Universal invalidation remains: a completed daily close strictly below a support zone's lower boundary invalidates support; a completed daily close strictly above a resistance zone's upper boundary invalidates resistance. Equality does not invalidate. Invalidation, expiry and supersession are evaluated independently for every role instance. A flip is always a new level instance.

When one close both crosses the source central price and distal zone boundary, `SUPERSEDED_BY_FLIP` and creation of the opposite-role instance take precedence over `INVALIDATED`. At a shared weekly boundary, expiry is applied before any new current-week instance is activated.

Setup availability is an orthogonal append-only flag:

```text
SETUP_AVAILABLE → SETUP_CONSUMED
```

Attribution consumes the level for originating future setups in that strategy identity, but does **not** end its price-level lifecycle. A consumed level remains active for target inventory until invalidated, expired or superseded.

## 8. Proximity observations

Proximity is notification-only and does not create or confirm setups.

- `APPROACHING`: current midpoint is outside but within `0.50 × current Daily ATR14` of a zone.
- `TOUCHED`: current midpoint lies within the inclusive zone bounds.

`LevelProximityEvent` is deduplicated by `(level_id, proximity_state, observation_bucket, data_version)`. Frequent prices may create these records but cannot mutate levels or setup state.

## 9. Physical setup detection and attribution

### 9.1 Long sweep/reclaim

For each active support level:

1. Full strategy books require bullish daily entry bias at sweep completion.
2. Previous completed H1 midpoint close is at or above the zone lower boundary.
3. Sweep H1 midpoint low is strictly below the zone lower boundary.
4. Sweep H1 midpoint close is at or above the zone lower boundary.

Short rules reverse side, role and inequality.

### 9.2 Event deduplication

All qualifying levels on the same `(instrument, direction, sweep_h1_timestamp, detector_version, data_version)` create exactly one physical `SetupEvent` and one attribution per qualifying level. The four registered books consume this shared physical-event stream; they do not run independent detectors.

- Duplicate scans are idempotent.
- Multiple levels from one family remain separate attributions but produce at most one family-book setup for that physical event.
- The combined book produces at most one setup regardless of family count.
- Attributed levels become setup-consumed for the shared detector when the `SetupEvent` is created but remain eligible target inventory while price-active.
- A consumed level cannot participate in a later physical event.
- A fresh overlapping level can create a later event independently.
- Daily entry-bias evidence and its provisional supporting swing are captured and frozen when the completed sweep creates the `SetupEvent`.
- During the three-H1 confirmation window, EMA eligibility is not recalculated. An EMA-only change does not cancel a valid pending setup and does not retroactively create a `SetupEvent` for a sweep that was ineligible when it completed.
- A long pending setup invalidates after a completed daily close strictly below its provisional supporting swing low. A short pending setup invalidates after a completed daily close strictly above its provisional supporting swing high.
- Same-timestamp structural invalidation precedes confirmation. At confirmation, freeze the latest still-valid supporting swing for post-entry structural invalidation.

### 9.3 Confirmation

The sweep candle is not a confirmation candle. Within the following three completed H1 candles:

- long confirms on the first midpoint close strictly above the sweep midpoint high;
- short confirms on the first midpoint close strictly below the sweep midpoint low.

A second sweep does not reset the threshold or expiry. No confirmation by the third following H1 completion produces `EXPIRED` with reason `CONFIRMATION_WINDOW`.

## 10. Analysis and state-transition contract

### 10.1 H1 analysis outcomes

Each completed H1 evaluation creates one compact immutable analysis record per instrument/strategy/data identity:

| Outcome | Meaning |
|---|---|
| `NO_SETUP` | Data valid; no active level or sweep transition |
| `LEVEL_ACTIVE` | Data valid; levels exist but no new physical sweep |
| `CANDIDATE_CREATED` | One physical setup was created with one or more attributions |
| `DATA_INCOMPLETE` | Required evidence unavailable or conflicted; no inference |

Unique key: `(instrument, completed_h1_timestamp, detector_version, data_version)`.

Outcome precedence is `DATA_INCOMPLETE`, `CANDIDATE_CREATED`, `LEVEL_ACTIVE`, then `NO_SETUP`. Confirmation/expiry of an existing setup is recorded in its transition ledger; absent a new candidate, the hourly outcome is `LEVEL_ACTIVE` when any price-active or pending item exists.

### 10.2 Setup transitions

`WATCHLIST`, `APPROACHING` and `TOUCHED` are dashboard projections over a setup-available level and its `LevelProximityEvent` records. No physical `SetupEvent` exists before a completed sweep, so those labels cannot be mistaken for strategy state or historical eligibility.

| From | To | Exact guard |
|---|---|---|
| — | `TRIGGER_PENDING` | Completed sweep/reclaim creates a deduplicated physical event |
| `TRIGGER_PENDING` | `CONFIRMED` | First of next three completed H1 closes crosses frozen confirmation threshold |
| `TRIGGER_PENDING` | `EXPIRED` | Third following H1 completes without confirmation; reason `CONFIRMATION_WINDOW` |
| `TRIGGER_PENDING` | `INVALIDATED` | Every attributed level becomes price-inactive, or completed D close crosses the provisional supporting swing, before/simultaneous with confirmation |
| `TRIGGER_PENDING` | `CANCELLED_DATA_QUALITY` | Required evidence becomes unavailable/conflicted |
| `CONFIRMED` | `MISSED_FILL` | Expected next H1 interval is a registered market closure, no defensible H1 open exists, or opening side is at/beyond the adverse stop |
| `CONFIRMED` | `BLOCKED_SESSION` | Next H1 entry timestamp is outside the registered session union |
| `CONFIRMED` | `BLOCKED_SPREAD` | Either registered spread ceiling fails at entry |
| `CONFIRMED` | `NO_TARGET` | No active opposing target zone qualifies at entry |
| `CONFIRMED` | `INSUFFICIENT_REWARD` | Frozen target reward is less than 1.5 initial R at entry |
| `CONFIRMED` | `CANCELLED_DATA_QUALITY` | Entry evidence, precision, ATR or conversion is unavailable/conflicted |
| `CONFIRMED` | `ENTRY_PENDING` | Defensible side-aware H1 fill and all pre-entry deterministic restrictions pass; entry/stop/target are frozen |

`event-policy-none-v1` creates no `BLOCKED_EVENT` transitions. A future event policy is a separate identity.

At the expected entry boundary, terminal guard priority is: unexplained data failure, session, registered closure/no quote, spread, adverse-stop gap, no target, insufficient reward, then `ENTRY_PENDING`. This priority controls one canonical reason when several facts coexist.

### 10.3 Trade-simulation transitions

| From | To | Exact guard |
|---|---|---|
| `ENTRY_PENDING` | `OPEN` | Side-aware entry is established and portfolio allocation is positive after unit rounding |
| `ENTRY_PENDING` | `BLOCKED_CAPACITY` | Common-fraction allocation or unit rounding produces zero units |
| `OPEN` | `STOPPED` | Stop trigger occurs first under the execution adapter |
| `OPEN` | `TARGETED` | Target trigger occurs first under the execution adapter |
| `OPEN` | `DAILY_STRUCTURE_INVALIDATION` | Registered daily close invalidates frozen supporting structure before another exit |
| `OPEN` | `TIME_EXIT` | First adapter open after ten completed post-entry daily candles, before another exit |
| `OPEN` | `UNRESOLVED_DATA` | Required exit evidence is unavailable/conflicted; no fabricated result |

Every transition is append-only and records prior/new state, effective timestamp, decision timestamp, reason, evidence IDs/hash, strategy/data/execution identities and job ID. A current-state cache may exist only if reconstructable from transitions.

## 11. Session and spread restrictions

### 11.1 Session

The entry timestamp must fall in the union of:

- `08:00–17:00 Europe/London`
- `08:00–17:00 America/New_York`

Start is inclusive; end is exclusive. IANA timezones govern DST. Do not delay an out-of-session confirmation; record `BLOCKED_SESSION`.

### 11.2 Spread policy

Both conditions must hold at the primary H1 entry open:

```text
opening_spread <= pair_absolute_ceiling
opening_spread / H1_ATR14 <= 0.10
```

The pair absolute ceiling is generated without returns as the nearest pipette at or above the empirical 99th percentile of completed H1 opening spreads during eligible session windows in development 2010–2018. All six values and the input distribution hash are frozen before signal counting. No outcome-conditioned adjustment is permitted.

### 11.3 Historical event policy

`event-policy-none-v1` performs no event lookup, exclusion, relabeling or post-hoc subgroup deletion. Existing event records may be audited or shown separately but cannot enter historical strategy features. Any `event-blackout-v1` requires proven point-in-time schedules and is a separate strategy/data identity, initially prospective-only.

## 12. Entry, stop and target

### 12.1 Primary entry

`execution-h1-stop-first-v1` enters at the next completed-data H1 interval open after confirmation:

- long entry: ask open;
- short entry: bid open.

The H1 open is explicitly an approximation, not a historical executable quote.

### 12.2 Stop

At entry:

```text
buffer = max(opening bid/ask spread, 0.10 × completed H1 ATR14)
long_stop  = sweep_mid_low  - buffer
short_stop = sweep_mid_high + buffer
```

Round long stops downward and short stops upward to instrument precision.

Per-unit quote-currency initial risk is `entry_ask - long_stop` for a long and `short_stop - entry_bid` for a short. Convert that amount to CAD with the latest valid point-in-time quote-to-CAD conversion at entry. Missing conversion is `CANCELLED_DATA_QUALITY`; no current-rate substitution is allowed.

### 12.3 Independent target inventory

Targets use every active opposing `RESISTANCE`/`SUPPORT` level, independent of entry bias and entry-family attribution.

- Long: among zones whose lower boundary is strictly above entry ask, choose the smallest lower boundary; target that lower boundary.
- Short: among zones whose upper boundary is strictly below entry bid, choose the largest upper boundary; target that upper boundary.

Ties use: weekly before daily swing before breakout flip, then earliest activation, then stable level ID. The target level ID and price freeze at entry and never trail or mutate.

If no target exists, use `NO_TARGET`. If target distance is below `1.5 × initial risk`, use `INSUFFICIENT_REWARD`.

## 13. Exit contract

No breakeven move, trailing stop, scaling out, pyramiding or averaging down exists.

Exit candidates:

1. stop;
2. target;
3. daily structure invalidation;
4. ten-session time exit.

The daily candle containing entry counts only when it completes after entry and is therefore the first completed post-entry daily candle. Exit at the next side-aware H1 open after the tenth such completion.

At a common H1 boundary, adverse stop-gap handling precedes target and scheduled exits. A scheduled daily/time exit uses the next H1 bid open for a long and ask open for a short.

## 14. Execution adapters

### 14.1 `execution-h1-stop-first-v1` — primary and complete

- Entry uses next H1 ask/bid open.
- Long stop: bid low touches stop; short stop: ask high touches stop.
- Long target: bid high touches target; short target: ask low touches target.
- Stop and target touched in the same H1 candle: stop first.
- Stop gap: fill at the worse of stop and adverse H1 open.
- Target fill: frozen target, with no favorable gap improvement.
- Entry H1 open already at/beyond the adverse stop: `MISSED_FILL`.
- Daily/time exits use next H1 side-aware open.
- Missing/conflicted H1 evidence produces no result.

This adapter alone defines the primary historical result and must be fully reported even when M1 refinement is unavailable.

### 14.2 `execution-m1-windowed-v1` — paired refinement

This adapter cannot alter signals, levels, confirmation, stop, target, allocation or primary results.

Retrieve complete BA M1 windows only for:

1. the H1 entry interval; and
2. any primary H1 interval in which stop and target both touched or in which exact trigger ordering affects the exit classification.

Window completeness requires a successful manifest spanning the full market-open H1 interval, completed M1 candles, no duplicates/conflicts and no unexplained missing market-active minute. If incomplete, label the paired refinement unavailable; do not exclude or alter the primary trade.

Within a complete window:

- use first qualifying M1 side-aware open/touch;
- apply the same gap and side rules as primary;
- if stop and target occur in one M1 candle, stop first;
- record whether M1 agrees with or changes the primary H1 outcome/timestamp/price.

M1 retrieval happens only after signal-count and numeric evaluation-policy freeze, because windows may expose post-entry prices. S5 remains deferred.

## 15. Historical portfolio allocation

Identity: `portfolio-common-fraction-025-100-050-v1`.

At each simultaneous entry timestamp:

- mark current book equity side-aware at that H1 open, including realized and open P&L;
- each setup's risk budget is `0.25% × current book equity`, and its unrounded requested units are that budget divided by CAD initial risk per unit;
- already open allocated risk consumes aggregate and same-direction currency capacity;
- aggregate planned open risk cap: 1% of current equity;
- each gross same-currency/same-direction bucket cap: 0.5%;
- opposing exposures are not netted;
- find the largest common allocation fraction `f ∈ [0,1]` such that scaling every simultaneous request by `f` satisfies all remaining constraints;
- calculate `f` as `min(1, aggregate_remaining / simultaneous_requested_total, bucket_remaining / simultaneous_requested_in_bucket for every used bucket)`; skip zero denominators and clamp negative remaining capacity to zero;
- round units down to venue granularity and recompute planned risk;
- do not redistribute residual capacity after rounding;
- zero units produce `BLOCKED_CAPACITY`;
- pair order, confidence and outcomes never affect allocation.

A long `BASE_QUOTE` setup charges its full planned risk to `long BASE` and `short QUOTE`; a short charges `short BASE` and `long QUOTE`. Risk is not split between the two buckets.

All four books maintain independent C$10,000 research equity and accounting. Prospective owner-selection policy remains unchanged and is not part of this historical identity.

## 16. Cost identities

### 16.1 Primary view

`cost-observed-spread-only-v1` includes:

- side-aware OANDA bid/ask entry and exit;
- adverse gap and ambiguity rules from the selected execution adapter;
- separate historical commission is unknown and excluded, not assumed to be zero;
- historical financing is unavailable and excluded;
- timestamp-appropriate CAD conversion where available.

The primary result is **observed-spread-adjusted; separate commission unknown and excluded; pre-financing; not exact net broker P&L**.

### 16.2 Sensitivity grid

`cost-commission-financing-grid-v1` always retains observed spread and evaluates the Cartesian grid:

- round-turn commission: `0.0`, `0.5`, `1.0` pip per position;
- annual financing cash-flow rate: `-6%`, `-3%`, `0%`, `+3%`, `+6%` of position notional.

Negative financing is a cost; positive is a credit. These are bounds, not reconstructed OANDA history and not a base-case assertion.
The `0.0` commission cell is one sensitivity scenario, not evidence that the account historically charged no commission.

Rollover sensitivity uses 17:00 New York, one day Monday/Tuesday/Thursday/Friday and three days Wednesday; holidays are unavailable and disclosed. Quote-currency financing is converted to CAD at the latest valid point-in-time conversion at each modeled rollover; unavailable conversion makes that scenario unresolved. Spread is never added twice.

For units `u`, rollover-side midpoint `p`, signed annual scenario rate `r` and rollover multiplier `d`, sensitivity cash flow in quote currency is `abs(u) × p × r × d / 365`. Round-turn commission in quote currency is `abs(u) × pip_size × commission_pips`; it is charged once per resolved position and then converted point-in-time to CAD.

Report every grid cell separately as a scenario-adjusted estimate, not a reconstructed historical net return, plus the proportion of trades/holding days exposed to rollover. Never select a preferred cell based on profitability.

## 17. Comparators

All comparator identities and deterministic random seeds freeze before returns.

### 17.1 `comparator-bias-level-touch-v1`

- Same universe, daily bias, levels, session/spread/data restrictions, target inventory, exits, costs and portfolio policy as full strategy.
- For support, trigger is the first completed H1 whose midpoint low is at/below zone upper after the previous close was strictly above zone upper. For resistance, trigger is the first H1 whose midpoint high is at/above zone lower after the previous close was strictly below zone lower.
- No failed-break or confirmation is required.
- Entry is next H1 open.
- Long stop is touch midpoint low minus the registered buffer; short stop is touch midpoint high plus that buffer.
- One event per level instance; physical overlap is deduplicated identically.

This tests whether failed-break confirmation improves a simpler biased level touch.

### 17.2 `comparator-failed-break-no-bias-v1`

- Same failed-break/reclaim, confirmation, execution, target, risk and cost rules.
- Removes EMA and daily-structure entry-bias requirements only.
- Direction derives from level role: support permits long, resistance permits short.
- Post-entry structure invalidation is unavailable; exits are stop, target or ten-session time exit.

This tests whether the daily trend filter adds value.

### 17.3 `comparator-matched-random-h1-v1`

For every full-strategy entry-eligible physical event, create 100 deterministic random-timing replicates without using returns:

- same pair, direction, partition, calendar year, eligible session label and daily regime label;
- candidate timestamps have complete pre-entry evidence and are not actual setup timestamps;
- deterministic index is SHA-256 of `matched-random-h1-v1|setup_stable_key|replicate_000..099` modulo the sorted candidate pool;
- collisions advance cyclically to the next unused candidate;
- entry uses next H1 side-aware open;
- stop distance in price and target R multiple are copied from the source setup’s entry-time geometry and translated around random entry;
- maximum hold, execution, costs and portfolio policy match the full strategy.

This is a timing null, not a tradable level strategy. Report the full 100-replicate distribution and full-strategy percentile, not a cherry-picked replicate.

### 17.4 Full comparator

`failed-break-any-level-deduplicated-v1` is the primary combined strategy. Family books are attribution analyses and multiplicity-controlled challengers, not additional portfolio returns.

## 18. Return-blind signal-count procedure

Identity: `failed-break-signal-count-v1`.

### Stage S0 — data and spread freeze

Using development 2010–2018 only and no forward trade outcomes:

1. verify dataset coverage/quality and warm-up;
2. calculate pair/session opening-spread distributions;
3. derive and freeze pair absolute 99th-percentile ceilings;
4. publish row counts, missingness and distribution hashes;
5. freeze the completed strategy/data/execution/cost/portfolio manifests.

### Stage S1 — signal counting

Run detection only through theoretical entry eligibility. The diagnostic process must not request, serialize, aggregate or display any candle or return after each theoretical entry timestamp.

The restricted entry-evidence projection may read exactly the entry H1 timestamp, bid open and ask open. The entry candle may be read only after completion and admission to the frozen dataset, while preserving the open's original effective timestamp. The open may determine only the side-aware theoretical entry, entry-time restrictions and reward-to-risk eligibility; it must reveal nothing that happened after that open.

Allowed outputs:

- active/invalidated/expired/superseded/consumed levels;
- proximity, sweep, attribution and confirmation counts;
- block/missed pre-entry reasons;
- entry-eligible setup counts;
- counts by pair, year, direction, level family, session and strategy identity;
- physical-event overlap and attribution multiplicity;
- issuance-date/week and shared-currency cluster counts;
- simultaneous-request and conservative maximum-horizon concurrency counts;
- data-quality and spread coverage;
- proposed M1 window counts/bytes without downloading post-entry windows.

Forbidden outputs or accesses:

- entry-candle bid or ask high, low or close, and entry-candle volume;
- any later price row;
- stop, target, time-exit or post-entry structure outcome;
- P&L, R outcome, win rate, payoff, drawdown or favourable/adverse excursion;
- comparator returns;
- M1 post-entry data;
- execution-resolution functions or imports;
- parameter changes based on later prices.

Enforcement requirements:

- a signal-count code path with no import of return/execution-resolution functions;
- query/data-reader cutoff at each theoretical entry timestamp, with only timestamp/bid-open/ask-open projected from the completed entry candle;
- output schema that has no return fields;
- immutable command/configuration hash and audit record;
- report hash reviewed before evaluation-policy registration.

The signal-count reader must fail closed if any caller requests a forbidden entry-candle field or any price row after the theoretical entry timestamp.

### Stage S2 — evaluation-policy freeze

After S1 and before any P&L calculation:

1. use only counts, cluster structure, missingness and pre-entry geometry to simulate attainable power;
2. freeze numeric minimum raw setups, resolved trades, effective clusters, observation period, coverage, ambiguous-execution tolerance, replay fidelity and minimum practical effect;
3. freeze confidence level, block/bootstrap method, block-length rule and multiplicity correction;
4. publish `failed-break-evaluation-policy-v1` with hash/effective time;
5. prohibit policy changes after any return is exposed; changes require v2 and another untouched evaluation allocation.

## 19. Chronological partitions

Partition assignment uses the New York calendar year of setup confirmation. All pairs share boundaries.

| Partition | Confirmation years | Permitted use |
|---|---|---|
| Development | 2010–2018 | Data diagnostics, signal counts, spread ceilings, then development returns after policy freeze |
| Walk-forward validation | 2019–2022 | Sequential annual validation; no in-place parameter changes |
| Untouched evaluation | 2023–2025 | Open only after development/validation gates under frozen identities |
| Prospective shadow | 2026 onward | Live completed-candle monitoring, no orders |

Rules:

- Pre-2010 candles may be used only as warm-up if available and declared; otherwise 2010 decisions begin only after complete EMA200/ATR/swing warm-up.
- Purge any confirmation whose latest possible ten-session H1 exit is not strictly before the next partition boundary; calculate this from the aligned daily calendar rather than a fixed UTC-day subtraction.
- Validation is evaluated in annual chronological folds. No parameter is refit from fold returns.
- Any strategy change after 2019–2022 results creates a new identity and leaves 2023–2025 untouched for the old identity only; it cannot silently reuse that evaluation for the new version.
- Prospective shadow records the exact effective strategy/data versions and must be replayable from stored evidence.

## 20. Persistence contract

Compact historical H1 analysis rows belong in PostgreSQL. Material records retain detailed evidence:

- strategy/data/execution/cost/portfolio manifests;
- levels and lifecycle events;
- setup events and attributions;
- transitions;
- eligibility evaluations;
- allocations and units;
- fills, exits and simulations;
- data conflicts/incidents;
- evaluation policies/assessments;
- prospective replay/shadow mismatches;
- governed Claude explanations after deterministic verification.

Conceptual entities and idempotency keys, to be mapped onto existing Django ownership before migrations are proposed:

| Concept | Canonical identity/key |
|---|---|
| `StrategyDefinition` / `StrategyVersion` / `StrategyParameterManifest` | immutable name/version/content hash |
| `DatasetVersion` | immutable manifest hash and optional parent |
| `MarketCandle` | instrument + granularity + timestamp + dataset version; BA stored together |
| `CandleConflict` | existing candle + incoming payload hash + ingestion run |
| `MacroEventSnapshot` | retained existing provider identity; unread by historical v1 |
| `Level` | family + source candle + role + activation + detector/data version |
| `LevelLifecycleEvent` | level + from/to + effective timestamp + evidence hash |
| `LevelProximityEvent` | level + proximity state + observation bucket + data version |
| `AnalysisRun` | instrument + completed H1 timestamp + detector/data version |
| `SetupEvent` | instrument + direction + sweep H1 timestamp + detector/data version |
| `SetupLevelAttribution` | setup event + level |
| `SetupTransition` | setup + from/to + effective timestamp + evidence hash |
| `EntryEligibilityEvaluation` | setup + book + execution + event/spread policy versions |
| `TradeSimulation` | setup + book + execution + portfolio version |
| `PortfolioAllocation` | book + simultaneous timestamp + setup + portfolio version |
| `TradeOutcome` | trade simulation + terminal transition |
| `CostAssessment` | trade simulation + cost identity/scenario |
| `ClaudeExplanation` | analysis/setup + prompt/model + input snapshot hash |
| `JobRun` / `ResearchRun` | job type + configuration hash + dataset cutoff |
| `DataQualityIncident` | dataset + series/key + incident type + evidence hash |

Smallest anticipated persistence delta is: extend source choices for six instruments and W, add immutable strategy/dataset manifests and candle conflicts, add material level/setup/attribution/transition/simulation records, and reuse existing candle, job, forecast-evaluation, paper-trade and dashboard structures where their contracts fit. Exact model changes remain an implementation-design deliverable, not authorization here.

Large JSON is acceptable until measured table/index/WAL/backup size demonstrates a problem. No artifact-storage service is introduced speculatively. If measured payload growth requires artifacts, that is a separately approved infrastructure/data-contract version with content hashes and PostgreSQL lineage.

## 21. Evaluation-policy schema, numeric values pending S2

The strategy policy must contain:

- strategy/data/execution/cost/portfolio/comparator hashes;
- primary estimands: observed-spread-adjusted expectancy in R, before unknown commission and financing, per physical setup; and the corresponding daily portfolio return;
- minimum raw, entry-eligible, resolved and paired counts;
- minimum effective date/week/shared-factor clusters;
- minimum observation period and data-quality coverage;
- paired comparator rules;
- confidence level and multiplicity control across four strategy identities;
- stationary/block-bootstrap method over daily portfolio returns;
- cluster-aware interval/randomization method for paired observed-spread-adjusted R differences;
- minimum practically important effect;
- cost-grid robustness requirement;
- maximum-drawdown distribution relative to planned target risk;
- pair/family/year/direction/session/currency concentration limits;
- ambiguous H1 rate and M1 disagreement reporting;
- replay-versus-shadow equality/fidelity tolerance;
- owner-only non-activating promotion decision.

Frozen statistical method:

1. Aggregate the combined book to one side-aware C$ daily return series, retaining zero-return days inside each evaluation partition.
2. Estimate portfolio expectancy and drawdown uncertainty with 10,000 deterministic stationary-bootstrap replicates. Mean block length is `max(5, round(1.5 × N^(1/3)))` calendar days for partition length `N`; seed is SHA-256 of the evaluation-policy hash plus replicate number.
3. Estimate setup-level observed-spread-adjusted R uncertainty, before unknown commission and financing, by resampling aligned New York calendar weeks with replacement, keeping every cross-pair event and attribution in a selected week together. Use the same 10,000 deterministic replicates.
4. Report raw non-empty week count and Kish effective week count `(sum n_week)^2 / sum(n_week^2)` to expose concentration; also report pair, family and gross currency-direction shares.
5. Evaluate comparator differences on shared physical events where pairing exists; otherwise report separately bootstrapped difference distributions. Evaluate the random-timing null against all 100 registered replicates.
6. Treat the deduplicated combined book as primary. Apply Holm multiplicity adjustment to the three family-book secondary hypotheses; the familywise error level is numeric policy content frozen at S2.
7. A promotable result must satisfy the S2 minimum counts/coverage, positive uncertainty gate, minimum practical effect, comparator and pre-registered cost-sensitivity robustness gates simultaneously. Commission/financing grid cells are scenario-adjusted estimates, never reconstructed historical net returns. Numeric cutoffs remain intentionally unset until S2.

No fixed 10% drawdown retirement is an inferential failure rule. Safety controls and strategy evidence remain separate.

## 22. Prospective shadow and replay fidelity

Prospective operation begins only after historical gates and creates no orders.

- Run after every completed H1 and after aligned D/W closes.
- Use the same strategy domain functions and frozen identities as replay.
- Frequent prices create only proximity events.
- Store every analysis, transition, block, theoretical allocation/fill and outcome.
- Offline replay of the same frozen period must reproduce deterministic levels, setups, states, prices and outcomes.
- Every mismatch is an incident; no silent reconciliation.
- Claude is added only after deterministic replay equivalence and receives facts only. It cannot alter state.

Claude input is a hashed structured snapshot of deterministic bias, swings, levels, sweep/confirmation, restrictions, entry/stop/target/R, data quality and state. Structured output is limited to explanation, contradiction already present in the snapshot, incompleteness/block reason, invalidation/risk explanation and disclaimer. Requests/responses are append-only and linked to analysis/setup, strategy/feature/prompt/model versions, timestamps, latency, token use and error state. Claude cannot introduce facts, transition state, size positions or produce orders.

## 23. Required tests before implementation phases proceed

### Data contract

- BA midpoint derivation and side separation;
- W/D alignment across both DST transitions;
- completed-candle cutoff;
- duplicate idempotency;
- differing same-key conflict quarantine;
- dataset-version immutability;
- market-session gap handling.

### Indicators and levels

- EMA/ATR seed and as-of boundaries;
- strict pivot confirmation delayed exactly two daily candles;
- weekly/swing/breakout activation, flip, supersession, expiry and invalidation;
- outward zone rounding and frozen width;
- target inventory independent of bias.

### Setups and transitions

- multi-level one-event deduplication;
- family and combined-book attribution;
- consumed-level prohibition;
- exact three-H1 confirmation expiry;
- session/DST and spread blocks;
- idempotent duplicate jobs/transitions;
- data-quality cancellation.

### Execution and costs

- side-aware entry/stop/target;
- entry gap/missed fill;
- H1 stop-first ambiguity;
- scheduled exit precedence;
- M1 window completeness and paired-only behavior;
- common-fraction allocation and downward unit rounding without redistribution;
- gross same-direction currency buckets;
- spread counted once;
- commission/financing grid signs and rollover counts;
- point-in-time CAD conversion failure.

### Research controls

- partition purge boundaries;
- signal-count reader fails closed for forbidden entry-candle fields or any post-entry price row;
- signal-count output rejects return fields;
- deterministic comparator seeds;
- evaluation policy required before P&L command;
- untouched partition cannot open early;
- replay/shadow equivalence.

## 24. Change control and Phase 1 gate

This specification does not authorize implementation. Review must explicitly approve:

1. strategy/data document and machine manifest hashes;
2. the 99th-percentile absolute spread derivation and 0.10 H1-ATR ceiling;
3. comparator definitions;
4. cost sensitivity grid;
5. transition and partition contracts.

After approval, implementation may begin only as a separate request. Numeric strategy-evaluation thresholds remain blocked until the audited, return-blind S0/S1 report is reviewed and the S2 policy addendum is frozen.
