# Governed Portfolio Learning — Four-Quadrant Map

**Status:** Exploration complete; Slices 1–3 implemented
**Prepared:** 2026-08-20  
**Scope:** Prospective portfolio admission, notifications, postmortems, and
learning governance for the private FX research product

This is the durable output of the second `explore-unknowns` walk. It is the
controlling map for this phase. `docs/project-map.md` remains the broader
product architecture and historical decision record. Where the two disagree
about this phase, this map contains the newer decision.

Implementation must not silently change a settled decision or fill an OPEN
item. Code discoveries that force a deviation belong in an implementation log
and must be folded back into this map.

---

## 1. Known knowns — settled ground

### Product boundary

- The product is private, single-user, research-only, and paper-only.
- It records advice; it does not submit, stage, or transmit broker orders.
- Every valid recommendation is preserved and scored even when portfolio
  capacity prevents paper admission.
- “Research-only” means no portfolio allocation. It never means suppressing,
  deleting, or rewriting the original recommendation.
- Recommendations, selections, outcomes, assessments, and reviews are
  append-only records. Corrections are explicit superseding records.
- No agent may autonomously change prompts, models, weights, strategy,
  scoring, capacity policy, or promotion gates.
- Historical LLM recommendations are never reconstructed. The semantic
  thesis layer learns only from genuinely forward-issued recommendations.
- The technical and execution layers may be backtested on properly separated
  point-in-time data.

### Current repository territory

The repository already owns four distinct facts:

1. `Recommendation` freezes evidence, request/output, probabilities, levels,
   citations, timing, token use, provider identity, and estimated cost
   (`forecasts/models.py:229-280`, `forecasts/recommendations.py:155-240`).
2. `RecommendationResolution` scores the directional thesis independently of
   execution (`forecasts/models.py:459-520`,
   `forecasts/recommendations.py:507-561`).
3. `PaperTradeEntry` and `PaperTradeResult` observe conditional execution and
   outcome separately (`forecasts/models.py:539-635`,
   `forecasts/paper.py:19-147`).
4. `PositionSizeAdvice` and exposure reporting implement the present CAD risk
   policy (`forecasts/models.py:374-391`, `forecasts/sizing.py:12-154`,
   `forecasts/exposure.py:12-64`).

The queue is PostgreSQL-backed and now uses unique scheduled occurrences,
row-locked claims, bounded retries, owned leases, heartbeats, execution
deadlines, and abandoned-work recovery (`operations/models.py`,
`operations/services.py`).

There is no current admission/cohort, notification projection or sender,
postmortem, experiment, or promotion-history model. The outbox and delivery
attempt primitives exist but do not send Gmail. Calibration is assembled
dynamically in `dashboard/views.py`; it is not a frozen reproducible assessment.

### Intended flow

```text
immutable recommendation
        |
        +--> always enters research scoring
        |
        +--> versioned capacity assessment
                    |
                    +--> fits safely --------> admitted paper lifecycle
                    |
                    +--> competing set ------> owner selection request
                                                   |
                                                   +--> immutable selection

frozen outcomes + execution + costs
        |
        +--> deterministic thesis review
        +--> deterministic execution review
        +--> deterministic reconciliation
                         |
                         +--> optional bounded Claude interpretation
                         +--> non-actionable learning observation
```

### Existing sizing policy retained for v1

- Model equity: C$25,000.
- Risk per setup: 0.5%, or C$125.
- Aggregate and currency-direction limits remain the currently versioned
  policy until changed prospectively.
- Waiting conditional setups consume potential capacity.
- Confidence is context only. It does not rank candidates or allocate risk.

---

## 2. Known unknowns — decision ledger

