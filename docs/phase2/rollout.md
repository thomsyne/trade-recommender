# Phase 2: twelve-pair live data acquisition

This code supports prospective FX research data collection. It does not establish
predictive skill, trading readiness, improved performance, or portfolio diversification.
The data universe has fewer USD-only relationships; future currency-level risk
aggregation is still required before any trading expansion.

## Registry and eligibility

| Order | Code | Base | Quote | Decision enabled | Ingestion enabled after migration/initial seed |
|---|---|---|---|---|---|
| 1 | EUR_USD | EUR | USD | yes | yes |
| 2 | GBP_USD | GBP | USD | yes | yes |
| 3 | EUR_GBP | EUR | GBP | yes | yes |
| 4 | USD_CAD | USD | CAD | yes | yes |
| 5 | USD_JPY | USD | JPY | no | yes |
| 6 | AUD_USD | AUD | USD | no | yes |
| 7 | USD_CHF | USD | CHF | no | yes |
| 8 | NZD_USD | NZD | USD | no | yes |
| 9 | EUR_JPY | EUR | JPY | no | yes |
| 10 | GBP_JPY | GBP | JPY | no | yes |
| 11 | AUD_JPY | AUD | JPY | no | yes |
| 12 | AUD_CAD | AUD | CAD | no | yes |

`active` owns decision eligibility. `ingestion_enabled` permits live collection,
independently of `active`. Unknown newly created rows default ingestion-disabled.
Migration 0030 preserves existing identities and active values and enables existing
canonical or active rows; it creates no instruments, jobs, occurrences or evidence.
`seed_canonical` creates missing canonical rows and 48 candle jobs, preserves existing
collection disables and next-run times, and repairs canonical metadata/parameters.
It creates no development users, fixtures, candles, or model outputs.

The eight rows with decision `no` are ingestion-only. Allowed artifacts are bid/ask
candles, immutable observation revisions/conflicts, deterministic technical snapshots,
request provenance, terms and operational diagnostics. Each live HTTP observation
records its UTC retrieval instant and provider RequestID (empty if unavailable), so a
new fetch of an identical window can record A→B→A changes. Replaying the same persisted
manifest remains idempotent. Recommendation and pair-evidence
batches still enumerate exactly the four active pairs. Direct decision creation rejects
inactive instruments. Ingestion invokes resolution, paper and review work only for an
active instrument, rechecked after the fetch. No prompts, recommendation schedules,
model identity, mechanical strategies, portfolio policy or paper policy are expanded.
Model-provider call volume is unchanged: no new model calls are introduced.
OANDA candle request volume increases as estimated below.

The frozen six-pair failed-break historical universe, acquisition manifests, terminal
binders and archived evidence remain unchanged. This Boolean does not govern historical
acquisition. NAS100 evidence remains separate negative research. No records are rewritten.

## Schedule and capacity assumptions

Supported granularities are H1 (3,600 seconds), H4 (14,400), D (86,400), W (604,800).
M15 and M1 are deferred to a separately authorized phase covering API cadence, storage,
completion rules and strategy use. Multi-timeframe market structure, buyer/seller
behavior, setup detection and abstention are future work; no such strategy exists here.

There are 48 canonical candle jobs: 24 new identities relative to the old six-row
registry, and 32 newly enabled jobs relative to its four enabled pairs. Each enabled
pair polls 24 + 6 + 1 + 1/7 = 31.143 times per calendar day, including weekends.
Twelve pairs yield approximately 373.714 runs/day, versus 124.6 before: +249.143/day. The existing
hourly terms job stays 24 runs/day (two HTTP requests/run), with a larger instrument
payload. Newly created jobs use slot `(display_order-1)*4 + granularity_index`, with
initial delay `60*(slot+1) + 3600*floor((interval-3600)*(slot+1)/(49*3600))` seconds.
Distinct minute phases within the hour prevent cross-granularity initial collisions. Thus all new jobs are
spread within one interval; reseeding does not move existing timestamps. Canonical live jobs require latest-only recovery. Reseeding repairs policy drift
to latest without moving existing deadlines; the read-only report rejects drift.
The scheduler retains one latest occurrence per overdue job and unique occurrence keys.
After downtime, up to 48 candle jobs can still be immediately due; staggering does not
promise a burst-free recovery. Retries use the existing bounded attempts/backoff, and
one failed occurrence does not prevent other jobs being claimed. Monitor queue latency.

