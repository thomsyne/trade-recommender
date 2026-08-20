# FX Forecast Lab — Four-Quadrant Project Map

**Status:** Planning complete; Foundation, Market Truth, Forecast Contract, Research Evidence, Governed Recommendations, Prospective Calibration, and Paper Execution implemented
**Prepared:** 2026-08-18  
**Purpose:** Durable source of truth for the first implementation and future Amp threads

This document is the output of an `explore-unknowns` quadrant walk. It records
what is settled, what was decided, what tacit preferences were extracted, what
landmines constrain the design, and what remains open. Implementation must not
silently fill an OPEN item or contradict a settled decision.

---

## 1. Known knowns — settled ground

### Product identity

This is a **private, single-user FX forecasting research instrument**. It is
not initially a production trading system, public signal service, investment
adviser, or live execution engine.

The system will:

- follow USD/CAD, GBP/USD, EUR/GBP, and EUR/USD in broker-standard orientation;
- collect point-in-time market, macroeconomic, news, approved social, and
  cross-asset evidence;
- produce immutable 20-trading-day macro outlooks and conditional
  five-trading-day tactical recommendations;
- attach direction, probability, entry conditions, expiry, target,
  invalidation, contrary evidence, source provenance, and exact data cutoff;
- operate internal paper ledgers rather than submit broker orders;
- evaluate every forecast, abstention, entry, and paper outcome prospectively;
- compare model, mechanical baseline, human, and adaptive-management results
  without rewriting original records;
- use nightly agents to propose versioned experiments, never silently alter the
  active method;
- eventually test whether conservative-cost paper profitability accompanies
  forecast quality.

### Initial market and evidence scope

- **FX:** USD/CAD, GBP/USD, EUR/GBP, EUR/USD.
- **Cross-assets:** two-year yield differentials, crude oil, gold, S&P 500,
  VIX, and Bitcoin.
- **Technicals:** H4/daily swing pivots, prior daily/weekly highs and lows,
  ATR/realized volatility, and one EWMA trend measure.
- **Chart vision:** secondary experimental input only; deterministic technicals
  remain authoritative until vision demonstrates incremental value.
- **Social:** approved officials, institutions, and named journalists may enter
  directly. Everything else enters only through reputable reporting.

### Operating model

- Development and review happen in Amp orbs.
- The unattended application will run on one AWS EC2 host through Docker
  Compose.
- Checked merges to `main` deploy immutable images automatically after tests.
- The dashboard is publicly reachable over HTTPS but restricted by source IP,
  password, and TOTP.
- Critical infrastructure failures leave the host through SNS email; trading
  and research notifications remain in the dashboard.
- Secrets live in AWS Systems Manager Parameter Store and are accessed through
  narrow IAM roles.
- PostgreSQL uses continuous WAL archiving, daily backups, and S3 retention,
  targeting no more than 15 minutes of data loss and four hours to restore.

### Current repository facts

The repository now contains the Django/PostgreSQL application, durable
scheduler/worker, OANDA market ingestion, deterministic technicals, immutable
forecast controls, official four-economy macro and release calendars, broader
RSS collection, seven intermarket series, and scheduled pair-level evidence
snapshots. Governed model recommendations are immutable, evidence-cited, and
advisory. Versioned probabilistic outcomes now resolve prospectively after five
sessions. Directional setups are separately observed with hourly bid/ask paper
execution; research remains unable to issue or mutate forecasts.

---

## 2. Known unknowns — complete decision ledger

All entries below were closed by the user unless marked **Territory** or
**OPEN**.

