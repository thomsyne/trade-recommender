# Verification record and reproduction

This record distinguishes original-base failure, intermediate diagnostics and
final available-evidence verification. None is a production activation approval.

## Final combined results

| Exact PostgreSQL version | Executed | Result | Test time |
|---|---:|---|---:|
| 15.14 | 1,456 | OK, zero failures/errors/skips | 1,235.804 s |
| 17.6 | 1,456 | OK, zero failures/errors/skips | 1,243.058 s |

Each run explicitly excluded the same six restore-required tests listed below;
1,462 tests were discoverable. No other tests were dropped. Both fresh-head
migration/no-op checks preserve 99 domain tables, row/sequence state and exact
recorder/catalog fingerprints. Both clean server restarts preserve fresh/restored
database fingerprints. Ruff lint/format, Django check, migration-drift check,
compileall, Terraform formatting and all listed offline CI script tests pass.

## Original base and intermediate diagnostics

The original base cannot build an empty test database on either PostgreSQL 15.14
or 17.6: `market.0027_gate8i_final_dataset_acceptance` raises
`Gate 8I requires the accepted complete successor acquisition` before tests run.
There is therefore no original-base full-suite pass or set of executed testcase
failures to compare. No fake migration was used to obtain a base pass.

After genuine empty bootstrap became possible, the first installed-head diagnostic
ran 1,447 tests with 260 errors and two failures. The old historical fixtures tried
to undo irreversible current history. The other issues were an impossible accepted
fixture, an old Gate5 catalog expectation, a superuser role assertion and a stale
S1 refusal expectation. Historical tests now own separate databases; application
behavior was not weakened to make them pass.

The inherited PG15 intermediate run completed all 1,448 available tests in
3,783.220 s with six errors and two failures. The first actual parallel PG17 run
completed 1,456 in 1,278.648 s with three errors and five failures. Their union of
exact failing identities is below; all are targeted by subsequent corrections.

| Class (module prefix retained) | Test suffixes | Diagnosis |
|---|---|---|
| `market.tests.test_gate7a_acquisition_canary.Gate7AActivationTests` | `test_command_success_stores_exactly_the_sealed_series_once` | Current-model delete collector followed a relationship absent in the historical graph; use historical model deletion |
| Same class | `test_invalid_price_failure_is_terminal_and_sanitized` | A price substring matched timestamp seconds; still reject raw JSON price values and every secret/OHLC marker |
| `market.tests.test_zzzzzzz_gate7a_migration.Gate7ATruncateGuardTests` | `test_direct_multi_table_and_cascade_truncates_fail_without_data_loss`, `test_governed_row_deletes_remain_rejected` | Missed historical isolation |
| `research.tests.test_migrations.Phase2ADataMigrationTests` | `test_injected_rewrite_failure_rolls_back_data_and_trigger_removal`, `test_multi_book_rewrite_is_reversible_and_preserves_protection`, `test_preflight_rejects_entry_pending_and_mismatched_job_lineage` | Missed research historical isolation |
| `market.tests.test_gate7b_audit_completeness.DeferredAuditEvidenceTests` | `test_eventless_terminal_transitions_are_rejected_at_commit` | Audit lookup omitted subject type and collided with another row's numeric ID |
| `research.tests.test_provider_observed_s1.ProviderObservedRunTests` | `test_cad_conversion_uses_latest_sealed_completion_strictly_before_entry` | Legacy completion still admits an older Friday close; assert the exact rate/time rather than incorrectly requiring None |
| `research.tests.test_exploratory_return_memory_v2.RuntimeBoundaryTests` | `test_corrected_boundary_permits_isolated_success`, `test_memory_error_and_partial_result_fail_closed`, `test_timeout_restores_state_and_terminates_worker` | Django daemon workers cannot launch child processes; execute this class in the parent and count it in the same result |

One PG17 diagnostic was deliberately interrupted after 626 tests when the runner
was found to flatten Django's parallel suite. Its partial `OK` is **not** full-suite
evidence. Filtering now happens before partitioning. The six runtime-boundary tests
run in the parent when parallel mode is requested; they are not excluded or mocked.

