# Phase 5.5 pre-release verification evidence

Engineering evidence, not independent acceptance. The full registered development
population and its reports are complete and verified. Independent pre-release
review remains outstanding. The historical holdout remains sealed and unevaluated.

## Frozen revision 2 checks

The executable registration is `frozen-registration-v2.json`. No registered
source changed after its freeze. Original Phase 5 sources, migrations and
prospective populations remain unchanged.

| Check | Observed result | Private evidence under `.candidate-data/phase55-v1/` |
|---|---|---|
| Focused synthetic revision 2 | 43 tests run; six database-dependent skips. Not database coverage. | `revision2-focused.log` |
| PostgreSQL 15 focused candidate | All 99 tests passed, including original strategy-library and new validation tests with explicit audit database access. | `pg15-focused-suite.log`, `pg15-focused-status.log` |
| PostgreSQL 15 broad attempt | Interrupted; not a pass or a complete suite. | `pg15-full-suite.log` |
| PostgreSQL 17 complete available-evidence suite | 1,563 tests ran in 3,661.653 seconds; one class-setup error; exit 1. Not green. | `pg17-full-suite.log` |
| Merged-main reproduction | The same class-setup error reproduced on the unchanged merged base. Six methods could not start. | `merged-base-failure-reproduction.log`, `base-checkout.log` |
| Repository lint/format | Passed at the frozen source candidate. | `ruff-final.log` |
| Django checks / migration drift / compile | Passed at the frozen source candidate. | `django-checks.log` |
| Preloaded reporting equivalence | Complete EUR_USD continuation baseline and all four separately attributed overlays produced byte-identical canonical JSON and plain English through the frozen preloaded-row APIs versus ordinary export. | `preloaded-report-equivalence.log`, `early-complete-reports.log` |
| Actual-data restart/idempotency | Replayed EUR_USD continuation [2019-01-25,2019-01-28), including a modeled-trade opportunity. All three daily checkpoint bodies matched; no existing checkpoint was rewritten. | `real-data-idempotency.log` |

The PostgreSQL failure is `DetectorV2QueryBudgetTests` setup: its legacy
`HistoricalDiscoveryPlan` fixture conflicts with `market_validate_discovery_plan`.
The canonical trigger raises `discovery plan conflicts with canonical contract`.
This is reproduced on merged main, not inferred from an unrelated failure. It
has not been suppressed or repaired outside this task's scope. The complete
suite therefore remains a documented verification limitation.

The disposable PostgreSQL 15 and PostgreSQL 17 test clusters, merged-base
reproduction checkout, and locally compiled PostgreSQL 17.6 build were cleaned.
Existing shared PostgreSQL installations and unrelated worktrees were not changed.
Acquisition, immutable validation catalogs, runtime environment, reports and logs
remain private replay evidence; they are not temporary test databases.

## Reporting without changing the frozen algorithms

The existing `saved_rows` API verifies each complete development checkpoint chain.
The existing `report` API accepts a preloaded list as well as a callable iterator.
For repeated views, verified rows may be retained in memory, omitting only the
decision payload unused by reporting and sharing equal dictionaries/strings.
Every opportunity and every field consumed by `report`, `overlay_rows` and
`paired_increment` is retained. Original evaluation identities are preserved.

Report construction still invokes the registered `report`, `overlay_rows`,
`paired_increment`, `development_proposal`, `identity_digest`, `plain_english`
and immutable publication functions. This is invocation of the existing APIs,
not a changed model, report schema, threshold or admission rule. Byte equivalence
was checked against ordinary export before using the faster invocation. Aggregates
must preserve the registered instrument order and fixed account denominator;
FVG comparisons must retain the same-session confirmed opportunities. Partial
checkpoint chains remain errors, never reports labelled complete.

## Final population and interrupted attempts

The final idle-catalog pass verified all 180 baseline/instrument chains: 2,191
consecutive daily checkpoints each, 394,380 in revision 2. Every checkpoint body
hash and chain predecessor was checked. Independently derived planned-opportunity
counts matched: 1,565 per daily/ORB identity, 37,560 per H1 identity and 150,240
per other M15 identity. Four overlay identities remain paired views, not separately
selected directional populations. The catalog contains zero holdout checkpoints.