| ID | Question | Settled decision |
|---|---|---|
| KNU-1 | Nightly-agent authority | Agents produce versioned proposals; owner approval is required. |
| KNU-2 | First executable boundary | Internal paper portfolio; no OANDA order submission. |
| KNU-3 | Forecast horizons | Separate 20-trading-day macro and five-trading-day tactical products. |
| KNU-4 | Success definition | Score macro direction, tactical direction, entry activation, target-before-invalidation, and net paper P&L separately. |
| KNU-5 | Pair orientation | Broker-standard pairs only; no inverse display mode in v1. |
| KNU-6 | Research breadth | Broad web discovery is allowed, but curated and official sources have priority. |
| KNU-7 | Initial budget range | User is comfortable with CA$50–100/month where useful sources justify it. Superseded in scope by KNU-39. |
| KNU-8 | Paywalled content | Hybrid: permitted automation where licensed; otherwise evidence links and manual review. |
| KNU-9 | Chart analysis boundary | Deterministic levels are primary; chart vision is secondary commentary. |
| KNU-10 | Technical breadth | Minimal fixed toolkit; new indicators require versioned experiments. |
| KNU-11 | Cross-asset inputs | Rates, oil, gold, S&P 500, VIX, and Bitcoin. |
| KNU-12 | Direct social input | Approved officials/institutions/journalists direct; all other social material via reputable reporting. |
| KNU-13 | Interface family | Dashboard system of record plus scheduled briefs/alerts. |
| KNU-14 | Notification channel | Business notifications dashboard-only. Critical operations were revised by UU-1 to add SNS email. |
| KNU-15 | Runtime progression | Develop in Amp orbs, deploy to EC2 when unattended scheduling is ready. |
| KNU-16 | Deployment trigger | Successful checked merges to `main` deploy automatically. |
| KNU-17 | Retention | Permanent forecasts/features/citations/hashes; full-text retention follows source-specific rights and expiry. |
| KNU-18 | Approved changes | Every approved change creates a new prospective experiment version. |
| KNU-19 | Historical prices | About ten years daily and three-to-five years H4. |
| KNU-20 | Account model | Public HTTPS, one application user. Authentication strengthened by UU-2. |
| KNU-21 | Secrets | AWS Systems Manager Parameter Store. |
| KNU-22 | Paper capital representation | Normalized R/% performance plus CA$1,000 feasibility view. |
| KNU-23 | Confidence sizing | Evaluate confidence-scaled sizing. |
| KNU-24 | Initial confidence authority | Primary portfolio capped at 1%; shadow portfolio tests the full confidence scale. |
| KNU-25 | Event/weekend exposure | Permit and label in paper research; model spread/gap costs and report cohorts separately. |
| KNU-26 | Promotion minimum | Fifty tactical forecasts over six months, revised by UU-6 to require dependence-aware effective evidence. |
| KNU-27 | Model upgrades | Pin exact identifiers; every upgrade is a new overlapping experiment. |
| KNU-28 | Missing providers/data | Required/optional freshness policy; critical missing data blocks action, context gaps degrade visibly. |
| KNU-29 | Downtime replay | Backfill factual data honestly; never reconstruct missed historical LLM forecasts. |
| KNU-30 | Login recovery | Owner-only reset through authenticated AWS Systems Manager/CLI. |
| KNU-31 | Schedule anchor | New York FX close, Sunday reopening, completed OANDA H4 candles, timezone-aware Toronto display. |
| KNU-32 | Event response | Capture immediately; action only after corroboration, freshness/spread checks, and a versioned stabilization window. |
| KNU-33 | Existing positions after events | Primary ledger preserves original management; adaptive shadow ledger may act on superseding forecasts. |
| KNU-34 | Forecast frequency | Weekly macro forecasts; tactical forecasts only on material changes; one active tactical recommendation per pair. |
| KNU-35 | Material change | Versioned deterministic triggers: major releases/statements, technical breaks, direction/level changes, or meaningful probability shift. |
| KNU-36 | Source quality | Per-evidence provenance matrix: tier, directness, recency, corroboration, revision state, and content type. |
| KNU-37 | Source conflicts | Preserve disagreement, lower confidence, and block action when a required fact remains unresolved. |
| KNU-38 | First paid-data priority | Structured economic calendar and point-in-time macro data. |
| KNU-39 | Budget accounting | CA$50–100 monthly cap applies to paid data/publications; AWS and Anthropic are tracked separately. |
| KNU-40 | Backups | Layered PostgreSQL/S3 backups; strengthened by UU-4 with continuous WAL and explicit RPO/RTO. |
| KNU-41 | Evidence display | Claim-to-evidence cards with timestamps, provenance, conflicts, and permitted snapshots. |
| KNU-42 | Explanation form | Structured base case, support, contrary evidence, invalidation, uncertainty, and what changes the view. |
| KNU-43 | Recommendation approval | Parallel autonomous-model and human-filtered paper ledgers. |
| KNU-44 | Abstention | Publish and score outlooks even when there is no valid trade setup. |
| KNU-45 | Human decisions | Structured accept/reject/modify reason codes locked before outcomes. |
| KNU-46 | Manual forecasts | Human may create a separately attributed structured thesis; model records remain immutable. |
| KNU-47 | No-trade opportunity cost | Prospectively issue a standardized shadow trade for each abstention. |
| KNU-48 | Transaction costs | Forward observed bid/ask plus versioned slippage, gap, and financing models; report gross and net. |
| KNU-49 | Authentication | Password and IP allowlist; strengthened by UU-2 with TOTP. |
| KNU-50 | Publication presentation | Evidence cards with permitted excerpt, provenance/access labels, direct link, and usefulness feedback. |
| KNU-51 | Human/model influence | Optional blind mode locks a human thesis before model reveal. |
| KNU-52 | Historical cost uncertainty | Optimistic/base/conservative scenarios; conservative survival is required. |
| KNU-53 | Audit | Append-only reproducibility audit of jobs, inputs, prompts/models, outputs, tools/costs, failures, user actions, and experiments. |
| KNU-54 | Spend control | Hard per-run, daily, and monthly caps by provider/job; optional work pauses first. |
| KNU-55 | Model output | Strict schema/invariant validation, one bounded repair attempt, then fail closed. |
| KNU-56 | Prompt injection | All fetched content is untrusted quoted data; retrieval/synthesis and authorities are separated. |
| KNU-57 | Historical data quality | Deterministic checks, targeted independent comparisons, and frozen dataset manifests. |
| KNU-58 | Application stack | Python/Django monolith, PostgreSQL, Python worker/scheduler, HTMX-style UI, browser charting. |
| KNU-59 | EC2 topology | Single-host Docker Compose: proxy, web, worker, scheduler, PostgreSQL; S3 off-host backup. |
| KNU-60 | Rollback | Immutable versioned images, health checks, application rollback, backward-compatible migrations. |
| KNU-61 | Destructive migrations | Explicit approval, verified backup, maintenance mode, migration validation, controlled resume. |
| KNU-62 | Operations view | Dashboard shows freshness, schedules, durations, retries, costs, queues, failures, and safe replay. |
| KNU-63 | Job retries | Idempotent bounded retries, transient/permanent classification, exponential backoff, visible failed queue. |

