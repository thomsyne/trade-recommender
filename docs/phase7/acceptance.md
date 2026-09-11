# Phase 7 preregistered acceptance matrix

Engineering scope only; independent acceptance remains pending. Base is merged
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
