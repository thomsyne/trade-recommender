# V2 exploratory-return execution authorization readiness

## Decision

The existing immutable `research.JobRun` is sufficient. Exactly-once concurrency remains enforced by the PostgreSQL UNIQUE constraint on `research_jobrun.idempotency_key`; an `IntegrityError` is a terminal refusal and is never converted into success. No migration, calculator change, outcome-adapter change, cohort change, cost-policy change, or persistence-model change is required.

The fixed authorization permits one future invocation of:

`.venv/bin/python manage.py calculate_exploratory_returns_v2 --execute`

It does not execute or preview that result. Retry, resume, replacement, filtering, policy tuning, promotion, live trading, provider access, production access, and deployment remain prohibited.

## Runtime boundary

Before importing the outcome adapter, the loader verifies canonical authorization bytes, file and self hashes, every upstream artifact and source pin, native arm64 `.venv/bin/python`, the compatible Postgres.app PATH entry, the exact research database and Unix-socket settings, zero connection persistence, absent provider/API credential variables, and the local-socket-only sandbox attestation.

Before the first outcome-bearing query, the transaction verifies:

- exact `market` migration 0027 and `research` migration 0015;
- local `trade_recommender_research` database identity;
- accepted dataset, registration, contract, StrategyVersion, S0 and S1 semantic identities;
- accepted application-count fingerprint and 132 successful attempt-1 chains;
- exact 82-event geometry identity and 186 non-additive memberships;
- absence of the governed return-result JobRun and idempotency key.

The default command runs those checks inside `SET TRANSACTION READ ONLY`. Its SQL auditor rejects mutations, OHLC/entry-geometry columns, and non-count access to outcome tables. The permitted query purposes and column categories are:

- `django_migrations`: app, name, count and latest-name aggregation;
- dataset/registration/contract: IDs, semantic names, versions, manifest, contract, inventory, configuration and report hashes;
- strategy/parameter manifest: IDs, semantic identities, detector identity, content and manifest hashes;
- accepted S0/S1 JobRuns: IDs, job identities, strategy/dataset foreign keys, configuration hashes, status, and accepted return-blind evidence documents;
- acquisition lineage: attempt number, ingestion status, rejected count and dataset relationship;
- application tables: `COUNT(*)` only for the pristine-state fingerprint;
- prospective result: governed `research_jobrun.idempotency_key` existence only.

No candle OHLC, spread, entry/stop/target price, post-entry conversion price, terminal event, return, P&L, equity, drawdown, or performance field is permitted.

The execution is bounded by a 900-second wall-clock timer and a 1 GiB address-space ceiling. The memory ceiling is more than nine times the measured 110,280,704-byte synthetic peak, while remaining fail-closed; it is not a production-runtime prediction. Pre- and post-operation non-overwriting backups, mode 0600, SHA-256 sidecars, and successful `pg_restore --list` remain mandatory operational prerequisites.

## Return-blind persistent readiness

The governed default command completed with `AUTHORIZED_NOT_EXECUTED`, 82 events, zero outcome queries, and zero writes under a sandbox denying every network path except `/private/tmp/.s.PGSQL.5432`. The inspected persistent state matched the accepted application fingerprint and contained no return-result idempotency key. The later additive migration-selector check is covered by focused refusal tests; no execution command was invoked.

## Synthetic disposable PostgreSQL rehearsal

The committed rehearsal uses an explicitly prefixed disposable database containing only a minimal synthetic `research_jobrun` table. It does not restore or copy research evidence.

- 82-event adapter/calculator/PostgreSQL persistence: 0.798028 seconds.
- Peak RSS: 110,280,704 bytes.
- Successful phase calls: one lineage check, one sealed synthetic preload, one duplicate check, one insert and one readback.
- Rows written: one synthetic `research_jobrun`; every other application table zero.
- Repeat invocation: refused.
- Concurrent invocations: one commit and one PostgreSQL UNIQUE-constraint refusal.
- Injected insert and readback failures: zero surviving rows.
- Canonical result and all section hashes reconstructed after readback.
- Progress remained count/stage-only.

The disposable database `exploratory_return_auth_synthetic_20260904_1418` was dropped after confirming no active session used it.
