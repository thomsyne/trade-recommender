# Consolidated independent-review correction cycle

Base: clean `phase5/explicit-strategy-library` at
`4424f5afac96bd68d064aa9d1f615c66314626d0`. Acceptance remains pending independent
final verification. No market outcomes, provider access or production activation.

## Frozen corrections, before implementation

1. Replay prior-buffer ancestors oldest first, at most 256 records including the
   requested record. Reject cycles, absent ancestors, unsupported definitions,
   mismatched identities/hashes, cross-instrument/definition links and non-increasing
   cutoffs. A child integrity check verifies every ancestor, not just its own bytes.
2. Decision series retain their contiguous-history gate. Outcome series expose
   exact sorted cited observations without a global continuity gate. The simulator
   checks the signal-to-entry prerequisite and each active interval until terminal
   exit; irrelevant later gaps never erase a result.
3. A new forward migration validates exact JSON shapes and strategy/schema
   compatibility. Python uses the same structural contract. SQL does not calculate
   forecasts, fills or returns. Existing records and migrations remain unchanged.
4. Outcome evidence requires explicit base/quote/account currencies, quote-per-base
   cost units and account-per-quote conversion units, nonempty provenance, lowercase
   SHA256, aware ordered times and finite Decimal values. Invalid evidence fails
   closed before any available account-currency result.
5. `fast-mr-h1-v1` owns `adverse-limit-h1-v1`, separately attributed from the market
   simulator. The completed H1 signal close is the frozen limit. Placement occurs
   only at the next eligible H1 opening after information availability and latency;
   validity is [entry, next registered H1 opening), with the existing six-H1 time
   stop. Candidate expiry is the latest placement boundary, not order lifetime:
   delayed recording must not collapse valid order lifetime to zero. Modeled buy ask
   (sell bid) is midpoint plus (minus) half documented spread. An opening through
   the limit assumes fill at the limit, never favorable gap improvement. An
   intrabar touch cannot establish queue priority or ordering: unavailable, never
   a favorable assumed fill. Stop-first applies to both-hit bars after an opening
   fill; adverse gap beyond invalidation is unavailable. Missing spread/costs,
   calendar, latency, financing or conversion evidence is unavailable. Commission
   and exit slippage remain explicit; no entry slippage can worsen a limit price.
   No executable-fill or realistic tick-path claim is made.
6. Each public arithmetic boundary uses a fresh Decimal context: precision34,
   ROUND_HALF_EVEN, fixed default traps (InvalidOperation, DivisionByZero, Overflow),
   fixed exponent bounds. Ambient precision, rounding, traps and flags cannot leak.

The registry remains 19 strategy IDs. Definition revision 2 binds corrected source
and simulator contracts; forward admission pins change, never existing rows.
Existing revision-1 definitions cannot silently be reused or overwritten: explicit
version conflict/unsupported-definition is the fail-closed disposition. Historical
evidence stays immutable and is not relabeled as corrected evidence.

## Review lessons

Hashes certify bytes, not semantics or ancestor validity. A suffix test must pass
through the actual loader, not only the pure simulator. JSON storage needs closed
schemas even when Python dataclasses are strict. Unknown currency or provenance is
not usable evidence. Execution hypotheses require their own frozen contract; ORB
approval does not authorize a mean-reversion substitution. Determinism includes
the caller's Decimal context, not merely repeat execution in one process.

## Reproduction and discriminating coverage

All six independent findings were reproduced on the unchanged correction base
before implementation. Four pure regression methods produced five failing
assertions (invalid currency and short hash were separate subcases); two storage
methods failed because forged-parent consumption and cross-kind SQL admission
were wrongly accepted. These were genuine red results, not expected-failure skips.

The final correction tests cover forged hash-consistent parents and grandparents,
valid chains, cross-definition/instrument links, missing ancestors, bounded depth
and cycles (SQL mutation refusal plus simulated corrupt reads); stop/target/expiry
prefixes and pre-entry/active/post-exit gaps; Python/SQL closed-shape parity for
every field; invalid evidence types, units, currencies, timestamps and numbers;
limit fills/nonfills/gap-through/ambiguity/latency/missing spreads; and independent
Decimal contexts. Successful persisted ORB simulation, idempotent retry, integrity
and a gapped later-cutoff suffix are exercised end to end using normal historical
ingestion and forward migration, without disabling guards or rewriting evidence.

The delayed-recording limit regression additionally failed before the placement
expiry/lifetime distinction was corrected. That intermediate failure and both
interrupted combined-run pairs are not final passes. The interrupted pairs ran
670/670 and 635/635 tests respectively with no reported failures, but were stopped
before completion to incorporate corrections.

## Isolation and unchanged boundaries

Exact PostgreSQL 15.14 and 17.6 source builds, UTF8/locale C, pgcrypto, private Unix
sockets and disposable data directories live only beneath the owned temporary
root `/tmp/phase5-correction-owned`. Commands use a cleared environment with
explicit socket/port/user/database settings, never `.env.local` or an existing
database. The archived correction base is read-only test input. Focused tests
include real separate-connection concurrency, non-superuser raw SQL admission,
forward migration/reverse/reapply and populated evidence preservation/refusal.

