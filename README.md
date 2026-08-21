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
- hourly bid/ask paper setup tracking with immutable entries, adverse ambiguity
  handling, spread-aware exits, expiry, gross pips, and R-multiples;
- immutable optimistic/base/conservative financing and commission sensitivity
  with bounded New York rollover counts and separate net-pip/net-R views;
- hourly private OANDA account-term snapshots with prospective long/short
  financing schedules and explicit missing-commission state;
- prospective, capacity-limited paper-portfolio admission with immutable cohorts,
  automatic all-fit decisions, and owner selection for competing setups;
- an owner-only research inbox plus optional Gmail notifications delivered from
  the durable outbox with authenticated in-app decisions;
- immutable deterministic thesis, paper-execution, and reconciliation reviews
  with frozen cohorts, explicit missing denominators, source lineage, and an
  owner-only postmortem notebook;
- optional rights-cleared Sonnet postmortems with immutable method/spend audit,
  cited non-authoritative interpretations, quarantined source proposals, and a
  five-independent-cohort gate before owner-authorized challenger design;
- immutable champion/challenger experiment eras, frozen method and evaluation
  identities, daily append-only health assessments, dependence-balanced proper
  scores, uncertainty bounds, and owner-only non-activating promotion records;
- idempotent PostgreSQL job queue, scheduler, worker, retries, and backoff;
- fail-closed single-host AWS production deployment at
  `fx-forecast.thomsyne.dev` with an EIP-backed Route 53 A record and HTTPS,
  owner TOTP/recovery codes, throttled login, rollback readiness, and compressed
  S3 PostgreSQL backups;
- bounded allowlisted RSS/API retrieval with SSRF, redirect, XML, type, and
  response-size protections;
- immutable official release snapshots, policy-rate vintages, provenance,
  deduplication, discrepancy tracking, and rights metadata;
- Today, Decision, Timeline, market workspace, Research, and Operations interfaces;
- deterministic fixture data so every screen works before credentials exist.

Article/full-text research, exact account-specific cash/CAD returns, and paid
providers remain deliberately out of scope. AWS deployment is private,
paper/research-only, and documented in [deployment operations](docs/deployment.md).
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
account ID; prospective financing capture does. The ID is stored only as a
SHA-256 fingerprint and is never rendered or logged. Review
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
| `.venv/bin/python manage.py build_postmortems` | Freeze terminal deterministic review cohorts |
| `.venv/bin/python manage.py interpret_postmortems` | Interpret eligible contract-v3 postmortems when explicitly enabled |
| `.venv/bin/python manage.py refresh_experiments` | Append dependence-aware health assessments for registered experiment eras |

Docker Compose describes the eventual single-host process topology and can be
used on a machine with Docker via `docker compose up --build`. It is a local
development topology; the hardened topology is `deploy/compose.production.yaml`.

Bounded postmortem interpretation is off by default. To opt in, configure
`ANTHROPIC_API_KEY`, set `POSTMORTEM_INTERPRETATION_ENABLED=true`, and rerun
`seed_research` so the daily job is enabled. It has a separate US$20 monthly
default cap and never replaces deterministic review facts.

## Documentation

- [Architecture](docs/architecture.md)
- [Project map and roadmap](docs/project-map.md)
- [Current handoff](docs/handoff.md)
- [Gmail owner notifications](docs/gmail-notifications.md)
- [AWS deployment, backup, rollback, and restore](docs/deployment.md)
- [OANDA provider contract](docs/providers/oanda.md)
- [Forecast contract](docs/forecast-contract.md)
- [Governed recommendation contract](docs/recommendation-contract.md)
- [Research ingestion contract](docs/research-ingestion.md)