Existing default windows remain H1/H4: 14 calendar days; D: 90 days; W: 730 days.
Approximate upper bounds per initial instrument poll are 336/84/90/105 candles
respectively (about 240/60/64/104 allowing FX weekends). All fit within the existing
4,999-interval page window and normally require one request each. No extra backfill
is added. Every later poll still refetches its whole default window; capacity must
budget repeated payloads, not just new candles. Eight pairs add roughly 69,384
returned candle records/calendar day at calendar upper bounds, or roughly 50,000
with ordinary FX closures. Twelve pairs total roughly 104,076 upper-bound records/day.
This is approximately 250 extra candle HTTP calls/day before retries. Terms add no
new call cadence. Initial 32-poll onboarding transfers approximately 4,920 candle
records across eight pairs, distributed over their initial stagger windows.

Ordinary new unique intervals across eight pairs grow by roughly 1,248/week
(120 H1 + 30 H4 + 5 D + 1 W per pair), or 178/day averaged over the week.
Each unique interval also has an initial observation; revisions add observations
without replacing old evidence. Approximately 7,475 extra ingestion runs, manifests
(stored as live run parameters), job occurrences and success audits accrue per
30-day month, plus failures/conflict audits. Technical snapshot growth is bounded by
new source sets under existing snapshot deduplication. At illustrative 2–8 KiB per
run/manifest/audit/occurrence group, operational metadata adds 15–60 MiB/month; at
2–8 KiB per candle+observation+indexes, ordinary new candle evidence adds 10–42 MiB/month.
Technicals, revisions, WAL, backups, indexes and table bloat are additional. These are
planning assumptions, not measured storage guarantees. Repeated payload parsing and
snapshot calculation can dominate CPU/memory despite modest final row counts.
Technical-snapshot computation currently may load the full stored series, so its
cost and peak process RSS must be measured as accumulated history grows.

At a measured 1–10 seconds/run, added worker duty is 4–42 minutes/day, potentially
higher on the small instance or during provider latency. The largest default H1 page
is a few hundred rows per instrument, not an in-memory twelve-pair aggregate. Observe
actual peak RSS, free memory/swap, worker duration p95/p99, queue wait, HTTP latency,
429/5xx and retries, database/WAL/backup growth and free disk before expanding waves.
Unit tests cannot demonstrate production capacity.

## Read-only diagnostics

Run `python manage.py report_fx_onboarding` in the separately authorized environment.
It emits bounded JSON for 8 × 4 series, with registry eligibility, schedule identity,
enabled state, interval, next/last occurrence, latest successful ingestion and complete
interval, candle count, freshness, failures/quarantine, revisions/conflicts, technical
availability and forbidden artifact counts. It never prints raw responses or tokens.
Registry/schedule or ingestion-only integrity violations exit nonzero. Missing/stale
collection is reported per series without pretending overall data readiness.

States: `not_yet_ingested` means no live candle; `fresh` means the existing FX calendar
and poll grace are satisfied; `stale` means a completed interval is overdue;
`failed` reflects a failed live run or latest failed job; `quarantined` reflects the
latest quarantined run; `disabled` takes priority when collection is disabled. Separate
freshness and failure counts remain visible in disabled state. There is no invented
holiday calendar: apparent holiday gaps require operator investigation. A `revision`
records changed provider content; a `conflict` records a change to evidence already
referenced outside market data. Inspect lineage, never overwrite the frozen candle.
A→B→A remains a three-observation history. Quarantine/failure requires diagnosis, not
deleting/replacing evidence or declaring the whole wave healthy.

Other read-only checks: `python manage.py check`,
`python manage.py showmigrations market`, `python manage.py makemigrations --check --dry-run`,
and the onboarding report. Do not run seed as a read-only verification command.

## Later production rollout — NOT executed or authorized

Deployment, production access and each activation require separate owner approval.
Before deployment/seed, pause scheduler and worker dispatch under the approved operating
procedure. Because seeding with a configured OANDA token enables eligible jobs, stage
all eight onboarding instruments as `ingestion_enabled=False` and their 32 schedules
as `enabled=False` before resuming dispatch. Review the report and original four jobs.
Do not accidentally start all eight by merely running seed with production credentials.
No activation command in this document has been executed.

For an approved wave, set only that wave's `ingestion_enabled=True`, keep `active=False`,
and enable its four canonical schedules per instrument, preserving or deliberately
reviewing overdue deadlines. Confirm OANDA source/token availability through the existing
approved secret mechanism without printing values. Existing job disables may be reset
by reseeding: use ingestion disable as the persistent per-instrument rollback control.

1. USD_JPY and AUD_USD.
2. USD_CHF and NZD_USD.
3. EUR_JPY and GBP_JPY.
4. AUD_JPY and AUD_CAD.

