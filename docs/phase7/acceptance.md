# Phase 7 preregistered acceptance matrix

Preregistered engineering scope; final PM disposition appears below. Base is merged
`b850c4ea618c34397e86fd8133b7255ff972f8ba`. Isolated branch
`phase7/evidence-quality-ai`; no shared Phase5.5 files or resources may change.
This matrix and audit contract must be committed before implementation.

| ID | Contract / deliverable | Discriminating evidence required |
|---|---|---|
| A | New append-only evidence records, protective references, forward migrations only; no historical rewrite | Prior migration/source fingerprints; SQL update/delete/truncate refusal; populated reversal refusal |
| B | Exact representation includes retrieval, item identity, title, supplied summary, publication/observation times, canonical identity, digest, language/type, rights identity | Same item edited in title/time/summary yields distinct representation; replay never selects latest; cross-document retrieval forgery refused |
| C | Independent retrieval integrity, timestamp precision, tier/directness, conflict/corroboration, relevance, freshness, rights | Quality never grants permission; unknown historical properties remain unknown; no whole-item verified claim |
| D | Duplicate/repeated/title/time/summary/correction/disagreement/retraction/unclassified taxonomy; cutoff-aware conflict | Before/equal/after cutoff; repeated representation not material; contextual conflict never unqualified support; required unresolved facts abstain |
| E | Six content fields × seven uses, processor/source scoped append-only rights review | Headline yes/summary no; storage yes/LLM no; LLM yes/redistribution no; unknown/expired/superseded/wrong source/processor fail closed; prospective decisions frozen |
| F | Versioned deterministic FX/macro relevance and stable ranking after rights/relevance/dedup, cap 20 | EUR/ECB vs USD_CAD; BoC vs EUR_GBP; generic business; crypto-only vs explicit USD liquidity; systemic; ZZ; ties/caps; full denominator and reasons |
| G | Canonical self-contained frozen packet with required/contextual/optional readiness | Missing/stale/future/blocked/material required evidence abstains; later representation/rights/policy changes preserve bytes; duplicate IDs/instrument/version/hash-consistent semantic forgery rejected |
| H | Dormant bounded Claude contract, closed cited claim schema; no market/strategy/risk authority | Invented levels, strategy promotion, risk/abstention override, profit, excluded or unqualified conflicted citations, injection and unsupported causal claims refused |
| I | Allowlisted external projection, exact support mapping, model/cost/token bounds, safe errors; immutable method pins | No raw/OANDA/numeric or reconstructable market values/URLs; wrong model/excess cap/exception leakage; source versions fail closed; no live provider call |
| J | Logical discrepancy incident dedupe independent from immutable observations and delivery attempts | Concurrent identical incident creates one identity; normalized fields/window stable; material variants distinct; unsafe source text absent |
| K | Truthful explicit projection only; no automatic current page switch | Distinguish exact timestamp property, at-cutoff vs later conflict, rights/use, deterministic vs interpretation; no visual change planned |
| L | Dormant explicit service/admin/test paths only | No imports/consumers/schedules/notifications/model spend/recommendations/trades activated; protected-file and consumer scan |

## Verification and gates

Focused synthetic tests during implementation; once stable, PostgreSQL 15 and 17
admission/migration/concurrency tests, `make check`, offline CI and one complete
available-evidence suite. Retain exactly the inherited six discovery-plan restore
exclusions and their hash pins. Partial runs are not passes. Independent review
then at most one consolidated correction cycle, then PM traceability. No self-
acceptance. No provider calls, prompt fitting to the small diagnostic sample,
push, PR, merge, deployment, activation, schedules, trades or Phase5.5 release.

## Audit gate

See [audit contract](audit-contract.md). Owner totals are unverified claims until
the correct snapshot is identified. Audit availability is separate from synthetic
engineering verification and cannot be replaced with fabricated historical facts.

## Final requirements-only PM decision — 2026-09-11

**ACCEPT Phase7 for opening a PR/merge review only.** No mandatory requirement
remains open within the approved dormant implementation scope and amended
verification discipline. This is not a full-suite green result, merge execution,
new source/model permission, consumer activation, provider spend, deployment,
notification/schedule/recommendation/strategy activation, Phase5.5 release or trading
approval. No finding is waived by this document.

