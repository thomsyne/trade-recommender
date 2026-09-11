# Phase 6A deterministic assessment and eligible trade-intent contract

Status: **engineering design and preregistered acceptance matrix**. This document
is frozen before implementation. Engineering completion is not self-acceptance,
economic admission, activation, or permission to trade. Base, local `origin/main`,
and required source identity are `005b21f042cbc0aacd556c83ef16c86742cba06a`.

## Authority and ownership

The new `assessments` app owns a dormant deterministic projection from already
immutable Phase 4, Phase 5, Phase 7, eligibility, cost, and capacity records to an
assessment and, only when every gate is open, an **eligible trade-intent candidate**.
It has no consumer. It must not import or write `Recommendation`, lifecycle,
portfolio, paper, sizing, notification, task, schedule, provider, or model code.
Those systems must not import this app. Phase 5.5 outcomes are not consumed or
seeded here. The canonical eligibility set is therefore empty and the default
answer is exactly `no_economically_admitted_strategy`.

An intent candidate is a frozen research proposition. It is not an order, fill,
recommendation, portfolio admission, sizing result, broker quote, executable price,
notification, or permission to trade. No M15 schedule or provider/model call is
added. Positive tests use explicit synthetic immutable fixtures only.

## Frozen inputs and output

The method definition pins the closed schemas, reason precedence, strategy roles,
required-evidence policy, time semantics, arithmetic, and upstream contract hashes.
Every assessment has an aware information cutoff and exact identities/hashes for:

1. one verified Phase 4 snapshot containing completed derived monthly context
   (`monthly-context-v1` from complete D sessions), W, D, H4, H1, and M15;
2. each verified Phase 5 evaluation and exact strategy definition/version;
3. one immutable eligibility snapshot and its immutable entries, whose database
   admission time is not caller controlled and is no later than the cutoff;
4. an exact Phase 7 frozen packet only when the method-bound strategy requirement
   names it; caller convenience cannot add/remove that requirement;
5. immutable point-in-time cost evidence with original timestamp precision,
   source/version, spread, commission, slippage/latency and financing components;
6. an immutable versioned capacity assessment with policy/source identity,
   aggregate disposition and both directional currency-leg dispositions.

Missing is unavailable, never neutral or zero. Sentiment is unavailable in v1.
Current broker terms and current mutable portfolio state are not consulted.
Canonical JSON is UTF-8 sorted compact JSON with no floats/Decimals. SHA-256 binds
each payload and complete manifest. Replay loads and semantically authenticates all
upstream rows before reproducing byte-equivalent output.

Every output has nine closed fields: (1) HTF regime and macro/event/sentiment
availability; (2) major zones with timeframe/age/tests/invalidation; (3) exact
eligible strategy versions/roles; (4) separate bull/bear supporting, opposing,
pending and rejected triggers; (5) completed-candle trigger/confirmation and the
earliest next-M15 entry without broker-executability claims; (6) gross R, exact
cost components and net R; (7) frozen aggregate/currency capacity identities and
dispositions; (8) invalidation/expiry/supersession; (9) primary reason and every
ordered gate result. Each field carries `available`, `unavailable`, or `closed`.

Only Phase 5 `phase5/setup-v1` output may originate in v1. Continuous forecasts
need a future separately versioned adapter. Risk overlays constrain only.
`carry-readiness-v1` and unavailable outputs cannot originate. No generic
confluence or manufactured shape is permitted. A setup's exact Phase 5 geometry
is retained; v1 never invents entry/stop/target.

## M15 and ORB semantics

The first completed session M15 freezes the opening range. A later completed M15
may confirm it; wick and strict-close strategies remain distinct. The earliest
entry is Phase 5's registered next-M15 `entry_at`, strictly after the signal bar and
not before actual availability. M15 never implies M1, ticks, intrabar path, queue,
broker quote, or fill. Missing M1 is a capability fact, not a veto unless a future
method-bound strategy explicitly requires it. No strategy in v1 does.

## Eligibility, costs, capacity, evidence, and gates

Eligibility is immutable per strategy definition/version, role, instrument, era,
half-open validity interval, Phase 5.5 decision/manifest identity, decision
knowledge time, and admission provenance. The append service stamps admission with
database time, refuses decision knowledge in the future or before the governing
decision, refuses validity before admission, and cannot relabel an existing row.
This phase ships no command, migration data, or production caller that appends an
admission. Later population requires a separate explicit reviewed append operation.

