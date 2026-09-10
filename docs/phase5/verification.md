# Phase5 engineering evidence — not strategy acceptance

This is the historical initial handoff at `4424f5a`. The consolidated correction
cycle's contracts, verification and remaining gates supersede it where stated in
[corrections](corrections.md); acceptance remains pending independent verification.

Verification date: 2026-09-10. No market outcomes were used to tune definitions,
scalars, simulator rules, cost screens, populations, eras or thresholds. Tests use
synthetic inputs or disposable local databases. No provider request, deployed
database access, trade, production mutation, schedule or activation was performed.

## Checkout and preregistration

Initial clean local `main`, fetched `origin/main` and required base were all
`131a2fc1cd6d2d849cb13a94ce5b937cf0fe8a44`. Safe fast-forward was a no-op. Branch:
`phase5/explicit-strategy-library`; repository:
`https://github.com/thomsyne/trade-recommender`; worktree:
`/Users/oluwatomisintaiwo/Projects/trade-recommender`.

The acceptance matrix, ADR and exact formulas preceded implementation. A–F are
local checkpoints `324aafd`, `38c4ca5`, `609c0a9`, `971827c`, `6b8a90d`, `eeff352`.
G contains persistence, attribution, commands, final checks and draft corrections:
H1 level events with subsequent M15 BOS, delayed recording without backdated
entry, entry at/after snapshot cutoff, lossless decimal input evidence, adverse
rollover-boundary treatment and final schema/source/SQL pins. Those corrections
precede any real research registration or outcome evaluation; throwaway fixture records are not accepted research
evidence. No existing or applied migration was rewritten.

Specification SHA256:
`d4e1f0e635f8faf800feddf5a61ec6ce88932fcdae6642930766ce31c61d3c64`.
Canonical implementation-file-map SHA256:
`554b925a6c67adc8f1cccdd7fdc086d49a0392678d63b8adaa304815a47d4591`.
Both are bound into all 19 definition digests, pinned by migration 0039.

## Reproducible PostgreSQL isolation

Docker daemon was unavailable. Exact public PostgreSQL 15.14 and 17.6 sources
were built with `clang -arch x86_64` and OpenSSL. Both servers use UTF8/locale C,
pgcrypto and private Unix sockets only, under `/tmp/tr-phase5-owned/`; ports
55465 and 55467 respectively. `SHOW server_version` verifies the exact versions.
The original checkout was archived to an isolated base directory, not mutated.

The test environment is cleared with `env -i`; only HOME, executable PATH,
explicit disposable database settings, `POSTGRES_CONN_MAX_AGE=0`, and isolated
`tblib==3.1.0` are supplied. Representative combined command (adjust version/port
and use the same absolute Python executable from the archived base):

```sh
env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/local/bin \
  PYTHONPATH=/tmp/tr-phase5-owned/test-deps \
  POSTGRES_HOST=/tmp/tr-phase5-owned/socket-15.14 POSTGRES_PORT=55465 \
  POSTGRES_USER=phase5 POSTGRES_DB=phase5 POSTGRES_PASSWORD=unused \
  POSTGRES_CONN_MAX_AGE=0 .venv/bin/python manage.py test \
  --testrunner=market.tests.phase45_runner.AvailableEvidenceRunner \
  --parallel 4 --noinput
```

Focused library command: `manage.py test market.tests
--pattern='test_strategy_library*.py' --noinput`. Migration coverage uses a
historical 0037 database, fingerprints all populated prior tables, applies 0038/
0039, reverses/reapplies empty guards and verifies populated reversal refusal.
Concurrency uses four real separate database connections, not mocked locks.

## Test results and failures

