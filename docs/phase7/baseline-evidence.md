# New deployed baseline, not a reproduction of remembered totals

The owner explicitly authorized this new measurement after confirming the
historical artifact/cutoff was unavailable. Audit definitions were committed first
in `15e2fa8`; the measured aggregate is [baseline.json](baseline.json).

| Measurement | New measured result | Unverified historical claim |
|---|---:|---:|
| Recommendations | 324 | 292 |
| Recommendations with legacy conflict known at issuance | 242 | 222 |
| Distinct affected recommendation-document references | 777 | 734 |
| All frozen news slots | 6,438 | Unknown |
| Narrow crypto/no-obvious-title-link slots | 1,260 / 6,438 = 19.571295% | ~17.27%, original formula unknown |

All recommendations were contract 3: EUR_GBP 82, EUR_USD 80, GBP_USD 81,
USD_CAD 81. Issuance range is 2026-08-25T04:28:38.097718Z through
2026-09-08T13:35:19.215483Z. Latest information cutoff is
2026-09-08T13:35:18.627241Z. The 777 references were already conflicted by both
issuance and information cutoff. A further 1,351 references first had a legacy
conflict observed after issuance but before the audit cutoff. This does not mean
those documents are false, nor establish conflict materiality.

All 6,438 frozen slots lacked jurisdiction metadata. Snapshot-current source-policy
distribution across 1,370 stored representations was CA82/EU25/GB53/US16/ZZ1194.
It is an all-representation distribution, **not** a recent-news-at-issuance result.
The broad claim about nearly all recent news therefore remains unverified as
phrased. No current source policy was substituted for a missing frozen property.

## Source and query identity

Application instance `i-06a17f7ac14d7b282`, region `us-east-1`, source label
`deployed-primary`, verified database `trade_recommender`, server PostgreSQL15.14.
The Phase5.5 replay instance and its data/resources were not accessed.

Metadata-only SSM command: `2fff0396-b6f1-46cf-b326-6ff32f8a2aa9`.
Aggregate command: `6e31b743-30a1-4744-8e20-494f38d64f4a`.
Read-only transaction cutoff: **2026-09-11T15:33:10.685194Z**;
snapshot identity `95219:95219:`. Audit implementation/source SHA256:
`97584f77a3f81f2641733fbf44edbc4825fb0cac35f8446475e0ff93cde410a3`.
Canonical input-projection SHA256:
`46ac3570d30f195cde7bc19e47f144e5b4523f9a23e17e77dc5858345b0b8e3b`.
Migration inventory SHA256:
`4735c217130fa8298c1f134be701cb14695fb4b96264cb943a362eefeaf2f553`.

[Source provenance](source-provenance.json) retains hashes of four deployed
implementation modules from a separate safe metadata read. The deployed build
revision reports `unknown`; image digest is unknown. These gaps are not silently
filled with the local merged revision. No database dump was acquired and no
snapshot export remains open. The transaction's source-row hash and aggregate
are frozen, but full exact source-row replay needs a matching retained restore.
That limitation is distinct from the fully reproducible audit algorithm.

## Reproduction without secrets or production mutation

Use the committed standalone `research/evidence_baseline.py` at the recorded hash.
It imports no new model and can run from an in-memory payload on the deployed
container. Run `main(metadata_only=True, code_sha256=<verified file hash>)` first,
then `main(metadata_only=False, code_sha256=<same hash>)`. The established route is
SSM to the application instance, then Docker Compose `exec -T web python -` in
`/opt/trade-recommender`; do not print `.env`, environment dumps, expanded Compose
configuration, connection strings, or raw exceptions. The extractor closes any
idle connection, asserts read-only mode, uses repeatable read/UTC and statement/
lock bounds, and always rolls back/closes. It emits only aggregate counts/hashes.

The exact SQL projections, JSON envelope (`input_payload.evidence.recent_news`),
lexical vocabulary, duplicate/reference definitions and as-of comparisons are in
the committed source and [preregistered audit contract](audit-contract.md). Frozen
input titles drive the diagnostic; current document titles do not. A later live
run is another baseline, not a reconstruction of this transaction. A matching
authorized restore must reproduce the input hash before claiming exact replay.
No Claude call, source-body export, backup/restore command, production mutation,
or provider request was used. The diagnostic never sets relevance targets.