Reviewed the clean local/unpushed candidate
`7bfd68d8fb2dfc28e651f075c25b896c4c474ff0`, tree
`f99abb007804e03a708cac890388f332463260ea`, on `phase7/evidence-quality-ai`;
base and local `origin/main` both
`b850c4ea618c34397e86fd8133b7255ff972f8ba` (verified ancestor).
This PM decision adds documentation only; the reviewed implementation stays exact.

Evidence: the complete A–L matrix and audit contract above, [baseline evidence](baseline-evidence.md),
[baseline JSON](baseline.json), [source provenance](source-provenance.json),
[correction history and receipts](corrections.md), [runbook](runbook.md),
the exact base-to-candidate changed-path scope and relevant implementation/test
contracts, [engineering handoff](https://ampcode.com/threads/T-01a09110-7688-775f-ba1a-cd212b3a9ebc),
[independent findings and closure](https://ampcode.com/threads/T-01a09140-4063-75bc-8942-99dc5a575d94),
and [owner/coordinator authorization history](https://ampcode.com/threads/T-01a0678e-9ea5-722f-99ad-8099c7ec5f76).
This was traceability review, not another broad code audit or a fresh database test run.

| Requirement | Final PM disposition and discriminating evidence |
|---|---|
| Audit | Satisfied by the explicitly authorized replacement baseline, not replication: read-only deployed PG15.14, DB `trade_recommender`, cutoff `2026-09-11T15:33:10.685194+00:00`, transaction `95219:95219:`. Contract3 recommendations 324; conflict-known-at-issuance 242; affected refs 777; first-conflicted-later refs 1,351; slots 6,438; narrow diagnostic 1,260/6,438 = 19.571295%. Frozen jurisdictions all unknown; separate current-policy CA82/EU25/GB53/US16/ZZ1194 across 1,370 representations. Old 292/222/734/~17.27% remain unverified context, never optimization targets. |
| A — persistence/history | Satisfied: forward 0016–0023, protective references, SQL mutation refusal, populated reversal refusal and concurrency/preservation regressions. All base files except model-registration hook `research/apps.py` are unchanged. S1 model source restored exactly; no pin, artifact or old test relaxed. |
| B — exact representations | Satisfied: immutable retrieval/item/title/summary/time identities and parser replay; F1 admission-time macro label and F2 original timestamp provenance close fabricated text/precision. Later mutable labels cannot rewrite replay. |
| C — independent quality/permission | Satisfied: quality axes are separate from rights; unknown precision remains unknown and required evidence abstains. No whole-item truth claim or storage-to-Anthropic permission inference. |
| D — revisions/conflict/cutoff | Satisfied: edits retained rather than declared false; before/equal/after-cutoff cases, F4 template preconditions and F5 serialized legacy discovery tests. Future consumers must explicitly admit legacy conflicts before selecting cutoff; historical arrival remains unknown. |
| E — rights | Satisfied: six fields × seven uses, source/processor/review/date/rationale and prospective supersession. Headline/summary, storage/LLM and LLM/redistribution distinctions tested; absent, wrong-scope, expired and superseded permission fail closed. No approval seeded. |
| F — relevance | Satisfied: deterministic pair/macro/systemic linkage, ZZ grants none, crypto/source alone insufficient; stable dedup/rank/cap 20 after permission/relevance with full universe, exclusions and denominators. No outcome fitting. |
| G — packet/readiness | Satisfied: canonical frozen inputs, rights, provenance, conflict/relevance and required IDs replay independently of current state. Missing/stale/future/blocked/material-or-unknown required evidence abstains before context preparation; semantic forgery and late-arrival/concurrency regressions discriminate. |
| H/I — Claude boundary | Satisfied for the approved conservative subset: exact nominal source reports and finite relationship-bound templates; no directional support/opposition without mechanical proposition. V3 Python/SQL grammar closes original numeric/authority and composed evidence-rewrite attacks. Closed citations, caps, model/method identities and safe errors enforce the boundary, not prompts alone. No network transport or market/strategy/risk/profit/abstention/activation authority. |
| J — incident dedupe | Satisfied: concurrent logical identity/delivery idempotence retains every discrepancy and distinguishes material changes; explicit safe notification seam only, no automatic caller. |
| K/L — consumers/UI/dormancy | Satisfied: existing consumers, methods, pages, configuration, schedules and history unchanged. Registration loads declarations only. No UI appearance change, hence no screenshot requirement. No strategy/Phase5.5/trading switch. |
| Workflow/verification | Satisfied under explicit later owner instructions: engineer → independent F1–F5 review → consolidated correction → bounded remaining F3 and authorized S1 closure → PM. Final PG15/17 focused coverage and independent closure exist; broad/offline limitations below are retained, not called passes on the final candidate. |

### Findings closed by evidence, not prose

F1/F2/F4/F5 were independently closed at the consolidated correction. F3 remained
open despite those green tests and was closed only after prospective v3/0023:
all three authentic evidence-rewrite directives and variants reject, while neutral
reports remain. Independent historical comparison covered 36 v1/v2 cases with
identical acceptance decisions and all ten accepted request/result bytes matching.
Old rows/methods remain stable; relabelling and new predecessor admission refuse.
The S1 source-pin repair moved seven unchanged declarations into
`research.evidence_models`, registered in Django phase two. Independent AST and
fresh-process/migration-state checks preserve tables, labels and ownership; both
exact formerly failing S1 governance tests pass. Bounded closure found no P0–P3.

PM recomputed the Python source manifest:
`78aa185bb6390cac49cfbc2eec9af7ee068247098a0e8707db72faad84f71e13`;
the protected `research/models.py` SHA256:
`cb72ee3f0ea35b6e0388bdc26394c80c283607d20c7be0a473c77d6ffe5048e9`;
v3 method digest:
`8200e7f3bc2158c440d6ee8173789c2fc305faeb45ba5ead95f710e22bf759bd`;
and v2 predecessor:
`806b8ed616ae3e0d2758e38758e34539b4c5a266439dae09e5bc9b59a7e226b0`.
Audit extractor SHA256 matches the frozen baseline:
`97584f77a3f81f2641733fbf44edbc4825fb0cac35f8446475e0ff93cde410a3`.
Original Phase7 migrations remain byte-identical across subsequent repairs;
all pre-Phase7 migrations, six inherited exclusions and their source/identity pins
are unchanged. Existing-consumer reference scan found no activation path; changed
files contain no bulky artifacts (largest 37,323 bytes) or detected credential/key
patterns. Pattern screening is not a comprehensive secret audit. Diff whitespace
checks passed; no external state was inspected or changed in this PM review.

### Retained evidence limits and why they do not block PR review

- **No final-candidate complete broad-suite pass.** The sole clean completed run
  was earlier `abaef12`: 1,554 tests, 1,498.470s, exit 1, two S1 pin errors. Those
  exact errors were repaired and directly tested; the run does not become green
  retroactively. Exactly six inherited restore-required exclusions remain.
  Mixed-source exit143/SIGTERM lacks a complete summary and is invalid evidence.
  The owner expressly consumed the one-run budget and prohibited another broad
  run after F3/S1 localized repairs. Acceptance follows that amended discipline;
  it does not assert unexecuted final broad coverage or readiness to deploy.
- Final frozen-source engineering receipts show 42 tests passed on PG15.19 and
  PG17.11, `make check` and migration drift passed. Reviewer independently ran
  eight scoped tests on PG15.19, drift/diff, manifest and historical comparison.
  PM inspected receipts and recomputed static identities; PM did not rerun tests.
- Separate offline CI/deployment checks passed at original `d7c27a1`, per the
  engineering execution record: IAM audit, bootstrap/remote-deploy simulations,
  backup (13 tests), infra policy, production Compose, Terraform formatting and
  Django `check --deploy`, all exit 0. Not rerun on final source and not a hosted
  CI pass. Local Terraform was 1.5.6 versus workflow 1.13.3. Deploy/infra/workflow/
  config inputs are unchanged; later repair instructions required focused checks,
  drift and `make check`, not a fresh offline suite. Preserve this qualification.
- Baseline aggregate/input hash is frozen, but no matching retained source-row
  restore/dump exists; deployed build revision/image digest are unknown. Exact
  historical/source-row replay is not established. Replacement baseline acceptance
  does not convert current policy or legacy timestamps into historical facts.
- Nominal grammar intentionally restricts coverage; expansion needs prospective
  method review. Pricing remains owner-review-required, not a current quote.
  Future rights review, consumer-required-evidence binding and activation remain
  separate gates; this acceptance grants none of them.