### Known-unknown items closed by the territory

- Provider rate limits use lawful caching/deduplication, reset-aware deferral,
  and bounded retries.
- Model failures appear as explicit failed/degraded runs and never create an
  actionable recommendation when required validation fails.
- IP allowlist maintenance uses a safe owner-only SSM operation, never a
  temporary global-open rule.
- Newly discovered sources begin in quarantine/context status and require
  licensing, lineage, reliability, cost, and coverage review.

### OPEN known unknown

| Item | Status | What unblocks it |
|---|---|---|
| Exact economic-calendar/PIT provider | **OPEN** | Trial Trading Economics and alternatives against Canada/US/euro-area/UK coverage, timestamp/revision/PIT behavior, API reliability, model-processing rights, retention terms, and CA$50–100 data budget. |

---

## 3. Unknown knowns — extracted product taste and context

| ID | Extracted preference | What it reshaped |
|---|---|---|
| UK-1 | Pair workspace is decision-first, with Research and Timeline beneath it; Operations is separate. | Prevents scheduler/cost density from obscuring trade decisions. |
| UK-2 | Landing page is “Today’s decisions”: four pair cards ordered by urgency, then material events/changes. | Establishes the primary navigation and information hierarchy. |
| UK-3 | Decisions use a modern premium financial-product style; research is editorial; charts use a dark workstation style. | The UI deliberately supports distinct cognitive modes rather than one generic theme. |
| UK-4 | Desktop is complete; mobile is a focused companion for decisions, evidence summaries, accept/reject, and paper status. | Prevents deep research/operations from being compromised by mobile-first constraints. |
| UK-5 | After absence, one chronological catch-up brief explains missed events, changes, expiries, results, and failures. | Adds a return-to-context workflow instead of forcing review of every daily brief. |
| UK-6 | “Done” means owner-operable after three months away: one-command local start, architecture and provider docs, deployment, migration, backup, restore, and experiment lineage. | Documentation and recovery are deliverables, not later cleanup. |