| ID | Question | Answer | Closed by |
|---|---|---|---|
| GL-1 | Are recommendations dropped when capacity is unavailable? | No. Preserve and score all; mark non-admitted rows research-only. | User |
| GL-2 | Who decides among setups that cannot all fit? | The owner selects a competing set. Never rank by confidence. | User |
| GL-3 | Does an unselected setup become eligible after it triggers? | No retroactive admission. | User |
| GL-4 | Can a selection be changed? | It is immutable. A new selection may supersede it only while the entire cohort remains pending. | User |
| GL-5 | What closes a selection cohort? | Any member trigger or expiry, or a materially new recommendation batch. | User |
| GL-6 | How are existing recommendations treated? | `legacy-unadjudicated`, research-only. Admission begins prospectively at a recorded policy-effective timestamp. | User |
| GL-7 | Is confidence visible? | Yes, labelled as uncalibrated context; never used for ranking or capacity. | User |
| GL-8 | Notification channels | Dashboard inbox plus Gmail. | User |
| GL-9 | Email credential | Gmail app password secret; never the normal account password. | User |
| GL-10 | Can email approve a selection? | No. Email contains a safe authenticated dashboard link only. | User |
| GL-11 | Immediate notifications | New selection requests, terminal failures, stuck work, and material staleness. | User |
| GL-12 | Digest cadence | Event-driven review after successful ingestion/resolution; consolidated digest near 7 p.m. `America/Toronto`; weekday digest and deeper Sunday brief. | User |
| GL-13 | Digest ordering | Actions, then research changes, then system health. | User |
| GL-14 | Overnight authority | Fail closed and surface state. Incomplete input produces neither admissions nor postmortems. | User |
| GL-15 | OANDA data sent to Claude | **A now:** no OANDA-derived values. Deterministic code owns prices, levels, and technical facts. Once the system is mature, explicitly recommend seeking written permission for option B; transition only after permission is recorded in the rights gate. | User |
| GL-16 | Postmortem boundaries | Separate immutable thesis review, execution review, and combined reconciliation. | User |
| GL-17 | Who owns factual conclusions? | Deterministic code owns outcomes, scores, timing, paths, costs, and classifications. | User |
| GL-18 | Claude’s postmortem authority | Claude receives a frozen, rights-cleared packet and may add bounded cited interpretation only. Unsupported output is rejected and cannot change facts or policy. | User |
| GL-19 | Claude review budget | Separate US$20/month Sonnet budget. Deterministic reviews complete when exhausted. | User |
| GL-20 | First learning output | Each outcome may create a non-actionable observation. | User |
| GL-21 | Candidate-hypothesis gate | At least five dependence-aware issuance cohorts. | User |
| GL-22 | Who starts a challenger? | Owner only; challenger is prospective and versioned. | User |
| GL-23 | When may automatic adaptation begin? | Not initially. Automation may be reconsidered only after a substantial governed history; it cannot arrive as a silent code change. | User |
| GL-24 | Source discovery | Agents may propose newly discovered sources. New sources begin quarantined and require owner approval and rights/reliability review. | User |
| GL-25 | Primary device | Desktop complete; mobile remains functional. | User |
| GL-26 | Selector presentation | Decision-first cards with live capacity calculation and visible confidence. | User |
| GL-27 | Review presentation | Long-form notebook; deterministic facts visibly separate from Claude interpretation; chronological thesis timeline; visible data freshness and experiment health. | User |
| GL-28 | Mission Control placement | Separate Operations/Mission Control surface, not mixed into pair decisions. | User |
| GL-29 | External infrastructure alerting | Gmail handles owner-facing application events; an independent channel such as SNS remains appropriate for host-level failures that can disable Gmail delivery. | Territory |
| GL-30 | Larger promotion gate | Keep the broad-map minimum of time, raw rows, effective evidence, calibration, and guardrails. Exact effective-sample thresholds remain versioned and conservative. | Territory |

### OPEN known unknowns

| Item | What unblocks it |
|---|---|
| Gmail sender, recipient, and app-password secret names | Owner supplies the deployment Gmail addresses and app password when email delivery is implemented. Local tests use a fake backend. |
| Exact immutable Anthropic model identifier and current pricing | Confirm from the API immediately before implementing model review; persist requested and returned identity plus pricing version. |
| Rich OANDA-to-Claude option B | Written permission for the exact fields, transformations, retention, and external processor. The application must later prompt the owner to revisit this when the system is mature. |
| Economic-calendar/PIT provider | Complete the provider trial already defined in `docs/project-map.md`; this does not block the admission state machine. |
| Production AWS values | Region, domain, source CIDRs, SNS destination, and final secret paths before deployment. |

---

## 3. Unknown knowns — extracted context and taste

