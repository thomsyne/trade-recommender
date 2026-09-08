# Five-finding Phase 2 remediation

This is a bounded correction of the independent-review findings on
`phase2/g10-ingestion-only`, starting at `5d67c30e3b0528f157d22e53c83fec87b7c43ed3`.
Base and merge base are `61ff8bc021744b0b785843c994db422c9a742431` (`origin/main`),
which includes the required Phase 1 ancestor. Initial worktree was clean. Prior
acceptance records remain historical records; this correction requires independent
re-review and confers no production or strategy activation authority.

## Finding dispositions and policy

1. **Canonical acquisition windows:** both default and explicit aware starts are
   floored to the existing registered grid before provider access and persistence.
   H1/H4 use exact UTC instants admitted by the authoritative session predicate;
   D/W retain New York17:00, DST and Friday rules. The original increasing-range
   requirement is retained. The end remains unchanged, and only candles complete
   within the request are accepted. Each page filters leading/overlapping intervals
   according to its actual `includeFirst`; later pages overlap the last accepted
   candle, not the exclusive page end. Empty pages do not skip an unobserved
   boundary. Manifests record actual per-page `includeFirst` values. Migration0029
   and all existing evidence-integrity checks are unchanged.
2. **Dashboard semantics:** canonical seeding now enables collection eligibility
   for all twelve pairs, so absent-token demo data correctly says configuration
   is missing, not that inactive pairs are outside collection scope. Intentional
   collection disable, source unavailability, explicit schedule disable and normal
   scheduling are verified in rendered DOM/text for a decision pair and an
   ingestion-only pair. Templates/styles are unchanged; no unnecessary screenshot
   substitution for DOM semantics was used.
3. **Truthful onboarding health:** collection availability, freshness, requested
   coverage, technical presence and forbidden artifacts have distinct fields.
   Expected complete keys use the registered calendar, with a100,000-key bound.
   Source observations up to the successful run's finish and its returned count
   are checked against the request window. Earlier complete storage cannot hide
   a later partial response. Coverage samples are limited to five keys. States
   and exit semantics are documented in rollout.md; partial acquisition fails
   integrity even if the latest candle is recent or technicals exist.
4. **Semantic schedules:** all48 identities are validated by task and canonical
   parameters as well as name. Both disabled and enabled aliases fail integrity.
   Seeding refuses ambiguous duplicates transactionally; ordinary canonical
   metadata and latest-only-policy repairs preserve deadlines. Wrong task,
   parameters, interval, schedule type, timezone/local-time settings, recovery
   policy and enabled-state contradictions are rejected by the report. Exact
   simultaneous enabled deadlines are reported without resetting legacy phases.
5. **Direct CLI:** twelve choices come from `Instrument.Code`, and exactly four
   granularities come from the existing live/calendar domain. The CLI reaches the
   same authoritative task guard. Unsupported inputs fail, disabled instruments
   never construct a provider client, and ingestion-only runs retain isolation.

The rollback/canary documentation preserves the original four decision pairs and
all eight inactive onboarding pairs. No strategies, model behavior, M15/M1,
portfolio activation, historical backfill policy or historical evidence changed.

## Reproduction and verification evidence

New evidence is retained at:
`/Users/oluwatomisintaiwo/trade-recommender-artifacts/phase2-remediation-gbc6jm9p/`.
Original failing logs are preserved, including fixture-development mistakes rather
than rewriting them as successes.

- `before-fixes.log`: all five findings reproduced before implementation edits:
  unaligned-window failures, old dashboard wording, false health/partial coverage,
  unnoticed duplicate schedules and rejected CLI choices.
- `before-policy-and-clock.log`: exact pre-fix source archive separately reproduces
  `all` policy passing report checks, and H1/H4 current-time requests rejected by
  migration0029. Two tests: one assertion failure and two window subcase errors.
- `focused-second.log`:95 tests passed, covering early corrected windows/report/
  CLI cases, existing Phase2/OANDA/seed, dashboard readiness and diagnostics.
- `final-focused.log`:264 tests; accepted superuser assertion and two new test
  fixture omissions (required paper details/run parameters). Only fixture data
  was corrected; assertions and production constraints were preserved.
- `final-focused-corrected-fixtures.log`:264 tests,263 passed, accepted runtime-
  superuser assertion only; zero errors. Includes all Operations and Dashboard
  tests, all new remediation tests, Phase2's32 pair/granularity mocked ingestions,
  overlap/revision/lineage, real0030 migration, seed/queue, CLI and existing
  recommendation/paper/portfolio/sizing regression populations.

Every database/container resource used here was newly created for this remediation.
No earlier test database, production database, backup or restored research data was
used. PostgreSQL ran only at127.0.0.1:55593 with a new disposable role and database
names ending `_gbc6jm9p`. Only the documented0027 test-bootstrap accommodation was
recorded fake; other migrations ran genuinely. The main baseline schema ends at0029
and the branch at0030. Tests involving schema mutations ran serially.

The reusable command runner `run.py` in that evidence directory starts Python with
an explicitly constructed environment (no environment files or inherited secrets):

