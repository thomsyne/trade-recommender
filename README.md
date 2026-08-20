# FX Forecast Lab

A private, single-user FX forecasting research instrument. Trustworthy market
data now feeds immutable, prospectively scored forecast contracts before any
LLM forecasting is permitted. Official macro research is preserved in a
separate point-in-time evidence ledger.

> Development fixtures are invented and visibly labelled. Nothing in this
> repository is trading advice or a live-order system.

## What works now

- PostgreSQL-backed Django application with owner authentication;
- canonical USD/CAD, GBP/USD, EUR/GBP, and EUR/USD instruments;
- OANDA v20 daily/H4 bid-and-ask retrieval with explicit unsmoothed New York
  alignment and completed-candle filtering;
- fail-closed quality checks for timestamps, gaps, duplicates, OHLC shape,
  crossed bid/ask, completeness, and volume;
- immutable retrieval manifests and database-enforced append-only audit events;
- deterministic ATR, EWMA, prior levels, and local pivot support/resistance;
- immutable versioned 20-session macro and five-session tactical targets;
- locked mechanical EWMA baselines, explicit abstention, deterministic
  resolution, and multiclass Brier scoring;
- governed Claude recommendations from fresh immutable evidence, strict
  evidence-ID citations, explicit abstention, audit metadata, and spend caps;
- prospective five-session recommendation resolution, multiclass Brier scoring,
  directional hit rates, and guarded calibration reporting;
- idempotent PostgreSQL job queue, scheduler, worker, retries, and backoff;
- bounded allowlisted RSS/API retrieval with SSRF, redirect, XML, type, and
  response-size protections;
- immutable official release snapshots, policy-rate vintages, provenance,
  deduplication, discrepancy tracking, and rights metadata;
- Today, Decision, Timeline, market workspace, Research, and Operations interfaces;
- deterministic fixture data so every screen works before credentials exist.

Article/full-text research, paper positions, paid providers, and AWS deployment
are deliberately not implemented yet.
See the [project map](docs/project-map.md) for those boundaries.

## Fresh orb setup

```bash
./.agents/setup
make test
make dev
```

`make dev` starts the supervised web service and prints an Amp portal URL. In
development, sign in with `owner` / `orb-demo-only`. Override the password with
`DEMO_OWNER_PASSWORD` before running setup. This fixture credential must never
be used in deployment.

Setup installs PostgreSQL, creates a local development role/database, creates a
virtual environment, installs pinned dependencies, migrates, and seeds the
four canonical instruments. It is safe to run repeatedly.

## OANDA practice data

Create a free OANDA practice account and expose these secrets to the process;
never commit or paste them into chat:

```bash
export OANDA_API_KEY_TEST='...'
export OANDA_ACCOUNT_ID='...'
export OANDA_ENVIRONMENT='practice'
./.agents/resume
.venv/bin/python manage.py ingest_oanda USD_CAD H4 --days 14
```

`OANDA_TOKEN` remains a supported alias. The candle endpoint does not need the
account ID today, but retaining the separate setting avoids conflating
credentials when account reconciliation is added. Review
[OANDA provider constraints](docs/providers/oanda.md) first.

## Commands

| Command | Purpose |
|---|---|
| `make check` | Django checks, migration drift, and Python compilation |
| `make test` | Full PostgreSQL-backed test suite |
| `make dev` | Start/reuse the supervised Amp portal service |
| `make worker` | Run the durable worker loop |
| `make scheduler` | Run the durable scheduler loop |
| `make ingest` | Show required arguments for direct OANDA ingestion |
| `make baseline` | Lock one macro and tactical mechanical baseline per pair |
| `make resolve` | Resolve every forecast whose later sessions are available |
| `make recommend` | Generate governed recommendations from fresh pair evidence |

Docker Compose describes the eventual single-host process topology and can be
used on a machine with Docker via `docker compose up --build`. It is a local
development topology, not the hardened AWS deployment.

## Documentation

- [Architecture](docs/architecture.md)
- [Project map and roadmap](docs/project-map.md)
- [Current handoff](docs/handoff.md)
- [OANDA provider contract](docs/providers/oanda.md)
- [Forecast contract](docs/forecast-contract.md)
- [Governed recommendation contract](docs/recommendation-contract.md)
- [Research ingestion contract](docs/research-ingestion.md)
