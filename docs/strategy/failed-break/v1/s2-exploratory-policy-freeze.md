# Failed-break S2 exploratory-only policy freeze

Status: `EFFECTIVE_EXPLORATORY_ONLY` as of 2026-09-03. This document reports
the canonical policy; the JSON artifact is authoritative.

## Governed identities

- Candidate commit: `cfe9d19eef2f76bec2328098be77f68bf3103320`
- Geometry commit: `58fb2bb83c58aa1397ce315ab21239da74019cd7`
- Effective artifact SHA-256: `4f70ea3c86569de5b54ad3f18d7c1021b6067532ba9fb42b62faf1a0b2676e8c`
- Effective policy self-hash: `c30896d2fcd943f647f93f53077e7d7d9163c455cca20aad91df8fbcd667e26f`
- Clarified geometry artifact SHA-256: `4749633ac8c3f28e977e7697ba9f1b9d32425de84afde183a2d0fd98e4c7b27b`
- Clarified geometry self-hash: `af2f0d6e2e865dcdc8d9825c039d5df650059e717cd09fad92b0f41ff72a8fb7`
- Clarified geometry report SHA-256: `f6f9df6a9b2c943171018a8674e659c5fd773a6ae1f4b4562ab097fd90096e8b`

## Effective boundary

The structured policy requires `exploratory_only: true`,
`promotion_eligible: false`, and
`promotion_permanently_prohibited: true`. The registered 2010-2018 cohort can
never promote this strategy, regardless of any outcome. Owner, CLI,
environment, database and data-only overrides are all prohibited. A future
confirmatory evaluation requires a separately governed, genuinely untouched
cohort. This policy and cohort also have no live-trading authorization path.

The 0.20R practical-effect target is unconditionally immutable after the
return-blind geometry became known. The S2-03 `[0.5R, 1.0R, 2.0R]` grid is the
hypothetical statistical-sensitivity simulation grid. The separate
`[0.5R, 1.0R, 1.5R]` grid is solely the return-blind geometry/MDE diagnostic
grid. They are not interchangeable, and neither overrides the other. No
observed return may select, replace or reinterpret either grid.

At the 0.20R target, the geometry/MDE diagnostic is adequate at sigma=0.5R and
inadequate at sigma=1.0R and sigma=1.5R. Confirmatory adequacy is therefore not
established across that diagnostic grid, and the diagnostic cannot authorize
promotion. The S2-03 2.0R simulation point remains intact. The 408 singleton
statistic is non-authoritative, and confirmed-setup Kish cannot substitute for
trade-level effective sample size.

The 15-cell cost sensitivity is exactly the Cartesian product of three
commission assumptions and five financing assumptions. It is a commission ×
financing grid, not an adverse-slippage grid. S2-02 keeps additional slippage at
zero and adds no slippage model; observed bid/ask spread remains applied under
the governed execution convention. Exploratory results therefore exclude
additional execution slippage beyond that spread. This optimistic limitation is
another reason they cannot authorize promotion or live trading. Any future
slippage model requires a new strategy/policy version and genuinely untouched
confirmatory evidence.

## Decision ledger

S2-01 through S2-07 are all `RESOLVED_OWNER_AUTHORIZED`. Their recommendation
objects and rationales are byte-for-byte transcriptions from the reviewed
candidate and are verified that way by the loader. The candidate S2-05 owner-gate
wording is retained solely for that traceability and is explicitly subordinate
to the permanent no-promotion boundary; it grants no authority.

## Separate authorities

- Policy freeze: `AUTHORIZED_EFFECTIVE`.
- Exploratory return execution: `SEPARATELY_UNAUTHORIZED`.
- Strategy promotion: `PERMANENTLY_PROHIBITED`.

This freeze accessed only committed candidate, S1-derived return-blind geometry
and owner-authorization evidence. It did not access a database, candle payload,
post-entry outcome, provider or network, and it did not calculate a return.
