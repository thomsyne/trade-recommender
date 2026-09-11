# Phase 7 dormant evidence contract and review flow

**Merge is not activation.** Nothing here authorizes packet/model consumers,
provider spend, broader Anthropic content, strategy promotion, Phase5.5 release,
deployment, notifications, recommendations, execution or trading. Independent
engineering review and PM acceptance are separate from deterministic validation.

## Ownership and immutable lineage

`research.evidence_quality` owns pure v1 rights/conflict/relevance/packet semantics.
`research.evidence_store` owns explicit append operations and immutable-source
replay. `forecasts.evidence_context` owns an offline request/response contract;
it contains **no network transport**. Existing ingestion, recommendation,
interpretation, schedules, consumer configuration and pages remain unchanged.

`research.evidence_models` owns the seven Phase7 model declarations. They retain
the `research` app label, original tables, fields, constraints and migrations.
`ResearchConfig.import_models()` imports the extension after the historical
models module, during Django's model-registration phase and before `models_ready`
or any `ready()` hooks. No evidence service runs at startup. The historical
`research/models.py` is byte-identical to the required base and its S1 source pin;
no governance pin or artifact was relaxed. The fresh-process registration test
checks this import boundary and exact migration-state equivalence. Since
`import_models()` is a framework lifecycle hook rather than a prominently
documented customization API, retain that regression on Django upgrades.

Seven new research records use protective FKs, unique canonical digests, ORM
mutation refusal and SQL update/delete/truncate guards. `recorded_at` comes from
the database clock, not the caller. Source reviews and evidence writes serialize
through a transaction advisory lock in READ COMMITTED. Packet construction takes
the same lock before querying its universe. Different processes therefore cannot
backdate an uncommitted new representation through a packet cutoff. The existing
test-database/auth-table-lock truncate exception is reused; production/non-owner
truncation is not enabled. Populated reversal refuses before dropping evidence.

`ExactEvidence` captures the supplied title/summary/publication timestamp rather
than current `ResearchDocument` text. It binds immutable retrieval bytes/hash,
source item identity, canonical URL/hash, language/content type, first-observed
and retrieval timestamps, storage rights identity, and separate quality properties.
News admission reparses the immutable RSS/Atom retrieval and requires an exact
item match. Macro admission binds the exact immutable observation, normalized
value and retrieval; identity is series + observation period, not latest vintage.
Forward correction migration 0022 stamps the admitted macro series label in a
protected column and requires matching headline and empty supplied summary in
SQL. Replay compares that frozen label, never a later mutable series label.
An older candidate row without this provenance remains unchanged but cannot be
authenticated by the corrected loader; no current label is backfilled as history.
Macro timestamp precision must match the immutable observation's provider versus
retrieval precision (or explicitly remain unknown). News precision is checked
against the original XML timestamp: a date-only or timezone-free value cannot
be promoted merely because the legacy parser supplies a UTC datetime. Unknown
formats stay unknown. Required evidence without provider-exact precision abstains.
The old canonical document/representation/discrepancy remains intact. Nothing
backfills an unprovable historical permission, directness or timestamp precision.

SQL validates structural identity, closed envelopes and relational provenance;
it does not pretend that a hash proves a natural-language statement. A hash-
consistent raw-SQL text forgery is detected by parser replay. `freeze_packet`,
`load_frozen_packet`, `record_context_result` and the integrity audit verify that
replay before downstream use. Never bypass those with an ORM row or accept the
pure synthetic helpers as an authenticity service.

## Rights review is per content/use/processor, not item quality

Each review has six rows: raw body, headline, supplied summary, normalized fact,
derived label, URL/attribution. Each has seven independent cells: private storage,
private display, deterministic processing, external LLM processing, internal
reports, notifications, redistribution. Every cell is one of allowed, prohibited,
unknown, review-required, expired or superseded. Unknown is not permission.

An owner/reviewer must inspect the governing terms or written permission, identify
the actual source and processor, and retain the terms hash/version where lawful.
Record the terms URL, reviewer/time, jurisdiction, attribution, retention/deletion,
expiry and rationale. Do not copy protected terms bodies merely to obtain a hash.
Use `review_rights` to append a full prospective decision matrix; `supersedes`
must identify the preceding source/processor review. There is no seeded approval.
`local` storage reviews do not grant `anthropic` processing rights. The old
source-wide `llm_processing_allowed` flag is never consulted by this slice.

New exact storage requires a current local review for every stored populated
content field and URL/attribution. Packet inclusion independently requires an
as-of Anthropic review for deterministic headline processing, external headline
processing and attribution. A denied supplied summary is withheld independently.
External projection still withholds all raw bodies, URLs, normalized numeric
values and market levels even if a review says allowed. Numeric/authority-bearing
source text makes the external request unavailable rather than being rewritten.
Attribution text must itself pass the external-text boundary. Written permission
is a future review seam, not a source flag override. Expiry never automatically
deletes historical packets: retention/deletion is an explicit owner/legal review.

## Conflict and relevance are frozen facts about a cutoff

