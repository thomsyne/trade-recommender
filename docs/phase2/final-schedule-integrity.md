# Final bounded Phase 2 schedule integrity remediation

Scope: `phase2/g10-ingestion-only`, starting at `8011645decdf0e090d4f6da030147be7eb8ffcc6`; verified clean worktree and merge base `61ff8bc021744b0b785843c994db422c9a742431`. No acquisition, eligibility, strategy, model, migration, scheduler execution or seed deadline calculation changes.

## Identity contract

`parse_schedule_identity` is the single parser used by reporting, semantic duplicate detection, seed preflight and canonical schedule policy validation. It accepts only a dictionary with exactly `instrument` and `granularity`, both strings belonging to `Instrument.Code.values` and `LIVE_INTERVALS`. It validates types before membership/grouping. It returns a canonical tuple or ordered static reason codes:

- `malformed_parameter_container`
- `missing_instrument` / `missing_granularity`
- `wrong_type_instrument` / `wrong_type_granularity`
- `unsupported_instrument` / `unsupported_granularity`
- `unexpected_extra_parameter`

No diagnostic interpolates parameter values, unexpected key names or stored job names. Identity issue details contain only the database job ID and reason codes. The report adds `schedule_identity_issues` with `total` (malformed job count), `omitted` and at most 50 `details`, ordered by job ID. JSON keys and global errors are sorted. Seed's text diagnostics use the same bounded information; the report's terminal failure message is fixed. Determinism is for the same database snapshot and `as_of` time.

The inventory streams all ingestion jobs to count every malformed row, retaining only 50 details and at most two jobs per valid identity (enough to prove duplication). Malformed rows do not prevent assessment of other rows. Valid semantic duplicates remain a separate error. Reporting never repairs rows; seed refuses malformed identities before making changes. This intentionally replaces the former test expectation that seed silently repaired unknown parameters. The existing disable/deadline/policy-repair assertions remain, and the new tests assert refusal and exact row preservation for every malformed case.

## Exact recurring collisions

For each enabled, semantically valid, canonically named ingestion job with an interval recurrence and usable deadline, normalize the aware deadline to UTC. Subtract the UTC Unix epoch and calculate:

```text
microseconds = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
interval_microseconds = interval_seconds * 1000000
collision iff (deadline_a - deadline_b) % gcd(interval_a, interval_b) == 0
```

There is no floating-point conversion, lookahead or sampling. Positive recurrence periods guarantee that an integer common solution can advance beyond both initial deadlines. Every unordered pair is checked once, in canonical order; each collision has one global diagnostic with bounded IDs/canonical labels and references on both affected instrument rows. With at most 48 canonical jobs, there are at most 1,128 pairs. Disabled, non-ingestion and malformed identities do not enter collision analysis. Missing, naive, non-datetime or non-normalizable deadlines and invalid recurrence intervals fail conservatively with static codes. Duplicate semantic identity errors remain independent of collision checks.

The 48 seeded minute phases are distinct modulo the hourly gcd. Repeated seed preserves deadlines, including deliberately colliding deadlines; validation reports collisions without silently correcting them. Latest-only overdue scheduling continues to create at most one occurrence per job. No schedules were activated outside disposable test fixtures.

## Evidence and verification

The original code failed three regression methods: unhashable granularity raised `TypeError`, two long unknown aliases leaked their raw value, and H1/H4 deadlines one hour apart escaped collision detection. All three pass after remediation.

The new suite contains 14 methods with adversarial subtest matrices covering containers, missing keys, all requested wrong types, unsupported values, extra keys, long Unicode/control/secret-like strings, malformed aliases mixed with valid jobs, detail overflow, deterministic JSON/text, exact recurrence phases, timezone offsets, microseconds, invalid deadlines, seed preservation and read-only SQL/row checks.

Detailed commands and retained logs: `/Users/oluwatomisintaiwo/trade-recommender-artifacts/phase2-final-two-b2c97wpa/`. The test runner uses a sanitized environment, `PSYCOPG_IMPL=python`, local Postgres.app libpq, loopback port 55617 and a newly initialized temporary cluster. Unicode tests use newly created UTF-8 databases. The initial SQL_ASCII test setup was unsuitable for Unicode and was superseded, without changing assertions. Schema preparation uses only the accepted sequence `migrate market 0026`, `migrate market 0027 --fake`, `migrate`; no other bypass or skip.

