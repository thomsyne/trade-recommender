# Failed-break v2 S1 return-blind geometry

Recommendation: **keep the next policy exploratory-only, with return execution,
backtesting, promotion and live trading still unauthorized.** This recommendation
is not effective policy and cannot unlock returns.

The accepted v2 S1 ledger contains **188 `ENTRY_PENDING` book evaluations across
83 distinct physical setup events**. One event, setup 1722, has two memberships
but no complete ten-provider-D-session horizon inside the development partition.
The accepted boundary rule therefore purges it without deleting or changing S1
evidence. The eligible geometry is **82 physical events and 186 memberships**.

## Source and identity

The fixed-path projector binds S1 acceptance artifact
`5760dd2dd60a2d6a6087b5116b085a8a3774db1512962af0622bc0e3eeed93d5`,
self-hash `5f1497b7e47da958469d8b8c13d2608243e7a0f811eb30f54f4d5fe65f2bbcab`,
aggregate evidence
`4fd959c4185034599f9eee803d476aa7249fb995d2560325071b3fc4dbb5c2d1`,
and projection
`5aab5a0e20eae00c6984a7740d9df5d14f0c575b3b0a997b66e055818d66e714`.
It also verifies the accepted v2 strategy, dataset, contract, registration, S0,
configuration and report identities.

Physical identity is the accepted setup natural key: instrument, direction,
sweep timestamp, detector identity and dataset version. The database uniqueness
constraint and one evaluation per setup/book make the 188-to-83 collapse
unambiguous. Every event, evaluation membership and evidence hash is in the
artifact; the purged event remains explicitly recorded.

## Population and clustering

Eligible entries span `2010-02-16T19:00:00Z` through
`2018-12-03T19:00:00Z`.

| Book | Events | Dates | Weeks | Week Kish | Factor clusters | Factor Kish | Horizon peak | Capacity-positive |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Combined | 82 | 76 | 68 | 60.0357 | 69 | 61.1273 | 3 | 81 |
| Weekly | 38 | 38 | 37 | 36.1000 | 37 | 36.1000 | 2 | 38 |
| Daily swing | 38 | 37 | 37 | 36.1000 | 37 | 36.1000 | 2 | 38 |
| Breakout | 28 | 27 | 26 | 23.0588 | 26 | 23.0588 | 3 | 28 |

The combined book has 76 non-empty New York entry dates, 68 New York ISO
entry-week clusters with exact Kish `1681/28`, and 69 shared-factor clusters
with exact Kish `3362/55`. Shared-factor clusters are transitive connected
components within the same New York entry week, linked whenever either currency
is shared, ignoring direction and book.

There are 81 distinct entry timestamps: one simultaneous timestamp contains two
physical events and the other 80 contain one. Maximum-horizon geometry has 34
overlapping event pairs and a peak of three concurrent physical requests under
the established allocate-before-equal-boundary-release convention. No price or
exit inside any horizon was read.

## Return-blind distributions and concentration

Physical events by instrument are AUD_USD 12, EUR_GBP 7, EUR_USD 15, GBP_USD
20, USD_CAD 13 and USD_JPY 15. Directions are 45 long and 37 short. Sessions
are London 18, London/New York overlap 30 and New York 34.

Annual counts for 2010–2018 are respectively 14, 14, 7, 9, 6, 7, 5, 11 and 9.
Book memberships are combined 82, weekly 38, daily swing 38 and breakout 28.
Sixty physical events have two books and 22 have three. Family memberships are
weekly 38, daily swing 38 and breakout 28.

Largest physical-event concentrations are GBP_USD `20/82` (24.39%), long
`45/82` (54.88%), New York `34/82` (41.46%) and year 2011 `14/82`
(17.07%). The largest entry-week and shared-factor clusters are each `3/82`
(3.66%). Combined-book memberships are `82/186` (44.09%) of all memberships;
memberships are not independent trades.

The fixed-C$10,000 diagnostic reuses only pre-entry CAD unit risk, C$25 requested
risk, C$100 aggregate risk, C$50 currency-direction caps, common-fraction
allocation and sealed maximum horizons. It yields 81 positive-unit and one
zero-unit combined request. This is a capacity diagnostic, not an allocated or
resolved-trade count, and it is neither a lower nor upper bound once marked
equity and early exits exist.

## Detectable effect and policy floors

With target effect `0.20R`, 95% two-sided normal design and 80% power, the
conservative effective count is `1681/28` (the smaller of entry-week and
shared-factor Kish). Minimum detectable effects are:

