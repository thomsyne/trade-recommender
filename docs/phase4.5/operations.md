# Local operational envelope and deployment gates

Status: engineering evidence for independent review, not production capacity
certification. No scheduler, provider acquisition or decision consumer is added.

## Reproducible probe

Run `manage.py test market.tests.phase45_benchmark --noinput` on an otherwise idle,
disposable exact-version PostgreSQL cluster with pgcrypto. Use cleared environment
credentials and a test role with CREATEDB/CREATEROLE. Do not point this at an
existing database. PostgreSQL 15.14 and 17.6 were built with OpenSSL; both use
Python 3.11.4 / Django 5.2.17, macOS, x86_64 processes on a 10-core Apple M1 Pro,
16 GiB host RAM. Each measured PostgreSQL cluster was idle apart from its probe;
other-version tests could run on the same host. This is not the deployed ARM
t4g.small's performance or a host-isolated benchmark.

The fixture writes 5,620 synthetic, quarantine-source observations through normal
live ingestion: M15 2,000; H1 1,200; H4 600; D 1,300; W 520. Daily history spans
about five years and weekly history ten years; every series exceeds its descriptor
lookback. Prices and counts are deterministic; timestamps are relative to the
run date so the finite selection window remains exercised on later reruns. Real
system recording stays enabled. This is **not accepted acquisition evidence**.

The probe creates a five-granularity snapshot, checks semantic integrity, captures
ORM query count and one `EXPLAIN (ANALYZE, BUFFERS)` selection plan, races four
writers on a new identity, then drains eight cutoffs with a connection interruption
halfway through. Exactly one writer creates the raced identity; the drain leaves
eight identities with no integrity violations. This tests reconnect/idempotency,
not an OS crash or durable queue redelivery after a database crash.

After its tests completed, each task-owned server was cleanly stopped and restarted.
Exact recorder/catalog and row/sequence fingerprints of both the fresh-head database
and genuine restored database remained identical on 15.14 and 17.6. This additionally
proves clean-restart persistence, not crash recovery or production queue recovery.

RSS is Python's process peak and one PostgreSQL backend sample after reconnect,
not a summed server peak. WAL is the cluster-wide insert-LSN delta, including the
probe's ingestion and audit writes but excluding test-schema installation. Storage
is heap, indexes and TOAST for observation/snapshot tables only. It excludes other
ledgers, WAL retention, backups, replicas, filesystem overhead and deployment logs.
Do not extrapolate these numbers linearly into a production capacity promise.

## Both exact versions meet the local envelope

| Measurement | PostgreSQL 15.14 | PostgreSQL 17.6 |
|---|---:|---:|
| Ingest 5,620 observations | 6.039 s (931/s) | 5.680 s (989/s) |
| First snapshot | 2.779 s / 43 queries | 2.858 s / 43 queries |
| Four-writer new-identity race | 5.234 s / one identity | 5.409 s / one identity |
| Eight-cutoff drain | 18.519 s (0.432/s) | 18.790 s (0.426/s) |
| Peak Python RSS | 135,118,848 B | 148,430,848 B |
| Sampled backend RSS | 44,597,248 B | 45,318,144 B |
| WAL inserted | 11,353,904 B | 11,518,784 B |
| M15 selection execution | 0.569 ms | 0.572 ms |

Both M15 plans use `candle_obs_series_rev_idx`, bitmap heap scan, in-memory sort,
Unique and Limit: 500 returned rows, 43 shared buffer hits, zero temporary blocks
written. No unbounded Python history materialization was introduced. Timing is
observational, not a stable microbenchmark guarantee. The following storage
measurements are identical on both versions:

| Table / bytes | Heap before → after | Indexes before → after | TOAST before → after |
|---|---:|---:|---:|
| Observation | 0 → 1,589,248 | 73,728 → 1,425,408 | 8,192 → 8,192 |
| Snapshot | 0 → 8,192 | 49,152 → 98,304 | 8,192 → 1,302,528 |

