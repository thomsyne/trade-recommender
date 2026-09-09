# Engineer handoff — Phase 3

Status: READY for independent adversarial testing; **NO-SHIP pending independent
tester/PM acceptance and the full-schema historical-test compatibility assessment**.
This document is implementation evidence, not self-approval. No PR push, merge,
deployment, production activation, learning or promotion occurred.

Branch: `phase3/experiment-lifecycle-foundation`.
Base: `16a27029f6f78af35adb040a8b70c98744f226c4`.
Design and all-state matrix: `design.md`; activation/recovery: `runbook.md`.
Artifact directory:
`/Users/oluwatomisintaiwo/trade-recommender-artifacts/phase3-engineer-a25i6t9j`.

## Verification and exact differential

All commands used `.venv/bin/python` with explicit disposable PostgreSQL host
127.0.0.1, port55647, rolephase3_engineer, UTF8 and sanitized environment. Full
command/returncode/stdout/stderr history is `commands.jsonl`. No real provider,
email or external service was called. The initial default-host history check was
blocked by sandbox before connection/access; every subsequent Django invocation
specified the disposable database explicitly.

- `manage.py test forecasts operations dashboard --keepdb --noinput`: branch
  **188/188 passed**,33.080seconds; final execution SQL assertion4/4 passed1.094s.
- Same original affected command on untouched base:153 tests,5failures/4errors,
  21.704seconds. `base-broader.log`, `base-failures.json` retain exact identities;
  `branch-final-broader.log` is the final green branch run. No original base fixture
  was edited or replaced. Intermediate failures remain in logs.
- Combined command adds `market.tests.test_phase2_ingestion`,
  `market.tests.test_phase2_remediation`, `market.tests.test_h1_alignment_diagnostics`,
  `market.tests.test_gate8d2_readiness_correction`: branch257 tests/20errors126.611s;
  base222 tests/19errors67.980s. **This command is not green.** Nineteen shared
  failing identities have different causes: base rejects reversal of market0027's
  registration validator; branch stops earlier at irreversible Phase3 migrations.
  The additional branch failure is
  `Phase2MigrationTests.test_forward_preserves_six_ids_and_active_states_with_safe_unknown_default`.
- A separate disposable clone of the task's normally migrated base schema executes
  the current branch's unchanged `Phase2MigrationTests` with a standalone unittest
  harness:2/2 pass1.317s. It asserts forecasts0017 is installed and0018 absent.
  This exercises normal historical rollback/forward assertions without faking,
  disabling or reversing Phase3. It does **not** establish compatibility with the
  fully installed branch migration graph. That remains for independent assessment.
  `historical-isolation-final.log` and `phase3-historical-harness.py` preserve it.
  Initial harness used a non-test database name and correctly failed governed
  flush; corrected uniquely named `test_` database uses the existing allowance.
- `makemigrations --check --dry-run`: no changes. Ruff changed Python paths pass;
  Django system checks in final tests report no issues.

## Adversarial and migration evidence

`forecasts/tests_phase3` adds35 tests: every semantic target field, DST endpoint,
pre-spend control blocking, frozen-band arithmetic, one shared endpoint, immature
missing rejection, exact maturity and24-hour boundaries, rawSQL mutations,
all five new-table UPDATE/DELETE/TRUNCATE rejection, shared-trigger table branches,
concurrent target/control/resolution/transition retries, repeated-target Brier and
cutoff populations, strict schedules and execution evidence availability.

All five shared execution-trigger tables have valid service-created facts and
invalid SQL probes: cohort member, selection member, admission, entry and result.
Both prediction tables exercise issuance-window rejection; both derived-resolution
tables exercise missing shared source and unscored Brier rejection. Entry/result
also exercise frozen execution/endpoint evidence. Assertions require specific
owning messages, not any unrelated uniqueness exception. Failed probe design and
shared-trigger field-access defects were retained and corrected before handoff.

Fresh schema installed0018–0025 normally. Populated upgrade preserved551 original
rows/103 original tables and columns, excluding only expected new content types
and permissions. Final0023–0025 upgrade preserved578 rows/108 tables exactly.
`populated-before.json`, `populated-after.json`, `populated-final-before.json`,
`populated-final-after.json` record per-table SHA256/counts. Contradictory rawv4
fixture caused0019 preflight to reject atomically: three recommendation rows
unchanged, zero installed Phase3 functions and no0019 migration record;
`atomic-preflight.json` records the probe. No historical repair/backfill happened.
Final legacy report:2unpaired,1legacy_unadjudicated,1abstained,0prospective violations.

Real local app UI uses synthetic records produced through actual services, not
mocked templates. `screenshot-manifest.json` maps admitted-awaiting-entry, owner
pending/closed, entered, target-hit, invalidated, expired-not-activated,
expired-unobserved, missing-data, abstained, legacy-unadjudicated/unpaired,
missing/incompatible control and mature/immature populations to inspected DOM/PNG.
UI work exposed and fixed cached reverse-relation projection staleness and entered
coverage-gap handling. Empty coverage now carries honest versioned source details.

## Review map and residual risks

`engineer-traceability.json` maps all20 user requirements to implementation/tests;
it supplies pointers, not independent acceptance. The report's static code paths
cover the named target/control, lifecycle, experiment and scheduling checks;
independent tester should inject contradictory populations and inspect fail-closed
behavior, including rows normally prevented by constraints.

The original four-instrument scope, prompt/schema, setup/adverse execution/cost
rules, immutable historical migrations and research histories remain protected.
Runtime-superuser bypass is the explicitly deferred role-hardening risk. Weekly
clusters remain conservative proxies, not proven independence. No synthetic
sample provides evidence of skill or profitability. Exact target equality does
not imply equal model/control contextual information sets.

Known unresolved limitation: combined historical migration tests cannot reverse
through the new irreversible dependency. Do not relabel this as inherited or
silently omit it. Independent tester must determine whether an honest permanent
historical-state harness is required before accepting the branch.