| Assumed sigma | MDE | Assessment at 0.20R |
|---:|---:|---|
| 0.5R | 0.1808R | Adequate |
| 1.0R | 0.3616R | Inadequate |
| 1.5R | 0.5424R | Inadequate |

Confirmatory adequacy is not established across the scenarios. The geometry is
large enough only for a separately authorized descriptive exploratory analysis;
it cannot support promotion or live trading.

The prior v1 S2-04 floors are reported only as non-effective comparison
diagnostics. Combined geometry satisfies the return-blind confirmed-count,
eligible-count, date/week, Kish, calendar and registered-coverage floors.
Resolved allocation, genuine pairing and later unresolved-data counts remain
unknowable. Each family fails the 50-event floor; weekly and daily each have 38,
and breakout has 28. Breakout also fails the 30-date, 30-week and 30 week-Kish
floors and cannot meet either the 50 resolved-event or 30 paired-event floor.
Weekly and daily cannot meet the 50 resolved-event floor; their paired-event
counts remain unknowable. No v2 S2 floor becomes effective here.

## v1 comparison

Against accepted v1 geometry, eligible v2 has 82 versus 90 physical events,
186 versus 204 memberships, 76 versus 81 dates, 68 versus 73 weeks, 69 versus
74 shared-factor clusters, and peak concurrency three versus five. Seventy-five
semantic event cores overlap; 15 are v1-only and seven are v2-only.

Thus v2 worsens raw sample volume by eight events, while its lower clustering
raises week Kish from 59.5588 to 60.0357 and factor Kish from 60.4478 to 61.1273.
The concurrency reduction also improves capacity geometry. These improvements
do not offset the loss of sample volume or establish confirmatory adequacy.

The geometry formulas and sealed-horizon rule are unchanged. The cohort changes
under the two governed v2 detector corrections: complete D/W admission independent
of H1 coincidence, and the corrected supporting-swing validity interval. The
artifact lists every v1-only and v2-only semantic event, but does not invent a
counterfactual allocation of individual differences between those two rules.

## Monthly objective diagnostic

The eligible cohort averages exactly `41/54`, or 0.7593 potential physical
events per calendar month. At C$25 risk per request, achieving C$800–C$1,000 per
month would optimistically require roughly **42.15R–52.68R per potential event**
even before costs, capacity blocks, losses or inactive months. The desired
8%–10% monthly objective on C$10,000 is therefore structurally unrealistic at
this observed opportunity frequency before outcomes are considered. This is a
frequency/risk arithmetic diagnostic, not a profitability conclusion.

## Isolation and identities

Eight fixed query shapes read only semantic identity, status, evidence hashes,
pre-entry timestamps, pre-entry CAD unit risk and sealed D/H1 timestamp
membership. They never reference the candle table or select any bid/ask/mid
price, entry/stop/target price, outcome, return, P&L, drawdown, paper-trade or
backtest field. All database passes used `REPEATABLE READ READ ONLY`, the local
Unix socket, a fixed research database name, explicit rollback, provider
credentials unset and external networking denied.

Two final projections completed in 3.63 and 3.58 seconds and produced identical
canonical artifact bodies. Earlier fail-closed development probes also rolled
back without writes. No S0/S1 rerun, persistent write, provider, production or
outcome access occurred.

- Artifact SHA: `b3bc76fa4ac226793a24f11a9a65f9b549e7231ace11e399f6d81c1599e41fdc`
- Geometry self-hash: `a3c2f7e3f3f7d722228233c158b51eaa296557daf0c19860c79848a788ffc140`
- Eligible event-set SHA: `8abb97a0e658d7079b9cfffd66259609b00f7c57aba89209a01cb5673df9fbd8`
- Eligible membership SHA: `7bf33678f10ddbb395757baf1cefd2e460ecd35cd76f28bab2d545ba504a2396`
- Raw 188-membership SHA: `a0b2ba9021b8ebe76d184ac768b219c564f40e5cbeb7a8df7c7d2b019d94c87f`
- Structured report SHA: `c0d49dbd82c680a44a75d71d31b107d38482071423a88e70c656cf8a5cfa1b8e`
- Source projection SHA: `1e06defb9f7e3b30bf575ad92c25d3ac8c70883deb84a982d95deb5040fccad9`

Return execution, backtesting, effective S2 policy, promotion/live trading,
provider access, production access and deployment all remain unauthorized.