### Consumer, environment, and inheritance

- **Consumer:** one owner only.
- **Environment:** Amp orbs for development; private application state on AWS
  EC2/PostgreSQL/S3 once scheduling begins.
- **Inheritance:** future Amp threads must be able to build, operate, restore,
  and extend the system from repository documentation and versioned records,
  without relying on conversation history.

---

## 4. Unknown unknowns — landmine map

### Decided landmines

| ID | Finding | Resolution |
|---|---|---|
| UU-1 | Dashboard-only alerts fail with the dashboard. | Critical host, backup, certificate, deployment, security, stale-data, and budget failures send SNS email. |
| UU-2 | Password plus IP is not strong independent authentication. | Require password, TOTP, and allowed source IP; recover through SSM. |
| UU-3 | Private access does not grant universal automation or external-LLM rights. | Apply source-specific terms; process full text where permitted, otherwise use links/metadata/permitted excerpts/notes. |
| UU-4 | Daily backups can lose irreplaceable forward evidence. | Continuous WAL + daily backups; target ≤15-minute RPO and ≤4-hour RTO; verify by restore drills. |
| UU-5 | H4/D OHLC cannot prove intrabar entry/stop/target sequence. | Hourly bid/ask now drives paper fills; same-hour ambiguity receives the adverse result. |
| UU-6 | Fifty overlapping/correlated rows are not fifty independent observations. | Keep row/time minimums but require distinct parent/event clusters, effective sample size, and dependence-aware uncertainty. |
| UU-7 | Repeated proposals can optimize the judge rather than improve forecasts. | Frozen prospective champion/challenger runs, locked metrics/window, shadow candidate, complete attempt history. |
| UU-8 | Repeated syndicated articles create false corroboration. | Track claim lineage and independent provenance families; URL count is not evidence count. |
| UU-9 | Chart vision duplicates deterministic price evidence. | Vision remains a separate frozen-renderer ablation and cannot raise confidence until prospectively validated. |
| UU-10 | Outcome-weighted sources can create self-reinforcing monoculture. | Fixed diverse core, exploration quota, human-approved discovered-source proposals, prospective masking/ablation. |
| UU-11 | Human-filtered cases are selected and cannot prove human causal value. | Human/model comparisons are descriptive in v1; no causal claim without later randomized review availability. |
| UU-12 | Multiple metrics enable winner-picking. | Proper five-day probabilistic score is research-phase primary; calibration, coverage, drawdown, and conservative-cost results are guardrails. |
| UU-13 | P&L must eventually matter without contaminating early development. | After an evidence gate, start a new prospective trading-validation era where conservative-cost net paper P&L is co-primary. |

### Data and simulation sharp edges

These are implementation constraints, not optional decisions:

1. Request and persist explicit OANDA bid/ask candles; midpoint is a feature,
   never an execution price.
2. Pin `smooth=false`, explicit New York alignment, and only `complete=true`
   candles. Candle timestamps are interval starts.
3. Derive market boundaries with IANA timezones and an FX calendar, never a
   fixed UTC hour or weekday arithmetic.
4. A forecast can execute only after issuance using the first later executable
   quote and applicable side.
5. Historical stop/limit touches do not imply exact fills; gap, bound, and
   cancellation behavior must be modeled.
6. Validate OANDA pagination, uniqueness, monotonic timestamps, expected gaps,
   price component, alignment, and request manifest.
