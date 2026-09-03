# Failed-break detector v2 bounded benchmark

This report records return-blind measurements for the additive CI and benchmark correction based on `270b7b388acc94060b0ba06558a1a034383a481a`. It is not a v2 S0 acceptance, an S1 runner, or authority to execute S1.

## Environment and reproducibility

- Apple arm64, macOS 26.5.2, Python 3.11.4, Django 5.2.17.
- Persistence database engine: PostgreSQL 15.5 on a private Unix socket with TCP disabled.
- Harness: `research/benchmarks/detector_v2_benchmark.py`, SHA-256 `7716b25b9388077a2fab1ed942c7328efa5e901d021f0c9a671b09b41a68aa57`.
- Compute result: `detector-v2-compute-benchmark.json`, SHA-256 `b35a7b310218d9832b3de52318fdbc8df2a6d51d82abbd285e48684c5917fd56`.
- Persistence result: `detector-v2-persistence-benchmark.json`, SHA-256 `3d14e52022aa4378cfe776a7f9643da8356098967648fb0475d7309f16a53277`.
- Accepted backup: `trade_recommender_research-post-gate-s1.dump`, independently verified SHA-256 `9b8bb6845fe1f8b9dcb0f340d13c0edfe09529564065095318781c89c7a677e0` before restore.

Compute invocation (provider credentials unset):

```bash
.venv/bin/python -m research.benchmarks.detector_v2_benchmark \
  --output /private/tmp/detector-v2-compute.json compute --events 63500
```

Persistence invocation after restoring the accepted backup into `detector_v2_benchmark_post_s1` in an isolated temporary PostgreSQL cluster:

```bash
POSTGRES_DB=detector_v2_benchmark_post_s1 \
POSTGRES_USER=oluwatomisintaiwo POSTGRES_PASSWORD= \
POSTGRES_HOST=/private/tmp/detector-v2-tests.1Oj66V/socket POSTGRES_PORT=55439 \
POSTGRES_CONN_MAX_AGE=0 \
.venv/bin/python -m research.benchmarks.detector_v2_benchmark \
  --output /private/tmp/detector-v2-persistence.json persistence \
  --dataset-id 3 --instrument AUD_USD --year 2018
```

The exact socket path was ephemeral. The benchmark refuses database names without the `detector_v2_benchmark_` prefix. Its only writes were to `detector_v2_benchmark`, an isolated mirror schema removed before exit. The restored public `research_analysisrun` count remained 344,667. The disposable databases were dropped, the server stopped, and its temporary directory removed.

The database-backed query-budget regression is runnable from a clean checkout against any disposable PostgreSQL bootstrap database with:

```bash
POSTGRES_DB=<disposable-bootstrap> POSTGRES_USER=<test-role> \
POSTGRES_HOST=<isolated-socket> POSTGRES_PORT=<isolated-port> \
POSTGRES_CONN_MAX_AGE=0 \
.venv/bin/python manage.py test \
  research.tests.test_failed_break_detector_v2_queries \
  --settings=config.detector_v2_test_settings
```

Those dedicated settings synchronize current model tables without running the data-gated production migration graph. They do not alter migration 0027 or production settings. The regression creates no fixture dependency on an existing research database or backup, proves one registration query per run, proves three preload queries per instrument, and repeats the preload at one and five rows per granularity to prove row-count invariance.

## Compute-only workload

The deterministic 63,500-event fixture contains 60,000 H1, 3,000 D and 500 W sealed timestamps. Its inventory SHA-256 is `d5bb9e6f4100c60272d92ba632eb1e65710c0808830cbb95f95c327a6926e139`.

| Phase | Seconds |
|---|---:|
| Inventory construction and canonical hash | 0.072426 |
| Ordered completion merge, admission projection, exact membership check and horizon index | 0.283125 |
| Total including result construction | 0.412539 |

This supersedes the unrecorded approximate two-second projection with a reproducible measurement. It is deliberately compute-only: it excludes registration validation, ORM preload, persistent evidence writes, full level/setup/eligibility materialization and all outcome work. It must not be presented as complete S1 runtime.

## Disposable persistence workload

AUD_USD calendar year 2018 contained 6,216 H1, 259 D and 51 W sealed members. Return-blind accepted S1 evidence supplied representative counts of 6,216 analyses, 308 levels, 310 lifecycle events, 11 setups, 20 attributions, 28 transitions and 17 entry-eligibility evaluations.

| Phase | Seconds |
|---|---:|
| Established registered-dataset validation | 1.671831 |
| H1/D/W preload (three ORM queries) | 0.500225 |
| V2 admission plus incremental H1 ATR and D EMA/ATR/pivot computation | 0.051328 |
| Return-blind workload-count queries | 0.018623 |
| Isolated schema setup | 0.014775 |
| AnalysisRun-shaped persistence | 0.026537 |
| Level and lifecycle persistence | 0.004387 |
| Setup, transition and attribution persistence | 0.001784 |
| Entry-eligibility persistence | 0.000608 |
| Constraint/row-trigger verification | 0.001195 |
| Canonical report/hash generation | 0.004803 |
| Transaction commit | 0.001633 |
| Total | 2.322544 |

The isolated tables exercised primary-key, unique, foreign-key and check constraints plus a row-level evidence-hash trigger. Inserts used set-based batches. This is the closest safe workload without creating the separately reviewed persistent v2 runner. It does not reproduce the full governed production triggers, ORM payload construction or complete detector materialization, so these figures are an optimistic database-engine measurement rather than a complete S1 timing.

The persistence benchmark used the established production registered-dataset validator. The standalone v2 helper `validate_registered_successor` was also inspected: it currently equates `DatasetVersion.name` with the effective contract identity, while the accepted restored dataset row is named `failed-break-provider-observed-historical` and carries the effective identity relationally as `oanda-ba-ny17-friday-provider-observed-v2`. Changing that protected detector source would change its reviewed source and artifact pins, so this correction does not do so. The separately reviewed runner must resolve this fail-closed integration point under explicit governance; the clean query-budget fixture proves the one-query shape, not activation against persistent data.

## Complete-v2 planning range

The expected 344,817 v2 H1 analyses are 55.4725 times the measured instrument-year analysis count. Direct linear scaling of the measured reusable phases is about 34.4 seconds, but that is only a measured lower bound. Applying an explicit 3–15× engineering allowance gives a provisional **2–9 minute** range for a future preloaded, batch-writing v2 S1 runner on this machine.

The range assumes no per-row ORM reads, bounded bulk writes, similar v1-to-v2 level/setup/entry cardinality, single-process execution and comparable PostgreSQL/WAL state. It can become nonlinear through larger canonical evidence payloads, real governance triggers, index growth, batch-size choices, transaction memory, supporting-swing bookkeeping or changed v2 event cardinality. The actual reviewed runner must be benchmarked again before persistent activation; this range is not a runtime promise.

No post-entry outcome, return, P&L, provider, credential, production database or persistent research database was accessed. The remaining activation prerequisites are a governed v2 S0 acceptance and a separately reviewed runner, including resolution of the registered-dataset validation integration point above.
