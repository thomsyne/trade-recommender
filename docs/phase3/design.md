# Phase 3 design decision record

Status: implementation design, not acceptance or activation authorization.
Base: `16a27029f6f78af35adb040a8b70c98744f226c4`.

## Ownership decisions

`TargetContract` remains the reusable method definition. `TargetOccurrence` owns a
single daily reference event; `TargetResolution` owns its sole eventual outcome.
Both belong to forecasts. Existing Forecast and Recommendation retain their
historical columns and gain nullable occurrence links; their resolutions gain a
nullable shared resolution link. New recommendation contract v4 requires all
links. No migration creates forecasts, recommendations, samples or transitions.

The occurrence identity includes instrument code, contract key/version and exact
definition digest, reference candle content hash and timestamp, fixed-precision
midpoint/band, horizon, UTC evidence cutoff, and resolution/classification rules.
It excludes insertion IDs, creation time, model, probabilities and setup geometry.
The cutoff is the availability time of the frozen daily candle and technical
snapshot, not recommendation generation time. Repeated observations of that same
daily evidence therefore predict the same occurrence; an actual evidence/cutoff
change produces another identity. Model contextual evidence has its own cutoff
and must be available before generation; it does not redefine the scored event.

The existing registered New York daily session calendar owns the fifth successor
endpoint. Missing a session must never shift the endpoint to the sixth available
database row. Resolution remains absent until maturity, then missing if endpoint
evidence is unavailable. Missing/cancelled outcomes have no endpoint or score.

Operational reconciliation resolves older targets before registering the latest
target and issuing its exact tactical EWMA control. Generation only looks up an
already issued exact control, before any provider reservation. Explicit v4 era
registration is required; existing eras are neither reassigned nor activated.

## Lifecycle transition matrix

One append-only RecommendationLifecycleEvent chain is authoritative for v4;
PaperLifecycleEvent remains historical/low-level execution evidence. Services
serialize transitions on the recommendation row; PostgreSQL verifies the chain.
The common projection uses this chain for v4 and provable facts for legacy.

| State | Predecessor | Trigger/evidence | Successors | Terminal |
|---|---|---|---|---|
| abstained | none | abstain action | none | yes |
| awaiting_portfolio_assessment | none | directional issuance | portfolio_ineligible, awaiting_owner_decision, cancelled | no |
| portfolio_ineligible | awaiting_portfolio_assessment | durable reasoned disposition | none | yes |
| awaiting_owner_decision | awaiting_portfolio_assessment | cohort membership | admitted_awaiting_entry, closed_unselected, cancelled | no |
| admitted_awaiting_entry | awaiting_owner_decision | valid selection/admission | entered, admission_revoked, expired_not_activated, expired_unobserved, missing_data, cancelled | no |
| closed_unselected | awaiting_owner_decision | explicit decision/closure | none | yes |
| admission_revoked | admitted_awaiting_entry | revocation fact | none | yes |
| entered | admitted_awaiting_entry | admitted paper entry | target_hit, invalidated, expired_after_entry, missing_data | no |
| target_hit / invalidated / expired_after_entry | entered | paper result | none | yes |
| expired_not_activated | admitted_awaiting_entry | verified complete H1 coverage + nonactivated result | none | yes |
| expired_unobserved | admitted_awaiting_entry | incomplete H1 observation through expiry | none | yes |
| missing_data | admitted_awaiting_entry / entered | missing daily endpoint | none | yes |
| cancelled | pre-entry nonterminal | explicit cancellation evidence | none | yes |
| legacy_unadjudicated | derived only | ambiguous historical facts | no synthetic transition | no |

Each transition records recommendation, predecessor, static reason, source fact,
versioned details, timestamp and idempotency digest. Terminal transitions cannot
be reopened. Operational failure is retryable assessment, not business rejection.
Every v4 directional issuance atomically receives a durable disposition record;
membership or explicit ineligibility follows reconciliation. Cohort deadlines are
fixed, closure explicit, repeated targets cannot open competing owner decisions.
Selection rechecks current capacity while holding the portfolio lock.

## Evaluation and compatibility

Policy v2 retains 180 days, 24 weekly clusters, 50 samples, 90% mature coverage
and existing calibration thresholds. Repeated predictions average within target
before weekly aggregation; paired control contributes once per target. Report
both sample and target populations; primary coverage uses mature distinct targets.
Every scored target needs an exact prospective control and shared outcome before
paired readiness. Uniform outperformance alone cannot authorize promotion.

