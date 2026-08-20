# OANDA v20 provider contract

## Fixed request semantics

- endpoint: `/v3/instruments/{instrument}/candles`;
- `price=BA` (bid and ask, never default midpoint);
- `smooth=false`;
- `alignmentTimezone=America/New_York`;
- `dailyAlignment=17`;
- only `complete=true` responses persist;
- timestamps represent interval starts and normalize to UTC;
- pagination windows contain at most 4,999 intervals and later pages use
  `includeFirst=false` to prevent boundary duplication.

The current canonical granularities are `D`, `H4`, and `H1`. Broker daily,
four-hour, and hourly series remain separate; one is never reconstructed from
another. Hourly bid/ask candles support prospective paper execution only.

## Cost boundary

OANDA documents annual long/short financing rates, account-specific commission
fields, financing weekdays, and `daysCharged` through the account instrument
endpoint. Those values can vary by instrument, side, date, holiday, division,
and account terms. The application does not yet capture point-in-time account
instrument snapshots because `OANDA_ACCOUNT_ID` is not configured.

Paper cost reporting therefore remains sensitivity-only under
`paper-cost-sensitivity-v1`: it uses OANDA's published position-value formula
and standard 5 p.m. New York/Wednesday rollover semantics, but labels its 0%,
3%, and 6% adverse annual rates plus 0.0, 0.5, and 1.0 pip commissions as stress
assumptions rather than observed charges.

## Credentials

Use `OANDA_API_KEY_TEST` for an OANDA practice token through the environment or
future AWS SSM integration; `OANDA_TOKEN` is also accepted. The token is
intentionally absent from fixtures, manifests, database rows, logs, and
exceptions. A missing token disables schedules and causes direct ingestion to
fail explicitly.

Set `OANDA_ENVIRONMENT` to the environment that issued the token (`practice` by
default, or `live`). Prefer a practice token: although this application only
calls the read-only candle endpoint, a live personal access token may grant
broader account permissions outside this application.

## Stored provenance

Every attempt stores source, instrument, granularity, requested range, fixed
parameters, SHA-256 manifest, counts, state, timing, and bounded failure text.
The manifest records requested URLs/statuses but not authorization headers or
raw provider content.

## Known boundary

Provider terms and the owner's exact Canadian account/instrument availability
must be confirmed before production use. OANDA content is not approved for
external LLM processing in the source registry.
