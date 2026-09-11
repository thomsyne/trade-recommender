# Phase 6A bounded closure correction trace

Status: **corrected engineering candidate; bounded independent closure remains open**.
This forward-only repair is limited to R1–R3 against corrected candidate commit
`ce089dbb2813dff5574d50c20d4eabbec2ddf3df`, tree
`943a9e568c3290ae6a4926f74ae0aa5a5c10413d`. The original and consolidated
candidate commits, manifests, and receipts remain unchanged. Applied migrations
`0001`–`0003` are byte-preserved; method `1.2.0` and migration `0004` apply the
prospective contract.

| Finding | Narrow correction | Discriminating verification |
|---|---|---|
| R1 populated-v1 eligibility bypass | Latest SQL reconstructs the exact instrument-bound canonical-empty payload, era, three provenance digests, no expiry, chronology, digest, manifest, and empty output. Only method 1.2 is newly admissible. | A wrong-era/1-2-3-hash eligibility admitted under `0002` is preserved by forward migration but rejected by Python and latest raw-SQL assessment admission; canonical SQL/Python output parity remains exact. |
| R2 v1 replay regression | Replay dispatches exact historical method identities. The frozen v1 engine is retained only for canonical-empty, dependency-free rows; current admission remains latest-only and unsafe historical inputs fail integrity. | A genuine row produced by the engine at original candidate commit under `0002` replays byte-equivalently and audits clean after `0004`; a new v1 insert is refused. |
| R3 delayed next-M15 semantics | Entry validation uses the same registered market-session successor used by Phase 5 setup construction, choosing the first successor when known by its boundary and otherwise the second. It never adds 15 minutes to provider availability. | Real Phase 5 candidate fixtures cover exact boundary, one-microsecond delay, delayed seconds through the standard fixture, and Friday-to-Sunday FX succession. |

The previously closed F3/F4/F5-original/F6/F7 and A/L/V boundaries are unchanged
and receive regression coverage only. Production eligibility remains exactly empty;
no Phase 5.5, cost, capacity, evidence, candidate, legacy, provider/model, schedule,
or execution authority was added. This trace is not self-acceptance or permission
to trade.
