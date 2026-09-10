# Phase 4 — Review Lessons

Defects and gaps discovered during independent review, and how they were
resolved. Two independent-tester passes were run against the branch; the first
raised findings, the second re-verified the corrections.

## Round 1 findings → resolutions (committed as slice 9, `578e976`)

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | P1 | `compute` fetched eligible candles and built the input manifest with **no lookback** — the manifest and O(history) feature lists were unbounded, contradicting the stated bounded-window contract (design §14, handoff). | Added `compute.LOOKBACKS` (per-granularity), pinned in `DESCRIPTOR_DEFINITION["lookbacks"]`, threaded into `build_input_manifest` and every `eligible_observations` call. Definition → 0.7.0. |
| 2 | P2 | `structure._zone_id` hashed only `[version, low, high]`, contradicting design §7.2 (`[version, instrument, timeframe, min, max]`); same band collided across instruments/timeframes. | `_zone_id(low, high, instrument, timeframe)`; liquidity level id uses the same helper. |
| 3 | P2 | `consolidation_state` documented a `failed_bars` retest/failed-breakout window it never implemented (dead parameter, only `breakout` emitted). | Reworked over a `failed_bars`-length tail window; emits `breakout`/`retest`/`failed`. |
| 4 | P3 | FVG had no expiry and no internal-swing-break invalidation (design §7.4). | Added `expired` (unfilled after `FVG_EXPIRY_BARS`); internal-swing-break made an explicit documented deferral (no overclaim). |
| 5 | P3 | Liquidity sweep/acceptance scanned bars **predating** the reference level's formation. | Restricted to `bars[pivot.index:]` (at/after formation). |
| 6 | P3 | Integrity report implemented a subset of design §11 while the docstring/handoff implied the full list. | Added `malformed_payload_schema` + `unsupported_granularity`; docstring rescoped honestly (remainder structurally precluded by immutability/uniqueness/determinism). |

No P0 was found in either round: the tester could not produce future-data
leakage, an immutability bypass, or a causality defect.

## Round 2 (re-review) → all six RESOLVED, **ACCEPT for PM review**

Independently verified each fix (bounded fetch/manifest empirically; zone-id
collision-freedom; consolidation failed/retest; FVG expiry; liquidity slice;
integrity checks), plus regression: 113 focused tests green, protected diff
(`market/technicals.py`, `forecasts/`) empty, determinism/causality/immutability
intact. One non-blocking nuance was raised — the eligible-observation **DB query**
still scanned O(history) rows before slicing — and was then fixed in `3abcecc`
(bounded cursor), so the scan itself is now bounded.

## Round 3 — deeper independent review (slice 10, `d01b138`)

A more rigorous independent review found **sixteen** findings the first two passes
missed (no P0). All corrected with discriminating tests
(`test_market_state_review_fixes`). Summary:

| # | Sev | Finding | Fix |
|---|---|---|---|
| 1 | P1 | Snapshot identity bound only requested candles; empty M15/H4 collided; an added consumed M15 candle silently changed an H1 snapshot. | Identity now binds scope + all consumed candles (incl. auxiliary M15/D/W) + macro/event evidence hashes. |
| 2 | P1 | Definitions did not govern computation; no terminology registry. | compute rejects a non-matching definition; new `terminology.py` registry; compute/integrity fail closed on unregistered terms and banned vocabulary. |
| 3 | P1 | Malformed inserts allowed; integrity certified contradictory snapshots; malformed manifest crashed it. | Migration 0033 CHECK constraints (hash format, JSON shape); integrity adds instrument/granularity/terminology/availability checks and bounded malformed handling. |
| 4 | P1 | Lookback bounded Python only; SQL scanned all history. | `DISTINCT ON (timestamp) … LIMIT` + supporting index. |
| 5 | P1 | Observed positions substituted for registered intervals; a single day was a "completed month"; no monthly trend. | Registered-consecutiveness for swings/FVG; monthly context with full-session completeness. |
| 6 | P1 | Historical FVG/ORB facts backdated and requalified by later ATR. | Bars carry completion + spread; created_at/breakout_at at completion; contemporaneous ATR. |
| 7 | P1 | FVG spread-norm/internal-break/ORB retest/overnight extremes missing; expiry could un-expire. | All implemented; expiry window-bounded. |
| 8 | P2 | Event vintage window applied before dedup; future retrievals admitted; empty = attested. | Latest vintage before window; retrieval enforced; coverage-unavailable distinct. |
| 9 | P2 | Acceptance declared before the reclaim window matured. | Requires the full window. |
| 10 | P2 | Zone tests counted pre-formation; wrong exit threshold; no lifecycle. | From formation, `>=` margin, expiry + invalidation. |
| 11 | P2 | Failed breakout counted as a retest. | Retest requires holding beyond the boundary. |
| 12 | P2 | Equal highs/lows mislabelled / undetected. | `equal_high`/`equal_low` labels; local-extrema detection. |
| 13 | P2 | Read-only preview wrote a definition. | In-memory unsaved definition. |
| 14 | P2 | Task retry non-idempotent; registration raced. | Cutoff required; atomically idempotent registration. |
| 15 | P2 | Two new parity failures after a migration-reversal test. | Parity setUp re-installs the M15 SQL mirrors. |
| 16 | P3 | `expected_candle_timestamps` rejected valid M15 starts. | M15 alignment added. |

## Lessons

- A "bounded window" claim must be enforced at the **fetch and the query**, not
  just the output slice — declaring `lookbacks: {}` silently made the whole
  contract unbounded.
- Feature identities that must be globally unique (zone ids) have to bind their
  full scope (instrument, timeframe), or they collide across contexts.
- Documenting a parameter/behavior (retest/failed) that the code does not
  implement is a design/impl contradiction a PM will reject — implement it or
  mark it an explicit deferral.
- Honest scoping beats overclaiming: an integrity report that names exactly what
  it checks (and what is precluded structurally) is stronger than one that
  implies coverage it lacks.
