# Phase5.5 sealed offline engine

This is an engineering candidate, not acceptance or trading approval. Use the
private acquisition cache from the coverage audit; never seed instruments or run
the production scheduler to use this engine. Original Phase5 definitions,
prospective populations, migrations and negative failed-break evidence are unchanged.

## Freeze before development

Use the isolated `.candidate-data/phase55-v1/venv`, with `OMP_NUM_THREADS`,
`OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` and `VECLIB_MAXIMUM_THREADS` all set to
`1`. The executable registration binds package versions, timezone bytes, source
bytes, the outcome-blind coverage audit, acquisition lineage and exact manifests.
Run `python -m research.validation_batch register` and commit its JSON output as
`docs/phase5.5/frozen-registration-v2.json` **before** invoking `run`. Preserve
the first registration in `frozen-registration.json`; see `validation-revision-2.md`
for the development-discovered initialization correction. Registration
records its real creation time in the private append-only SQLite catalog; it
never asserts historical acquisition or historical registration.

The specification and acceptance matrix were committed before outcomes. The
registration source digest additionally binds the complete opportunity, exposure,
cost, missingness, robustness, dependence and reporting implementations. Source
or runtime drift refuses; material changes require a new immutable revision.

## Bounded development and restart

`python -m research.validation_batch run --registration ID --strategy ID
--instrument PAIR --start UTC --end UTC` evaluates 1–32 whole UTC days. Only
the registered development interval is admitted, before any price blob is loaded.
Start a pair/identity at `2019-01-07T00:00:00+00:00`; subsequent chunks require the
preceding daily checkpoint. Repeat an interrupted chunk: identical bytes converge;
conflicting bytes refuse. A crash cannot publish half a checkpoint. Each daily
checkpoint includes every planned opportunity, including unavailable/no-setup/
occupied states, and carries active-position state into the next chunk.

There are 15 baseline/readiness identities and four paired risk identities.
Overlay runs require `--baseline` and reuse that baseline's exact opportunities;
they cannot create an independently selected directional population. A complete
run traverses every registered instrument and baseline over development, then
reports each baseline and each overlay separately for every baseline. No strategy
family is pooled with another. The six ORBs retain separate session identities.

The explicit prerequisite failures for daily financing, range, carry and macro
are evaluated as unavailable without loading prices unnecessarily. The EWMAC and
breakout exposure mappings are frozen in the contract but are not executed in
the absence of mandatory genuine financing. No model financing substitutes.

## Reports and limits

`python -m research.validation_batch report --registration ID --strategy ID
--instrument PAIR` writes immutable canonical JSON and plain English under
`.candidate-data/phase55-v1/reports`. Use `aggregate` for the fixed 12-account
population, or add `--baseline ID` for an overlay. Reporting refuses incomplete
checkpoint chains. Aggregate account return uses 12 independent CAD100000
accounts, including unavailable instruments, rather than selecting survivors.

Observed BA spread, modeled commission/slippage and retrospective conversion are
separate. Realized drawdown is explicitly **not mark-to-market drawdown**. Candle
data does not establish actual fills, queue, path, or exceptional-session vintages.
Gaps invalidate affected lookbacks rather than being invented as market closures.
Active UTC ISO weeks are primary dependence units, with cross-week holdings linked
conservatively. Missingness and inadequate evidence produce inconclusive, never a
pass. Missing exceptional-session vintages block integrity-clean retention even
if diagnostic net is positive. No candidate can be retained in this engineering run.

The historical holdout is sealed and this candidate has **no release option**.
An authorized continuation must preserve this exact frozen manifest, thresholds,
candidate proposal and source history. Do not execute holdout outcomes to verify
the seal: use synthetic refusal tests.

## Forward capability and ownership

`shadow` reports elapsed time and missing evidence, not synthetic confirmation.
The manual `forward_shadow` API accepts only an original verified Phase4
`SnapshotInput`, rejects retrospective bars/future cutoffs, and binds paired
overlays to the same baseline snapshot. Its execution/net remains unavailable
without genuine forward execution evidence. It performs no collection, ORM write,
recommendation, schedule or order. The 8–12-week window begins 2026-09-11; elapsed
calendar time alone is never evidence.

Keep private acquisition/catalog/report artifacts for replay. Clean owned test
databases and processes; do not alter shared databases or the shared virtualenv.
Independent review, a maximum of one consolidated correction cycle, and PM
traceability follow the clean committed engineering handoff. No push or activation.
