# ADR: Phase5 consumes immutable descriptive evidence, not implied trade authority

Status: readiness specification only; Phase5 implementation and activation are
not authorized. Phase4.5 engineering results do not establish predictive value.

## Immutable input envelope

Consume only `market-state/descriptor-v0` snapshots governed by
`market-state-descriptor@0.12.0` and the exact registered definition digest.
The unchanged definition digest is
`9213b548d3e6c6656805d2cf230c242926f08a42112373d7518d685384b9f7d3`.
Bind instrument, information cutoff, requested granularities, input manifest,
evidence manifest, both manifest digests, output digest and idempotency key.
Read exact immutable observations by timestamp, granularity, revision and content
hash. Never substitute the current Candle row for a cited historical revision.
Unknown definitions or mismatched runtime parameters fail closed.

All consumed auxiliary M15/D/W observations are in the input manifest even when
not requested explicitly. Numbers are canonical Decimal strings at the pinned
six-decimal half-even quantum; preserve units and midpoint versus bid/ask basis.
Creation time is not information availability. Eligibility is bounded by interval
completion, observation, system recording and the frozen cutoff. Later research
retrievals, revisions and suppressors must not leak into earlier decisions.

## Complete consumption matrix

| Phase4 output / version | Availability and missingness | Permitted Phase5 derivation | Forbidden reinterpretation |
|---|---|---|---|
| Eligible count/latest candle | Completed, latest eligible revision inside pinned lookback; absent history unavailable | Explicit minimum-history filter | Count means full market coverage; latest current revision replaces cited revision |
| Swings / `swing-v1`, trend / `trend-v1`, sequence / `swing-sequence-v1` | Right-hand confirmation and every prerequisite must be available; ties follow pinned algorithm | Versioned structure filters | Swing pivot time is confirmation time; retroactive entry |
| ATR / `atr-v1`, volatility / `volatility-v1`, regime / `vol-regime-v1` | Warmup/population requirements; unavailable is not zero volatility | Explicit normalized feature or regime condition | Recompute using a later ATR/population or change percentile thresholds |
| Compression/expansion / `compression-expansion-v1` | Contemporaneous population and transition dependencies | Versioned transition filter | Pending pattern is a confirmed breakout |
| Equilibrium / `equilibrium-v1`, persistence / `persistence-v1` | Required contiguous history and confirmed structure | Explicit context filter | Equilibrium guarantees reversal or persistence forecasts returns |
| BOS / `bos-v1`, CHoCH / `choch-v1` | Close/confirmation and prerequisite availability | Versioned structure-change condition | Rename descriptive change as an execution signal without a strategy contract |
| S/R zones / `zone-v1`, equal levels / `equal-levels-v1` | Confirmed pivots, ATR normalization and expiry bound to evidence | Proximity/overlap filters with stated units | Actual resting orders, institutional ownership or known stop locations |
| Supply/demand candidates / `sd-candidate-v1` | Descriptive displacement and source dependencies | Candidate context only | Verified supply/demand inventory |
| Consolidation / `consolidation-v1` | Range, breakout/retest/failure and all dependency timestamps | Versioned lifecycle filter | Late range evidence backdated to the first bar |
| Prior day/week/month/session extremes / `prior-extreme-v1` | Only completed, sufficiently covered periods; gaps unavailable | Explicit prior-period comparison | Current incomplete period or universal exchange calendar |
| Monthly context / `monthly-context-v1` | Exact completed month membership, sufficient daily history | Monthly context filter | A partial month is complete; fill missing days implicitly |
| Sweeps / `sweep-v2`, acceptance / `acceptance-v2` | Confirmation, invalidation, expiry and gaps; pending not emitted confirmed | Versioned lifecycle condition | Real liquidity, stops, executed order flow or guaranteed reversal |
| FVG / `fvg-v1` | M15/H1/H4 only; contemporaneous ATR/spread/pips, lifecycle and dependencies | Geometric gap proxy | D/W applicability; actual unfilled orders or inevitable fill |
| ORB / `orb-v1`, sessions / `session-v1` | First completed M15, London/NY wall-clock session, registered dependencies | Explicit session-range filter | Missing opening candle is an empty range; holiday attestation inferred from weekday |
| Spread / `spread-v1` | Frozen bid/ask close and contemporaneous ATR; ATR may be unavailable | Cost-awareness filter using stated quote units | Executable future spread, fill guarantee or full transaction cost |
| Events / `event-state-v2` | Latest known vintage and retrieval; exact-time active windows; no supported attested-empty coverage | Explicit event-risk filter; unknown blocks any rule requiring known-safe | No event rows means safe; date-only event has invented precise time/severity |
| Macro / `macro-regime-v1` | Exact policy-rate vintages/retrievals and jurisdiction; missing side unavailable | Versioned macro-context condition | Revised data available at original release; unsupported causal economic forecast |
| Data-quality status | Input completeness axis only, separate feature availability/integrity/freshness | Require all relevant axes explicitly | `complete` means every feature available, calendar attested or strategy tradable |

Every derived filter needs a new Phase5 definition/version, canonical parameters,
source snapshot identity, evaluation cutoff and an explicit unavailable policy.
Combining descriptors may form a hypothesis; it must not mutate Phase4 outputs
or silently inherit authority from historical research approvals.

## Phase5 acceptance gates

| Gate | Required before implementation/activation | Current boundary |
|---|---|---|
| Engineering | Independent review of Phase4.5; exact-version tests; no unresolved current-state regression | Not self-accepted |
| Migration rollout | Genuine accepted backup restore and recorder/data/sequence proof on PG15.14 and PG17.6 | Genuine deployed restore proves refusal only: deployed history ends at 0023 without accepted successor acquisition; accepted-success/already-applied-0027 proof remains mandatory |
| Definition | Exact Phase4 contract/digest, feature versions, lookbacks, rounding, units and requested/auxiliary scope | No reinterpretation or mutable alias |
| Causality | Equality/late-observation/late-recording/revision tests; confirmation availability; no future data | Replay exact immutable inputs |
| Missingness | Separate unavailable, not-applicable, invalidated, expired, empty and unknown states | No default neutral/false/safe |
| Calendar | Reviewed provider/entity/instrument-specific version, coverage and known-at attestation | Missing attestation blocks readiness; frozen Phase4 calendar unchanged |
| Provenance | Research lineage, retrieval times, content hashes, rights and immutable revisions | No synthetic accepted acquisition claims |
| Operations | Deployment-sized RSS/WAL/storage/query/lock/backlog budgets and failure alerts; crash/restart rehearsal | Synthetic local measurements are not production capacity |
| Hypothesis | Versioned setup rules, return-blind derivation, holdout policy and explicit acceptance owner | No Phase5 strategy code in this change |
| Execution | Separately authorized lifecycle, cost, sizing, risk, decision eligibility and rollout controls | Existing Phase3 behavior and four enabled pairs unchanged |
| Scheduling | Explicit approval for each new schedule/consumer and M15 acquisition | Phase4 remains unscheduled; M15 dormant |
| Review | Independent reviewer verifies evidence, exclusions and clean local commits | No push, PR, deploy or activation implied |

This matrix authorizes documentation only. It does not authorize provider calls,
new acquisitions, signals, recommendations, forecasts, sizing, execution or
production changes. Hypothesis acceptance and operational rollout are separate
decisions with separate evidence.
