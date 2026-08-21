# Current handoff

## Completed

The Foundation and Market Truth slice is implemented. It includes PostgreSQL
setup, Django authentication, canonical instruments and source policy,
OANDA bid/ask ingestion, fail-closed quality validation, deterministic
technicals, append-only audit, durable scheduler/worker primitives, fixtures,
tests, and Today/Pair/Operations interfaces.

The Forecast Contract slice is also implemented: immutable macro/tactical
target versions, exact market evidence snapshots, parent forecasts, explicit
abstention and conditional-entry fields, five/twenty-session resolution,
mechanical controls, mean multiclass Brier scoring, PostgreSQL mutation
triggers, and Decision/Timeline rendering.

The Research Ingestion slice is implemented: a safe allowlisted fetch boundary,
immutable raw RSS/API snapshots, official central-bank release feeds and
policy-rate series for CAD/USD/EUR/GBP, deterministic normalization,
publication/retrieval/vintage timestamps, deduplication, revisions/conflicts,
rights metadata, scheduled jobs, provider-comparison records, and a read-only
Research ledger. See `docs/research-ingestion.md`.

The Decision Evidence extension is implemented: five broader business/market
RSS feeds, S&P 500/VIX/Bitcoin/WTI/US 10-year/broad-USD context, a slower
explicitly labelled World Bank-derived gold series, official BoC/Fed/BoE/ECB
decision calendars, and four-hour immutable pair evidence snapshots. Pair
pages show evidence freshness, source count, pair macro, intermarket, calendar,
and news without creating or changing forecasts.

The Governed Recommendation slice is implemented: a provider-neutral contract
with Claude Sonnet 5 as the initial adapter, strict structured output and
semantic checks, evidence-ID citations, explicit abstention, prompt-injection
separation, immutable input/output audit, idempotency, four-hour scheduling,
and per-run/daily/monthly spend caps. It remains advisory and separate from the
mechanical control. See `docs/recommendation-contract.md`.

The Prospective Calibration slice is implemented: version 2 freezes an exact
daily reference and neutral band, records up/neutral/down probabilities, resolves
after five later completed daily sessions, and stores immutable multiclass Brier
and directional hit outcomes. Version 1 is excluded rather than reinterpreted.
The separate Calibration page suppresses conclusions until 30 outcomes exist.

The Paper Execution slice is implemented: hourly OANDA bid/ask collection runs
every hour, directional v2 setups transition through waiting, immutable entry,
and immutable result records, and adverse ordering resolves ambiguous hourly
candles. The Paper page reports spread-aware gross pips and R-multiples while
explicitly excluding financing and keeping results separate from calibration.

The Portfolio Exposure slice is implemented: unresolved directional setups are
decomposed into long/short currency legs, waiting and entered states remain
visible, and deterministic controls flag repeated factors, opposing views, and
more than two same-direction setup equivalents. The Exposure page is advisory;
it does not imply sizing, statistical correlation, or broker enforcement.

The Cost Sensitivity slice is implemented: each activated result receives an
immutable optimistic/base/conservative net-pip and net-R assessment. It bounds
hourly timing ambiguity, applies New York rollover and standard Wednesday
three-day semantics, and keeps observed gross execution separate from declared
financing/commission stress assumptions. It does not claim exact broker charges,
cash returns, or CAD accounting.

Prospective OANDA Account Terms capture is implemented: the configured v20
account successfully returns CAD account context and financing schedules for
all four pairs. Immutable hourly records preserve long/short rates, rollover
days, margin, pip location, response hash, environment, and a one-way account
fingerprint. The practice response omits commission, which remains visibly
unknown rather than assumed zero.

Position Sizing and Batch Reliability are implemented: each unresolved
directional setup receives immutable advisory units under a fixed C$25,000 CAD
model portfolio, 0.5% setup risk, 2% aggregate risk, and 1% same-direction
currency-factor caps. Conversion paths use only hourly candles available at the
sizing timestamp. The practice NAV is not used and no broker order can be
created. Recommendation batches attempt every pair, retain idempotent successes,
fail visibly when any pair remains incomplete, and expose the latest state on
Operations.

The Governed Learning reliability kernel is implemented. Recommendation
contract v3 withholds numeric OANDA market/technical data from Anthropic and
attaches levels through deterministic local policy. Exact contract versions
fail closed; v2 remains resolvable without being rewritten. Position-size and
paper-cost assessments are append-only per policy version, paper lifecycle
events explicitly represent legacy/pending/entered/closed/missing states, and
preexisting unresolved recommendations are marked legacy-unadjudicated.

The operations queue now uses owned expiring leases, heartbeats, execution
deadlines, stale-work recovery, safe error summaries, explicit missed-run
policies, and timezone-aware daily wall-clock schedules. Transactional outbox,
delivery attempts, and the controlled Gmail SMTP worker are implemented, and serialized
provider-budget reservations prevent concurrent authorization from exceeding
declared caps.

Prospective portfolio admission is now implemented. A versioned activation
timestamp keeps all earlier recommendations research-only. Complete new batches
are assessed under one serialized CAD-risk policy: all-fitting sets are admitted
automatically, while competing sets create an owner-only inbox decision. Owner
selections are append-only, idempotent, and may only be superseded before any
cohort member's entry price triggers. Confidence is displayed as uncalibrated
context and never ranks or allocates capacity. The Gmail SMTP adapter activates
only when the settings in `docs/gmail-notifications.md` are supplied and fails
closed otherwise.

The Deterministic Postmortem slice is implemented. Once both the prospective
five-session recommendation outcome and terminal paper lifecycle are available,
the system freezes a point-in-time review cohort and separate immutable thesis,
execution, and reconciliation assessments. Missing execution remains an
explicit denominator; source lineage and projection hashes are retained;
corrections append superseding assessments without changing cohort membership.
The owner-only Reviews notebook and pair timeline render these facts without
Claude interpretation. Daily/hourly ingestion and `resolve_forecasts` attempt
the idempotent review build; `build_postmortems` supports explicit operation and
later correction reassessment.

## Verification gate

Run:

```bash
./.agents/setup
./.agents/setup
./.agents/resume
make check
make test
make dev
```

Then authenticate through the portal and review Today, USD/CAD H4/Daily,
Research, and Operations at desktop and narrow viewport widths.

## Next pickup

Implement Slice 4 from `docs/governed-learning-map.md`: rights-cleared bounded
Sonnet interpretation and a non-actionable governed learning queue. Deterministic
review facts must remain authoritative and complete when model work is disabled,
over budget, or rejected.

## Still OPEN

- provider permission for restricted/full-text external-model processing;
- paid economic-calendar/PIT provider trial;
- remaining BLS/Census release-calendar automation;
- exact historical OANDA financing before the first captured snapshot;
- account-specific commission terms (not supplied by the practice endpoint).