| ID | Extracted knowledge | What it changes |
|---|---|---|
| UK-GL-1 | The owner wants a recommendation instrument, not a trading terminal. | Lead with the decision and reasons; keep operational mechanics elsewhere. |
| UK-GL-2 | Confidence is useful context but not trusted enough to allocate capital. | Show it on cards with calibration status; prohibit confidence ordering in code. |
| UK-GL-3 | The owner wants proactive assistance but retains consequential authority. | Agents discover, summarize, and propose; selections and experiments require owner action. |
| UK-GL-4 | Email is an attention channel, not the system of record. | Keep messages concise and safe; all state and approval live in the app. |
| UK-GL-5 | The owner wants both rapid decisions and deep research. | Separate action cards from an editorial notebook and chronological timeline. |
| UK-GL-6 | “Learning” must become useful before statistical promotion is possible. | Permit observations and hypothesis queues early, but label them non-actionable and dependence-limited. |
| UK-GL-7 | The owner accepts useful paid services but dislikes waste. | Deterministic work always completes; model review is capped separately; add subscriptions only after a measured gap. |
| UK-GL-8 | The product may run unattended on one EC2 host. | Recovery, stale-work detection, independent alerting, and restore drills are product behavior, not optional infrastructure polish. |
| UK-GL-9 | Visual quality matters to trust. | Desktop selector, notebook, and charts require representative-state browser verification, not template-only checks. |
| UK-GL-10 | OANDA permission may become worthwhile after the system proves itself. | Preserve a rights-gated upgrade seam and an explicit future owner reminder rather than permanently discarding option B. |

### Consumers and environment

- **Human consumer:** one authenticated owner.
- **Machine consumers:** scheduler, worker, deterministic assessors, optional
  Anthropic interpreter, Gmail delivery worker, dashboard projections, and
  future experiment evaluators.
- **Development:** Amp orb with fake email and provider fixtures by default.
- **Unattended runtime:** one private EC2 deployment with PostgreSQL and
  off-host backup/monitoring.
- **Handoff rule:** no behavior may rely on this conversation. Contracts,
  decisions, provider rights, and deviations live in repository records/docs.

---

## 4. Unknown unknowns — landmine map

### Decided landmines

| ID | Finding and evidence | Resolution |
|---|---|---|
| UU-GL-1 | Concurrent exposure reads can admit two setups into the same remaining capacity (`forecasts/exposure.py:18-60`). | Serialize the complete assessment/admission command on a durable portfolio guard; reread state inside one transaction. |
| UU-GL-2 | “No paper result” currently doubles as “active,” so missing data can reserve capacity forever (`forecasts/exposure.py:18-23`, `forecasts/paper.py:146-147`). | Explicit admitted lifecycle with terminal `expired-unobserved`, `cancelled`, and `missing-data` states. |
| UU-GL-3 | Worker death after claim strands `running` jobs (`operations/models.py:30-37`, `operations/services.py:38-52`). | Leases, owner/heartbeat, execution deadlines, stale-running reaper, and crash tests. |
| UU-GL-4 | Email/model side effects and DB commits have an uncertain crash boundary. | Transactional outbox/attempt records with stable keys; never send from request or assessment transactions. |
| UU-GL-5 | Fixed-second schedules drift across DST and collapse missed intervals (`operations/services.py:18-33`). | IANA wall-clock schedules and explicit per-job catch-up/skip policy; never reconstruct missed LLM recommendations. |
| UU-GL-6 | Dynamic cohorts change as late data arrives (`forecasts/recommendations.py:507-537`). | Freeze cohort membership, eligibility cutoff, policy versions, and terminal coverage state. |
| UU-GL-7 | One-to-one sizing/cost records cannot represent prospective policy reassessment (`forecasts/models.py:374-391,648-664`). | Versioned append-only assessments; admission references the exact assessment used. |
| UU-GL-8 | Broad `contract_version__gte=2` silently applies v2 logic to future contracts (`forecasts/paper.py:21-46`, `forecasts/recommendations.py:507-534`). | Dispatch exact versions; unknown versions fail closed. |
| UU-GL-9 | Thirty correlated rows become `REPORTABLE` (`dashboard/views.py:383-445`). | Replace raw-row maturity with frozen eras, cluster/effective counts, intervals, and permanent descriptive language until promotion. |
| UU-GL-10 | Citation validation proves membership, not claim support (`forecasts/recommendations.py:456-469`). | Structured claim-to-evidence mapping, directness, contradiction, and independent provenance family. |
| UU-GL-11 | Conflicted evidence remains model eligible (`research/services.py:457-487`). | Propagate quality into packets; quarantine or explicitly represent conflict; required unresolved facts force abstention. |
| UU-GL-12 | Prompt-injection resistance is only a model instruction (`forecasts/recommendations.py:80,113-120`). | Treat it as mitigation, not a guarantee; add hostile canaries and fail-closed output/evidence checks. |
| UU-GL-13 | Model/request identity omits returned model, prompt/schema hash, and pricing lineage (`forecasts/recommendations.py:137-184`). | Freeze full method identity and open a new experiment era whenever any component changes. |
| UU-GL-14 | Raw exception text is persisted and rendered (`operations/services.py:55-66`, `templates/dashboard/operations.html:6`). | Store safe structured error codes/summaries; redact diagnostics; notifications use allowlisted fields only. |
| UU-GL-15 | Login currently means any Django user can query global private records (`dashboard/views.py:46-558`). | Enforce an owner permission invariant on every view/action; test an authenticated non-owner. |
| UU-GL-16 | Empty ingestion can report success and recycle old evidence (`market/quality.py:12-51`, `market/services.py:78-99`). | Distinguish `new`, `no-new-data`, `partial`, `delayed`, and `failed`; gate dependent work on expected fresh coverage. |
| UU-GL-17 | Web/DB health does not prove scheduler, worker, or nightly output health (`dashboard/views.py:39-43`). | Process heartbeats, queue/lease age, expected-output SLA, and independent external monitoring. |
| UU-GL-18 | Current Compose/settings expose development defaults (`config/settings.py:7-16`, `compose.yaml:18-27`). | Separate fail-closed production settings/deployment; run `check --deploy`; no direct public app port. |
| UU-GL-19 | External/provider text and unrestricted URLs can enter future UI/email projections (`research/models.py:74-104`, `templates/dashboard/research.html:81-138`). | Dedicated allowlisted review/notification DTO, HTTPS-safe-link policy, plain-text email, hostile-string tests. |
| UU-GL-20 | Current OANDA-derived values enter Anthropic without a field-level rights gate (`research/services.py:492-505`, `forecasts/recommendations.py:401-430`). | Option A now: remove them from model packets. Add per-field rights manifests and retain a governed option-B upgrade. |

