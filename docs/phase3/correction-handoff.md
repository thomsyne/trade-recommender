# Independent-review correction handoff

This records engineer corrections to reviewed commit
`e74defa3ab502a18e6d2d3ca9d93e252a18ede39` on
`phase3/experiment-lifecycle-foundation`. It is **NO-SHIP pending independent
re-review and subsequent PM review**, not engineer approval. The branch remains
local. The base is `16a27029f6f78af35adb040a8b70c98744f226c4`.

Correction evidence directory:
`/Users/oluwatomisintaiwo/trade-recommender-artifacts/phase3-correct-3aw65q2q`.
`commands.jsonl` contains exact commands, exit status and full outputs, including
all failed probes and fixture corrections. Its sixth record reproduced all eight
initial findings on unchanged e74defa: nine tests, three failures/three errors;
accepted downgrade, backdated shared resolution and premature expiry are printed
explicitly. Those diagnostic acceptance probes were inverted in repository tests.

## F1–F8 dispositions and adjacent evidence

| Finding | Owning correction | Discriminating evidence |
|---|---|---|
| F1 precision | Explicit six-decimal HALF_EVEN in Python; SQL `phase3_price` in forward migration 0026; exact validation remains | `ReviewBoundaryTests`: both half-micro tie directions and exact value, real target/control and endpoint writes. `PersistedSemanticReviewTests`: persisted registered contract variants, canonical uniqueness independent of new row ID, unsupported resolution versions rejected and registered Christmas weekday endpoint equal in Python/SQL. Existing full identity-content matrix retained. |
| F2 cutover | Forward 0027 adds nullable `recorded_at`, always overwritten by PostgreSQL `clock_timestamp()` on new insertion. Effective registered v4 cutover rejects newly inserted v1/v2/v3 even with backdated generated/audit timestamps. Application checks use database time; report separates grandfathered null-audit rows from downgrades | `ReviewBoundaryTests`, `LegacyCutoverReviewTests`, `IntegrityPopulationTests`; `legacy-preservation.json` proves every original column unchanged after normal populated base→0030 upgrade, null new fields and zero invented lifecycle events. Refresh ORM instances to read trigger-owned recorded_at. |
| F3 endpoint availability | Application and0026 SQL require completed exact endpoint, successful ingestion and finished_at no later than resolution | Before/at/after availability; scored/unscored missing/cancelled endpoint-shape SQL matrix; failed/running ingestion source rejected. Incomplete candles are rejected by existing `stored_candles_complete` before they can reach shared-resolution SQL; application counterpart is tested with an explicit read-boundary counterfactual, without bypassing that constraint. |
| F4 semantic state proof | Source/model/canonical transition checks plus 0028/0030 require true registered maturity and evidence for H1 gaps, missing daily endpoint, full-coverage expiry and pending-only revocation; cancellation remains distinct and may precede maturity | `TransitionMatrixTests` observes every legal edge with real source facts and challenges wrong-source SQL plus earlier-time application/SQL immediately before each valid append. Boundary tests cover exact maturity, malformed details, no-entry/entered gaps, daily missing, early cancellation and rejection after entry. `OwnerBoundaryTests`: real late historical evidence changes target and closes every old multi-instrument member; real newer admission displaces prior available capacity. |
| F5 signed interval | Signed support is independent of range width; unsigned Brier default preserved | Independent arithmetic at negative/zero/positive support endpoints and multiple cluster counts. `PersistedAssessmentTests`: 50 real v4 targets, controls, shared and derived outcomes across more than 180 days reach descriptive_ready. A separate fully unmocked integer-percentage fixture has summed rounded Brier 4.708949, mean .094179 and upper .222222 exactly. The separate strict-comparator test substitutes only interval upper on an otherwise ready persisted population to isolate equality from other gates; it is explicitly a substituted boundary test, not the unmocked fixture. Fully ready fixture also rejects stale/wrong-era owner assessment; SQL and app sample method/dependence forgery reject. |
| F6 malformed diagnostics | Recurrence shape is validated before gcd or date arithmetic; invalid rows produce static codes | Real null/zero schedules; all scalar/list/object/null/long identity JSON shapes through read-only command and seed rejection; daily and malformed arithmetic inputs; unequal 6/10-second periods first collide at 24 seconds, microsecond offset does not; 61 violations retain only 50 safe detail entries. SQL trace permits SELECT and Django DECLARE cursor FOR SELECT only. |
| F7 audit cutoff | The report applies one as_of to shared and derived resolution, lifecycle, paper, cohort, selection, admission, sample and assessment facts | `ActualFutureFactCutoffTests` persists later entry/result/shared/both derived scores and demands identical earlier report. Existing future missing and cancellation boundaries plus real later material cohort/closure/admission also preserve earlier report. All named report violation codes have positive and clean read-population counterexamples, including nine simultaneous absent dispositions, semantic source contradictions, assessment leakage/pairing and malformed source diagnostics. |
| F8 historical harness | Permanent `HistoricalDatabaseMixin` isolates the original Phase2 migration class in UUID-owned normally migrated historical schema; current installed graph is not mutated or made reversible | Both original test assertion bodies remain unchanged. Full current schema exists in the original runner database. Temporary historical market 0030 / research 0014 visits 0029→0030 normally, uses only documented market 0027 accommodation, and drops its exact database. Assertions prove original connection identity and ordered migration history restored. Exact integrated suite no longer has the branch-only Phase2 migration failure. Nineteen existing Gate8 failing identities still have different base/branch causes and are not called passing. |

