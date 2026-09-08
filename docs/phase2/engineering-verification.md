# Engineer verification record

Base: `main` / `origin/main` at `61ff8bc021744b0b785843c994db422c9a742431`.
Branch: `phase2/g10-ingestion-only`; prerequisite Phase 1 commit
`6cc1325d06538cefaf1cf25b49175fdcbfcb8a22` is an ancestor. Coordinator fetched
refs, checked merge base and clean worktree before implementation. No applicable
AGENTS.md found. No push, deployment, production access or provider calls occurred.

Ownership inspection covered Instrument registry, canonical/research seeders,
OANDA live/historical boundaries, store_ingestion and live observation/snapshot
lineage, validation/freshness, task dispatch, durable scheduler/worker, decision
creation/batches, sizing conversion graph, portfolio/paper/reviews, pair evidence,
historical failed-break ownership and dashboard active filters. Final changes to
research/services.py and forecast creators are only inactive-entrypoint guards;
no historical acquisition, strategy, model prompts, archived evidence or UI changes.

New migration 0030 adds the single acquisition field and enables existing canonical
and active rows without changing identities or active values. A real 0029→0030
migration test checks six realistic rows and active/inactive unknown rows. Concurrent
seed testing uses independent PostgreSQL connections. The final Phase 2 tests cover
12/4/8 registry counts, 48 schedule identities, deterministic minute phases,
reseed/deadline stability, disable preservation, direct disabled task rejection,
terms code set/missing configuration, direct decision entrypoint rejection,
32 HTTP-mocked pair/granularity ingestion cases (JPY/sub-unit six-decimal prices),
zero forbidden artifacts and downstream calls, all-pair A→A→B→A overlap history,
invalid OHLC/crossed/incomplete rejection, malformed responses, report states,
batch/portfolio/dashboard enumeration, actual migration and concurrent seed.
Existing OANDA, quality, observation, lineage, technicals, freshness and queue tests
cover pagination/includeFirst, DST/alignment, gaps, cross-source changes, immutable
conflicts, data-bound technical snapshots and scheduler recovery.

Evidence files are external new artifacts under
`/Users/oluwatomisintaiwo/trade-recommender-artifacts/phase2-g10/`.
`engineer-failing-old.log`: before implementation, 4 tests produced 3 failures and
1 error (missing eligibility field, coupled resolution, six-code registry/terms).
`engineer-malformed-failing-old.log`: missing candle lists and text completion
produced 2 failures/1 error before the narrow live parser correction.
`engineer-focused.log`: first expanded PostgreSQL run: 142 tests/32.125 seconds,
one accepted superuser assertion failure; all Phase 2 and actual migration cases passed.
`engineer-final-focused.log`: 154 tests/47.988 seconds, the same single accepted
superuser assertion; all 19 then-current Phase 2 tests and old0028/0029 fixture tests passed.
The legacy migration fixture now inserts Instrument using the historical0028 model,
deferred-loads its current service identity and restores current graph leaves in teardown.
Every original assertion remains intact. This fixes a concrete new missing-field fixture
incompatibility, not the deferred0027 gate.

`engineer-final-full-suite.log`: 1,097 tests/422.493 seconds, 1 failure/353 errors.
Base full suite: 1,078 tests/427.267 seconds, 7 failures/330 errors. Exact IDs and exception
lines are in `engineer-final-full-differential.json`: no branch-only assertion failures;
32 branch-only error IDs report the newly added column missing after earlier failed
backward migrations leave an older schema. These are **new failure manifestations**,
not claimed to be identical failures or a green suite. Their exact IDs are rerun on a
clean schema in `engineer-final-regression-command.json` / `engineer-final-regression.log`.
Base-only IDs are also retained; no performance or bug-fix claim is inferred from their
absence in a schema-cascaded run.

`engineer-exact-window-failing-old.log`: three actual mocked fetches of an identical
window with A→B→A volumes produced only one run, failing the new regression (1 test).
The live client now records retrieval time/RequestID in request provenance to distinguish
new HTTP observations from persistence replay. Historical fetch manifests are untouched.
The final regression verifies three runs/three observations and one frozen candle,
then replays the exact final manifest without adding anything. This late correction is
covered by the final focused regression; the earlier full run was at b0a4ed3.

Tests use `env -i`, an isolated PostgreSQL cluster at 127.0.0.1:55482, user
`phase2_test`, disposable databases, and mocked HTTP transports. The installed
psycopg binary has the wrong architecture, so `PSYCOPG_IMPL=python` and the local
Postgres.app library path are used. No environment files or secrets were loaded.

Sanitized command prefix (from repository root):

```sh
env -i PATH=/Applications/Postgres.app/Contents/Versions/latest/bin:/usr/bin:/bin \
  DYLD_LIBRARY_PATH=/Applications/Postgres.app/Contents/Versions/latest/lib \
  PSYCOPG_IMPL=python DJANGO_SECRET_KEY=phase2-test \
  POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55482 POSTGRES_USER=phase2_test \
  POSTGRES_DB=phase2_final .venv/bin/python manage.py
```

Disposable bootstrap: migrate market to0026, record only0027 with `--fake`, then
apply remaining migrations genuinely. This is the pre-existing accommodation in
market/tests/timeline.py; historical evidence was never synthesized or changed.
Clean migration graph failure was independently reproduced on base. Runtime
superuser and migration0027 remain accepted/deferred exceptions, not repaired here.
Full app suites run serially: `test market operations forecasts research dashboard
--keepdb --noinput`. They cannot be represented as a clean full-suite pass because
backward migration tests hit the missing0027 validator and cascade into later tests.
Exact baseline-versus-branch failures and final focused outcomes are recorded in this
record, the external handoff and logs; no tests were skipped or assertions weakened to hide them.

Static checks: `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`,
`.venv/bin/python -m compileall -q market operations forecasts research dashboard`,
`git diff --check`, and sanitized Django `check` plus
`makemigrations --check --dry-run` are required before handoff.

This is an engineer handoff for independent testing, never implementer acceptance.
Production capacity, canary observations and strategy activation remain unapproved.

## Final clean verification outcome

`engineer-final-regression.log`: **76 tests passed in 66.679 seconds** on freshly
accommodated `test_phase2_regression`. This includes all **20 Phase 2 tests**, existing
OANDA/quality suites and **every one of the 32 branch-only error IDs** from the full
suite differential. Thus the additional full-suite error manifestations were reproduced
as older-schema poisoning, and their concrete runtime regression surface passes on
head schema. No skips or weakened assertions were used. Historical source files,
research contracts, prompts and existing evidence remain unchanged.

The full suite is still not green and is not described as green: its one remaining
assertion and common errors are retained in the exact differential artifacts. The
isolated broad focused run has the accepted runtime-superuser assertion only. Operational
capacity, canary rollout and season-specific DST observation remain pending separate
production authorization. The engineer considers this **READY for independent testing**,
not self-approved for acceptance, deployment or trading.