All 975 JSON/English pairs passed canonical-byte, identity, text, attribution,
account-denominator and sealed-state checks: 900 instrument views and 75 separately
attributed aggregates covering all 19 identities. The final report index freezes
every report identity and both file hashes. All formal dispositions are
inconclusive under the preregistered evidence-first rule, not passes. Negative
diagnostics, failed robustness gates and unavailable reasons remain visible.

The first revision's body, actual registration clock and all 21,921 partial
checkpoint hashes are preserved. Both runner registrations were committed before
their respective logged development runs. The metadata-only final seal check
matched the original 456 sealed chunks / 660,885 observations without selecting
price blobs. No registered runner source or runtime changed during revision 2.

The final synthetic run passed 37 executed tests with six database-dependent
skips (43 total); lint and format checks passed for 549 files. The earlier PG15/17
results and complete-suite limitation above remain unchanged. Forward readiness
reports zero elapsed complete weeks and missing evidence, not confirmation.

Do not treat interrupted job logs as passes. Earlier workers were deliberately
repartitioned and resumed. One redundant AUD/JPY worker later timed out at SQLite
`BEGIN IMMEDIATE` during a concurrent full-chain read. That read was stopped;
the other worker completed the preserved chain. The final successful integrity
pass ran after all writers stopped. The interrupted read and timeout logs remain
indexed alongside the successful final pass. Use a backup or idle writers for
full-chain reads; no source or timeout parameter was changed after outcomes.

All owned batch, report, verification and log-tail processes are closed; temporary
report backups are gone. Private replay artifacts remain intentionally retained.
`evidence-index.json` contains the final closed-file hashes, exact changed paths,
checkpoint history and links between registration, seal, catalog and reports.

## Closed evidence hashes

The earlier closed-file index below is preserved. The complete final index is
`evidence-index.json`. These are test/replay artifacts, not environment or
credential files; no active log is represented as a frozen result.

| Private filename | Bytes | SHA-256 |
|---|---:|---|
| `revision2-focused.log` | 154 | `2dd685d86ffde469d08fd2216a7e1a5721cba3076979b9032e193d203b996db1` |
| `pg15-focused-suite.log` | 359 | `f785715317af5575beaeefd14f488ad64ae88f9122cc06975a7505f1281578d5` |
| `pg15-focused-status.log` | 57 | `7dd5c4a76ea7b23652e17ccc9d6b27db91627ab41f4657e56a69a8cba538391a` |
| `pg15-full-suite.log` | 10314 | `2eb9bc4d06e48caa4c2ecf00ee8495f03b81f8b0c127fc7b1fd384c0dc211070` |
| `pg17-full-suite.log` | 11244 | `e84a5b3e02b91d6306513be88a6e81876dcbdf59b2fc462699165fe0eaa10336` |
| `merged-base-failure-reproduction.log` | 5521 | `b88ada0742989cadc8860daa127d86a982c8bbbfd014a8e4182cb92e06fafad0` |
| `base-checkout.log` | 136 | `224b7e4e850724d1d80a4bc47f7efcfd8e319c41e2acef9c38818db5ec0754a6` |
| `ruff-final.log` | 47 | `8de57fb5d722d98112c10284eeaacd5f81b481afc07a66e9a19f66186684feb8` |
| `django-checks.log` | 68 | `c0f41e9d77fda2dc38b65183611472aa000dc0dc520211e6ca4ca14f52e1024d` |
| `preloaded-report-equivalence.log` | 550 | `83637e9a92b575ae233c412c1eceece3bc0305a7551bfdd9a61adc4f9747de81` |
| `early-complete-reports.log` | 1493 | `09c35d737bebecedce21b617341b58bc5286cf9058b0fb54204f8c321f4a013d` |
| `real-data-idempotency.log` | 429 | `dadc8ef898d16fcd9eb79cf1d1c7ccd99351a514848e06fa711811877b9a5de3` |
| `prior-revision-preservation.json` | 437 | `f2049f329546b4d6f5f567e735a748fddf0af80079e9870d4d9d60c81ab09fc2` |