No reviewed migration 0018–0025 or older migration was rewritten. Corrections are
forward 0026–0030, with no additional fake, disabled migration module, trigger
bypass or immutability relaxation. The original main migration graph dependencies,
including research 0014, remain intact. The historical fixture boundary and its
limits are explained in `review-lessons.md`.

## Regression evidence and fixture changes

The untouched base archive matches all 478 Git blobs; see
`base-source-verification.json`. Exact base broad command reproduced the tester:
222 tests, five failures, 23 errors,59.632 seconds. Initial corrected branch broad
run was 285 tests / 21 errors: 19 Gate8 identities plus two review fixtures that
fabricated missing_data with arbitrary labels. Those two fixtures now ingest an
actual entry and mature H1 gap, with historical clock room. Original cutoff,
missing-denominator and UI assertions remain; expected reason is the real
`hourly_coverage_unavailable`. A later 300-test broad run had only 19 errors.
`normalized-differential.json` records the final 301-test run and exact identities.
The final result is 301 tests / 19 errors in 145.055 seconds, zero branch-only
failing identities, and nine base-only failing identities. The 19 shared identities
have different causes: base market 0027 reverse validator
versus branch irreversible prospective migration 0030. Nine other base failing
identities pass on branch. No readiness failure remains after disk recovery.

Focused evidence includes 85 passing tests in 27.806seconds, the actual later-fact
cutoff test, and fully unmocked equality test (6.138 seconds). `makemigrations --check --dry-run`,
Ruff checks/format and `git diff --check` pass. Final exact broad command:

```text
manage.py test forecasts operations dashboard market.tests.test_phase2_ingestion market.tests.test_phase2_remediation market.tests.test_h1_alignment_diagnostics market.tests.test_gate8d2_readiness_correction --keepdb --noinput
```

The evidence retains mistakes in new test construction: reused existing contract
version; unrefreshed trigger-owned audit field; Django foreign-key descriptor
rather than read-boundary fixture; candle hash source rejected before intended
probe; incomplete source prohibited by existing constraint; nested/future fixture
clock; endpoint not yet available before expiry; and read-only DECLARE cursor
misclassified by a SELECT-only assertion. None was silenced by weakening a product
invariant. Read-only query syntax was inspected before adjusting that oracle.

## UI and safety

`screenshot-manifest.json` links 13 actual PNG/DOM pairs from the running current
app, including expiry/no-entry versus entered missing-data, target/invalidated,
closed owner, pending owner/assessment/admission, abstention, mature/immature
populations, missing/incompatible control and normally upgraded legacy state.
Fixture scripts use real local services and explicit synthetic provider stubs.
The owner-required fixture forces only the capacity choice so an open decision
can be shown; no production decision was made. Isolated headless Chrome captured
localhost only, and screenshots/DOM were inspected. No template changed during
this correction loop.

Disk fell below the unchanged 2 GiB readiness threshold; no unowned files or gate
were changed. The owned cluster was stopped until the user restored 66 GiB. One
restart omitted command-line port and failed to bind 5432 without connecting to a
database; restart explicitly on 127.0.0.1:55843 succeeded. All Django invocations
used sanitized explicit owned database settings, PSYCOPG_IMPL=python and the
Postgres.app library path. No default database, secrets, existing retained cluster,
real provider, email, production service, push, deploy or infrastructure action
was used. Final artifact manifest records cleanup and committed HEAD.

Remaining acceptance considerations: runtime database superuser is the previously
accepted/deferred constraint; the 19 historical Gate8 errors remain explicit;
review-population injections test corrupt read diagnostics without manufacturing
forbidden stored rows; confidence and promotion outcomes are descriptive research
checks, not profitability, skill or activation claims. Tester must independently
re-verify F1–F8 and adjacent evidence before PM starts.
