# Local correction evidence

Synthetic, disposable PostgreSQL evidence only. No provider, production, AWS,
deployment, or schedule activation was involved. These artifacts are engineering
measurements, not acceptance or a production capacity claim.

- `performance.json`: actual SQL, EXPLAIN ANALYZE/BUFFERS, 200 and 3,501 H1
  observations, build and persistence/verification query counts and latency,
  canonical JSON bytes, PostgreSQL heap/index/TOAST and column storage.
- `research-performance.json`: 3,501 H1 observations, 201 event vintages and
  200 macro observation revisions. Includes the reschedule-out-of-window case.
- `preservation.json`: table row counts and fingerprints before/after applying
  0034 to a fixture populated by the starting committed implementation.
- `protected.json`: source-file SHA-256 and an asymmetric 28-candle technical
  output fingerprint, compared at exact main base, starting commit, and correction.
- `differential.json`: exact failing identities and normalized exception causes
  from `manage.py test market operations forecasts --keepdb --noinput -v 2` on
  equivalently bootstrapped databases. Repeated teardown errors are retained per
  identity; raw failure counts are not unique test counts.
- `concurrency.json`: six non-superuser writers, one snapshot and one created
  result; all outputs equal.
- `checks.txt`: test/check output, migration accommodation and reversal evidence,
  protected checks, cleanup and final Git/remote verification.
- `changed-files.txt`: correction paths relative to the starting implementation.
- `*.py.txt`: the synthetic measurement/preservation probes, retained as text for
  reproducibility. Run only in an explicitly created disposable database through
  a sanitized environment as described below; these scripts insert fixtures.

All database bootstraps used UTF-8/template0, migrated normally to market 0026,
faked **only** the documented data-dependent market 0027, then migrated the
remaining graph normally. This is not an unqualified fresh-install claim.
The last performance database was cloned from the already normally migrated,
emptied disposable test database; it did not reuse prior performance fixtures.

To reproduce the probes, bootstrap a new private UTF-8 PostgreSQL cluster and
database using the runbook's 0027 accommodation. Run from the repository root,
with `env -i`, an explicit PATH/HOME, `DJANGO_SETTINGS_MODULE=config.settings`,
and explicit `POSTGRES_HOST` (the new Unix socket), `POSTGRES_PORT`,
`POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_CONN_MAX_AGE=0`. Invoke the repository's
`.venv/bin/python` on `performance.py.txt`, then `concurrency.py.txt`, then
`research_performance.py.txt`, redirecting stdout to new artifacts. Use a new DB
for each repeat; the probes intentionally create unique fixture identities.
For preservation, bootstrap the starting checkout, run `preservation.py.txt seed`,
migrate forward with the correction checkout and compare `preservation.py.txt
inspect`. Never substitute an existing unrelated database or source `.env.local`.

RSS values cover the whole Python process, including synthetic ingestion. They
are not isolated snapshot working-set measurements. WAL was not measured because
other disposable databases shared the cluster. Production scheduler load,
multi-instrument throughput, retention growth, and production capacity remain
unmeasured. PostgreSQL plans are planner choices for these fixtures, not a promise
that every selectivity/revision density uses the same plan.