7. Treat broker daily and H4 candles as distinct versioned source series.
8. Store macro observation period, release/vintage timestamp, revision state,
   source timezone, and availability cutoff. Historical work uses point-in-time
   values such as ALFRED vintages.
9. Convert every P&L, fee, spread, financing, and cash flow to CAD at event time
   using an explicit direction-aware conversion policy.
10. Preserve historical financing uncertainty as scenarios unless suitable
    date/instrument/side/account terms are obtained.
11. Net portfolio exposure and attribution by CAD, USD, EUR, and GBP, not only
    pair count.

### Evaluation sharp edges

1. One append-only event store is canonical; “ledgers” are immutable views.
2. Every forecast references an exact versioned target contract, information
   cutoff, parent thesis/event, evidence snapshot, model/prompt, and scoring
   contract.
3. Every eligible forecast and abstention resolves; coverage and risk-coverage
   accompany accuracy.
4. Learned transforms and calibrators use only temporally prior data; temporal
   tests purge at least the maximum overlapping horizon.
5. Report raw and effective sample counts and cluster uncertainty by horizon,
   event, parent thesis, pair, and common currency factor.
6. Proper probability scores, calibration, sharpness, coverage, and declared
   baselines remain separate from execution P&L.
7. Scoring code, labels, historical evidence, and promotion gates are not
   writable by proposal agents.
8. Postmortems say “associated with” unless prospective intervention or
   controlled ablation supports a causal claim.
9. A pinned hosted model is not bit-for-bit reproducible. Store returned model
   ID/request parameters and run deterministic drift canaries.
10. Macro and tactical products score separately; aggregate weights are fixed
    before evaluation.

### Legal, provider, and recordkeeping sharp edges

1. A source registry must record governing terms/version, acquisition method,
   permitted fields, retention, LLM processing, attribution, deletion, and
   export rules before ingestion.
2. RSS delivery is not blanket permission for permanent full-text storage.
3. Do not bypass paywalls, authentication, CAPTCHAs, metering, or technical
   protections.
4. Use the official X API for approved use; preserve IDs/provenance and comply
   with deletion/display/retention rules. Do not use X data to fine-tune a
   foundation model.
5. Keep OANDA data private, avoid reconstructable exports, and obtain provider
   confirmation before richer raw/derived data is sent externally or a second
   user is added.
6. Explicit open-government licences are honored with attribution; government
   publication alone is not assumed public domain.
7. Public signals, compensation, affiliate monetization, copy trading,
   execution for others, or any second user triggers a new Canadian
   registration/provider review.
8. Before live money, a Canadian tax professional must confirm income/capital
   characterization, CAD conversion, financing/expense treatment, retention,
   and any T1135 implications. Tax evidence must be separable from licensed
   article retention and kept for the required period (typically at least six
   years, subject to professional confirmation).

### Security and operations sharp edges

1. Isolate web fetching in an unprivileged worker with no AWS credentials or
   Docker socket. Block localhost, metadata, private/link-local/reserved IPv4
   and IPv6, DNS rebinding, unsafe redirects/ports, decompression bombs, large
   responses, slow streams, and excess concurrency.
2. Require IMDSv2, hop limit 1, narrow IAM roles, exact SSM parameter paths,
   KMS constraints, and explicit secret rotation/revocation.
3. Keep PostgreSQL, Docker, workers, and admin ports private. Prefer SSM over
   public SSH. Containers run non-root with bounded resources and rotated logs.
4. Build once in CI, publish an immutable digest, deploy that digest through
   GitHub OIDC, pin third-party actions by commit SHA, and serialize deploys.
5. Use expand/migrate/contract schema changes. Destructive work follows the
   approved maintenance workflow and never auto-restores a database over newer
   valid evidence.
6. Scheduler and execution are separate. Every occurrence has a unique durable
   key, singleton lease/advisory lock, atomic claim, idempotency, lateness,
   timeout, and retry policy.
7. Keep OS/containers/PostgreSQL/Django in UTC; monitor clock offset; retain
   source timezone and market calendar semantics.
