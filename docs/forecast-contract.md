# Forecast contract v1

This slice establishes the ruler used to evaluate future model forecasts. It
does not issue trading advice, estimate fills, or use news or an LLM.

## Versioned targets

Two immutable contracts are installed:

| Product | Endpoint | Neutral band |
|---|---|---|
| Tactical | Midpoint close of the fifth subsequently completed OANDA daily candle | `max(0.25 × issue-time daily ATR(14), 2 × issue-time closing spread)` |
| Macro | Midpoint close of the twentieth subsequently completed OANDA daily candle | `max(0.50 × issue-time daily ATR(14), 2 × issue-time closing spread)` |

The endpoint change is **Up** when it is strictly above the positive band,
**Down** when strictly below the negative band, and **Neutral** otherwise.
Equality is neutral. Horizons count validated completed broker sessions rather
than calendar days, so weekends and market closures do not need guessed UTC
arithmetic.

Midpoint is used only as the declared forecast-label feature. It remains
forbidden as an execution price. Conditional entry observations use the
applicable bid or ask OHLC and are labelled as a daily touch—not an assumed
fill. Fill ordering, costs, target/invalidation sequencing, and P&L remain in
the later paper-experiment slice.

## Locked record graph

Each forecast references:

- an immutable target contract and version;
- an immutable evidence snapshot with exact candle, technical snapshot,
  source, retrieval-manifest hash, and information cutoff;
- a method and method version;
- Up/Neutral/Down probabilities summing to one;
- an optional parent macro forecast;
- conditional-entry fields, session expiry, and explicit abstention;
- a separate immutable resolution once enough later sessions exist.

Application methods reject mutation and deletion. PostgreSQL triggers enforce
the same rule against queryset updates or direct SQL. Corrections therefore
require new records and versions rather than rewriting history.

## Mechanical control

`mechanical-ewma-v1` is intentionally simple and frozen:

- midpoint above EWMA by more than the contract band: 50% Up, 30% Neutral,
  20% Down;
- midpoint below EWMA by more than the band: 20% Up, 30% Neutral, 50% Down;
- otherwise: 25% Up, 50% Neutral, 25% Down.

Every control explicitly abstains from a trade setup. Its purpose is to prove
issuance, evidence locking, expiry, resolution, and scoring before comparing a
model against it.

## Score

Resolved directional forecasts use mean multiclass Brier score:

\[
\frac{1}{3}\sum_{k \in \{up, neutral, down\}}(p_k-y_k)^2
\]

Lower is better. Forecast quality remains separate from entry activation and
future paper P&L.

## Operations

```bash
python manage.py issue_baselines
python manage.py issue_baselines USD_CAD
python manage.py resolve_forecasts
```

Baseline issuance is idempotent for one instrument, target version, and exact
evidence hash. Daily OANDA ingestion automatically attempts resolution after a
successful validated batch. It does not automatically issue a new baseline;
forecast cadence and material-change issuance remain explicit policy.
The command refuses development fixtures so an immutable test record cannot
retain invented candles when the workspace transitions to OANDA. Fixture
forecast rendering is covered through an explicit test-only override.
