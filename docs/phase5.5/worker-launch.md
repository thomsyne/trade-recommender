# Isolated EC2 run: in progress, not review-ready

The owner approved creation, private development-data/code transfer and execution,
then extended the budget to 72 hours with progress checks every 24 hours. No
production application deployment, recommendation, provider request, order or
trade is authorized by this run. No historical holdout release is authorized.

## Current run

- Instance `i-06a84e1ebe6467381`, AWS account `590759815902`, `us-east-1`.
- On-Demand `m7i.2xlarge`, encrypted retained 100-GiB gp3, isolated VPC and role.
- Private bucket: `phase55-validation-590759815902-20260911132955760100000001`.
- Registration 6: `c64f5731ea8d0e77a9d6ae4889eaffec8135288881e75d039a58d30c7a566237`.
- Started **2026-09-11T14:08:19Z**; maximum ends **2026-09-14T14:08:19Z**.
- Amp progress checks: September 12, 13 and 14 at 14:09 UTC (10:09 Toronto).
  Stop monitoring earlier on a terminal outcome. The remote run/runtime cap do
  not depend on the Mac; Amp's inspection still needs a connected executor.
- Compute at USD 0.4032/hour: USD 29.0304 for the full 72 hours, plus storage,
  IPv4/S3/transfer charges. Retained storage remains billable after compute stops.

The scientific `phase55-batch.service` runs four disjoint groups, unprivileged,
with network denied, private temporary storage and read-only code/input. Each
group has its own immutable catalog. Completion/failure/timeout invokes the
separate preservation service, which archives idle outputs to the private bucket
and powers off after successful transfer. A transfer failure leaves the retained
instance/volume for recovery. No unit is enabled for automatic boot replay.

## Immutable evidence and verification

The input is a new development-only projection, never a backup of the acquisition
database. It contains 2,136 warm-up/development price chunks and 456 sealed
metadata-only chunks with NULL blobs. No sealed prices were copied or decoded.
Projection SHA-256 is `3b123b30d63e50dde064f7ca5f5afa504fa227a104ee1cdd1109ef2d3f7eaa27`;
the original audit digest and all original acquisition timestamps are unchanged.

Source checkpoint [1db619f](https://github.com/thomsyne/trade-recommender/commit/1db619f03ed9bdd8553c325a3e9d26e74fed1d34)
and registration freeze [eda52d7](https://github.com/thomsyne/trade-recommender/commit/eda52d784e533c26d080f65a5989718ebcf83654) precede revision-6
outcome calculations. The actual Linux runtime has Python 3.11.16 and unchanged
scientific package versions/timezone hashes. Revision 6 changes only explicit
revision, predecessor and source bindings from revision 5; all scientific fields
and the runtime are identical. Prior definitions, migrations and registrations
are preserved. Nothing was pushed or merged.

Mac and actual Linux sandbox: 66 focused tests, 60 passed, six DB skips. The
service startup probe verifies denied network/code writes, private temporary
files, and real arch/scipy.stats imports. A fixed 32-day, two-strategy EUR_USD
check matched all 64 Mac-reference checkpoints' decisions, costs, outcomes and
end states and passed cold-resume idempotency. Its evidence identity is
`8a45f4bc4015d938011fa6e98b439024d28b9173fb30bfe3eb2cdd4f66c0510d`.
This is sample verification, not full-population equivalence or acceptance.

The inherited PG15/PG17 focused results were 116 passed each before the worker
migration. No shared SQL, migrations or production consumers changed here; no
additional PG run was performed for host-only execution changes. The earlier
full PG17 suite remains 1,580 tests with two errors, not a pass. See
`correction-verification.md` for those limitations.

## Preserve the failed revision-5 startup honestly

Revision 5 started at 13:49:13Z but its ORB worker later failed when SciPy could
not create a temporary diagnostic stream. Other groups' progress did not make
that run complete. All workers were stopped and their source/catalogs/logs kept
at `/var/lib/phase55/work-v5-partial`. The private manual archive is
`outputs/revision5-partial/development.tar.gz`, SHA-256
`9baaa50ddc3159b4da69fe3499e0e32c3f31725a28c3592fad40e780cac86347`.
The preservation service also archived under `outputs/20260911T135302Z/` and
stopped compute; the same instance was restarted for revision 6. Neither partial
archive is the current run or a scientific pass. Earlier missing-test-dependency
and sandbox errno-expectation failures are retained in revision-5 logs.

## Inspection and eventual handoff

Read EC2 state and S3 first. While running, use SSM for service/group-log and
checkpoint-coverage inspection only. Current files live under
`/var/lib/phase55/work/.candidate-data/phase55-v1`: `worker-0.sqlite3` through
`worker-3.sqlite3`, `group-*.log`, completion markers and `reports-v6/`. Do not
mix these with the old partial run or the Mac revision-3/4 catalogs. Each final
archive includes service status; absence of a complete 975-report/75-aggregate
grid is incomplete, regardless of any process's exit status.

Once stopped, verify archive/checksum before inspecting private outputs. Preserve
all unavailable and losing outcomes. Reconcile the complete registration-bound
grid and development proposal, with semantic verification rather than hashes
alone, before returning the full correction handoff to the coordinator. Until
then this remains **in progress, not pre-release review-ready**. Missing financing,
exceptional-session/event vintages, macro, range and carry evidence still block
the applicable evaluations/retention. No holdout price access is permitted.