The 598 protected base files still have the canonical path-to-SHA256 map digest
`2de4502bbee0f0aa290afbb5a54fa37c3b20c36d8f143f02b79fa3475151b409`.
The original models prefix and initial handoff's Phase4 CASCADE guard probe are
unchanged. All pre-0040 migrations and Phase4.5 restore exclusions are unchanged;
there are no new consumers, schedules, activation paths or eligibility changes.

Correction definition revision 2 binds design SHA256
`0d00112e26ee38b19f92d970b02c6573cce4fb51943ede7a2d9d2f572b58e489`
and implementation-file-map SHA256
`e67a882b0733ac0282101fcab7b65fc8e2f9ff15f2bd6085453f8394bef69e47`.
All 19 migration admission pins match the independently generated definitions.

## Verification and limitations

Final focused suite: 56 passed on PG15.14 (23.685s) and PG17.6 (23.144s).
The affected inherited slice passed at archived base on PG15 (72, 6.883s) and
corrected code on PG17 (72, 7.228s). Base and corrected `make check` passed.
Offline CI-equivalent IAM, bootstrap, remote-deploy, backup (13), infrastructure,
Compose, isolated production-settings and Terraform-format checks passed locally;
no GitHub job or deployment was run.

The exact unchanged excluded module is
`research.tests.test_failed_break_detector_v2_queries`; base and corrected runs
both discover six tests but execute zero because
`DetectorV2QueryBudgetTests.setUpClass` fails at
`market_validate_discovery_plan()` line 72: `discovery plan conflicts with canonical
contract`. The six exact IDs remain in the historical verification document and
available-evidence runner. Their sorted-ID SHA256 remains
`bf0b6468bc644c40e5a5ef5fe077960c0ed01fe46fd7be840dc92cceafb01ffd`;
source SHA256 remains
`43dbd64834689ed592152769332246989d0b78c192af27546bea986f00ca99eb`.
No new fixture substitution or exclusion was introduced.

Three genuine pinned Student-t GARCH fits with isolated optional dependencies
(arch7.2.0/numpy1.26.4/scipy1.13.1/pandas2.2.3), ambient HALF_EVEN/UP/DOWN,
precision 3 and an Inexact trap produced identical encoded multiplier `0.684867`.
This is synthetic solver execution evidence, not predictive or cross-platform
equivalence evidence. No economic outcome population is certified. Real quotes,
financing/conversion evidence, carry data, event completeness, untouched holdout
results and owner acceptance remain gates, not fabricated evidence.

Both complete final available-evidence suites passed with exit 0: **1520 tests on
PG15.14 in 1633.841s; 1520 on PG17.6 in 1668.607s**. Both printed the exact six
restore exclusions. Representative command, with version-specific socket/port:

```sh
env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/local/bin \
  PYTHONPATH=/tmp/phase5-correction-owned/test-deps \
  POSTGRES_HOST=/tmp/phase5-correction-owned/socket15 POSTGRES_PORT=55465 \
  POSTGRES_USER=phase5 POSTGRES_DB=phase5 POSTGRES_PASSWORD=unused \
  POSTGRES_CONN_MAX_AGE=0 .venv/bin/python manage.py test \
  --testrunner=market.tests.phase45_runner.AvailableEvidenceRunner \
  --parallel 4 --noinput
```

Compact inspected-log SHA256 evidence (disposable raw logs removed):

| Run | SHA256 |
|---|---|
| Original pure red | `2b19e84fb00079fb900779bfb29a3d89e5526f8527e64638de28404178752cab` |
| Original storage red | `4bf51c918acbfe8176d556a416b92c2fd78f01309f5b5a3402f49fdf00cfc6a4` |
| Final PG15 focused | `dd8b3d62f9ad9b6c78b123b6c1fb48b272cfc53710021aee045b1d36dad317c5` |
| Final PG17 focused | `48c65d29bc55d0b92aa18e1f9317a4df05fa8228d1ccfbf342c441c1cec06264` |
| Final PG15 combined | `d9be41c0983aa443836acd3894b5652e95a22ab76aa5b85ba8ddf85044bda568` |
| Final PG17 combined | `7d38b38fca346dba9d4b1cca10a844c9b26f98c551cec9ac3cb15efd86723071` |
| Base excluded module | `b3d8cf76bb6c55a1cd56d22e367fac2dc0b9ddeb2afb7f4492157273507bf879` |
| Final excluded module | `7dbd0fd63c152148109c4a212b80cdc224890deee5408e41b6c9e6d5aaf68f2b` |
| Final make check | `8459e01ed3ba0efb70a68264cdcba5068ff1e82eb2b2cf0edbfb03da3006c9d1` |
| Offline CI checks | `d84b492ffeadefe5080b5c6750640a81f23d9856114e3d7640f5c7dd0c2c367f` |

Both servers stopped cleanly. The owned temporary root, builds, disposable data,
sockets, dependencies, archived checkout and logs were removed; the workspace
virtual environment was preserved. Read-only remote inspection still shows main
at `131a2fc1cd6d2d849cb13a94ce5b937cf0fe8a44` and no remote Phase5 branch.
All corrections are local to `phase5/explicit-strategy-library`; final commit and
clean-worktree status are reported in the thread handoff. No push, PR, deployment,
activation, production/provider access or self-acceptance occurred. Independent
final verification remains required for all six correction dispositions.
