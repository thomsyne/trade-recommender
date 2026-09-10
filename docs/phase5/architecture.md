# ADR: attributable offline contracts, without activation

Status: implementation specification; owner approval is limited to engineering
and M15-first ORB. Phase4/4.5 acceptance and operational limitations remain intact.

Continuous forecasts are dimensionless values capped at ±20, not probabilities
or orders. Setup candidates specify direction and price geometry, not fills.
Execution intents specify a next-interval simulation request. Execution results
carry modeled gross and net separately and may be unavailable. Risk overlays
carry a non-increasing multiplier, never a direction. These are distinct types;
none can flow into Phase3, recommendations, sizing, a portfolio or production.

Python owns formulas and exact replay. PostgreSQL owns append-only definitions,
input/output contracts, identities, foreign keys and concurrency. No new SQL
formula replicas. Persisted hashes bind canonical content but do not prove a
formula; independent Python replay is required. Pure calculations receive frozen
scalar observations and immutable JSON bytes, never ORM objects. Loading exact
Phase4 snapshots and persistence are separate functions, not hidden I/O.

Input dependency is exactly `market-state-descriptor@0.12.0`, descriptor schema
`market-state/descriptor-v0`, digest
`9213b548d3e6c6656805d2cf230c242926f08a42112373d7518d685384b9f7d3`.
Bind source snapshot ID/key, instrument, cutoff, requested granularities, input
manifest/hash, evidence manifest/hash and output/hash. Exact cited revisions are
read, not current Candle rows. Reject missing, unsupported or corrupt evidence.
Use Phase4.5 availability clocks and frozen registered calendar, never infer
provider-specific open coverage. Calendar attestation remains a separate gate.

Definitions include simulation/cost policy and population/era/holdout policy before
outcomes. Missing history/costs/calendar/macro data is an explicit unavailable
reason; it is not a losing trade, no-pattern, neutral forecast or known-safe period.
Synthetic fixtures may demonstrate formulas, not economic value. Later evidence
cannot change old outputs. Execution outcome data is never an input to detection.

Every speed/horizon and strategy variant is independently labeled. Within-family
equal combination is explicitly defined, with component outputs and exclusions
retained; no cross-family combination. ORB sessions and wick/close/FVG variants
never share an evaluation population. M1 would require a new prerequisite/version.
All failed-break v1/v2 artifacts remain unchanged negative evidence. New rules
start a new prospective era; historical reuse is exploratory, never untouched.

No registry entry in operations dispatch, no schedule, no consumer, no settings
change or instrument-policy change. Offline commands are explicit research tools.
Persisting an experimental record does not authorize promotion. Independent
engineering review, owner hypothesis acceptance and operational rollout are
separate gates.
