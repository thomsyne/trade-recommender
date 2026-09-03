# Failed-break S2 exploratory-only policy freeze

Status: `EFFECTIVE_EXPLORATORY_ONLY` as of 2026-09-03. This document reports
the canonical policy; the JSON artifact is authoritative.

## Governed identities

- Candidate commit: `cfe9d19eef2f76bec2328098be77f68bf3103320`
- Geometry commit: `58fb2bb83c58aa1397ce315ab21239da74019cd7`
- Effective artifact SHA-256: `2907ef566b08bc042ba81ef3ffc192af760b85e168f97e63aa8743ba9564e429`
- Effective policy self-hash: `f5d1a762d065271f5565a27450f6f8585e26cd976ac414084bd17257cc3cfeb8`
- Corrected geometry artifact SHA-256: `34a89d96143066b7bcbdf16af031687e1284d694af759d4719bf0d097b12cba1`
- Corrected geometry self-hash: `01f91963bd3972038ba33cc801bc21ab57247747f406381dbd5b62d6bbdb41fb`
- Corrected geometry report SHA-256: `28c2a5cbe182ebcee35c2d576b505fd277397b54e664691f954ac4b23c2b87ac`

## Effective boundary

The structured policy requires `exploratory_only: true`,
`promotion_eligible: false`, and
`promotion_permanently_prohibited: true`. The registered 2010-2018 cohort can
never promote this strategy, regardless of any outcome. Owner, CLI,
environment, database and data-only overrides are all prohibited. A future
confirmatory evaluation requires a separately governed, genuinely untouched
cohort. This policy and cohort also have no live-trading authorization path.

The 0.20R practical-effect target is unconditionally immutable after the
return-blind geometry became known. At that target, the trade-level effective
sample size is adequate for the sigma=0.5R scenario and inadequate for the
sigma=1.0R and sigma=1.5R scenarios. Confirmatory adequacy is therefore not
established across the preregistered scenarios. The 408 singleton statistic is
non-authoritative, and confirmed-setup Kish cannot substitute for trade-level
effective sample size.

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
