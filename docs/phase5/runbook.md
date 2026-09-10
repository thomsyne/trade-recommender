# Offline library operations and review gates

This is a research library, not a production strategy service. Its 19 frozen IDs
have no recommendation adapter, worker dispatch, schedule, sizing, portfolio or
Phase3 integration. Do not activate M15 ingestion or change instrument eligibility
to exercise it. Four decision-enabled and eight ingestion-only instruments remain
the existing policy. No executable quote or profitability claim follows from a
successful calculation or a passing engineering test.

## Read-only inspection

Use an authorized local database with the new forward migrations applied; never
apply migrations to shared infrastructure without separate approval. Start with:

```sh
.venv/bin/python manage.py strategy_library definitions
.venv/bin/python manage.py strategy_library preview --snapshot 123 --strategy ewmac-d-v1
.venv/bin/python manage.py strategy_library report --after-id 0
.venv/bin/python manage.py strategy_library integrity --after-id 0
.venv/bin/python manage.py strategy_library simulation-integrity --after-id 0
```

Use an actual immutable snapshot ID in place of 123. Preview consumes only exact
descriptor 0.12.0 observations and evidence; current candles are not a substitute.
Preview supplies no cost evidence, so continuous components cannot become an
affordable combination merely because their raw formula is available.
Use a snapshot at or before the candidate's assumed entry: a late snapshot returns
`snapshot_cutoff_after_entry`, never a historical fill. Input cost, financing and
conversion decimals are preserved exactly; output decimals use six-place half-even
rounding. Do not round input evidence to that output precision before submission.

Reports page at 100 rows; integrity pages at 20. Follow `next_after_id` until
`has_more` is false. A clean page is not a certificate for unscanned records or
their prior buffer lineage. Inspect every prior evaluation in that lineage.
Availability reports do not replay formulas and are not integrity certificates.
Hashes establish identity, not economic validity or semantic truth. SQL rejects
contract mutations; Python replay detects hash-consistent fabricated formulas.

## Explicit local research writes

`market.strategy.persistence.calculate(snapshot_id, strategy, costs=(),
previous_id=None)` is a manually invoked idempotent API, not a registered job.
It creates an immutable definition and evaluation in a transaction. A supplied
prior buffer must belong to the same strategy and instrument at an earlier cutoff.
Omitting it explicitly initializes the buffer at zero, not an existing position.
Do not compare selectively initialized runs as one continuous historical strategy.

`calculate_simulation(evaluation_id, outcome_snapshot_id, cost=..., calendar=...,
profile=..., terms=...)` separately stores an intent, outcome evidence and modeled
result. It replays the decision before simulation and requires a later exact
same-instrument snapshot. Costs, calendar and conversion/rollover evidence are
explicit typed inputs, not discoveries from current broker settings. Retry the
same request to obtain the same record; an altered attempt is refused. In
particular ORB allows only one attempt per definition/instrument/local session-day,
including an unavailable simulation. Do not rewrite an unavailable record to
improve its outcome. New assumptions require a new version/era and review.

Migrations 0038/0039 add only library contracts and guards. Existing evidence is
not backfilled or rewritten. Empty guard reversal/reapplication is tested; populated
reversal is deliberately refused. No production migration was run for Phase5.

## Missing evidence remains a gate

| Capability | Current disposition |
|---|---|
| EWMAC and breakout | Raw independently labeled components; only exact available, affordable speeds combine. D400 cannot satisfy EWMAC64/256 or breakout320 warmup. No uncited longer history. |
| H1 mean reversion | Prior completed daily equilibrium/alignment; late information moves execution to an eligible later opening or expires. No limit-fill inference. |
| ORB | London and New York wick, completed-close and qualified FVG are six distinct IDs. Approved close variant is `orb-m15-confirmed-v1:<session>`. M1 is a separate future prerequisite/version. |
| Pullback and failed break | Qualified Phase4 geometry only. H1 sweep/acceptance requires subsequent M15 structure; historical failed-break v1/v2 negative evidence remains terminal. |
| Range | Price-only edge/center hypothesis is implemented; source lacks attested event-expansion clearance, so evaluation fails closed. |
| Carry | Readiness only. Genuine PIT forwards, financing, rollover and broad ranking missing; policy rates never qualify. |
| Macro | Named event windows may pause, wide spreads may pause/reduce; absent event coverage never implies safe. Surprise unavailable without matching PIT consensus/release units. No production effect. |
| GARCH | Optional pinned solver via `requirements-phase5.txt`; absence, wrong version, nonconvergence or invalid variance is unavailable, never an EWMA fallback. Each challenger remains risk-only and capped at baseline. |
| Net simulation | Requires evidenced costs, calendar coverage and exit conversion/rollovers. OHLC dual hits are adverse; missing intervals are unavailable, not zero-return observations. |

The source pin is a SHA256 of the canonical map of implementation-file hashes in
`definitions.py`; registration and snapshot loading verify it. Definition hashes
also bind the specification, simulator and prospective population. SQL pins all
19 definition digests. After release, changing a formula, source pin, cost contract,
era or threshold requires a new version and forward migration, not editing stored
evidence or an applied migration.

## Research decisions remain outside this implementation

Development starts 2026-09-11 UTC; holdout is calendar 2027, half-open. Earlier
observations are exploratory, including inherited failed-break data. Registration
must precede holdout access. Do not release holdout data for iterative threshold
tuning. Every variant must stand alone before any separately approved combination.
Same UTC ISO week across currencies is one dependence group; positions crossing
weeks merge those groups. Raw sample counts are not independent observations.

`summarize_outcomes` accepts already verified, attributed simulator-derived gross
and net R rows; it is a diagnostic helper, not a database-backed acceptance engine.
Use the same frozen planned R as candidate geometry: quote-unit gross/net P&L
divided by `abs(reference - stop)`. Do not mix nominal cash across currencies or
refit the denominator from an observed exit. Continuous forecasts are not setup
trades; there is no implicit forecast-to-position or forecast-to-fill adapter.
The CLI reports availability, not strategy rankings or economic pass/fail. Frozen
52-week, positive-net and split-holdout thresholds are necessary review conditions,
not automated acceptance. FVG additionally requires positive paired untouched net
increment against the same-session close-confirmed comparator. No real outcome
population has been certified here.

Keep equity/options/dilution, HP momentum, candle triangular arbitrage,
acceleration, normalized-trend priority, subjective SMC/ICT confluence and RL
outside this registry. Engineering review, owner hypothesis acceptance, data
readiness and any later operational rollout are separate gates.