| Run | PostgreSQL 15.14 | PostgreSQL 17.6 |
|---|---|---|
| Base available-evidence suite | 1464 passed, 1657.834s | 1464 passed, 1676.831s |
| Initial library focused suite | 34 passed, 7.798s | 34 passed, 7.739s |
| Migration/persistence focused slice | 6 passed | 6 passed |
| Corrected H1/M15/source-pin library slice | 35 passed, 7.872s | Included in final combined run |
| Interrupted integration attempt | 787 executed, one assertion failure, 811.197s | 787 executed, same assertion failure, 811.357s |
| Interrupted before exact-input correction | 872 executed, zero failures, 825.536s; incomplete | 872 executed, zero failures, 825.488s; incomplete |
| Interrupted before entry/cutoff guard | 691 executed, zero failures, 408.214s; incomplete | 691 executed, zero failures, 408.159s; incomplete |
| Interrupted before adverse rollover correction | 1424 executed, zero failures, 1037.589s; incomplete | 1482 executed, zero failures, 1037.367s; incomplete |
| Final library focused suite | 42 passed, 8.168s | 42 passed, 8.042s |
| Final combined available-evidence suite | 1506 passed, 1635.819s, exit 0 | 1506 passed, 1653.492s, exit 0 |

Compact log fingerprints (SHA256; full disposable logs removed after inspection):

| Evidence | SHA256 |
|---|---|
| Base PG15 suite | `b591c823a44a5b4dd23d8981c64eb2cc8a5f19a8b9c49ef5d9e73646855d44d9` |
| Base PG17 suite | `2bf4be5472806936be456c269dca1f918449d17b7000dbbdc294621161d4912d` |
| Final PG15 suite | `8a9b4aa0bc1453868d2fc0d43de94c0627a034ec6741799049dfdacd0e9dd205` |
| Final PG17 suite | `3abdb4d4d2318ab3c2f4462bdae6e1c54cf626d31bdd3916102f91e142628f6b` |
| Final make check | `e7bb6492e7b7e26c183610bd7e643a955137c5b63add1f03e3d7ba86b2478a7c` |
| Base excluded module | `b0c0681ea106f5902e968ef8060aa6f43f2669a84797d413cc3b88f89ffa3d93` |
| Final excluded module | `fdea5bec065d8f56367612b9cc0ef9dabec0060c2dd7c12170a0140c2c2f9d87` |

The integration failure was
`market.tests.test_phase4_semantic_boundary.SemanticBoundaryTests.test_non_superuser_cannot_forge_semantics_or_mutate_valid_snapshot`.
Its `TRUNCATE market_marketstatesnapshot` was refused earlier by the new foreign
keys, so it could not produce the expected `must not be truncated` guard message.
The probe now uses `TRUNCATE ... CASCADE` to reach and test that same immutable
guard. Neither the assertion nor the guard was weakened. The corrected probe plus
seven simulator tests passed (8 tests, 0.096s on PG15). The failing intermediate
combined runs were explicitly interrupted after diagnosis, their databases
destroyed, and a complete final run started; interrupted runs are not full passes.

Review then found that rounding input cost evidence to six decimals could turn
`0.1000004` (unaffordable at sigma1) into affordable `0.100000`. That intermediate
run was also explicitly interrupted, without claiming its partial `OK` as a full
pass. Inputs now preserve exact decimal strings; only outputs quantize. Regression
checks demonstrate both sides of this competing interpretation, distinct stored
subquantum cost identities, half-even output rounding and exact conversion replay.

The last timing correction rejects a setup whose entry precedes its snapshot
cutoff. Equality is allowed; one microsecond later is unavailable. Both the pure
dispatcher and raw-SQL admission enforce this, preventing late snapshots from
authorizing historical fills. That intermediate run was stopped before changing
the source pins; its partial result is explicitly not the final combined result.

The final simulator correction includes rollover evidence at entry and exit
equality. It charges adverse fees at ambiguous boundaries, but awards a signed
credit only for a rollover strictly after entry and before the exit interval.
Fixtures distinguish positive fees, possibly unearned credits and definitely
earned earlier credits. The preceding run was interrupted and is not a full pass.

Earlier development fixture errors were corrected without weakening production
contracts: `make_market` returns two values, Bar uses NamedTuple `_replace`, and
the qualified FVG fixture must actually satisfy the existing spread/displacement
thresholds. The new persistence cost fixture initially used USD for USD_CAD;
the actual CAD quote currency corrected it without relaxing currency validation.
Extra simulator checks cover later stop gaps, target gaps, rollover
equality, weekend reopening and late conversion evidence.

## The inherited six restore exclusions are unchanged