Cost evidence is usable only when known by cutoff, exact timestamp precision is
declared, all required components are present, and `stale_after` is not passed.
Gross R is computed from frozen Phase 5 reference/stop/target geometry; net R
subtracts exact total round-trip cost divided by stop distance. Unknown spread,
excess strategy spread, stale/missing components, or nonpositive net R closes.

Capacity is consumed, never reconstructed. Missing, exceeded aggregate capacity,
or either exceeded directional base/quote currency leg closes. Evidence packets
are required only by the method's exact strategy requirement. Missing, stale,
conflicted, rights-blocked, imprecise, or otherwise not-ready required evidence
closes before any intent. AI/context text has no authority over strategy,
direction, trigger, eligibility, costs, capacity, or abstention.

Primary reason uses this frozen precedence while all gates are retained:

`input_integrity_failure`, `no_economically_admitted_strategy`,
`strategy_not_admitted_for_instrument`, `strategy_role_cannot_originate_intent`,
`required_timeframe_unavailable`, `m15_confirmation_unavailable`,
`required_evidence_not_ready`, `event_state_unknown`, `event_window_blocked`,
`technical_setup_absent`, `trigger_pending`, `trigger_rejected`,
`trigger_invalidated`, `trigger_expired`, `spread_unknown`,
`spread_exceeds_strategy_limit`, `cost_evidence_missing`, `cost_evidence_stale`,
`net_reward_nonpositive`, `capacity_assessment_missing`,
`aggregate_capacity_exceeded`, `currency_direction_capacity_exceeded`,
`conflicting_eligible_setups`, `unsupported_intent_shape`,
`unchanged_duplicate_intent`.

## Persistence, identity, and replay

Method, eligibility, cost, capacity, assessment, optional candidate, and explicit
candidate supersession observation records are append-only with protective foreign
keys, database-clock recording, closed SQL insert validation, update/delete/truncate
guards, canonical hash checks, and Python semantic replay. PostgreSQL advisory
locks serialize identity creation under READ COMMITTED. Same inputs return one
canonical assessment; a different output for the same input identity is a hard
determinism failure.

Candidate semantic identity includes strategy/direction, exact evaluation and
geometry, trigger/confirmation, entry/stop/target/invalidation/expiry, eligibility,
cost/capacity dispositions, required-evidence readiness, and predecessor terminal
state. A candle timestamp alone is insufficient. An unchanged live candidate is
recorded as a sit-out assessment with `unchanged_duplicate_intent`; material
identity creates a successor linked to the prior candidate. Supersession is an
append-only observation and never mutates prior intent. Migration reversal is safe
only while all Phase 6A tables are empty.

## Preregistered acceptance matrix

| ID | Requirement | Discriminating verification |
|---|---|---|
| A | Authority and bilateral legacy isolation | import/AST and DB-count tests prove neither side creates the other's artifacts; no schedule/provider/model/notification code |
| B | Frozen causality and exact lineage | later admission/evidence/candle/cost/capacity cannot alter old bytes; bad upstream hashes fail load/replay |
| C | Monthly/W/D/H4/H1/M15 availability and honest M15 semantics | missing monthly/M15 closes; wick ≠ close; strict next-M15; M1 never inferred or vetoed |
| D | Empty, immutable, non-backdated economic eligibility | perfect setup + empty set sits out; forged/backdated/wrong instrument/era/version rejected |
| E | Attribution and roles | setup can originate only when admitted; continuous requires absent adapter; overlays/readiness cannot originate |
| F | Complete nine-field assessment and closed taxonomy | schema rejects omissions/extras; deterministic precedence and all gate results retained |
| G | Exact point-in-time costs | unknown/stale/precision fabrication/zero substitution/excess spread/nonpositive net R close |
| H | Frozen hard capacity | missing/aggregate/currency-leg exceed close; later portfolio policy/state irrelevant |
| I | Candidate-only boundary | no recommendation/order/fill/sizing/execution fields or consumer; AI text cannot override gates |
| J | Idempotency and semantic dedup | concurrent same inputs one row; unchanged later assessment no duplicate; geometry/disposition/terminal change yields linked successor |
| K | SQL/Python integrity and replay | raw-SQL hash-consistent provenance forgery fails admission or authenticated load; byte-equivalent replay; populated reverse refused |
| L | Existing stack unchanged | source/governance pins and legacy tests remain; legacy dispatch creates no Phase 6A row and vice versa |
| V | Verification/handoff | focused PostgreSQL checks, migration drift, parity, replay, concurrency, `git diff --check`, `make check`; no broad suite without authorization |

No row is self-accepted. Independent review owns acceptance and any future
Phase 5.5 eligibility append, consumer, activation, deployment, or trading decision.
