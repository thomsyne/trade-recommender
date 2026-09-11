# Phase5.5 historical acquisition v1 — authorized Option 2

The owner authorized read-only historical OANDA acquisition after the initial
coverage blocker. This supersedes the need for a pre-existing restore, not the
holdout seal or mandatory evidence rules. Acquisition is not an outcome
calculation. No original Phase5 source/definitions/population or historical
ingestion registrations will be modified or reused under a false identity.

Population from merged `market/management/commands/seed_canonical.py:INSTRUMENTS`,
confirmed against migration0030:
EUR_USD, GBP_USD, EUR_GBP, USD_CAD, USD_JPY, AUD_USD, USD_CHF, NZD_USD,
EUR_JPY, GBP_JPY, AUD_JPY, AUD_CAD. The four decision-enabled/eight ingestion-only
policy stays unchanged. Do not execute seed commands to acquire offline data.

Acquire independent provider BA W/D/H4/H1/M15 series from 2017-01-01 through
2026-09-07, exclusive. Partition at 2019-01-07, 2025-01-06 and 2025-11-10;
do not have a request straddle any boundary. These are provisional validation
periods, not a finding that coverage has passed. W/D use at most 365 calendar
days, H4 180 days, H1 90 days, M15 28 days per request (all <4999 intervals).
Provider canonical from/to, BA, unsmoothed, NY17, Friday weekly alignment,
includeFirst=true for each independent half-open request. Reject out-of-window,
duplicate, unordered, incomplete, malformed/nonfinite/nonpositive or invalid
bid/ask geometry. Empty responses remain counted, not treated as success evidence.

Use the repository OANDA historical read-only client. The account ID is not
needed by the candle endpoint and must not enter manifests. The practice token
is parsed from `.env.local` into process memory, never printed/persisted/hashed.
Persist only normalized candle content, whitelisted provider metadata and true
request-start/acquisition-completion clocks in a private local acquisition store.
Do not pretend those clocks were contemporaneous with historical candle dates.
No account endpoint, trading endpoint, production DB, migration or schedule.

Store under `.candidate-data/phase55-v1/` (ignored by Git). Append-only SQLite
acquisition artifacts provide atomic chunk completion and restart/deduplication;
this is a private data cache, not a substitute for strategy registration or its
PostgreSQL admission contracts. Separate metadata-only inventory from blob
loading. Every chunk binds the acquisition plan and source code hashes, exact
request, observations and true acquisition clocks. Acquire single-threaded with
bounded requests/retries, no retry on authentication errors. Report failures
without provider message bodies or credentials. No existing data is overwritten.

The two holdout partitions may be acquired and audited for metadata only.
No evaluation loader may return their price blobs before explicit release.
Development must additionally pass the frozen registration/coverage gate.
Reassess all twelve pairs and five granularities, missing intervals/revisions,
calendar/cost coverage and prior use before freezing validation dates.

## Conservative costs are a separate model, never forged historical evidence

Owner authorized preregistered conservative modeled costs where genuine costs
are absent. Bind a new model/validation revision with actual registration time;
never backdate `CostEvidence.known_at` or existing snapshot availability to make
Phase5 production contracts accept retrospective inputs. Reports must say
model-based retrospective, not broker-observed execution or executable fills.

Numerical bounds and exposure mappings must be committed before outcomes.
Missing mandatory calendar/macro/financing/conversion or other evidence still
blocks affected evaluations. Carry cannot use policy rates; range cannot assume
event clearance; macro cannot assume no events. Acquisition does not waive these
rules or guarantee that every acquired candle is usable in retrospective replay.

## Acquisition revision 2 boundary correction, still before outcomes

The first real W canary correctly failed the interval guard: OANDA's
`includeFirst=true` includes the candle covering an unaligned `from`, even when
its start precedes `from`. Three bounded attempts produced zero stored chunks.
The failed revision-1 cache is preserved separately, not rewritten.

Revision 2 uses includeFirst=true only when `from` is on the registered interval
grid; otherwise false. Each request is still an independent half-open chunk.
Additionally exclude a candle whose registered completion crosses the enclosing
period end; retain its timestamp as a boundary exclusion, not its price values.
In particular a Sunday daily candle before Monday holdout start must not carry
holdout prices into the development blob. Internal chunk ends do not discard
otherwise valid candles; period ends do. Registered completion is a boundary
model, not provider-specific event/calendar attestation. Tests discriminate the
straddling candle from an earlier valid daily candle. Source pins and the private
acquisition registration change to `phase55/acquisition-v2` before new requests.