The default runner is **not** claimed green. Both archived-base PG15 and final
PG17 reproduce the same failure before any of the six tests executes:
`DetectorV2QueryBudgetTests.setUpClass`, `django.db.utils.ProgrammingError:
discovery plan conflicts with canonical contract`, raised by
`market_validate_discovery_plan()` line 72. Each run found six tests, ran zero,
and exited 1 with one setup error. The genuine accepted restore remains an
external prerequisite, not fabricated fixture data or a disabled trigger.

Exact unchanged prefix:
`research.tests.test_failed_break_detector_v2_queries.DetectorV2QueryBudgetTests.`

```text
test_contract_identity_as_dataset_name_is_refused
test_dataset_name_as_contract_identity_is_refused
test_every_other_pinned_identity_mismatch_remains_fail_closed
test_every_registration_identity_mismatch_remains_fail_closed
test_exact_accepted_dataset3_identity_uses_one_registration_query
test_preload_query_budget_is_three_independent_of_row_count
```

Sorted full-ID set SHA256:
`bf0b6468bc644c40e5a5ef5fe077960c0ed01fe46fd7be840dc92cceafb01ffd`.
Excluded source SHA256:
`43dbd64834689ed592152769332246989d0b78c192af27546bea986f00ca99eb`.
The available-evidence runner prints those six IDs and verifies both hashes;
its parent-only isolated-worker handling and exclusions are untouched.

## Offline checks and optional solver

`make check` passed at both archived base and final: Ruff lint/format,
Django checks, no migration drift and compileall.
The following CI-equivalent local checks passed without triggering
any GitHub job or deployment:

- `check-deploy-iam-policy.py`: 5900-character policy audit.
- `test-bootstrap-host.sh`, `test-remote-deploy.sh`.
- `test-backup.sh`: 13 tests; expected failure-injection log messages are not test failures.
- `test-infra-policy.py`, `test-production-compose.sh` (rendering needs no daemon).
- `manage.py check --deploy` with isolated nonproduction environment values.
- Terraform 1.13.3 `fmt -check -recursive infra`, using a temporary official
  Darwin binary whose archive matched the published SHA256
  `5ef8e19091106b1921af26db5bcee3cd84a475eae2fd190fc02b1049b320d042`.

The local execution is macOS, not a claim that a GitHub Ubuntu job ran. No UI
changed, so no rendered screenshot is applicable.

Optional solver dependencies were installed only into an owned temporary target:
arch7.2.0/numpy1.26.4/scipy1.13.1/pandas2.2.3. For 300 synthetic percent returns
`Decimal(((i*37)%101)-50)/100`, baseline `Decimal('.2')`, two genuine Student-t
GARCH fits produced identical encoded output, multiplier `0.684867`, reason
`capped_at_baseline`. This verifies execution/determinism/cap, not predictive value
or cross-platform bitwise equivalence. Wrong version and nonconvergence are tested
as unavailable, with no hidden EWMA fallback.

## Final handoff checks

All 598 other base-tracked files are byte-identical to the required base. Their
canonical sorted path→SHA256 map hashes to
`2de4502bbee0f0aa290afbb5a54fa37c3b20c36d8f143f02b79fa3475151b409`.
The only two existing-file exceptions are the append-only `market/models.py`
extension (entire original byte prefix preserved) and the documented CASCADE
guard probe. All old migrations, Phase4/4.5 implementation, restore exclusions,
failed-break binders, instrument policy, operations, forecasts, settings, deployment
and CI files remain unchanged. New library consumers are absent from forecasts,
operations, config and dashboard; that static boundary is also tested.

After both complete combined runs, read-only `git ls-remote` confirmed main still
at the required base and no remote `phase5/explicit-strategy-library` branch.
Both owned PostgreSQL servers were stopped cleanly; the disposable source builds,
databases, sockets, logs, solver/test dependencies, Terraform binary and archived
base were removed. The workspace virtual environment was preserved. Checkpoint G
contains this evidence; final status is checked after its local commit.
No economic acceptance, cross-strategy
combination, production migration, push, PR, merge, deployment or activation is
authorized by this evidence. Every requirement's engineering disposition and
remaining data/owner gates are in [acceptance](acceptance.md).