### Sharp edges the implementation must preserve

1. Admission is one atomic state transition, not a mutable flag on a
   recommendation.
2. Selection cards derive capacity from one locked/versioned assessment. They
   never recompute a historic decision using today’s constants.
3. A trigger, expiry, or materially new batch closes the whole selection
   cohort. A stale browser POST must fail without partial mutation.
4. All admission mutations are owner-only, POST-only, CSRF protected,
   idempotent, audited, and scanner/prefetch safe.
5. Every email links to normal authentication and then a sanitized internal
   destination. It is not a bearer approval URL.
6. A delivery retry may create another attempt but not another logical
   notification. Provider response and uncertain outcome are retained safely.
7. Outcomes close only from complete data observed by the declared cutoff.
   Persist exact candle and ingestion-run identities. Corrections supersede.
8. Frozen postmortem membership includes every eligible item and explicit
   missing/unevaluable denominators; late data cannot rewrite the cohort.
9. Deterministic review completes before optional interpretation. Claude
   receives no raw provider payload, raw article body, raw exception, secret,
   unrestricted URL, or OANDA-derived value.
10. Interpretation uses structured claims and permitted citations. It cannot
    write outcomes, scores, classifications, capacity, policy, or strategy.
11. Postmortems use “associated with,” not causal wording, absent a
    prospective intervention or controlled ablation.
12. Learning counts issuance/event/factor clusters, not rows. Five cohorts
    create a candidate hypothesis only—not evidence of skill.
13. Budget reservations serialize authorization; estimated and billed costs
    remain distinct. Optional model work pauses before deterministic work.
14. Source discoveries are quarantined proposals. Discovery never grants
    ingestion, retention, or external-processing permission.
15. Confidence remains visibly uncalibrated until its own dependence-aware
    calibration gate passes.

### OPEN landmine gates

| Gate | Status and unblocker |
|---|---|
| OANDA option B | **OPEN intentionally.** Obtain written permission, record governing terms and exact permitted fields/transforms/processor, then run the rights-gate tests. The product should recommend this review once operational maturity is demonstrated. |
| Paid/restricted full text | **OPEN per source.** Licence must permit the exact automated access, retention, and external-model processing. A consumer subscription alone is insufficient. |
| Production email deliverability | **OPEN until deployment.** Verify Gmail app password, sender/recipient, SPF/DMARC implications, rate limits, redaction, retries, and test delivery without exposing credentials. |
| Effective-sample promotion thresholds | **OPEN by design.** Pre-register before a challenger begins; never select thresholds after viewing its results. |
| Host-independent critical alert | **OPEN until AWS slice.** Configure and test SNS or equivalent independently of the app host. |

