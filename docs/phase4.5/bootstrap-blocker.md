# Checkpoint 1 blocked: empty bootstrap versus historical acceptance

Historical investigation record, superseded by the authorized narrow replacement
design and [checkpoint-1.md](checkpoint-1.md). The statements below describe the
pre-authorization worktree, not the current implementation. Genuine accepted
restore proof remains a mandatory pre-deployment gate, not a bootstrap bypass.

This is a reproducible architectural conflict, not a waived test failure or
Phase 4.5 completion. No application, test, migration or CI code has changed.

## Direct evidence

At base `62cf0a095407b1ec29d9c4999ccc56de38fee9d8`, a newly initialized
task-owned PostgreSQL 15.19 cluster, UTF-8/C locale, received an empty database.
The process environment was cleared and only disposable connection settings were
supplied. `python manage.py migrate --noinput` failed with:

`RuntimeError: Gate 8I requires the accepted complete successor acquisition`

The last applied market migration was
`0026_gate8g_successor_acquisition_activation`. Both
`market_historicalingestionattempt` and `market_candle` had zero rows.
No migration was faked, no SQL guard was repaired or disabled, and no existing
database or external provider was accessed. PostgreSQL 15.19 is diagnostic
evidence only, not the requested 15.14/17.6 certification.

`market/migrations/0027_gate8i_final_dataset_acceptance.py`, lines 160–177,
requires a pinned successor plan with exactly 132 successful first attempts and
365,055 summed stored candles. Its forward operation checks that acceptance state
before installing the prospective registration validator. It has no empty-graph
branch. A later ordinary forward migration cannot run before this prerequisite.

`market/tests/historical_database.py` currently avoids that prerequisite with
`migrate(..., fake=True)`. Retaining this would leave the predecessor registration
validator installed, so it cannot certify the true current-state schema.
Fabricating accepted acquisition records would not be honest disposable evidence.

The other inherited obstruction, `forecasts.0031_phase3_observation_integrity`,
uses `RunSQL` without reverse SQL. That rollback problem can be solved by creating
historical graphs from empty disposable databases; it does not justify altering
irreversibility or excluding ordinary regression tests.

## Required scope decision

The requested combination of an honest current-state/fresh migration harness,
unchanged historical migrations, no production behavior changes in checkpoint 1,
and no runtime SQL repair cannot bootstrap this graph without genuine accepted
acquisition evidence. Such evidence is not available through the authorized
disposable-only workflow. A bootstrap bypass must not be silently treated as
certification or hidden among historical-test exclusions.

Recommended resolution: explicitly permit a **new replacement/squashed bootstrap
migration** for empty installations, leaving original migration files and already
applied production history untouched. Its empty path must install the exact
current durable guards without asserting any acquisition acceptance; populated
or contradictory partial histories must retain their original checks. This is a
change to installation behavior and needs an explicit exception to checkpoint 1's
no-production-behavior-change constraint. Exact installed catalog comparisons,
fresh and populated paths, and partial-history refusal tests are mandatory before
using it as the ordinary test baseline.

An ordinary trailing forward migration alone is not this solution. No replacement
migration has been authored pending the scope decision.

## Acceptance mapping and unperformed work

Acceptance gates 1a/1b/2c are blocked on bootstrap policy. Gates 2a/2b/3a–3c/4a
remain unimplemented. No broad suite, failing-identity differential, benchmarks,
exact-version matrix, populated migration preservation or protected semantic
fingerprints are claimed. No checkpoint is marked complete or self-accepted.

The acceptance matrix was written before any implementation edit. The private
cluster was stopped and its directory removed after the diagnostic. Only these
two documentation files are retained; no raw log, fixture database or machine
path is part of the handoff. The four requested engineering commits have not
been created; a documentation-only checkpoint preserves the blocked investigation.
