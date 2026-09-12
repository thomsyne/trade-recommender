# Coverage gate blocked — no outcomes calculated

Audit date: 2026-09-11 UTC. This is an engineering checkpoint, **not** a frozen
registration, development evaluation, candidate/reject proposal or pre-release
review candidate. All strategy output access, including the historical holdout,
remains closed. No strategy evaluator or simulator was run, even on synthetic
data, during this audit stage.

## Prior-use attestation

The coordinator relayed the owner's exact statement in this engineering thread:

> I attest that no Phase 5 strategy results for that period have previously been inspected.

The explicitly identified period is [2025-01-06,2026-09-07) UTC. General market
knowledge is not disqualifying. This statement supplies the human attestation;
it is not inferred from database counts. Merged Phase5 documentation states no
observed economic population was certified; Git history shows the implementation
and review checkpoints on 2026-09-10. Deployed Phase5 tables are absent, rather
than present with zero rows. Earlier deployed `research_analysisrun` has zero
rows. Other historical failed-break evidence in repository history is preserved
and remains prior research, not reclassified as untouched Phase5 evidence.
No result payload or old performance table was read to establish these facts.

## Sources inspected and limitations

| Source | Observation | Meaning |
|---|---|---|
| Shared checkout `.candidate-data` | Three directories, no files | No local candidate dataset available there. |
| Default local PostgreSQL connection | Connection timeout | Local database coverage unknown, not zero; no database started or modified to repair it. |
| Configured AWS deployed primary | Online SSM; two successful read-only metadata audits inside existing web container | Source inspected without migration, deployment, restart, provider request or application writes. |
| Deployed governed dataset table | Zero rows | No governed dataset manifest available here. |
| Deployed candle observation ledger | Table absent | Acquisition/revision semantics cannot be reconstructed from this source. |
| Provider contract/code | OANDA BA candle endpoint, explicit historical terms limitations | Endpoint capability is not proof of acquired 2017–2026 coverage or genuine historical costs. No provider call made. |
| Other restores / historical data hosts | No qualifying source supplied to this thread yet | Unknown, not asserted absent globally. Coordinator asked for pointers. |

The existing environment files were parsed for configuration without printing
credentials. AWS access used the configured instance only. SSM necessarily
records command invocation metadata; the commands performed read-only SELECTs
in repeatable-read transactions, 60-second statement and two-second lock limits,
at most 500 output groups per query. No files were created on the deployed host
by the audit payload. Its only output is permitted metadata, gzip transported
to avoid SSM text truncation and saved locally as JSON. Successful decoding and
JSON parsing confirmed complete transport. No secret/account identifier, price,
direction, forecast, result, return or raw provider body is in these artifacts.

## Coverage by provisional period

Four pairs contain candle rows: EUR_GBP, EUR_USD, GBP_USD, USD_CAD. The deployed
instrument table has six rows, including AUD_USD/USD_JPY without candles in the
audited periods. This is not the canonical 12-instrument validation population.
Every reported candle has bid/ask columns present; this is neither executable
spread evidence nor permission to infer ticks, queue, path or fills.

| UTC half-open period | Coverage per covered pair |
|---|---|
| Warmup [2017-01-01,2019-01-07) | No candle rows. |
| Development [2019-01-07,2025-01-06) | 19 W rows, 2024-08-30 21:00 to 2025-01-03 22:00. No D/H4/H1/M15. |
| Sealed first [2025-01-06,2025-11-10) | 44 W rows, 2025-01-10 22:00 to 2025-11-07 22:00. No D/H4/H1/M15. |
| Sealed second [2025-11-10,2026-09-07) | 42 W rows; 76 D rows starting 2026-05-24 21:00; 483 H1 and 121 H4 rows starting 2026-08-09 21:00. No M15. |

No within-source duplicate intervals were found in the legacy coverage groups.
Nominal discontinuities are reported, not treated as missing trading intervals:
each pair has one >7-day spacing in development W and first-half W (608400s),
and second-half D/H1/H4 discontinuity counts 15/4/4 with maximum spacing
259200/176400/187200s. Without a genuine expected-open calendar, these are not
classified as weekends, DST or defects. No price calculations were needed.

There are 475 practice terms captures per pair, first acquired 2026-08-22 02:00,
last 2026-09-10 23:00 UTC. **None supplies commission.** Financing-day metadata
is present, but does not establish historical rate/rollover coverage. Account
currency is CAD. Historical slippage and account-conversion evidence are not
established. Calendar vintages begin 2026-08-23 and have no consensus entries;
date-only events are separately counted. They cannot attest empty windows or
provide historical event coverage. Macro coverage/acquisition/vintage metadata
for 27 series is retained without reading values; policy rates are not carry.

## Date and development decision

