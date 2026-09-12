# Baseline audit contract v1 (preregistered)

Claimed baseline: 292 recommendations; 222 with one or more document conflicts
already known at issuance; 734 recommendation-document references with such a
conflict; approximately 17.27% crypto-heavy slots lacking obvious macro/pair-title
relevance; nearly all recent news has generic global jurisdiction. These are
claims, not expected assertions, thresholds, or optimization targets. The original
artifact is not merged. Its cutoff and diagnostic vocabulary are unknown.

## Snapshot and provenance

Prefer the exact deployed read-only snapshot that produced the claims. Record
snapshot byte SHA256, deployed source revision, schema/migration inventory digest,
transaction cutoff (UTC, inclusive), extraction time, query/implementation hash,
and canonical audit-input SHA256. A fresh deployed read-only repeatable-read
transaction is a **new baseline**, never a reproduction of an earlier population.
Never use the active Phase5.5 private data or replay resources. No raw body,
provider values, credentials, or unrestricted URLs in committed audit outputs.
Inspect production only through an existing authorized read-only route; no schema,
configuration, container, service, schedule or data mutation; never call Claude.

## Population and exact definitions

* Population: every persisted `forecasts.Recommendation` with `generated_at <= T`
  in the identified snapshot; include abstentions, all methods/contracts and pairs.
  Report counts by contract, pair and generation range. Missing generation time is
  separately invalid, not silently excluded. Do not deduplicate recommendations.
* Issuance = persisted `generated_at`; information cutoff is independently retained.
* Slots = every element (including repeated IDs) in each recommendation's frozen
  `input_payload` news list, using its actual envelope. Report missing/malformed
  envelopes and IDs separately. Do not join current snapshots to reconstruct slots.
* Reference denominator = distinct `(recommendation_id, document_id)` pairs in
  those slots; separately report repeated slots and total slots.
* Conflict-known-at-issuance = an immutable `ResearchDiscrepancy(kind='conflict')`
  whose `entity_key` equals `document:<canonical_hash>` for the referenced document,
  and `observed_at <= recommendation.generated_at`. Report additionally known by
  information cutoff, and first learned later (but by T). Canonical `quality` is
  not historical knowledge. Later discrepancies must not be backdated. The old
  classifier does not prove material falsehood; this is a legacy conflict diagnostic.
* Crypto diagnostic v1: frozen slot title contains whole-word crypto vocabulary
  (`bitcoin`, `crypto`, `cryptocurrency`, `ethereum`, `ether`, `blockchain`, `token`,
  `stablecoin`) and lacks whole-word pair currency/country/central-bank vocabulary
  or explicit macro vocabulary (`inflation`, `interest rate`, `central bank`,
  `liquidity`, `monetary`, `employment`, `gdp`, `recession`, `treasury`, `yield`).
  Denominator is **all frozen news slots**, not crypto slots or distinct documents.
  Missing titles counted separately; inspect only frozen title, not later content.
  Report numerator/denominator, exact rational and rounded percent. This is a
  narrow lexical diagnostic, not a relevance label or replication of an unknown
  original formula; never optimize the production relevance policy to match it.
* Jurisdiction: frozen slot value when present; missing is unknown. Separately
  report snapshot-current source-policy jurisdiction through the exact referenced
  representation if identifiable; never present current policy as issuance truth.
  `ZZ` is a generic code, not proof of global/systemic relevance.

## Reproducible artifact and reconciliation

Commit a sanitized aggregate JSON result with explicit unavailable fields, hashes,
definitions/version and differences from claims. Keep sensitive source material
outside Git. Re-run the same extractor over the same input to require identical
canonical bytes. If the exact snapshot cannot be obtained, record unavailable
instead of inventing counts; publish the reproducible command and pending gate.