Migration boundaries include existing immutability triggers and full-clean methods,
raw-SQL cross-table linkage, cohort/selection/admission facts and cutoff filtering.
New records receive UPDATE/DELETE/TRUNCATE protection; legacy fields remain nullable.
Migration preflight rejects contradictory prospective data atomically. No historical
probabilities, targets, links, lifecycle, owner selections or paper facts change.

## Verification plan

Write failing identity/calendar/transition/comparison regressions first. Exercise
raw SQL mismatches/mutation and concurrent retries on fresh UTF8 PostgreSQL only.
Use the documented market0027 fake accommodation only. Run serial affected suites
and the identical broader command on base and HEAD; identify inherited failures.
Inspect visible lifecycle states in DOM and screenshots after minimal view changes.
No provider/network spend, secret reads, push, deployment or activation is authorized.

## Concrete decision and evidence boundaries

Each recommendation's owner deadline is the earlier of generation plus 24 hours
and its registered target endpoint completion. A cohort uses the earliest of its
members' deadlines. A price trigger observed before selection closes the decision;
selection also rechecks the clock and observed complete H1 evidence. An unresolved
operational assessment closes as `cancelled / assessment_window_expired` at 24
hours. Retrying a provider-independent task never creates a business rejection.

A materially new target for any instrument represented in an open older cohort
closes that entire older cohort. Its remaining owner-pending members all receive
`closed_unselected` with the same explicit closure source, including instruments
whose targets did not change. Already admitted/entered/terminal members retain
their truthful states. Another recommendation for the same target cannot create
a competing open decision. No implicit latest-cohort rule remains authoritative.

The initial `PortfolioDisposition` is immutable issuance evidence that assessment
is required. The canonical chain then records membership or a reasoned final
ineligibility/cancellation; the record is never rewritten to simulate finality.
The projection rereads entry/result/admission/closure facts to avoid stale Django
reverse-relation caches and filters them to the requested cutoff.

A target's cutoff is its frozen daily/technical evidence availability. The model's
context packet can include later information available by generation. These are
explicitly different information sets predicting the same event. This design does
not claim model and control had identical contextual inputs. Tactical target
contract v2 supplies the frozen midpoint, band and horizon to the actual EWMA
probability computation. The existing EWMA method and probability table remain
version 1. For example midpoint 1.10, EWMA 1.09 and frozen band .005 classify UP
and produce (.5,.3,.2); recomputing a legacy .25 band would incorrectly classify
neutral and produce (.25,.5,.25). A regression distinguishes these calculations.

## Missing evidence and aggregation precision

Before entry, incomplete H1 observation through expiry means `expired_unobserved`.
Complete H1 coverage with no activation means `expired_not_activated` and has a
nonactivated paper result. After a proven entry, a coverage gap means
`missing_data`, retaining the entry and producing no fabricated result. Missing
registered daily endpoint evidence means `missing_data` only after eligible H1
execution evidence has been processed without proving an exit. The occurrence
defines maturity even when that daily candle is absent; a proven H1 target/stop
result does not depend on shared prediction resolution availability. Nonactivation
requires absence of observable entry triggers, not merely absence of an entry row.
A shared missing resolution requires no completed exact endpoint available by its
recorded cutoff; later arrivals do not rewrite that immutable outcome. Coverage-source
records carry versioned details even when no candles were observed. Existing
adverse intrabar ordering, bid/ask fills, costs, sizing and capacity limits remain.

Scores preserve existing six-decimal per-prediction Brier quantization, then
average within target, then within weekly dependence cluster. Thus the adversarial
ten-repeat/one-repeat fixture has exact unrounded model 13/75 and control31/150,
but stored-score aggregation gives .173334 and .206667, delta -.033333. It counts
two targets and one cluster. Naive row weighting reverses the conclusion. The
test derives the two-stage rounding independently. Calibration and sharpness use
the same target balancing; immature targets are excluded from mature coverage.

PostgreSQL's existing test-flush exception is reused exactly: only TRUNCATE, only
a database matching `test\_%`, and only while the backend holds AccessExclusiveLock
on auth_permission. UPDATE and DELETE receive no exception. Ordinary TRUNCATE
outside that flush context rejects on all five new immutable record tables.
Runtime-superuser trigger bypass remains the explicitly accepted deployment risk;
this work does not broaden the exception or claim role hardening.
