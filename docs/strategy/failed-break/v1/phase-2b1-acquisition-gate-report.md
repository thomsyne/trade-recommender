# Phase 2B.1 offline acquisition gate

**Status:** PASS — deterministic plan only; acquisition remains unexecuted.

## Frozen intent

- Acquisition contract/version: `failed-break-historical-acquisition` / `phase-2b1-v1`
- Source selector: `OANDA v20` / `oanda-v20-market-candles-v1`
- Strategy selector: `top-down-failed-break-continuation` / `failed-break-phase-1-freeze-v1`
- Instruments: AUD_USD, EUR_GBP, EUR_USD, GBP_USD, USD_CAD, USD_JPY
- Granularities: D, H1, W; combined bid/ask; New York 17:00; Friday weekly alignment
- Complete candles only; `includeFirst=true`; one provider request per logical chunk
- Per-instrument counts: D 2,567; H1 56,341; W 471
- Logical chunks: 84 (1 D + 12 H1 + 1 W per instrument)
- Total intended rows: 356,274
- All candle completions are strictly before 2019 in America/New_York.

## Stable results

- Plan SHA-256: `da4d050315fa5c528589bb073a80e26eec6da00dd7cbc5080a56dbd8b6383721`
- Dataset manifest SHA-256: `7b807646cf026e91f15444249ca5c1423ac9e4751c4778eb9546849ddc18689a`
- Ordered chunk manifest SHA-256: `dd0a9309c0ece6170b554581cfbf3b4ec8a9ad63a24c7b3a682b6948e58f87c9`
- `phase-2b1-acquisition-plan.json`: `6cf1197b22784812a7437e69db6df1b83ea83258efa118fabe902bcf41ed3086`
- `phase-2b1-offline-acquisition-report.json`: `4c7d98df2abd2ffb3142c50ad33702f041fe276d6bceb1f640a207e1436b6c8f`

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

The PostgreSQL-backed `HistoricalIdentityPortabilityTests` regression materializes the same
semantic plan twice with deliberately displaced source and strategy primary-key allocation and
compares the exact plan SHA, dataset-manifest SHA, all 84 request hashes, all 84 logical keys, and
the ordered-manifest SHA. Test database cleanup is deterministic and the test makes no network
calls.

## Safety conclusion

The artifacts contain stable selectors and canonical request intent only. They contain no database
primary keys, credentials, account IDs, authorization headers, raw provider URLs, or downloaded
candles. No OANDA client was created and no acquisition was executed while producing this gate.
