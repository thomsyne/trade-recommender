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
- `make check`: Ruff, formatting, Django check, no pending migrations and
  compileall pass. `git diff --check` passes.
- Exact checkpoint archive with all 18 new tests: **3 failing subtests,
  16 errors**, from absent commands/contracts/fields and missing drift checks;
  all pass on the implementation.
- Populated checkpoint upgrade→0037→0036→0037: every application table's count
  and complete JSON row SHA-256 unchanged at each stage. Includes existing
  definition/snapshot/observation rows; migration history is excluded by design.
  **549 rows across 110 tables**, fingerprint
  `7a0b3787422b322d1ef9d6f067f38b67bae2f9cb9f42e273fb15ade62c027d83`.
- Broad at committed code HEAD
  [`398feb3`](https://github.com/thomsyne/trade-recommender/commit/398feb35accff746574b8959f73aaecc46a2cecd):
  **1,044 tests, 2 failures/238 errors** in 385.740 seconds. No new or changed
  failing identities, terminal causes or repeated occurrences versus the retained
  verified checkpoint. Both sorted identity/cause/occurrence fingerprints are
  `bff7b147a631249e2fc36f278dc9a5afc664fb387032e999dd1da8e1dfc3b6ee`.
  The retained `results.json` itself still has its recorded SHA-256
  `f92b05da7248dd75e8ae810a7be7e42813bb263ae082db71c78c720236b204bb`.
  The exact final broad log hash is
  `135e783d676e80bade7d4a2a0cdb1cd70d3f778a9b900b397811aecf7388852b`.
  Remaining causes are unchanged irreversible forecasts0031 (238 occurrences),
  the Gate5 installed-function MD5 assertion, and the bootstrap-superuser assertion.
  The broad suite is **not green**; these failures were neither repaired nor waived.
- **164 protected source/migration files are byte-identical to the checkpoint**:
  forecasts, operations, settings, technicals, live acquisition/schedules and all
  historical market migrations. Inventory SHA-256:
  `deb01f6b8247d1686c57cd85490714c76dd19968cc162f97fe315e55b1ea1ae0`.
  H1/H4/D/W live intervals unchanged; zero schedules and zero direct consumer/drift
  findings in the disposable preservation database. Prior technical output
  fingerprint is retained, not represented as a new performance measurement.

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
Only verification documentation changes follow the tested code commit. No code
changes follow the final broad run. Research's full inherited non-green suite was
not rerun for this bounded task; direct event/macro Phase4 tests and all affected
market/operations tests were run.

## Log fingerprints and cleanup

Raw synthetic logs and database archives were removed with owned resources;
these SHA-256 values identify the executed checks, not claimed green substitutes:

| Check | Log SHA-256 |
|---|---|
| Focused 205 | `9da2d7cdc4aff1350b50efbc865e13a872efb5259bf3d4e76e5a8e88bfdf34ba` |
| Checkpoint red 18 | `ec16a102e4101de2d8a76489f917c5d4bb7a2ce161a987ae26a46db2641f4a90` |
| Final historical parity 10 | `4e38079cc769c8be41ca3437fe4a29719634d3a82fca34d01ce0dfae45010317` |
| Affected 153 | `85c3861b3c690b31a7e46171f0a17d470114085457985e012fd40841e88734d1` |
| Final make check | `73b6ab6b97c6944121a0e02839c3af90b7e34c5323d1e13bac8b33434fe2c6b6` |
| Final populated roundtrip | `33ad46d47df9d8d38ebc701d34b38eab08b60da8573e4408a3270d087a9ed04e` |

The task-owned PostgreSQL cluster on socket port 55493 was stopped, its socket
absence verified, and its databases, test roles, checkpoint archives and logs
removed. No task-owned worktree or temporary script remains. The four pre-existing
other worktrees were untouched. `git ls-remote` confirms live main still equals
local main/origin-main `a3fbe6ce7fc08895c5696a2a25744f46e5d6e284`, with no remote
Phase4 branch. No push, PR, deploy, activation, provider, production, AWS, OANDA
or `.env.local` access occurred. Final follow-through is documentation only;
acceptance remains superseded pending PM verification.
