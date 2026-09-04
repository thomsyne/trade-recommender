# Failed-break v2 exploratory return calculator

Status: `CODE_ONLY_SYNTHETIC_VERIFICATION_COMPLETE_REAL_EXECUTION_UNAUTHORIZED`.
The canonical preregistration JSON is authoritative. This implementation does
not grant access to real outcomes or authorize a persistent return run.

## Architecture decision

The existing `forecasts.paper` and `forecasts.costs` paths were not reused as
runtime engines. They are coupled to `Recommendation`/`PaperTrade` ORM writes,
use older generic calendar behaviour, and expose three coarse cost scenarios
rather than the governed 3 × 5 commission/financing grid. Reusing them would
change the accepted sealed-inventory, physical-event, conversion and cost
semantics. The new engine is a pure standard-library module. It accepts only a
normalized sealed-evidence value graph and performs no I/O.

The governance loader fixes the artifact path and binds the accepted v2 S1
outcome, 82-event geometry, effective exploratory-only S2 policy, detector and
successor dataset. The boundary-purged event is excluded. A future adapter must
provide exactly the governed 82 keys; this branch contains no such adapter,
management command, database model, migration or execution authority.

## Calculations

One physical event is one trade, risk budget, P&L observation and bootstrap
member. Book memberships are sorted non-additive labels. Entry is the frozen
side-aware open. The primary H1 adapter resolves adverse stop gaps first, stop
before target in a common candle, then daily-structure exit before the
ten-provider-D-session horizon at a common scheduled boundary. Expected sealed
H1/D evidence that is missing or conflicting yields `UNRESOLVED_DATA`; nothing
is dropped.

Daily structure invalidation is the first completed sealed D close strictly
beyond the frozen supporting swing, executed at the next sealed H1 bid open for
a long or ask open for a short. The horizon is the already-governed sealed H1
successor at or after the tenth actual provider-D completion. Each CAD route leg
is fixed and must use conflict-free sealed midpoint-close evidence completed
strictly before its decision timestamp; there is no wall-clock staleness rule.

Gross R and CAD P&L include observed bid/ask spread exactly once through
side-aware entry and exit prices. The engine reports that spread effect as
embedded rather than inventing an ungoverned counterfactual intrabar midpoint
fill. It never subtracts spread again. Commission is charged at terminal exit.
Financing includes each governed New York 17:00 rollover with its 1/3-day
multiplier. All 15 commission × financing cells are emitted; additional
slippage is exactly zero and remains an optimistic exploratory limitation.

Fixed diagnostics use CAD 10,000 and non-compounding CAD 25/50/100 risk. They
include all 108 months, all calendar-day 17:00 New York equity marks, monthly
and annual P&L, drawdown, streak and ratio metrics, and peak concurrent risk.
Undefined denominators are `null`. Sharpe and Sortino are descriptive only.
The return-blind geometry/MDE sigma grid `[0.5R, 1.0R, 1.5R]` and hypothetical
S2-03 sensitivity grid `[0.5R, 1.0R, 2.0R]` remain distinct. The deterministic
week-cluster bootstrap emits 10,000 replicates and the frozen linear percentile
interval; it cannot emit a promotion conclusion.

## Synthetic verification and performance

Focused fixtures cover long/short stop and target, adverse gap, stop-target
collision, horizon and structure exits, pre-entry rejection payloads, missing
and conflicting members, strictly-prior conversion, rollover financing,
multiple-book de-duplication, overlapping risk, all cost cells, complete event
sets, 108 months, undefined metrics, deterministic ordering and bootstrap, and
all authority refusals. Source-import inspection proves the calculator has no
Django, psycopg, HTTP, socket or subprocess dependency.

The committed benchmark is deterministic synthetic data: 5,000/10,000/20,000
events, two H1 rows and 15 cost cells per event. On arm64 macOS 26.5.2 with
Python 3.11.4, measured times were 6.941850 s, 13.881963 s and 27.761286 s;
peak traced memory was 77,477,977, 154,781,043 and 309,388,883 bytes. A repeated
20,000-event run took 27.936088 s and reproduced output SHA-256
`25b5a3e6fe10186d28ac23f46db4ec06a8c6490015eb085afabb8824afe055bb`.
This supports approximately linear scaling for this synthetic range only. It
does not measure the 10,000-replicate bootstrap, evidence loading, canonical
persistent writes, database constraints, backups, or a future complete run.

## Absolute boundary

Real outcome access, real return calculation, persistent execution, database
access, providers, production, promotion, live trading and deployment remain
unauthorized. No owner, CLI, environment, database, data-only, successful-result
or threshold-reinterpretation override can cross that boundary.