## Focused and external evidence

* Initial combined bootstrap/Gate8I/M15/Phase4-boundary selection: 67 tests each,
  green on PG15.14 (18.196 s) and PG17.6 (17.972 s).
* Expanded PG15 selection: 79 tests, green (68.255 s).
* Expanded PG17 selection: 126 tests, green (81.235 s).
* Final repair/bootstrap/real-child-process selection: PG17 23 tests, green
  (35.848 s); PG15 35 tests including availability/calendar, green (55.200 s).
* Nine bootstrap scenarios include exact delta, no-op, reversal/reapply, populated
  delegation/atomic refusal, catalog drift, writer contention and representative
  recorder behavior. They execute through real Django migration machinery.
* Genuine deployed-backup restore and atomic populated refusal: both versions,
  same row/sequence digest; see [external actions](external-actions.md).
* Synthetic operational probes: both versions green; measured limits, host and
  interpretation boundaries are in [operations](operations.md).

## Explicit restore-required exclusions

The unchanged class
`research.tests.test_failed_break_detector_v2_queries.DetectorV2QueryBudgetTests`
contains six tests whose fixture fabricates accepted sealed identities rejected by
the genuine guards. The available-evidence runner prints each excluded full ID:

* `test_contract_identity_as_dataset_name_is_refused`
* `test_dataset_name_as_contract_identity_is_refused`
* `test_every_other_pinned_identity_mismatch_remains_fail_closed`
* `test_every_registration_identity_mismatch_remains_fail_closed`
* `test_exact_accepted_dataset3_identity_uses_one_registration_query`
* `test_preload_query_budget_is_three_independent_of_row_count`

The default runner is unchanged and still exposes that fixture's setup failure.
A partitioned pass is not an unqualified default-suite pass. Genuine accepted
populated success and already-applied-0027 restore/no-op proof also remain gates;
the current deployed backup ends at 0023 and cannot supply them.

## Reproduction and protected behavior

Supply only disposable database credentials through a cleared environment, with
pgcrypto installed and a test owner able to create databases/roles. Run focused
tests before the combined suite. Optional parallel execution requires `tblib` for
traceback transport; it is test tooling, not an application runtime dependency.

```sh
POSTGRES_CONN_MAX_AGE=0 .venv/bin/python manage.py test --noinput --parallel 4 \
  --testrunner market.tests.phase45_runner.AvailableEvidenceRunner
make check
terraform fmt -check -recursive infra
```

Also run the offline CI IAM, bootstrap-host, remote-deploy, backup, infra-policy and
production-compose test scripts, not the deployment scripts themselves.
The application descriptor remains `market-state-descriptor@0.12.0`, digest
`9213b548d3e6c6656805d2cf230c242926f08a42112373d7518d685384b9f7d3`.
Scheduled live scope remains D/H1/H4/W; M15 stays dormant. Published migrations,
forecasts, operations, technical formulas and decision eligibility are unchanged.

## Local handoff and cleanup

The four local commits on `phase4.5/architecture-stabilization` separately cover
bootstrap/isolation, architecture/availability, operations/calendar and Phase5
readiness/evidence. They are not pushed. Live `git ls-remote` confirmed main remains
`62cf0a095407b1ec29d9c4999ccc56de38fee9d8`, matching local `main` and `origin/main`;
the Phase4.5 branch does not exist on the remote. Other worktrees were untouched.

Both owned PostgreSQL servers stopped cleanly. Their data directories, source
builds, private downloaded backup, temporary restart script and raw logs were
removed. The test-only `tblib` installation was uninstalled. No builds, tests,
restores or task servers remain running. The deployed environment and source
backup were not mutated; [external actions](external-actions.md) records the exact
backup version, read-only commands, restoration results and unmeasured costs.

Review starts at [the acceptance matrix](acceptance.md). Independent review and
the explicit accepted-restore/deployment gates remain necessary; this handoff does
not authorize activation or reinterpret Phase4 evidence as a trading signal.