---

## 5. Tweakable plan

This section is sorted by likelihood of changing, not build order.

### A. Judgment-heavy — keep versioned and easy to toggle

#### A1. Admission policy

Version the setup risk, aggregate cap, currency-direction caps, waiting-setup
treatment, cohort closure rules, and material-batch definition. Keep the
initial C$25,000/C$125 policy and owner-selection rule fixed for v1.

**Toggle later:** policy values and materiality thresholds—not atomicity,
immutability, or the prohibition on confidence ranking.

#### A2. Review and interpretation contracts

Define three deterministic review schemas and one optional interpretation
schema. Each interpretation claim maps to permitted evidence and is rejected
when unsupported.

**Toggle later:** prompt, model, included rights-cleared context, narrative
length, and budget. Every toggle creates a new method/experiment era.

#### A3. Learning and promotion

Start with immutable observations, then five-cohort candidate hypotheses,
owner-authorized prospective challengers, and larger pre-registered promotion
gates. Display raw and effective evidence separately.

**Toggle later:** effective-sample estimator, interval method, minimum cluster
counts, evaluation window, and guardrails—only before an experiment starts.

#### A4. Notification policy

Version event severity, consolidation window, digest contents, staleness SLA,
and channel routing. Keep app-only approvals and safe-link semantics invariant.

**Toggle later:** Gmail provider, digest clock time, and reminder escalation.

### B. Stable ownership boundaries

#### B1. Portfolio state machine

Versioned capacity assessments, cohorts, selections, admissions, supersessions,
and explicit lifecycle transitions. One serialized command owns capacity.

#### B2. Deterministic review engine

Frozen cohort membership, complete-data cutoff, thesis/execution/reconciliation
facts, coverage, costs, and lineage. Optional interpretation consumes only its
output projection.

#### B3. Experiment registry

Immutable method identity, source pack, prompt/schema/model/pricing versions,
champion/challenger status, cohort assignment, and promotion history.

#### B4. Owner interface

Decision-first selector and inbox; action-first digest; editorial review
notebook; chronological timeline; calibration/experiment health; separate
Mission Control. Desktop complete and mobile functional.

### C. Mechanical controls — builder may implement without reopening design

- leased queue claims, heartbeats, deadlines, stale recovery, and safe replay;
- transactional outbox, attempt records, fake email backend, and Gmail adapter;
- timezone-aware schedules, catch-up records, and market-session prerequisites;
- owner authorization, POST/CSRF/idempotency, safe redirects, canonical origin;
- structured redacted errors and allowlisted notification/review projections;
- production settings, security headers, self-hosted assets, health/SLA probes;
- migrations, database constraints/triggers, concurrency/fault-injection tests;
- implementation-deviation log and updated operator/runbook documentation.

---

## 6. Implementation sequence and acceptance gates

### Slice 1 — Reliable state and side-effect kernel — complete

Add exact-version dispatch, explicit recommendation/paper lifecycle,
versioned assessments, leased work, heartbeats/reaper, calendar scheduling,
budget reservations, and transactional outbox/delivery attempts.

**Gate:** PostgreSQL concurrency and crash-boundary tests prove provider budgets
cannot be concurrently over-reserved, expired occurrences are recovered,
logical deliveries are deduplicated with uncertain attempts retained, and
versioned assessments do not drift with current constants. Portfolio
over-admission is tested in Slice 2 when admission exists.

### Slice 2 — Prospective admission and owner selection — complete

Add policy-effective boundary, legacy classification, capacity assessments,
competing cohorts, immutable/superseding owner selections, admissions, selector
cards, dashboard inbox, Gmail notifications, and audit history.

Implemented with an explicit policy activation timestamp, serialized portfolio
guard, append-only cohorts/selections/admission events, trigger-aware cohort
closure, confidence-labelled selector cards, owner-only POST/CSRF controls,
dashboard notifications, and a controlled Gmail SMTP adapter over the durable
outbox. Real Gmail delivery remains disabled until deployment secrets and the
canonical URL are configured.

**Gate:** every recommendation remains scoreable; stale/duplicate POSTs fail
closed; trigger/expiry/new-batch closure is deterministic; confidence displays
but never affects ordering or allocation.

### Slice 3 — Deterministic postmortem notebook — complete