For every wave, require initial H1/H4/D/W success, 17:00 New York daily/Friday weekly
alignment (DST cases validated in tests and checked at actual transitions), no unexpected
gaps outside registered closures, no unexplained conflict/quarantine growth, bounded
worker duration and queue latency, acceptable API/error rates, memory and disk headroom,
and zero pair evidence, forecasts, recommendations, sizing, portfolio membership,
paper lifecycle and review records for that wave. Observe at least seven calendar days
including a completed W candle and weekend boundary before the next wave. DST rollover
remains an additional pending seasonal observation if the wave does not span a transition.
Thresholds for worker/API/disk alerts must be agreed from the existing instance baseline
before the first wave; no unit-test threshold is a production acceptance claim.

Rollback: disable affected schedules and set affected instruments' `ingestion_enabled=False`.
Queued tasks recheck eligibility before provider access. Stop dispatch/drain in-flight
fetches if an immediate cutover is needed; a fetch already started cannot be recalled.
Keep `active=False`. Preserve all candles, revisions, manifests, audits, jobs and occurrences.
Use exact schedule names in the report for failure recovery; do not delete evidence or
reset all jobs. Recheck the report and previous waves before any restart.

Runtime PostgreSQL superuser and migration 0027 fresh-test bootstrap are accepted/deferred
Phase 1 exceptions. This phase does not change either. No production schedules, model
strategies, notifications or trades have been activated by this implementation.


## Independent-review remediation: window, coverage and schedule integrity

Live defaults and explicit `from` values are floored deterministically **before** the
HTTP request and persistence to the existing registered interval grid. H1 is hourly
UTC; H4 uses the exact UTC instants admitted by the authoritative New York session
grid (including the existing DST shift). D uses Sunday–Thursday 17:00 New York;
W uses Friday 17:00 New York. `to` remains the caller/current aware instant; only
candles completing by that end are admitted. Leading out-of-window candles are
filtered before storage; migration0029's lineage constraints are unchanged. Later
pages start at the last accepted candle with `includeFirst=false`; an empty page
has no accepted boundary and its next request uses `includeFirst=true`. Neither
path skips the first unobserved boundary. Canonicalizing a start may add up to one
interval to the approximate default-window payload estimates above.

The report separately exposes registry eligibility, effective collection availability,
latest-candle freshness, requested-window coverage, technical-snapshot availability,
and forbidden artifacts. Availability requires the source, token/configuration and
canonical schedule, as well as instrument eligibility. Deliberately disabled schedules
remain disabled, with a distinct reason; missing/duplicate/drifted schedules fail
integrity. A recent candle or a technical snapshot is not coverage evidence.

Coverage compares the latest successful OANDA run's attested window with registered
complete intervals, observed source keys available by that run's finish, and that
run's returned count. Previously stored overlap cannot conceal a partial response.
Output gives expected/observed/returned/missing counts and up to five missing keys.
The calendar permits registered weekends and New York DST; no holiday closure is
invented. Expansion is bounded to100,000 expected intervals; larger requests report
an integrity violation rather than doing unbounded work. It does not change live
acquisition defaults or frozen historical acquisition contracts.

`state` distinguishes `disabled`, `unavailable`, `not_yet_ingested`, `partial`, `fresh`,
`stale`, `failed`, `quarantined`, `revised`, `conflicted`, and `integrity_violation`.
Freshness and coverage remain separate fields even when a higher-priority state is
shown. Failures/quarantine and revisions/conflicts have separate counts. Missing
technical snapshots are explicitly false, never inferred from freshness or coverage.
Integrity violations, incomplete requested coverage, forbidden artifacts, duplicate
semantic jobs, bad intervals/parameters/tasks, non-latest recovery, unavailable-but-
enabled schedules, and simultaneous enabled deadlines return nonzero. Intentionally
disabled schedules and missing credentials alone are operational states, not evidence
corruption. Do not treat exit0 as wave acceptance; inspect every series and gate.

The schedule identity is `(market.ingest_oanda, canonical instrument, granularity)`,
not its label. Both enabled and disabled aliases are rejected. Reseeding refuses
ambiguous semantic duplicates transactionally and leaves all rows unchanged; an
operator must authorize correction, preserving occurrence/evidence history. Ordinary
unambiguous canonical metadata/policy repairs remain idempotent and preserve deadlines.
The report never repairs rows. It diagnoses exact deadline collisions without inventing
an initial phase anchor for pre-existing schedules or silently resetting their cadence.

The direct `ingest_oanda` command derives its twelve codes and exactly H1/H4/D/W from
the domain definitions. It still goes through the authoritative task eligibility and
isolation boundary. These documentation commands confer no production access or
activation permission.
