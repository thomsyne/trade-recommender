# Correction-cycle verification

This records engineering checks, not independent acceptance or holdout release.
Revision 3 remains frozen; these checks do not change its sources or registration.

## Focused checks

The seven R1–R5 reproductions failed on revision 2 before correction. The preserved
private log is `corrections-red.log` under `.candidate-data/phase55-v1/`.
The corrected focused run executed 60 tests: 54 passed and six database-dependent
tests skipped. Disposable UTF8 PG15 and PG17 focused runs each passed 116 tests.
An initial SQL_ASCII PG15 setup failed; its log is retained, not counted as a pass.

Static lint/format checks, Django checks and migration-drift checks passed. The
protected implementation/migration diff was empty. Existing revision 1/2 artifact
hashes, checkpoint manifests and registration bodies/acquisition clocks were
checked without rewriting those artifacts. The metadata-only coverage audit used
SQL blob-read denial and a decompression sentinel; it matched the frozen audit.

The corrected English renderer was also exercised against all 975 existing
development reports. Canonical JSON round trips and reversed scenario dictionaries
produced identical English for every report, matching all 975 original stored text
files. Both original file hashes per report still matched the old index. This is
renderer-determinism evidence only, not semantic recertification of old reports;
successor report publication still requires the complete replay boundary.

## Full PG17 run failed with two errors

The complete run finished, rather than being interrupted: 1,580 tests ran in
4,699.895 seconds, exit 1, two errors. It is **not a suite pass**.

- `DetectorV2QueryBudgetTests.setUpTestData` failed the canonical discovery-plan
  guard. The same setup error reproduced on unchanged merged main
  `b850c4ea618c34397e86fd8133b7255ff972f8ba`, in an isolated worktree/database.
- `LiveObservationIdentityTests.test_out_of_order_and_repeated_revisions_are_idempotent`
  failed the observation-lineage future-timestamp guard. The complete 21-test
  class repeated that error on the candidate. The single test and then the full
  class passed on merged main. Therefore this error was **not reproduced on main**.
  The live ingestion implementation, migrations and test file are unchanged.
  A subsequent 30-sample, read-only clock bracketing check found Docker PG17 server
  timestamps earlier than the Mac timestamp taken before the request in 27 samples,
  by up to 0.672 ms. This establishes clock skew and is consistent with the failure,
  but does not prove its cause. No clock, timestamp or admission guard was altered
  to make a check pass. The failed broad result remains a verification limitation.

Logs preserve the complete suite, base reproduction, candidate/base class rechecks
and clock measurements. No further broad rerun was used to erase the failed result.

## Resource cleanup and remaining verification

Both owned PG15 clusters were stopped and deleted. After the PG17 checks, the owned
`phase55-correction-pg17` container and its disposable data were removed. The owned
temporary merged-base worktree `/tmp/phase55-correction-base.Zk15F5` was removed
after confirming it was clean. Other worktrees, containers and the Docker daemon
were left alone. No production database or provider trading endpoint was used.

Development replay and the complete successor-report reconciliation are recorded
separately when finished. Partial replay output is not evidence of a complete grid.
The holdout remains sealed and was not opened during these correction checks.