Freeze review cohorts and implement separate thesis, execution, and
reconciliation facts with explicit missing-data coverage and source lineage.
Render the notebook and chronological timeline without Claude first.

**Gate:** rerunning a frozen cohort produces identical membership/facts;
corrected data creates a superseding assessment; no causal language appears.

Implemented with point-in-time cohort cutoffs, append-only PostgreSQL-enforced
thesis/execution/reconciliation assessments, explicit missing denominators,
source hashes and lineage, cutoff-aware eligibility, a read-only owner notebook,
and pair timelines. Identical reassessments create no rows; changed source facts
append assessments linked to the records they supersede.

### Slice 4 — Bounded Sonnet interpretation and learning queue — complete

Add rights-cleared packet projection, full method identity, structured cited
interpretation, US$20 monthly reservation, observations, five-cohort hypothesis
gate, source proposals, and owner-authorized challenger creation.

**Gate:** deterministic review survives provider/budget failure; OANDA-derived
values and restricted fields cannot enter requests; injection/unsupported
claims fail; agents cannot alter active policy.

Implemented with a contract-v3-only rights projection, immutable prompt/schema/
model/pricing identity, structured cited output, separate daily/monthly budget
reservations, fail-closed provider attempts, non-actionable observations,
quarantined source proposals with owner notification, and a five-distinct-
issuance-cohort hypothesis gate. Owner authorization is an append-only audited
permission to design a future challenger; it cannot start an experiment or
change the champion, recommendation prompt, confidence, sizing, or risk policy.
The feature and its daily scheduled job remain disabled unless both the
postmortem feature flag and Anthropic credential are configured.

### Slice 5 — Reproducible experiment health

Add immutable experiment eras, dependence clusters, effective sample size,
baselines, intervals, calibration/sharpness/coverage, attempt history, and
promotion records. Replace the current raw-30 `REPORTABLE` rule.

**Gate:** 30 intentionally correlated fixtures remain non-reportable; method
changes create a new era; failed challengers remain visible.

### Slice 6 — Production privacy and unattended operation

Add owner-only authorization/TOTP/IP controls, production settings, EC2
deployment, independent monitoring, encrypted secrets, WAL backups, restore
drill, and host-independent critical alerts.

**Gate:** `manage.py check --deploy`, security/access tests, process-kill tests,
external-alert test, deployment rollback, and timed database restore all pass.

---

## 7. Facts to confirm before affected code is enabled

- Gmail sender, recipient, and app-password secret names.
- Canonical dashboard origin used in email links.
- Exact Anthropic model snapshot and pricing table at implementation time.
- FX holiday/calendar library and DST fixtures.
- Material-new-batch threshold and material-staleness SLA versions.
- Production AWS region, domain, source CIDRs, SNS destination, and SSM paths.
- Written OANDA permission before option B is even configurable.

These do not authorize a builder to guess. Local implementation should use
fixtures/fakes and leave external delivery disabled until its values are
provided.

---

## 8. Copyable implementation prompt

```text
Begin Slice 1 from docs/governed-learning-map.md: Reliable state and
side-effect kernel.

Treat that map as the controlling specification for this phase and
docs/project-map.md as broader context. Implement the smallest coherent
foundation required for prospective admission: exact contract-version
dispatch, explicit lifecycle states including missing/unobserved termination,
versioned append-only assessments, serialized portfolio mutation, leased queue
claims with heartbeat/deadline/stale recovery, timezone-aware schedule and
missed-run policies, provider budget reservations, and a transactional outbox
with delivery attempts. Do not yet build selector UI, send real Gmail, or add
Claude postmortems.

Preserve all existing recommendations and paper results. Classify legacy rows
without rewriting their contracts. Use PostgreSQL concurrency/fault tests to
prove that competing work cannot exceed capacity, worker death cannot strand a
job, retries cannot create duplicate logical delivery, and future contract
versions fail closed. Record any code-forced deviation in an implementation
notes document and update the map when necessary.

Keep OANDA-derived values outside all Anthropic requests. Do not push, deploy,
send external email, or change shared infrastructure without explicit owner
approval. Run targeted checks and the full relevant suite, then report the
schema/behavior changes and decisive verification output.
```

---

## 9. Definition of exploration completion

All four quadrants are captured here. Every consequential question discovered
during the walk is decided or has a named unblocker. The build plan preserves
judgment-heavy seams while collapsing mechanical controls. Implementation is a
separate task and starts only when the owner asks to use the prompt above.