Results:

| Run | Result |
| --- | --- |
| New identity/recurrence/report tests | 14 passed (also included in branch regression run) |
| Branch regression groups | 306 run in 132.226s: 301 passed, 2 failures, 3 errors |
| Exact `8011645` baseline, same existing groups | 292 run in 118.001s: 287 passed, 2 failures, 3 errors |
| Additional research seed/service tests | 12 passed on branch; 12 passed on baseline |
| Ruff lint/format, compile, diff check | Passed |
| Django check, migration drift, production-settings check with dummy configuration | Passed |
| IAM policy, bootstrap, remote-deploy, backup, infrastructure policy, Compose and Terraform format CI checks | Passed |

The exact normalized failure identities and failure/error classifications match baseline; no new failing identity. The non-green identities are:

- `market.tests.test_live_observations.LiveEvidenceDatabaseProtectionTests.test_connection_role_is_not_a_superuser`
- `forecasts.tests.test_frozen_evidence.FrozenEvidenceTests.test_paper_entry_and_exit_bind_hourly_bid_ask_observations`
- `forecasts.tests.test_recommendations.RecommendationTests.test_paper_trade_applies_adverse_stop_precedence_on_ambiguous_entry_candle`
- `forecasts.tests.test_recommendations.RecommendationTests.test_paper_trade_expires_unactivated_only_after_complete_hourly_coverage`
- `forecasts.tests.test_recommendations.RecommendationTests.test_paper_trade_uses_hourly_ask_entry_and_bid_target_after_entry_candle`

The four paper-trade cases return no result in both checkouts; they were neither changed nor skipped. The runtime-superuser limitation remains accepted/deferred. These are selected regression groups, not a claim that the full project suite is green or that it was rerun here.

Exact executed test arguments, working directories and exit codes are retained in `verification-commands.json`, `extra-commands.json` and `exact-commands.txt` in the artifact directory above. `final-two-run.py` records the sanitized environment; `static-results.json` records every static/CI command. The primary commands were:

```sh
python /private/tmp/final-two-run.py branch_utf8 test market.tests.test_schedule_integrity --keepdb --noinput
python /private/tmp/final-two-run.py branch_utf8 test research.tests.test_seed research.tests.test_services --keepdb --noinput --verbosity 2
python /private/tmp/final-two-run.py branch_utf8 check
python /private/tmp/final-two-run.py branch_utf8 makemigrations --check --dry-run
```

The expanded 306/292-test command lists include every Phase 2/remediation/onboarding test, OANDA, quality, freshness, canonical seed, terms, live observation/lineage, Operations, Dashboard, CLI, relevant decision-isolation groups and the previously selected historical residual tests. Research seed/service tests complete the seed coverage. All database test runs were serial.

## Disposition and residual risks

Both findings are fixed and the original reproductions plus adversarial cases pass. **ACCEPT for one final bounded independent review; no deployment authorization.** Existing malformed schedules or recurring collisions require a separate explicit correction; this report will reject them without repairing or rescheduling. Enumeration time remains proportional to the ingestion-job inventory so total/omitted counts are exact, while retained diagnostics are bounded. Ordinary concurrent database changes can produce a different report snapshot; the determinism tests fix state and time.

The final diff is limited to the shared validator, additive report metadata, the seed regression contract, new tests and this document. Existing schedules/evidence were not accessed or changed. Disposable fixtures alone exercised seed/scheduler writes; read-only report tests assert only SELECT/server-cursor SQL and unchanged rows. The disposable cluster, its databases and baseline archive were removed after testing; logs are retained externally. No push, merge, deployment, production/AWS/OANDA access or schedule activation was performed.

Changed files:

- `market/live_schedules.py`
- `market/management/commands/report_fx_onboarding.py`
- `market/tests/test_schedule_integrity.py`
- `market/tests/test_phase2_ingestion.py`
- `docs/phase2/final-schedule-integrity.md`
