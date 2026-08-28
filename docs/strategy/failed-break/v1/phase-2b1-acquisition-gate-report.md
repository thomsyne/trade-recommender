# Phase 2B.1 offline acquisition gate

**Status:** PASS — deterministic plan only; acquisition remains unexecuted.

## Frozen intent

- Acquisition contract/version: `failed-break-historical-acquisition` / `phase-2b1-v1`
- Source selector: `OANDA v20` / `oanda-v20-market-candles-v1`
- Strategy selector: `top-down-failed-break-continuation` / `failed-break-phase-1-freeze-v1`
- Instruments: AUD_USD, EUR_GBP, EUR_USD, GBP_USD, USD_CAD, USD_JPY
- Granularities: D, H1, W; combined bid/ask; New York 17:00; Friday weekly alignment
- Complete candles only; `includeFirst=true`; one provider request per logical chunk
- Per-instrument counts: D 2,571; H1 56,365; W 471
- Logical chunks: 84 (1 D + 12 H1 + 1 W per instrument)
- Total intended rows: 356,442
- All candle completions are strictly before 2019 in America/New_York.

## Stable results

- Plan SHA-256: `41570a010f18bb24b4b787cab407e45d4ef0b297034adc75e4f6fe14195865a8`
- Dataset manifest SHA-256: `fee412f6197ee8edbf54b47152901c8d05f3b3534ccd3df27fabbc7558cf7231`
- Ordered chunk manifest SHA-256: `b46e1eadbee5e5ee1be9e8d0443a4c7de7a02cc498b2d9eded63ffb1f85d78d9`
- `phase-2b1-acquisition-plan.json`: `94c4a7923b5335176755a2dcdae19e2acb41f8b1e03ca81cc1d494827d21d202`
- `phase-2b1-offline-acquisition-report.json`: `0c5827e66452c86f8edd22572ac238d749591ff0a55a40b3894b77e021ec864d`

The gate report's own file hash is intentionally not embedded in itself because a cryptographic
self-hash cannot be represented without changing the hashed bytes. Recompute all three immutable
artifact hashes with the command below.

## Independent recomputation

Run against a migrated disposable PostgreSQL database containing the governed source, approved
Phase 1 registration, and six instruments. This performs database writes for planning only and no
HTTP/provider request:

```bash
POSTGRES_DB="$DISPOSABLE_DB" .venv/bin/python manage.py report_failed_break_acquisition_plan \
  --plan-file docs/strategy/failed-break/v1/phase-2b1-acquisition-plan.json \
  > /tmp/phase-2b1-offline-acquisition-report.json && \
cmp /tmp/phase-2b1-offline-acquisition-report.json \
  docs/strategy/failed-break/v1/phase-2b1-offline-acquisition-report.json && \
shasum -a 256 \
  docs/strategy/failed-break/v1/phase-2b1-acquisition-plan.json \
  docs/strategy/failed-break/v1/phase-2b1-offline-acquisition-report.json \
  docs/strategy/failed-break/v1/phase-2b1-acquisition-gate-report.md
```

Two isolated databases were used for the gate. The governed source/strategy primary keys were
`1/1` in the first and `2/2` in the second. Their complete reports compared byte-for-byte,
including the plan SHA, dataset-manifest SHA, all 84 request hashes, all 84 logical keys, and the
ordered-manifest SHA.

## Safety conclusion

The artifacts contain stable selectors and canonical request intent only. They contain no database
primary keys, credentials, account IDs, authorization headers, raw provider URLs, or downloaded
candles. No OANDA client was created and no acquisition was executed while producing this gate.
