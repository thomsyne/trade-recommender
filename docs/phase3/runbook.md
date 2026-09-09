# Phase 3 operator runbook

This branch supplies a prospective foundation. It does not authorize promotion,
production activation, historical reassignment, a provider change or deployment.
Keep the existing four instruments, prompt/output schema, costs and setup rules.

## Local installation and prospective cutover

Use an explicitly named UTF8 disposable PostgreSQL database and explicit host,
port, database and user for every Django command, including checks. Apply normal
migrations. The repository's documented market0027 fake accommodation is the only
permitted exception; never disable triggers or fake Phase3 migrations.
Forecast migrations0018–0025 add nullable legacy links and prospective constraints;
preflight rejects contradictory v4 rows atomically. Do not repair historical rows
into prospective-looking records. Legacy unpaired and unadjudicated populations
are expected classifications, not backfill instructions.

`python manage.py register_phase3 --starts-at <future-aware-ISO-timestamp>` is a
read-only registration preview. An owner-authorized operator can add `--register`
to record the new v4 method/era and evaluation policy v2. It neither calls the
provider nor enables schedules. Registration must precede prospective issuance;
old-era recommendations never become v4 samples. Cutover timestamps cannot be
retrospective.

The canonical seed creates four disabled `forecast.reconcile_target_lifecycle`
jobs with staggered hourly UTC phases. Enablement is a separate owner/operator
decision after local validation. Inspect `report_phase3_integrity` first. Existing
ingestion deadlines and enabled flags remain unchanged. D/H1 successful ingestion
and the dedicated reconciliation task share target/control/lifecycle ownership.
The reconciliation task performs no model call or budget reservation; independent
steps retry target resolution, control creation, model resolution, lifecycle,
paper execution and health assessment. A failed step raises a bounded static
error while later steps still receive an attempt.

Before a model call, require the current exact frozen control, compatible target
contract and active registered era. Missing/incompatible controls block issuance
before budget reservation. Reconciliation may produce the needed control. It must
never attach a later control to an already-issued model prediction.

## Integrity and owner operations

`python manage.py report_phase3_integrity` prints bounded JSON with static codes,
identifiers, counts and a separate legacy section. It is read-only and exits
nonzero for prospective violations. Preserve its output; investigate ownership
before considering a new prospective event. Do not mutate immutable evidence.
Use explicit cutoffs supported by the command to audit historical assessments.

Owner decisions last no more than24hours and no later than target expiry. A price
trigger closes an unselected decision. A newer materially different target closes
the whole overlapping older cohort and all its owner-pending members. The inbox
shows closed decisions; retries of an identical final selection are idempotent.
Selection rechecks current exposure under the portfolio guard. Entry requires a
live admitted lifecycle state and observed H1 evidence. No confidence ranking or
larger exposure limit is introduced.

The ledger, dashboard, market detail, exposure and review projections share the
canonical state. Legacy absent entry/result is `legacy_unadjudicated`, never proof
of waiting. Missing observation and proven nonactivation are distinct. Evaluation
reports raw rows, distinct targets, mature/immature, scored/missing/cancelled,
paired controls, directional/abstention and execution populations separately.
Only distinct mature targets form coverage; repeated rows cannot buy readiness.

## Regression fixture interpretation

Existing tests now explicitly freeze decision clocks, register v4 fixture eras,
issue controls before models and use separate synthetic policy activations. Legacy
experiment fixtures explicitly remain v3. No base fixture was copied from this
branch. The revised-candle-during-provider test now expects a conflict because the
already-frozen prospective control cannot match a rewritten reference. Paper tests
observe H1 evidence before expiry; interpretation tests reconcile deterministic
closure before review. Owner selection is final for v4, including an empty choice.
The unchanged base has nine failures in the affected command; branch corrections
retain those assertions except where the explicit v4 lifecycle contract changes
the expected state. Full logs and individual failure identities are retained in
the engineer artifact directory named in the handoff.

## Non-goals and activation boundary

Existing evidence does not establish predictive skill. Existing paper results do
not establish profitability. Mechanical controls begin prospectively only after
separately authorized activation; historical recommendations remain unpaired.
Missing controls block paired claims. No strategy/model learning was added. New
Phase2 pairs remain ingestion-only. No active production policy changes
automatically. Deployment, schedule activation and provider spend each require
separate owner approval; this runbook is not that approval.
