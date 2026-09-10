# ADR: Python owns calculation; PostgreSQL owns durable facts

Status: proposed for independent review. No Phase1–4 semantic change authorized.

## Decision

Python owns pure interval/availability calculations, feature formulas, canonical
serialization and deterministic semantic replay. PostgreSQL owns relational
identity, uniqueness, immutability, transaction-time recording and synchronization.
Keep every published SQL guard. A Python check alone cannot protect direct SQL,
concurrent writers, deferred relationships or immutable snapshot identity.
Do not translate additional feature formulas to SQL and do not remove existing
enforcement merely because Python also validates the same input.

`market.availability` is the pure live-time boundary. Ingestion re-exports its
existing `live_candle_completion` API for compatibility. Live window enumeration,
frozen observation construction, feature availability and integrity verification
use that boundary. These changes do not alter query predicates, selection order,
descriptor body/version, output schema, hash inputs or runtime policy constants.

## Different clocks remain different contracts

| Value | Meaning and rule |
|---|---|
| Source timestamp | Start of the provider/registered interval; never knowledge time |
| Live completion | M15/H1/H4 absolute duration; D/W New York wall-clock close |
| Historical completion | `registered_candle_completion` retains the sealed legacy contract; provider-observed H1 has its explicit contract-dependent absolute rule |
| Observation time | Provider evidence was observed; not necessarily system-recorded yet |
| First known | Maximum of observed and recorded time; null recorded time retains legacy semantics only |
| Availability | Maximum of completion and first-known time |
| Cutoff | Equality is eligible; a one-microsecond later prerequisite is unavailable |
| Phase3 candle/run evidence | Existing successful-run and finished-at contract; do not silently replace it with Phase4 observation-revision semantics |

`eligible_observations` retains its indexed ORM predicates, finite elapsed-time
window, DISTINCT ON latest eligible revision and SQL LIMIT. The pure scalar API
does not fetch data or replace that query with Python filtering. Missingness,
later revisions and late recording never rewrite a previous snapshot.

## Persistence and replay

The input-series lock is acquired before selection and held until commit.
PostgreSQL time is checked after waiting. Identity includes definition digest,
instrument, cutoff, requested scope, input-manifest hash and research-evidence
hash. The identity lock and unique constraint resolve concurrent identical work
to one row. Different output for that identity remains a determinism violation.
Independent replay validates exact cited evidence and causal prerequisites;
canonical hashes alone do not prove semantic truth.

Retain bounded integrity paging, scope-specific definitions, immutable observation
revisions, research vintage lineage, and raw-SQL/non-superuser refusal tests.
No new ledger, adapter, configuration framework, schedule or consumer is needed.

## Alternatives rejected

* One completion formula for all historical and live data would alter autumn DST
  membership in sealed historical inventories.
* Python-only enforcement permits races and direct-SQL corruption.
* Duplicating feature formulas in SQL adds a second calculation authority.
* Refactoring Phase3 availability into Phase4 revision selection changes evidence
  identity rather than preserving behavior.

Verification uses explicit clock boundaries, DST divergence, existing SQL/Python
parity, descriptor-pin tests, immutable identity races, late evidence tests and
the combined available-evidence suite. Exceptional-session attestation is a
separate operational readiness gate; it cannot reinterpret the frozen calendar.
