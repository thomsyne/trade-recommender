# Mandatory omission verification — not acceptance

Checkpoint: `bc4469b37d7cc0511f55061085b78bb5f8ec4d60`; descriptor 0.12.0,
forward migration 0037. Acceptance remains superseded pending requirements-only
PM verification. No production/environment/provider access or activation.

Verification uses a task-owned socket-only PostgreSQL 15.5 UTF-8 cluster,
port 55493, with separate disposable checkpoint and final databases. Bootstrap
normally applies market0026, fakes only the unchanged data-dependent0027, then
normally applies the remaining graph. This is not an unqualified fresh-install
or PostgreSQL17 certification. No `.env.local` is loaded.

## Executed checks

- Focused Phase4/M15: **205 pass** (the 13 modules from `verify.sh.txt` plus
  `market.tests.test_phase4_omissions`, 18 new tests).
- The new tests cover all-table count/content fingerprints and traced SELECT-only
  SQL for empty/populated commands, nonzero exits, malformed/bounded definitions
  and inputs, event endpoints/statuses/overlap/DST/revisions, liquidity normalization,
  pending/gaps/equality/expiry/invalidation, raw chronology guards, exact dependency
  membership and persisted future-suffix invariance.
- Historical migration→SQL/Python parity: **10 pass**, exact existing command
  `market.tests.test_zzzzzzzz_live_observation_migration
  market.tests.test_observation_lineage.SqlPythonParityTests`.
- Affected: **153 tests, one inherited failure**, exact labels from the retained
  `results.json` affected command. Only
  `LiveEvidenceDatabaseProtectionTests.test_connection_role_is_not_a_superuser`
  fails with `AssertionError: 'on' != 'off'`. Non-superuser race tests pass; the
  bootstrap-superuser assertion is not suppressed or weakened.
- `make check`: Ruff, format (469 files), Django check, no pending migrations and
  compileall pass. `git diff --check` passes.
- Exact checkpoint archive with the first 17 new tests: **3 failing subtests,
  15 errors**, from absent commands/contracts/fields and missing drift checks;
  all pass on the implementation. A final full regression/broad run is pending.
- Populated checkpoint upgrade→0037→0036→0037: every application table's count
  and complete JSON row SHA-256 unchanged at each stage. Includes existing
  definition/snapshot/observation rows; migration history is excluded by design.

## Reproduction and remaining limits

Use the private-cluster bootstrap and environment variables documented by
`verify.sh.txt`, then add `market.tests.test_phase4_omissions` to focused tests.
Use `manage.py test market operations forecasts --keepdb --noinput -v 2` for
the broad run. Compare its exact failing headings/terminal causes/occurrences
with `eight/compare_broad.py.txt` and the retained checkpoint fingerprint, not
just failure counts. Run `preservation.py.txt seed` from a checkpoint archive,
then compare its `inspect` output after each migration step using the current
code. The script writes synthetic data only when explicitly passed `seed`.

The original production capacity, RSS/WAL, PostgreSQL17 and calendar-attestation
limitations remain. Consumer detection is a bounded direct-source scan, not a
dynamic/external information-flow proof. Event windows and liquidity expiry are
documented descriptive conventions, not calibrated trading rules. SQL enforces
shape/identity/chronology/dependencies; Python integrity supplies formula replay.
Final broad results, protected fingerprints and resource cleanup follow below.
