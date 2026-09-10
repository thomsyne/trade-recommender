# Bootstrap and historical isolation evidence

Engineering verification, not rollout authority or independent acceptance.
Published migrations are unchanged. The replacement has exactly one `replaces`
entry and retains the published populated forward and guarded reverse.

## Installation contract

An empty application database at 0026 receives the exact Gate8I registration
validator, with no acquisition, registration, candle or audit evidence inserted.
All inspected non-framework tables are locked until transaction commit. Any
populated table routes to the unchanged original operation without fallback.
After locking, any enabled row-level security also delegates: caller-visible
emptiness cannot establish database emptiness. No RLS setting or policy is changed.
Unsupported relation kinds (including views, materialized views and foreign
tables), or missing historical market tables, delegate before attempting locks.
Catalog drift fails atomically. Framework exceptions are limited to Django's
migration recorder, content types and permissions; an auth user is not exempt.

Fresh full-head migration and second-run no-op passed on PostgreSQL **15.14** and
**17.6**, built with OpenSSL and pgcrypto. Both original base graphs fail at
published 0027 with `Gate 8I requires the accepted complete successor acquisition`.
The baseline therefore has no honestly bootstrapped full-suite result.

At full head the 99 inspected application tables contain only the two published
forecast seed rows (portfolio guard and policy activation); this is not an
empty-evidence claim about every later migration. The registration validator's
SHA-256 is `39e01cbf2748adbcb81d9b5f1079fd5004fdd5260e55af72dec8537f2b1b93bc`.

`test_gate8i_empty_bootstrap` checks empty installation, exact catalog delta,
no-op, reverse/reapply, metadata/audit/user/unknown-table populated refusal,
function and trigger drift, and a concurrent writer. Review regressions cover
empty/populated materialized views and a non-superuser database owner with
ENABLE + FORCE RLS, no policy, and one hidden SourceRegistry row. Both original
and replacement refuse with the exact accepted-successor prerequisite error;
recorder, functions, triggers, rows, sequences, relation kinds, RLS flags and
policies remain unchanged. The administrator still sees the hidden row.
Its recorder fixture is explicitly representative: it records original-0027 on an isolated 0026 graph
solely to prove that Django adds the replacement recorder row without executing
an operation. It does not represent a production restore or accepted evidence.

## Historical ownership

`HistoricalDatabaseMixin` creates one uniquely named database per scenario,
migrates a fresh historical graph, and drops the database after the test.
The normal runner database's recorder timestamps, function definitions,
constraints and triggers must remain identical. Irreversible migrations remain
irreversible. No shared-head rollback, fake bootstrap or runtime SQL repair is
used. Older service fixtures temporarily bind three runtime model column lists
to their historical model shapes; teardown restores those Python metadata lists.
Historical auth permissions are created through Django's normal permission API.

The first honest full-head diagnostic ran 1,447 tests on 17.6: 258 irreversible
rollback errors, one invalid accepted-dataset fixture setup error, one outdated
S1 refusal expectation, an old Gate5 catalog assertion on the current graph,
and a role assertion against the cluster administrator (260 errors, 2 failures).
These identities are diagnoses, not waived current-state regressions.

Checkpoint verification includes genuine-restore refusal on both exact versions.
After the bounded review corrections, fresh-head/no-op and all 51 focused
bootstrap/reversal/recorder/contention/runner/historical tests pass on both versions.
Each final available-evidence suite executes all 1,464 selected tests: PG15.14 in
1,508.326 s and PG17.6 in 1,508.445 s, zero failures/errors/skips. Only the six
exact pinned restore-required tests are excluded from 1,470 discoverable tests.
The real child-process tests remain executed, not waived. See
[verification](verification.md) for final results and intermediate failure identities.

## Explicit unavoidable exclusions and deployment gate

After access was explicitly authorized, the latest genuine deployed backup was
restored on both versions. It contains 41,699 rows in 101 non-recorder tables and
77 recorder rows; its market history ends at 0023, with no dataset registrations.
Normal 0024–0026 preserved all restored rows, application sequences and original
recorder identities/timestamps. Original and replacement 0027 both refused with
the same accepted-successor prerequisite error, atomically preserving the 0026
catalog, rows, sequences and recorder. The replacement called original.forward
exactly once. See [external action evidence](external-actions.md) and the opt-in
`market.tests.phase45_restore.verify` reproduction probe.

No genuine **accepted-acquisition** backup was found. Genuine populated-success
and already-applied-0027 recorder preservation remain **unproven**; the genuine
incomplete restore proves negative behavior, not acceptance. Before any rollout,
restore a genuine accepted backup into disposable 15.14 and 17.6 environments; compare all
rows, sequence state, original recorder IDs/timestamps, catalog and no-op results.
Only the replacement recorder row may be added to already-applied history.
Run populated original-versus-replacement behavior and guarded reversal there.
Failure or absence of that proof prohibits rollout.

The six tests in
`research.tests.test_failed_break_detector_v2_queries.DetectorV2QueryBudgetTests`
also depend on a fabricated sealed registration rejected by current governance.
They remain unchanged, pending an honest restore-backed fixture. The explicit
`market.tests.phase45_runner.AvailableEvidenceRunner` prints every excluded ID;
it is not the default runner and does not label these tests skipped or passed.
The waiver is an exact six-ID set pinned with its fixture-source SHA-256, not a
class prefix. Identity/source drift fails closed; an injected unlisted regression
is retained and its failing body executes. See [verification](verification.md).
No synthetic data in this work is accepted provider acquisition evidence.

## Reproduction

Use uniquely owned empty PostgreSQL databases with the exact versions and
pgcrypto installed; clear credentials and supply only disposable connection
settings. Run normal `manage.py migrate --noinput`, then repeat and compare
recorder/catalog. Run focused bootstrap, historical, M15 and semantic-boundary
modules first, followed by:

```sh
POSTGRES_CONN_MAX_AGE=0 .venv/bin/python manage.py test --noinput \
  --testrunner market.tests.phase45_runner.AvailableEvidenceRunner
make check
```

The default unfiltered suite still reports the restore-required fixture failure;
do not describe the partitioned result as an unqualified full-suite pass.