## Thresholds are release gates, not newly installed monitoring

These are deliberately bounded acceptance limits for this fixture and proposed
initial deployment alerts. They are not permissions to run the dormant consumer.
The benchmark asserts its numerical limits; operations must implement and rehearse
alerts separately before a rollout. A breach fails certification; do not increase
a limit solely to obtain a green run.

| Measure | Local fixture acceptance | Deployment alert and failure response |
|---|---|---|
| First snapshot | ≤200 queries, <30 s | Warn above 100 queries or p95 15 s; stop new scheduling at 200 queries or p95 30 s pending plan/input review |
| Input selection | One query; ≤pinned lookback | Investigate changed index/plan or disk sort; refuse unbounded scope/history rather than dropping provenance |
| Writer synchronization | Four writers finish <120 s, one identity | Warn on lock wait >15 s; bound caller wait to 120 s, retry the same identity; any duplicate/divergent identity is a stop-the-line integrity failure |
| Python memory | Peak <1 GiB | Warn at 768 MiB, stop admitting new work at 1 GiB; measure deployment process/cgroup peaks before sizing |
| PostgreSQL memory | Sampled backend <256 MiB | Warn sampled backend >192 MiB; >256 MiB blocks certification; also require deployment-wide peak measurement |
| WAL | <512 MiB for whole fixture | Warn >256 MiB per comparable batch; >512 MiB fails; monitor retained WAL separately, pause new work before exhausting disk |
| Selected storage | <128 MiB after fixture | Warn >64 MiB; >128 MiB fails; forecast whole-database retention and backup growth separately |
| Backlog/reconnect | Eight cutoffs <240 s, no duplicates | Warn age >120 s or >4 queued; >240 s or >8 blocks new admission pending recovery; never relabel late evidence as on-time |
| Integrity | Zero violations | Quarantine affected output and stop dependent consumption; retain evidence, never SQL-repair it |
| Calendar | Exact profile/version, known-at and complete interval attestation | Any missing coverage is unavailable immediately; no grace period or weekday fallback authorizes readiness |

Before deployment, size these limits using the genuine accepted restore, actual
pair count, revision density, retention, concurrent ingestion, research/event
vintages and deployment CPU/memory/storage. Rehearse crash/restart, durable queue
redelivery, long outages, WAL retention and disk-pressure behavior. Those scenarios
remain deployment gates, not inferred successes from this local probe.

## Exceptional-session provenance and fail-closed boundary

The offline `calendar_policy` module does not modify frozen `ny-fx-week-v1`, Phase4
hashes, ingestion, eligibility, scheduler behavior or technical calculations.
An explicit reviewed `CalendarAttestation` supplies profile, version, source URL,
known-at, open intervals and closed intervals. Missing/profile-mismatched/later-known
attestation yields unavailable. A closed interval yields closed; partial overlap
yields irregular. Half-open boundaries permit an interval ending at closure or
starting at reopening, but require separate open coverage to attest it as open.

Source-backed fixture: [OANDA US holiday hours](https://www.oanda.com/us-en/trading/holiday-trading-hours),
Christmas 2025 FX close December 24 16:59 Eastern and reopen December 25 17:05
Eastern (21:59 and 22:05 UTC respectively). Local fixture version:
`us-fx-christmas-2025-reviewed-2026-09-10`; knowledge cutoff September 10, 2026
14:00 UTC deliberately does not attest historical availability in December 2025.
The fixture attests only this US-profile closure, not all surrounding open hours.
It is neither a Canadian-entity attestation nor universal FX exchange hours.
Only public documentation was consulted; no provider API acquisition occurred.

Five tests cover absent/other-profile attestation, closure, irregular partial
sessions, exact close/reopen boundaries, later knowledge and bounded explicit
open coverage. A deployment must supply its own reviewed entity/instrument profile
and source revision. Absence of an exception is not evidence that a session opened.