Exact duplicates, immaterial repeats, title edits, publication-time edits, summary
edits, provider corrections, material disagreements, retractions and unclassified
changes are distinct. SQL automatically appends changes between successive exact
representations. Explicit correction/retraction declarations append; they cannot
erase the observations. An edit does not prove that either representation is false.
Unresolved title/time/summary edits are `unknown`, not casually classified as
immaterial. Material declarations give `material`; duplicates/repeats are
`nonmaterial`. A later event is `post-cutoff` in pure as-of analysis and never
changes a stored packet. Legacy `kind=conflict` is conservatively represented as
unclassified: its historical timestamp does not prove material falsehood.
`EvidenceLegacyAdmission` separately preserves legacy `observed_at`, explicitly
unknown historical arrival, and database-stamped Phase7 discovery time. The new
opt-in `store_representation` service admits existing legacy conflicts for that
document under the same lock. An explicitly invoked `admit_legacy_conflicts`
refreshes discovery for later legacy rows; a future consumer must invoke it
before choosing its packet cutoff. No hook is added to existing ingestion.
The packet query uses only admissions known at cutoff, never a live legacy join.
Late legacy rows or admissions cannot change reconstruction at an old cutoff;
they qualify subsequent packets. Historical audit definitions remain unchanged.

Relevance v1 is deliberately deterministic and lexical, not an economic signal.
Frozen title currency/country/region matches score 40 per base/quote, a linked
central bank adds 20, declared release 10, explicit systemic-global vocabulary 30,
direct source 5, publication within a day 5, unresolved conflict subtracts 15.
Full vocabulary is versioned in `evidence_quality.py`. `ZZ` grants no relevance.
Crypto/CoinDesk requires both explicit pair linkage and macro vocabulary. Generic
business/global language is insufficient. No outcomes enter this calculation.
No headline processing occurs without deterministic permission.

Universe = every Phase7 exact representation known by cutoff. Every candidate,
rank, permission result and exclusion is retained; canonical-document dedup and
the 20-item cap follow rights/relevance admission. Stable ties use canonical hash
then representation digest. This may select fewer than 20 items. It is not tuned
to the baseline crypto percentage. Sources lacking exact rights-cleared records
are unavailable; the legacy feed is not silently promoted into this universe.

## Replay and bounded context

Packet fields bind schema/policies, instrument/cutoff, complete candidate universe,
exact representations and rights manifests, quality, conflict-at-cutoff, relevance,
stable rank, inclusion/exclusion reasons and required-evidence readiness. Canonical
UTF-8 JSON and SHA256 identify the entire packet. The explicit `required_ids`
contract marks necessary facts; caller omission does not establish a production
strategy's evidence needs. That future strategy/consumer binding is not activated.
Missing, future, stale beyond 72 hours, rights-blocked, materially conflicted or
unknown required facts produce deterministic abstention before Claude. Empty
evidence also abstains. Contextual conflicts remain qualified, not discarded.

`replay` recomputes decisions from frozen inputs, not current rights/conflict policy.
`load_frozen_packet` additionally checks immutable retrieval/representation lineage.
Current canonical titles, current terms and later records cannot alter stored
bytes. Corrections/new policy versions append; v1 code must remain available.

The dormant context method freezes model identity, prompt/schema hashes, pricing,
token/byte/cost caps and zero retries. Pricing is an **owner-review-required
assumption**, not a verified current provider quote. No provider call has occurred.
Accepted offline results retain the entire request/method and returned identity/
usage/cost/output. The closed output contains only executive summary, cited claim
groups, conflict interpretations, bounded thesis, abstention explanation and
research questions. Each claim binds exact field quotation, evidence ID,
relationship, fact/interpretation/hypothesis, directness and conflict state.

The corrected dormant context method is `bounded-evidence-context-v3`; its method
digest pins a nominal source-phrase grammar, explicit v2 predecessor identity,
and claim-support policy. It deliberately
admits only exact source quotations as source-report facts, or
finite uncertainty/conflict/research templates. Supporting/opposing directional
claims remain unavailable without a mechanically checkable support proposition;
citation membership alone cannot supply one. This is a conservative subset of
the permitted context scope, not a free-form thesis engine. No levels, numeric or
reconstructable values, outside facts, causal claims, strategy/risk/capacity/
abstention authority, profit, activation or learning-policy changes are admitted.
Prompts are only mitigation; closed validation is the enforcement boundary.
Invalid responses return a fixed safe error and are not saved with raw exceptions.
Source quotations and attribution must parse as a finite nominal report phrase;
contextual templates are admitted only by exact relationship-bound equality.
Template words do not grant permission to compose source prose. For example,
`USD market report` is allowed but `USD report market` is not; there is no
verb-object or evidence-status-reclassification production. Both Python and SQL
enforce the successor source grammar. This intentionally sacrifices coverage;
broader language requires a prospective method and review, not adding terms
because particular audit headlines were rejected. The unresolved
conflict template requires every cited item to be material/unknown at cutoff;
none, nonmaterial and post-cutoff cannot support it. Existing published methods
and histories are untouched. V1/v2 results retain their original policies for
historical replay, including their known limitations; they are not upgraded by
relabeling. Migration 0023 admits new results only under the successor pin, and
refuses populated reversal. No new result is admitted under a predecessor method.

## Notifications and integrity

`record_incident` creates only a logical incident identity: canonical document,
class, normalized changed fields and changed-value fingerprints, UTC-day policy
window. Materially different values remain different incidents. Every underlying
discrepancy remains. Explicit admin/test `notify_incident` reuses the established
idempotent owner-notification/outbox path; ingestion and packet construction never
invoke it. Notifications contain fixed safe wording and internal numeric subject
identity, no source text, URLs or exceptions. Delivery retries do not create a new
logical notification.

Run `manage.py audit_phase7_integrity` only against an explicitly selected database.
It sets REPEATABLE READ READ ONLY, 60s statement timeout and 2s lock timeout; output
is bounded aggregate record counts or a safe error. It checks all seven new record
types, immutable representation/source identity and semantic packet/context replay.
It does not activate a model, schedule or consumer. No default API/page was changed,
so this slice has no visual redesign or screenshot deliverable.
