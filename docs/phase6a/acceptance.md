# Phase 6A PM requirements acceptance

Date: 2026-09-11. Verdict: **ACCEPT for opening a PR/merge review only**.
This is a requirements-traceability decision for the exact dormant engineering
candidate below. It is not activation, deployment, economic admission, permission
to merge without review, or permission to trade.

## Accepted identity

- Implementation commit: `6c558173fd9a8d2a6d85aa46e75a31a3ef255c93`
- Implementation tree: `eb57ee54c63486c1e98a16047fdfdb14311a4bbe`
- Implementation parent: `ce089dbb2813dff5574d50c20d4eabbec2ddf3df`
- Exact base: `005b21f042cbc0aacd556c83ef16c86742cba06a`
- Closure source-manifest SHA-256: `116f749a651744aca1a9dc11996bb40ffade859c46205b6f0323fcef002fa31a`
  with all 17 entries verified
- Method 1.2 implementation SHA-256:
  `1b1d552759276d3887c50a82f9704d5ace4273cf6e6641b627e8d3b694cd68cb`
- Method/migration digest:
  `95bc41c6d6dfcc07f96ac7ec2982ec1f3deea58806cc6ad7581af987efa399e8`

The engineering thread's complete 36-file base-relative Changes capture was
reconstructed over the exact base and produced the stated tree. Separately
transferred loose Git objects recomputed to the stated implementation commit,
tree, and parent identities. The method implementation hash, method payload
digest, migration pin, and historical method 1.0/1.1 payload digests were also
recomputed and matched.

## Requirements disposition

| ID | Disposition | Traceability conclusion |
|---|---|---|
| A | Satisfied | The app is dormant and candidate-only. Source/import and database-count boundaries exclude Recommendation, order/fill, sizing, portfolio, notification, execution, provider/model, and schedule authority. |
| B | Satisfied | Aware cutoffs, exact immutable identities/manifests, authenticated upstream loading, replay, and later-input immutability preserve point-in-time causality. |
| C | Satisfied | Monthly/W/D/H4/H1/M15 are required and unavailable is not neutral; sentiment is explicitly unavailable. M15 uses the authenticated Phase 5 registered successor with exact-boundary, delayed-availability, and weekend coverage. Wick/close remain distinct; no M1/tick/intrabar/executable-quote inference or M15 schedule exists. |
| D | Satisfied | Eligibility is exact and immutable by strategy/version/role/instrument/era/knowledge/provenance, database-clock admitted, not caller-boolean or backdated, and canonically empty until separately reviewed Phase 5.5 authority exists. |
| E | Satisfied | Exact Phase 5 definitions and frozen roles govern attribution. Only setup output may originate; continuous, readiness, and overlays cannot escalate or manufacture confluence/shape. |
| F | Satisfied | The assessment has all nine required fields, the complete ordered gate taxonomy, deterministic precedence, explicit Phase 5 reason mapping, and a primary reason. |
| G | Satisfied | The pure contract handles exact frozen cost components, precision, staleness, spread limits, and net R without defaults. Production cost append/load authority is currently closed. |
| H | Satisfied | The pure contract consumes frozen aggregate and bilateral currency-leg capacity without mutable reconstruction. Production capacity append/load authority is currently closed. |
| I | Satisfied | The only positive artifact is an eligible trade-intent research candidate. Production candidate admission is prospectively SQL-closed while eligibility/cost/capacity authorities are absent. |
| J | Satisfied | Advisory locking and unique identity provide concurrent idempotency. Semantic identity includes evaluation/evidence, geometry, dispositions, and predecessor terminal state; unchanged intent closes and material change requires a linked successor. |
| K | Satisfied | Canonical replay, byte-preserved method 1.0/1.1 historical replay, method 1.2 latest-only admission, SQL/Python empty-output parity, closed schemas, hashes/provenance, append-only guards, populated forward/reversal safety, raw-SQL forgery resistance, packet parity, and predecessor/supersession integrity are covered. |
| L | Satisfied | Active legacy forecast/recommendation/lifecycle/portfolio/paper/task sources and pins are unchanged and bilaterally isolated; no active-file or governance-pin changes were introduced. |
| V | Satisfied with retained limits | Required focused PostgreSQL, adversarial, audit, drift, static, manifest, diff, and independent closure evidence is present. The explicitly prohibited broad suite was not run. |

No mandatory requirement is waived by this record. The initial seven findings
(fabricated SQL assessment/candidate, self-attested eligibility, backdated
self-attested cost/capacity, incomplete semantic identity, same-direction setup
handling, packet/predecessor parity, and gate order/mapping) are closed. The later
R1–R3 findings (malformed populated-v1 eligibility bypass, loss of v1 historical
replay, and delayed-availability M15 regression) are also closed. Independent
closure on the exact implementation candidate reported no remaining P0–P3 within
the authorized boundaries.

## Evidence and retained limitations

- Engineering: PostgreSQL 15.19 `assessments.tests` 37/37 and R1–R3 focus 21/21;
  read-only audit zero violations; `make check`, migration drift, Ruff/format,
  Django check, compileall, manifests/digests/diff/scope all clean.
- Independent closure: PostgreSQL 15.19 focus 21/21; malformed populated-v1 SQL
  refusal; byte-identical v1 replay and clean audit with noncanonical refusal;
  512 v1 plus 512 v1.1 legacy projection comparisons; latest-only admission; and
  exact/delayed/weekend Phase 5 M15 successor behavior independently reproduced.
- PostgreSQL 17 was unavailable in both review orbs. No PostgreSQL 17 result is
  claimed.
- No broad repository suite was run, by explicit workflow restriction. This is an
  acceptance limitation, not a green broad-suite claim.
- No UI changed, so visual verification is not applicable.

## Explicit non-authorizations

This acceptance does not authorize Phase 5.5 promotion or resource changes,
nonempty eligibility, cost or capacity authority, M15 scheduling, provider/model
usage, recommendation or notification, sizing or risk admission, deployment,
execution, or trading. Merge review must preserve dormancy. Any positive production
path, consumer, activation, or authority requires separate review and approval.