```sh
env -i PATH=/Applications/Postgres.app/Contents/Versions/latest/bin:/usr/bin:/bin \
  DYLD_LIBRARY_PATH=/Applications/Postgres.app/Contents/Versions/latest/lib \
  PSYCOPG_IMPL=python DJANGO_SECRET_KEY=remediation-test \
  POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55593 \
  POSTGRES_USER=remediation_test POSTGRES_DB=<new-disposable-bootstrap> \
  .venv/bin/python manage.py test <labels> --keepdb --noinput -v 2
```

Complete comparison command, identical on the exact main archive and branch:
`test market operations forecasts research dashboard --keepdb --noinput -v 2`.
Focused labels:
`market.tests.test_phase2_remediation market.tests.test_phase2_ingestion
market.tests.test_oanda market.tests.test_quality market.tests.test_freshness
market.tests.test_seed_canonical market.tests.test_terms market.tests.test_live_observations
market.tests.test_observation_lineage operations dashboard forecasts.tests.test_recommendations
forecasts.tests.test_portfolio forecasts.tests.test_sizing forecasts.tests.test_frozen_evidence
forecasts.tests.test_recommendation_batch`.

Static/CI checks: Ruff lint and format, Django check, migration drift, compileall,
diff whitespace, fail-closed configuration check with dummy settings, IAM policy
checker, stubbed bootstrap/remote-deploy/backup tests, infrastructure policy tests,
Compose config rendering and Terraform formatting. These tests execute no real AWS
or provider calls and no deployment. Commands/results are in `ci-results.json` and
`django-check-results.json`; all passed. `scope-integrity.json` records125 protected
files unchanged and both historical OANDA methods source-identical.

## Capacity and rollout unknowns

Estimates:24 new schedule identities,32 additional enabled jobs,249.143 additional
and373.714 total candle ingestion runs/day; approximately69,384 additional returned
records/day,4,920 initial returned records and1,248 new unique intervals/week.
Canonical flooring can add up to one interval to approximate window sizes. These
are arithmetic estimates, not production measurements. Overlap defaults are unchanged.

Worker duration/queue latency, provider latency/retries/API limits, database/WAL and
disk growth, full-series technical computation, process RSS and instance memory remain
unmeasured. Approved canaries must measure these before later waves. No production
access, schedules, push, merge, deployment, notifications or trading were authorized
or performed. Final comparison and cleanup results are recorded below when complete.

## Final results and independent re-review recommendation

The identical full command returned:

| Source | Tests | Assertion failures | Errors | Seconds |
|---|---:|---:|---:|---:|
| Exact main61ff8bc |1078|7|330|478.627|
| Corrected branch |1120|6|356|399.164|

**The complete suite is not green.** Normalized comparison has no branch-only
assertion failures; all six branch assertion failures also fail on main. There are
31 additional error identities (30 additional identities in the union of errors and
failures, because one already fails as an assertion on main). Each reports the
missing `ingestion_enabled` column after earlier migration failures leave the shared
schema old. Raw repeated/subcase error counts must not be equated with unique IDs.
`full-differential.json` retains both sets and per-ID exception excerpts.

`final-verification.log`: **292 tests in132.393 seconds;291 passed, one accepted
runtime-superuser assertion, zero errors**. This reruns the full focused population
and every additional error identity on clean current schema. All31 residual IDs
passed (`residual-clean-schema-results.json`). Exact argument array is retained in
`final-verification-command.json`. This includes the final per-page manifest assertions
and increasing-range guard, finalized after the full run began; no claim is made that
the older full run exercised those final assertions. The last missing-snapshot fixture
was strengthened to leave actual snapshot rows absent instead of mocking the report
query; its targeted rerun passed in1.662 seconds (`physical-snapshot-absence.log`).
No production assertions or migration checks were weakened, and no skips were added.

Independent fresh migration attempts against unused new baseline and branch databases
both fail at0027 with the same `Gate 8I requires the accepted complete successor
acquisition` error (`base-clean-start.log`, `branch-clean-start.log`). The accepted
bootstrap/runtime exceptions remain separate from the remediated behavior. No new
behavioral failure remains unexplained by the normalized comparison and clean rerun.

Recommendation: **ACCEPT for independent re-review of these five fixes**. This is
implementer verification and a re-review recommendation, not independent approval,
production acceptance, deployment authority or proof of capacity/trading performance.
All canary observations and operational thresholds remain pending owner approval.

Changed files (one remediation commit):

- `market/live_acquisition.py`
- `market/live_schedules.py`
- `market/oanda.py`
- `market/management/commands/report_fx_onboarding.py`
- `market/management/commands/seed_canonical.py`
- `operations/tasks.py`
- `operations/job_state.py`
- `operations/management/commands/ingest_oanda.py`
- `market/tests/test_phase2_remediation.py`
- `market/tests/test_phase2_ingestion.py`
- `market/tests/test_oanda.py`
- `operations/tests/test_diagnostics.py`
- `dashboard/test_readiness.py`
- `docs/phase2/rollout.md`
- `docs/phase2/remediation.md`

Cleanup: the newly created PostgreSQL cluster and all of its databases/source archives
are removed after verification; only new logs and report artifacts are retained.
`resources.json` identifies the created resources and `cleanup.json` records removal.
Existing databases and earlier Phase2 test resources were never used or changed.
