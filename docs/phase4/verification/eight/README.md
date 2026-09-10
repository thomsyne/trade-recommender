# Eight-finding engineering verification — acceptance remains superseded

Response to the [independent review](https://ampcode.com/threads/T-01a08985-818d-7698-aa9c-f843744479db).
The [handoff](../../handoff.md) gives all eight dispositions; design §18 pins
the chosen policies. This evidence does not replace fresh independent re-review.

Starting checkout: clean `phase4/deterministic-market-state` at
[`0188ee5`](https://github.com/thomsyne/trade-recommender/commit/0188ee51f1d4c44664db195ed005aca9243d9800),
including correction
[`160681b`](https://github.com/thomsyne/trade-recommender/commit/160681bf280c5e82fabfe9ac4ac3520cf17be774).
Exact base, local main, cached origin/main, merge base and live remote main:
[`a3fbe6c`](https://github.com/thomsyne/trade-recommender/commit/a3fbe6ce7fc08895c5696a2a25744f46e5d6e284).
No remote Phase4 branch was present. No fetch, push, PR, deployment or activation.
The local commit containing this directory is the engineering checkpoint.

## Reproductions and passing checks

All ten new tests were first run against exact starting HEAD: 11 assertion
failures including both ORB session subcases, no errors (`reproduction.log.gz`).
The final expanded test file was copied to the same exact-start archive and run
again: 12 assertion failures, no errors (`reproduction-final-tests.log.gz`).
Only the regression test file was added to that archive; implementation and
migrations remained at the exact starting commit. The extra failure asserts the
new explicit physical failure timestamp rather than raising a missing-key error.

| Finding | Regression method(s), abbreviated |
|---|---|
| 1 | `test_future_candidate_cannot_change_old_identity`: future candidate and eligible suppressor |
| 2 | `test_pair_uses_canonical_code`: mutated currency column, identical macro output |
| 3 | `test_forged_macro_digest_rejected`, `test_earlier_latest_candle_rejected`: recomputed hashes, wrong digest/unrelated lineage, stale or omitted latest candle, non-superuser SQL |
| 4 | `test_unused_macro_history_does_not_change_identity`, `test_quality_note_is_irrelevant_and_facts_are_immutable`: unused period, editorial edit/replay, semantic edit refusal, zero-query frozen build |
| 5 | `test_orb_downstream_availability_in_both_sessions`: before/equality/after prerequisites, failure/retest, production wrapper, malformed chronology |
| 6 | `test_unrelated_early_observation_does_not_delay_zone`: unrelated prefix versus actual right-hand confirmation |
| 7 | `test_missing_exact_prior_day_is_unavailable`: exact D/W/month/session, missing/late arrival, weekend/month boundary |
| 8 | `test_compression_expansion_relationship_is_emitted`: causal/reversed ordering, missing interval, pending, strict percentile/inclusive body and window equality, future suffix |

Final ten regressions pass (`new-tests-final.log.gz`). Full focused suite:
**173 tests pass** (`focused-final.log.gz`), using these `market.tests` modules:
`test_m15_live_granularity`, `test_market_state_context`,
`test_market_state_features`, `test_market_state_liquidity`,
`test_market_state_ops`, `test_market_state_orb_fvg`,
`test_market_state_persistence`, `test_market_state_review_fixes`,
`test_market_state_structure`, `test_phase4_corrections`,
`test_phase4_eight_findings`, `test_phase4_semantic_boundary`.

Raw-SQL probes execute as a non-superuser role. Historical/malformed integrity
checks are in that suite and `historical-integrity.json`: unsupported old
definitions and contradictory metadata are reported, not rewritten or certified.
The runtime-role assertion separately passes as a disposable NOSUPERUSER role
(`runtime-role-retry.log.gz`); this role received disposable test-table TRUNCATE
permission after an initial teardown permission error, not application changes.

`project-checks.log.gz`: `make check` passes Ruff, format (458 files), Django,
makemigrations (no drift), and compileall. Retained probe scripts also AST-parse.
`git diff --check` passes. No UI appearance changes require rendering.

## Migration and exact-base comparisons

Only new migration 0035 changes the DB contract. The populated exact-start fixture
has **549 rows across 110 application tables, including one snapshot**. Every
table count and row fingerprint matches through **0034 → 0035 → 0034 → 0035**:
see the four `preservation-*-final.json` files and migration log. No historical
application data was modified. Exact historical sequence
`market.tests.test_zzzzzzzz_live_observation_migration` followed by
`market.tests.test_observation_lineage.SqlPythonParityTests`: **10 pass**,
with no self-repair (`historical-parity-final.log.gz`).

Broad command: `manage.py test market operations forecasts --keepdb --noinput -v 2`
on equivalently bootstrapped exact-base/final databases:

- Base: 838 tests, 2 failures, 244 errors.
- Final: 1,012 tests, 2 failures, 238 errors.
- **No introduced failing identities or terminal causes.** The same installed
  Gate5 body-hash assertion and bootstrap-superuser assertion fail. All error
  occurrences have the same irreversible forecasts0031 cause. Six removed
  occurrences reflect the earlier historical-isolation correction, not these fixes.

Research command: `manage.py test research --keepdb --noinput -v 2`:
348 tests at each revision, identical 22 errors: 20 irreversible migrations,
one `discovery plan conflicts with canonical contract` ProgrammingError, and
one `direct v2 S1 execution is disabled; use the governed management command`
V2S1GovernanceRefusal. **No introduced or removed identities/causes.**

`differential.json` and `research-differential.json` retain exact identities,
occurrence counts and terminal cause text; only memory addresses are normalized.
The raw logs are compressed losslessly. Reproduce comparisons after decompressing
with `python compare_broad.py.txt BASE_LOG FINAL_LOG`. Broad suites are **not green**.

## Performance, protection and resource isolation

Private PostgreSQL 15.5, Unix socket only, unique directory
`/tmp/phase4-eight.UDqTP2`, port 55483, bootstrap role `p4admin`. All Django commands
used `env -i`, PATH/HOME and explicit POSTGRES_HOST/PORT/USER/DB/CONN_MAX_AGE=0;
standalone probes additionally set DJANGO_SETTINGS_MODULE. No existing databases,
provider services, production, AWS, OANDA or `.env.local` were accessed. Exact
base/start trees were git archives, not changes to shared branches/worktrees.
Bootstrap normally migrated to market0026, faked only the documented
data-dependent0027, then normally migrated the rest. This is not an unqualified
fresh-install certification. Roles, test DBs and synthetic fixtures were unique
to this private cluster. Cleanup is recorded in `completion.json`.

`protected.json`: 92 protected source fingerprints match exact base/start/final.
`schedules.json`: empty disposable inventories, scheduled H1/H4/D/W only;
no M15 or descriptor activation, no forecast consumption. These are not claims
about an uninspected production schedule inventory.

Measured synthetic performance, with actual SQL and EXPLAIN ANALYZE/BUFFERS:

- `performance-final.json`: 3,501 H1 observations, six build queries, 0.1374s.
- `research-performance-final.json`: 201 events/200 macros, seven build queries,
  0.2669s; 103,101 evidence bytes. Includes research candidate selection plans.
- `guard-performance-final-hours.json`: indexed actual latest selection returns
  one row in 0.071ms. Dense no-duplicate INSERT runs the new evidence trigger in
  106.916ms and existing semantic trigger in 189.861ms.
- `concurrency-final.json`: six non-superuser writers, one snapshot, one created,
  identical outputs.

Probes use the retained parent-directory performance/research/preservation scripts
and `guard_performance.py.txt`. Run only in a newly created disposable database.
`dst-horizon-reproduction.log.gz` retains an additional failure found during
verification: SQL calendar-day horizons varied with caller timezone. Final0035
uses elapsed 24/168-hour horizons and the non-superuser regression covers DST.

Not measured/certified: production capacity, PostgreSQL17, isolated feature RSS,
WAL, exceptional-holiday calendars. Query plans are fixture-specific, not a
constant-work guarantee under arbitrary revision density. Python integrity still
owns full formula replay; SQL does not duplicate every market formula. Superuser
trigger bypass remains outside non-superuser enforcement. Acceptance stays
superseded pending fresh independent re-review.

`changed-files.txt` lists this correction's paths. `sha256.json` inventories every
retained artifact except itself; gzip uses deterministic mtime=0.
