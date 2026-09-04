# Failed-break v2 exploratory-return runner architecture

Status: code-only implementation; persistent return execution is separately
unauthorized.

The runner has three fixed layers. The sealed-evidence adapter resolves the
accepted 82-event geometry and preloads registered H1/D candles in bounded
set-oriented queries. It emits exactly the normalized schema accepted by the
already governed pure calculator. The calculator remains the sole owner of
entry/exit, stop-first, conversion, commission, financing, equity and metric
formulas. The persistence service writes one immutable `research.JobRun` JSON
result inside one transaction, then reads it back and verifies its canonical
evidence hash before commit.

`JobRun` is the smallest compatible existing model: it already provides
semantic dataset/strategy foreign keys, a configuration hash, an immutable
record contract and a unique idempotency key. A new schema would duplicate
those controls. The complete result is one hash-bound JSON payload containing
lineage, configuration, the exact 82-key input manifest, calculator output,
per-section hashes and the complete report hash. No event is represented as an
independent trade merely because it has multiple book memberships.

The default management command loads only fixed committed artifacts and reports
`IMPLEMENTED_NOT_AUTHORIZED`. It does not instantiate the Django evidence
adapter, query outcomes or write. `--execute` first requires a separate
fixed-path authorization artifact. That artifact is intentionally absent, and
the current loader fails before importing the Django adapter. Adding an
arbitrary file, environment value, database row, CLI flag or owner override
cannot unlock execution; a later reviewed code gate must pin and verify exact
authorization bytes.

After future authorization, evidence selection remains limited to dataset
`phase-2b1r-v2`, strategy `failed-break-phase-1-admission-correction-v2`, the
accepted v2 S1 job and the committed geometry keys. Sealed inventory is loaded
before price rows; required candle keys are derived from event entry/horizon,
actual provider-D completions, possible H1 exits, rollover instants, daily
marks and fixed CAD routes. Missing, conflicting, unsealed, cross-lineage,
duplicate or unresolved evidence aborts the transaction. There is no partial,
retry or resume path.

The synthetic benchmark exercises the full adapter → calculator → transactional
store path for 82 physical events, including 10,000 deterministic bootstrap
replicates. Its repository-query counters represent the synthetic port calls,
not PostgreSQL SQL timing. Results explicitly exclude production database
latency, trigger work and JSONB commit latency; a disposable restored-database
rehearsal remains required before any persistent authorization.

The conservative initial operational ceiling is 15 minutes wall clock, enforced
externally for any future authorized run. This is a stop limit, not a runtime
promise: the synthetic 82-event rehearsal completed in about 4.54 seconds with
about 95 MB peak RSS, but it contains no PostgreSQL evidence-loading, constraint,
JSONB-write or commit latency. A disposable restored-database rehearsal must
validate that ceiling before persistent authorization.

The result is exploratory-only. It cannot authorize promotion or live trading,
and those boundaries are checked both in the preregistration loader and the
persisted result payload.