8. Enforce Django production checks, canonical hosts, trusted proxy boundaries,
   secure cookies, CSRF, HSTS after verification, login throttling, and session
   invalidation after credential change.
9. Monitor disk/inodes, certificate, WAL/archive lag, backup integrity,
   provider freshness, queues, costs, and security outside the host.
10. Redact credentials, cookies, restricted source text, prompts, and sensitive
    payloads from logs, traces, exception locals, CI output, and backups.

### OPEN landmine gates

| Gate | What unblocks it |
|---|---|
| Historical financing accuracy | Suitable point-in-time financing terms, or permanent sensitivity-only reporting. |
| Rich OANDA-to-LLM processing | Written provider confirmation for the exact data and workflow. |
| Paid/restricted full-text processing | Source licence or terms explicitly permitting automation, retention, and external model processing. |
| Live-money accounting | Canadian tax advice on the exact OANDA account and trading behavior. |
| Public/multi-user product | Fresh securities/derivatives, provider, copyright, privacy, security, and tax review. |

---

## 5. Tweakable build plan

This plan is deliberately sorted by **likelihood of changing**, not merely by
execution order. High-judgment choices stay easy to replace; settled mechanical
work is collapsed at the bottom.

### A. Most likely to change — keep behind versioned contracts

#### A1. Forecast and target contracts

Define executable schemas and golden examples for:

- 20-day endpoint macro direction;
- five-day tactical probability event;
- conditional entry activation and expiry;
- target-before-invalidation after activation;
- no-trade shadow benchmark;
- neutral bands, equality, cancellation, missing data, gaps, and market closure;
- parent thesis/event relationships and material-change triggers.

**Toggle points:** probability event definition, neutral band, tactical horizon,
10-point material-change threshold, stabilization delay.

#### A2. Source pack and provider trial

Build the source registry first. Start official/free connectors, then trial one
economic-calendar/PIT provider against a recorded fixture set. Broad web
discovery produces quarantined source proposals.

**Toggle points:** paid calendar vendor, news aggregator, X usage, source tiers,
retention, extraction versus full text.

#### A3. Forecasting method and experiments

Create the pinned Anthropic request contract, structured output schema,
evidence boundary, token/search budgets, model drift fixtures, and deterministic
validator. Establish frozen baseline, champion, and challenger identities.

**Toggle points:** model snapshot, prompt, source context, chart-vision
challenger, technical feature additions.

#### A4. Evaluation and promotion

Implement locked target resolution and scoring independently of proposal
agents. Start with proper forecast score and declared baselines; report
dependence-aware uncertainty, coverage, calibration, and guardrails. Start a
new evaluation era before P&L becomes co-primary.

**Toggle points:** exact proper score, minimum independent clusters, champion
window, guardrail thresholds, baseline weights.

#### A5. Paper execution and cost uncertainty

Implement one canonical event stream and immutable ledger views: autonomous,
human-filtered, primary management, adaptive management, confidence shadow,
and no-trade shadow. Use bid/ask, later executable quotes, ambiguity bounds,
CAD conversion, financing scenarios, and currency-factor exposure.

**Toggle points:** confidence-risk mapping, slippage/gap scenarios, financing
ranges, event/weekend policy before live money.

#### A6. Product presentation

- Today: four urgency-ordered decision cards and material events.
- Pair: Decision, Research, Timeline.
- Experiments and Journal: separate comparison/audit surfaces.
- Operations: jobs, freshness, failures, queues, costs, backup/deploy state.
- Desktop complete; mobile focused.

**Visual modes:** premium financial decisions, editorial research, dark dense
charts. The disposable planning mock is not a visual-quality reference.

### B. Medium likelihood — stable boundaries, replaceable providers

#### B1. Django application foundation

One Python repository and schema with Django auth/admin/migrations, PostgreSQL,
HTMX-style interactions, browser charting, typed provider interfaces, and
separate web/scheduler/worker processes.

#### B2. Point-in-time data pipeline

Raw immutable snapshots, normalized series, source manifests, quality gates,
release vintages, currency conversion, deterministic technicals, lineage
deduplication, and lawful retention/deletion jobs.