The proposed holdout spans 87 complete ISO weeks, with 44/43-week halves; tested.
Human prior-use attestation is established, **coverage is not sufficient**.
No replacement dates have been frozen: the inspected daily/intraday history
cannot supply even the required historical warm-up/development and the missing
cost/vintage evidence cannot be repaired by moving dates. Inventing a replacement
would violate the ordering gate. Original Phase5 prospective dates remain intact.

All 19 Phase5 identities remain **not evaluated**, not rejected and not retained:
EWMAC, breakout, fast MR, M15/H1 pullback, range, sweep reversal, acceptance
continuation, carry readiness, macro risk, fixed/EWMA/GARCH-t risk, and the six
London/NY wick/confirmed/FVG ORBs. A coverage blocker is not economic evidence
and is not an inconclusive strategy result manufactured by a mock batch engine.
Range/carry retain their existing unavailable evidence requirements.

Before a real registration can bind exact immutable manifests and dates, obtain
a qualifying governed historical source/restore and genuine cost/calendar/
financing/conversion vintages, or an explicit revised data-readiness scope from
the owner. No holdout release is requested. Engine, registration/persistence,
development evaluation and forward-shadow capability are still outstanding.

## Evidence identities and verification

| Artifact | SHA256 |
|---|---|
| Initial metadata audit `deployed-coverage.json` | `bdfcf17f6a5078cd16262ee131fc58dea4341a5b9828a6667388f4b6e3ba3d7e` |
| Follow-up `deployed-coverage-legacy.json` (includes legacy projection) | `fe9d05f3d8cb3974a04acec22339516649ac83a33a2243ae40e92f470f3c79b4` |
| Follow-up executed `research/validation_audit.py` | `d14893331d686642c65908095bef5a971cb01c75c84bbddd756861675b4eb0bd` |
| Final focused test log `audit-tests.log` | `6dca7e1e51eada992a634f95472986390e45c455948eddb1ff6b8deba8fb71e8` |

SSM invocations: `909565d1-5b23-4e13-abb3-b9093e10b125` (initial),
`5bacee2c-2a9d-44d0-b3ea-523204d4b02c` (legacy follow-up). Initial missing-column
queries are visibly unavailable, never retrospectively claimed successful.

Eight tests passed on **PostgreSQL 15.19 (Postgres.app), UTF8**, 0.108s.
They cover fixed query projections, UTC split boundaries, actual read-only SQL
write refusal, idle-connection enforcement, missing-table/column handling,
deterministic retry bytes, output-bound refusal, duplicate/non-null counts and
asymmetric timestamp discontinuities. No strategy outcome tests were run.
Ruff lint/format and `git diff --check` passed. No migrations or production
consumers changed, so PG15.14/17.6 integration and the full available-evidence
suite are deferred until a stable engine candidate, not claimed passed here.

The first seven-test attempt had four errors because the throwaway default
database used SQL_ASCII, returning bytes instead of the expected string for the
read-only guard. The guard correctly refused to proceed. A separate UTF8 database
fixed the fixture; the next seven-test run and final eight-test run passed, with
no guard relaxation. Initial failure log hash:
`662085505f458281e696d51e0c3d64638979a0702af4bc1ce1a4d750ee77eb83`;
intermediate UTF8 log hash:
`431fc1686d55269fefe8fd0efd20ce159fc53e60f9b144eb7f866c2d32342d1b`.

Reproduce focused verification only against a disposable database:

```sh
PHASE55_TEST_DSN='host=<owned-socket> port=<owned-port> user=<test-user> dbname=<utf8-test-db>' \
  .venv/bin/python -m unittest research.tests.test_validation_audit -v
```

Tests create/drop only uniquely named schemas in that explicitly supplied DB.
Without the variable, DB tests skip rather than contact configured production.

## Checkpoint preservation and cleanup

Local branch `phase5.5/offline-validation` starts at merged main
`b850c4ea618c34397e86fd8133b7255ff972f8ba`; local main, origin/main and live
remote main agreed before branch creation and after the audit. Acceptance/audit
contract checkpoint is `3195347`. All changes are new Phase5.5 documentation,
metadata artifacts and the standalone audit module/tests. Every base-tracked
file remains unchanged, including old migrations and Phase5 source digests.
No consumer/schedule imports were added. No other thread was created.

The owned PostgreSQL server was stopped cleanly. Its disposable cluster, sockets
and temporary logs under `/tmp/tr-phase55-owned` were removed after retaining
the final test log and recording earlier hashes. Existing database processes,
workspace virtual environment, environment files and user data were preserved.
Both read-only remote audit invocations finished successfully; no background
audit process, provider ingestion or schedule was left running. No push, PR,
merge, deploy, migration, activation, recommendation, order or trade occurred.