#### B3. Durable scheduling

Market-bound occurrence generation, singleton lease, durable unique job keys,
idempotent workers, bounded retry, failed queue, catch-up semantics, and cost
controls.

### C. Lowest likelihood — mechanical infrastructure

The builder is trusted to implement these settled controls without reopening
product design:

- Docker Compose development/EC2 topology;
- HTTPS reverse proxy and Django production settings;
- password + TOTP + IP allowlist and SSM recovery;
- Parameter Store/KMS/IAM role separation;
- ECR immutable images, GitHub OIDC, checked-main deploy, health rollback;
- continuous PostgreSQL WAL, S3 backup/retention, restore drills;
- CloudWatch/SNS critical alerts, external health checks, budgets;
- non-root containers, private networks, no public database/SSH/Docker;
- runbooks, architecture records, local setup, deployment and recovery docs.

---

## 6. Suggested implementation slices

These slices are dependency-aware, but each ends in something reviewable.

1. **Foundation — complete:** Django/PostgreSQL/worker skeleton, authentication, source
   registry, canonical time/currency/instrument types, local Compose, tests.
2. **Market truth — complete:** OANDA daily/H4 bid/ask ingestion, manifests, quality gate,
   New York alignment, deterministic technicals, basic charts.
3. **Forecast contract — complete:** target schemas, immutable event/evidence store,
   deterministic resolver, baseline forecasts, proper scoring fixtures.
4. **Research evidence core — complete:** official macro vintages/releases,
   approved RSS fetch boundary, provenance/lineage, policy-decision calendars,
   intermarket context, and immutable pair evidence. Paid consensus/PIT
   enrichment remains an optional provider trial.
5. **Model forecast:** pinned Anthropic synthesis, strict validation, budgets,
   abstention, evidence cards, immutable prompt/model records.
6. **Paper experiment:** entries, costs, ambiguity bounds, CAD/currency exposure,
   canonical ledger views, human decisions and manual theses.
7. **Learning governance:** proposals, source candidates, champion/challenger,
   promotion gates, calibration/effective-sample dashboard.
8. **Product UI:** Today, Decision/Research/Timeline, Journal, Experiments,
   Operations, catch-up brief, focused mobile views.
9. **AWS operations:** ECR/OIDC deployment, EC2, HTTPS, SSM/KMS, WAL/S3,
   recovery drill, external alarms, hardening and runbooks.

Live broker execution is not an implementation slice in this map.

---

## 7. Subscription and account plan

### Required to begin

| Account/service | Purpose | Cost posture |
|---|---|---|
| Anthropic API | Structured synthesis, web search, experiment challengers | Pay as used; separate from Claude chat subscriptions. Current web search is $10/1,000 searches plus model tokens. Enforce hard caps. |
| OANDA v20 practice | Bid/ask candles, prices, spreads, later practice reconciliation | Free demo/practice account and API token; no live funding required. |
| AWS | EC2, EBS, S3, KMS, Systems Manager, CloudWatch/SNS, ECR, DNS/certificate path | Outside the CA$50–100 data budget; estimate with AWS Calculator before deployment. |
| GitHub | CI, immutable images/deployment workflow | Existing account likely sufficient initially; usage depends on repository/Actions plan. |

A Claude Pro/Max subscription is **not required by the application**. It may
still be useful personally. TradingView and Feedly are **not required** for v1.

### Free official data core

- Bank of Canada Valet;
- Statistics Canada/open.canada.ca datasets with explicit licences;
- FRED/ALFRED and official US release agencies;
- ECB/Eurostat;
- Bank of England/ONS;
- official central-bank, finance-ministry, and government releases;
- permitted RSS feeds and approved social-account metadata.

### Likely first paid data subscription

Reserve up to **CA$50–100/month** for a structured economic-calendar and
point-in-time macro provider. Trial before purchase. Trading Economics is a
candidate, not a preselected dependency.

The trial must verify:

- Canada, US, euro-area, and UK events;
- UTC timestamps, revisions, consensus/previous/actual values;
- point-in-time snapshots and historical availability;
- API reliability, quotas, retention, attribution, and LLM-processing terms;
- export and deletion requirements;
- cost at the intended cadence.

### Optional only after demonstrated gap

| Option | Add only when |
|---|---|
| X API pay-per-use | Selected approved accounts materially require direct post retrieval. |
| NewsAPI/Feedly/commercial news | Public RSS and Anthropic discovery have measurable coverage/deduplication failures. |
| NYT/WSJ/FT/Medium consumer plans | They provide personal reading value; consumer access is not treated as an automation licence. |
| Cross-asset market vendor | Free/official sources cannot meet freshness or licensing needs for the focused macro basket. |
| Local model compute | Restricted sources require local inference or a controlled challenger warrants it. |

### Cost reporting

Report three budgets separately:

1. **Paid data/publications:** target CA$50–100/month.
2. **Anthropic:** token/search/cache/tool usage by job and forecast.
3. **AWS:** EC2, public IPv4, EBS/snapshots, S3/WAL, KMS, ECR,
   CloudWatch/log retention, DNS, and egress.

---

## 8. Facts to confirm before implementation reaches affected slices

These are map entries, not permission for a builder to guess:

- Exact five-day probability event and neutral-band definition.
- Exact OANDA Canada practice-account availability and account instrument list
  for the owner.
- Initial Anthropic model snapshot and maximum per-run/daily/monthly spend.
- Exact EC2 region, domain/DNS ownership, permitted source CIDRs, and SNS email.
- Exact economic-calendar trial candidates and their current terms.
- Source-by-source retention and external-model permissions.
- Historical financing availability and sensitivity ranges.
- Stabilization delay and material probability-change threshold.
- FX holiday/session calendar library and OANDA candle alignment fixtures.
- RPO/RTO restore-drill acceptance environment.

---

## 9. First-slice acceptance criteria

Before adding broad news or LLM forecasting, the foundation/market-truth slice
must demonstrate:

1. One documented command starts the local stack in a fresh orb.
2. Authentication, migrations, web, scheduler, worker, and PostgreSQL pass
   automated checks.
3. USD/CAD, GBP/USD, EUR/GBP, and EUR/USD daily/H4 bid/ask data ingest with
   explicit alignment, smoothing, completeness, pagination, and manifests.
4. Dataset quality tests detect injected gaps, duplicates, impossible candles,
   and timezone errors.
5. Technical levels are deterministic and reproduced from a frozen fixture.
6. No recommendation can reference an incomplete candle or execute at its own
   information cutoff.
7. Source, job, cost, and audit records are append-only and idempotent.
8. The initial Today/Pair/Operations skeleton reflects the approved information
   architecture, without treating the planning mock as final visual design.

---

## 10. Archived first-slice implementation prompt

```text
Begin the first implementation slice described in docs/project-map.md.

Treat the map as the source of truth. Implement only the Foundation and Market
Truth scope: a Python/Django monolith with PostgreSQL, separate scheduler/worker
processes, local Docker Compose, single-user auth foundations, source registry,
canonical instrument/time/currency types, append-only audit primitives, and
OANDA daily/H4 bid-ask ingestion with explicit New York alignment, smooth=false,
complete-candle enforcement, pagination, manifests, quality validation, and the
approved minimal deterministic technicals. Add a basic Today/Pair/Operations UI
skeleton using invented or fixture data.

Do not add Anthropic forecasting, broad web ingestion, paid providers, paper
positions, live execution, or AWS deployment in this slice. Do not invent any
item marked OPEN. If an exact fact in “Facts to confirm” blocks this slice,
surface the smallest focused decision before coding that part.

Update .agents/setup and .agents/resume for the chosen dependencies, verify them
twice/once as required, run targeted and full relevant checks, and leave the
repository in an owner-operable documented state. Do not deploy or push without
explicit approval.
```

---

## 11. Definition of planning completion

The quadrant walk is complete and the first two implementation slices are now
present in the repository. During implementation, discoveries update this map
rather than being silently absorbed into code or lost in conversation history.
The current next-agent prompt lives in `docs/handoff.md`.
