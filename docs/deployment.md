# Private AWS research deployment

## Shape and cost boundary

Slice 6 runs one ARM `t4g.small` in `us-east-1` with a 25 GB encrypted gp3
root volume, an attached Elastic IP, and Docker Compose. Caddy terminates TLS
for `fx-forecast.thomsyne.dev`; Terraform manages an A record in the owner's
existing public Route 53 hosted zone. Only 80/443 enter the host by default;
port 22 exists only for explicitly configured narrow key-only SSH CIDRs, and
Internet-wide SSH CIDRs are rejected by Terraform validation unless a
documented break-glass flag is set. SSM Session Manager is the administration
and recovery path. PostgreSQL, web, worker, scheduler, backup, and Caddy
containers all restart unless stopped. There is no load balancer, NAT gateway,
RDS, Secrets Manager, a new hosted zone, Tailscale, extra EBS volume, or paid
monitoring.

At typical us-east-1 on-demand rates, budget roughly US$18–22/month: about $12
for compute, $2 for gp3, $3.65 for the public IPv4 address, and low single
dollars or cents for ECR/S3, transfer, and requests. Verify current AWS pricing
before enabling the workflow. The deployment adds one low-query Route 53 A
record to the already-owned `thomsyne.dev` zone; existing hosted-zone charges
and negligible DNS query charges are not included above. The app remains
paper/research-only and is not an order execution system.

## Repository configuration

Create these GitHub Actions secrets:

- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`: a dedicated deployment IAM
  user's keys. Do not use account root keys or `AdministratorAccess`. Generate
  and attach the repository's complete scoped policy as described in
  [Dedicated deployment user](#dedicated-deployment-user). It includes the
  first-run state-bucket bootstrap; no separate Route 53 policy is needed.
- `PRODUCTION_ENV`: multiline dotenv content. It is written to one encrypted SSM
  `SecureString`, never Terraform state or the image. Do not add deployment-owned
  values such as `IMAGE_URI`, `PUBLIC_URL`, `DJANGO_ALLOWED_HOSTS`, `ACME_EMAIL`,
  or `BACKUP_BUCKET`. Required minimum:

  ```dotenv
  DJANGO_SECRET_KEY=<at-least-50-random-characters>
  POSTGRES_DB=trade_recommender
  POSTGRES_USER=trade_recommender
  POSTGRES_PASSWORD=<long-random-value>
  ```

  Add OANDA, Anthropic, EODHD, and email values only when those governed features
  are enabled. Use dotenv-safe values (quote values containing whitespace or `#`).

Repository variables:

- `ROUTE53_ZONE_ID` (**required**): the explicit ID of the existing public
  hosted zone authoritative for `thomsyne.dev`. Using the ID avoids selecting a
  similarly named private or duplicate zone.
- `ACME_EMAIL` (**required**): a non-secret owner email for Caddy certificate
  notices. It is appended to the host dotenv file by deployment and does not
  belong in `PRODUCTION_ENV`.
- `SSH_PUBLIC_KEY`: the owner's **public** key. Omit on a *new* deployment to
  create no key pair. On the existing instance keep it unchanged: `key_name`
  is immutable on EC2, so changing it would force instance replacement, which
  `prevent_destroy` blocks. Removing SSH *access* is done through the security
  group (`SSH_CIDRS_JSON`), not the key.
- `SSH_CIDRS_JSON`: JSON such as `["203.0.113.10/32"]`. It defaults to `[]`,
  which creates no port-22 ingress at all. Every entry must have a prefix
  length of `/8` or longer (parsed numerically, so `/00` counts as `/0`);
  Internet-scale entries (`0.0.0.0/0`, `::/0`, `/1` halves, `/2` quarters,
  anything shorter than `/8`) fail `terraform` variable validation and the
  security-group precondition unless `SSH_PUBLIC_BREAK_GLASS` is also `true`.
  `deploy/scripts/test-infra-policy.py` asserts the same floor statically.
- `SSH_PUBLIC_BREAK_GLASS`: leave unset. Set to `true` only for a recorded
  emergency in which SSM is unusable and a narrow CIDR cannot be determined;
  revert immediately afterwards. Password, keyboard-interactive, and root SSH
  login remain disabled by the host bootstrap regardless.

#### Closing public SSH on the running host (operator action, not applied here)

The audited host had port 22 reachable from the Internet. To close it without
replacing the instance:

1. Set the repository variable `SSH_CIDRS_JSON` to `[]` (SSM only) or to a
   narrow current CIDR such as `["203.0.113.10/32"]`. Leave `SSH_PUBLIC_KEY`
   as it is.
2. Do not set `SSH_PUBLIC_BREAK_GLASS`.
3. Run the deploy workflow (or `terraform apply` with the same tfvars). The
   only planned change is the security-group ingress rule; the instance, EIP,
   key pair, and IMDSv2 (`http_tokens = "required"`, hop limit 2 for the
   containers) are untouched. Review the plan output before approving.
4. Confirm afterwards with `aws ec2 describe-security-groups` that no rule
   allows `0.0.0.0/0` or `::/0` on port 22, and open an SSM session to prove
   the recovery path still works.

If the CI variables still carry `["0.0.0.0/0"]` when this change lands, the
next apply fails validation until the variable is corrected; that failure is
the intended guard, not an outage (the running host is unchanged).

#### Recovery without public SSH

Every administrative task in this document already runs through SSM:

```bash
aws ssm start-session --target <instance-id> --region us-east-1
sudo -i
cd /opt/trade-recommender
docker compose --env-file .env -f compose.production.yaml ps      # restart counts
docker compose --env-file .env -f compose.production.yaml logs backup --tail 100
```

SSM needs only the instance role (`AmazonSSMManagedInstanceCore`), outbound
443, and a running agent, all of which the bootstrap verifies. If the agent
itself is broken, EC2 Serial Console or a stop/start with a corrected user-data
script are the fallbacks; neither requires port 22.

Protect `main` so the `checks` job is required. Pull requests only run checks;
they cannot deploy. A successful push to `main` serializes deployment, builds
one ARM image, tags it with the full commit SHA, and pushes the immutable tag.

### Dedicated deployment user

The policy generator takes only the non-secret AWS account ID and public hosted
zone ID. It produces one policy for the exact names used by the workflow and
Terraform. Run it locally and inspect the result; do not commit the generated
file:

```bash
python3 deploy/scripts/render-deploy-iam-policy.py \
  --account-id 123456789012 \
  --route53-zone-id Z0123456789ABCDEF \
  --output /tmp/trade-recommender-github-deploy.json
python3 -m json.tool /tmp/trade-recommender-github-deploy.json >/dev/null
```

If the deploy user and policy already exist, replace the customer-managed
policy's JSON with the newly generated document before deploying a policy
change. Committing the generator does not update IAM automatically.

In the AWS console:

1. Open **IAM → Policies → Create policy → JSON**, paste the generated JSON,
   and create `trade-recommender-github-deploy`.
2. Open **IAM → Users → Create user**, create
   `trade-recommender-github-deploy` with no console access, and attach only
   that customer-managed policy.
3. Create one access key for the user's GitHub Actions use, put its two values
   in the repository secrets, then securely delete `/tmp/trade-recommender-github-deploy.json`.
   Rotate the key periodically and immediately after suspected exposure.

The policy can create and configure the exact account-named Terraform state and
backup buckets, including S3 native state lockfiles, so the first workflow run
is authorized. It manages the exact ECR repository, instance role/profile,
production parameter path, and hosted zone. `iam:PassRole` permits only
`trade-recommender-instance` and only to EC2. DNS writes are restricted to the
`fx-forecast.thomsyne.dev` A record in the supplied zone. The deploy user can
overwrite, but cannot read, the production `SecureString`; only the instance
role created by Terraform can read that exact parameter.

AWS does not support useful resource ARNs for several required control-plane
operations. Consequently, `sts:GetCallerIdentity`, ECR authorization,
Route 53 hosted-zone discovery, EC2 `Describe*`, SSM managed-instance
discovery/command-result polling, and the EC2 create/update/delete APIs use
`Resource: "*"`. Route 53's `ListHostedZones` API cannot be limited to the
configured zone; record reads and writes remain restricted to its exact ARN.
EC2 mutations are still
restricted to `us-east-1`, and Terraform applies the `Application =
trade-recommender`, `ManagedBy = Terraform`, and `Environment = research` tags.
`RunInstances` and related VPC APIs must authorize several not-yet-created or
dependent resource types in one request, so tag-only resource conditions would
make the bootstrap unreliable. S3, ECR, IAM, the parameter, SSM command target,
and Route 53 permissions are resource-scoped wherever AWS supports it. Review
the generated policy whenever infrastructure names or workflow AWS calls change.

S3 control-plane reads use `s3:Get*` only on the exact state and backup bucket
ARNs. This covers provider refresh calls whose IAM names do not share a stable
prefix, including `GetAccelerateConfiguration`, `GetReplicationConfiguration`,
and `GetEncryptionConfiguration`. It does not grant object reads: those require
object ARNs, and the policy lists only the exact Terraform state/lock and
deployment-manifest objects separately. Bucket configuration writes/deletes are
similarly covered by write permissions restricted to the two bucket ARNs. S3's
delete-encryption, delete-lifecycle, and delete-public-access-block APIs are
authorized by their corresponding `Put*` IAM actions. The CI policy audit
exercises representative implicit reads and waiters for every configured
Terraform resource class; it is a static guard, not a substitute for an AWS IAM
policy simulation or a live deployment.

## First deployment

1. Confirm the existing **public** `thomsyne.dev` hosted zone is delegated by
   the domain's registrar name servers, record its zone ID, and set
   `ROUTE53_ZONE_ID`. If the zone has CAA records, they must authorize Let's
   Encrypt (`letsencrypt.org`); no CAA record is also valid. Do not create a
   second same-named zone.
2. Generate the complete policy and create the dedicated AWS IAM user using
   [the console procedure above](#dedicated-deployment-user). Add the GitHub
   secrets/variables, including `ACME_EMAIL`. Creating this user/access key and
   confirming the existing public zone are the only unavoidable out-of-band
   AWS steps.
3. Push the reviewed commit to `main`, or run **Check and deploy → deploy**.
   The workflow idempotently creates the encrypted/versioned Terraform state
   bucket and uses S3 native lockfiles, then applies the infrastructure. No
   separate bootstrap command is needed.
4. Read `public_url` and `instance_id` from the Terraform apply output. The
   workflow waits up to ten minutes for public DNS to resolve the hostname to
   the EIP, then up to five minutes for Caddy's trusted certificate and Django
   readiness. Because `.dev` is HSTS-preloaded, browsers never permit an HTTP
   fallback: DNS delegation, CAA, ports 80/443, and certificate issuance must be
   correct before the first browser visit. Confirm `/health/live/` and
   `/health/ready/` return 200.
5. Start an SSM session and enroll the single owner interactively:

   ```bash
   aws ssm start-session --target <instance-id> --region us-east-1
   sudo -i
   cd /opt/trade-recommender
   docker compose --env-file .env -f compose.production.yaml exec web \
     python manage.py configure_owner_mfa --username owner --email owner@example.com
   ```

   Scan the displayed provisioning URI with Google Authenticator or another
   compatible TOTP application, verify one code, and store the ten recovery
   codes offline. They are displayed once and stored only as password hashes.
6. Sign in over HTTPS with password plus TOTP. Production has no demo seeding,
   no debug mode, and no app-level IP allowlist.

The instance and backup bucket have Terraform `prevent_destroy`; deliberate
teardown requires reviewing/removing those guards first. The state bucket is
outside Terraform by design so state cannot destroy itself.

If an interrupted first apply creates the exact backup bucket but its
read-after-create fails, Terraform may persist the resource as tainted; a hard
interruption can instead leave it absent from state. Bootstrap checks the
initialized remote state: it non-destructively clears partial-create taint from
an existing tracked bucket or imports an existing untracked bucket. It does
nothing when the bucket is absent and fails closed on authorization or other
unexpected `HeadBucket` errors. Completed resources remain in remote state and
are refreshed normally on the next apply.

## Deployment and rollback behavior

The workflow uploads only non-secret deployment manifests to the private backup
bucket, updates the one SSM SecureString, and invokes the host through SSM. The
same versioned, idempotent host bootstrap is embedded in first-boot user-data
and every SSM deployment. SSM waits for cloud-init to finish, emits bounded
cloud-final diagnostics when it failed, and repairs the existing instance in
place before deployment. It verifies the AL2023 host, Docker daemon, pinned ARM
Compose plugin, AWS CLI, SSM Agent, SSH hardening, and application directories.
User-data changes are ignored for an existing protected instance so a bootstrap
fix does not force replacement; SSM is the update path, while newly created
instances receive the latest bootstrap automatically.

After host readiness, the host pulls the exact SHA image using its instance
role, starts PostgreSQL, makes and uploads a compressed pre-migration dump,
migrates, restarts services, and waits for the Route 53 A record to converge
before allowing Caddy to request or renew a trusted certificate, then checks
HTTPS directly against the EIP using the custom hostname for TLS validation. If
readiness fails, it restores the previously recorded image and exits
unsuccessfully. Database migrations are not automatically reversed, so
migrations must remain backward compatible.

For an explicit rollback, run the workflow with `operation=rollback` and a full
40-character commit SHA that still exists in ECR. It also takes a pre-migration
backup before restarting that image.

## Backups, health, and restore

The backup container runs `deploy/scripts/backup.sh loop` every six hours
(`BACKUP_INTERVAL_SECONDS`). Each attempt is a sequence of explicitly checked
stages — `configure`, `dump`, `compress`, `validate`, `checksum`, `upload`,
`verify_upload`, `record` — and any failure stops the attempt without touching
the success state. The script is POSIX `/bin/sh`: `pg_dump` streams into
`gzip` through a FIFO; both are started in dedicated sessions (`setsid`, when
available) and terminated as a supervised process group on interrupt, so an
interrupt kills pg_dump and its whole pipeline (no orphaned dump) and the
dump's own exit status needs no `pipefail`. The compressed archive must pass
`gzip -t`, exceed `BACKUP_MIN_BYTES` (default 1024, deliberately
conservative), and carry both the pg_dump header and the `PostgreSQL database
dump complete` trailer; the object is uploaded with `--sse AES256` and its
sha256 attached as user metadata, and `head-object` verifies BOTH the size and
the checksum before anything is recorded as successful. Dump and upload run
as background jobs so `SIGTERM`/`SIGINT` interrupt promptly (further signals
are ignored while the handler runs), record an `interrupted` failure, and
remove the temporary archive (which lives under `BACKUP_WORK_DIR`, default
`/tmp` inside the container, never on the state volume). `backup.sh once`,
used before every migration by `remote-deploy.sh`, exits non-zero on any
failed stage, so a deployment cannot proceed past a failed pre-migration
backup; an unwritable state directory or a missing `flock(1)` also aborts
loudly instead of degrading.

State files under `BACKUP_STATE_DIR` (`/var/lib/trade-recommender`, the shared
`backup-state` volume) are written atomically and never contain credentials,
command bodies, or raw error output:

| File | Written | Content |
|---|---|---|
| `backup-in-progress` | while an attempt runs | `attempt_id`, `started_at`, `attempted_at`, `object_key`, `stage`; removed only after a terminal outcome is recorded |
| `backup-last-attempt` | every terminal attempt | `attempt_id`, `attempted_at`, `object_key`, `outcome`, `stage`, `category` |
| `backup-last-success` | genuine success only | `attempt_id`, `completed_at`, `attempted_at`, `object_key`, `sha256`, `size_bytes` |
| `backup-last-failure` | failed attempts | `attempt_id`, `failed_at`, `attempted_at`, `object_key`, `stage`, `category`, `exit_status` |
| `last-backup` | genuine success only | legacy marker (ISO timestamp) kept for compatibility |

Attempts are serialized with `flock(1)` on a lock file (`.backup-lock` inside
`BACKUP_STATE_DIR`), so the scheduler's backup loop and a deploy-time
`backup.sh once` — which run in different containers on the same state volume —
never overlap. The flock is owned by the kernel, so a crashed holder
(SIGKILL, host loss) releases the lock automatically; later attempts can never
deadlock on a stale PID file. Every attempt id is a random UUID (128 bits)
recorded in every state file *and* embedded in the S3 object key, so two
attempts can never share an id or overwrite each other's object. The
`backup-in-progress` record is written once the lock is held and before any
dump work (its write is mandatory: an attempt that cannot record durable
state aborts); it is removed only after a terminal outcome has been committed,
so a stale in-progress file unambiguously means the previous attempt died
without finishing (SIGKILL or host loss).

An attempt commits when `backup-last-attempt` reports `outcome=success`; the
record stage runs only after the upload was verified, and the success file and
legacy marker are best-effort publications made *after* that commit. A signal
in the publish window therefore never produces contradictory records: the
failure handler refuses to overwrite an attempt already committed as a success
for the same `attempt_id`, and a committed-but-unpublished success is simply
missing until the next run. Readiness compares identities by `attempt_id`
(falling back to `attempted_at` only for pre-fix files that have no id) and
distrusts a success file contradicted by a failure or non-success attempt of
the same attempt, reporting `backup.state = contradicted` until the next
successful run rewrites it.

Failure categories are stable tokens (`configuration_missing`, `dump_failed`,
`compression_failed`, `archive_unreadable`, `archive_too_small`,
`archive_content_invalid`, `checksum_failed`, `upload_failed`,
`upload_unverified`, `upload_checksum_mismatch`, `interrupted`, …). Bounded
stderr excerpts go to the container log only.

Readiness (`/health/ready/`) fails for an unavailable database, unapplied
migration, stale running job heartbeat, less than 2 GB free disk, or when the
**last genuine success** is missing or older than eight hours. A failed attempt
after a fresh success keeps readiness green but is exposed as
`backup.warning = last_attempt_failed` with the safe failure category. An
attempt whose durable in-progress record is older than the readiness window
(died or stuck without a terminal outcome) fails readiness with
`backup.state = attempt_stale` and is reported as `attempt_in_progress` on the
Operations page. The response also carries the running source revision and a
small `disk` block; it never exposes paths, keys, or checksums. Hosts that
predate the state files are honoured through the legacy marker's modification
time. The Operations page shows the full state (object key, checksum, size,
last failure) to the owner. Liveness deliberately checks only the web process.

### Isolated restore verification

`deploy/scripts/restore-check.sh` restores one archive into an explicitly named
**disposable** database and verifies it. It refuses any target whose name does
not contain `restore_check`, refuses protected names, validates the archive
(gzip integrity, optional expected SHA-256, header and completion trailer),
restores in a single transaction with `ON_ERROR_STOP`, and then checks
representative tables, constraints, triggers, the Django migration ledger, and
— functionally — that the restored append-only audit trigger still rejects an
update (inside a rolled-back transaction). It prints one `restore check
PASSED … ` or `restore check FAILED at <stage>: <category>` line and exits 0/1.

```bash
# Local drill against a disposable Postgres (libpq env vars select the server).
PGHOST=127.0.0.1 PGUSER=trade_recommender PGPASSWORD=… \
RESTORE_CHECK_DB=phase1_restore_check_$(date +%Y%m%d) \
  deploy/scripts/restore-check.sh --recreate --drop-after \
    --expect-sha256 <sha256 from backup-last-success> \
    s3://<backup-bucket>/postgres/20260907T120000Z-<attempt_id>.sql.gz
```

From the host, the same command runs inside the backup image (it has
`psql`, `createdb`, `gzip`, and `aws`) against a throwaway PostgreSQL container
on a private network; never point it at the production `db` service. Run the
drill after every schema migration and at least monthly; record the PASSED line
with the archive checksum. Limitations: the drill is not wired into CI because
it needs a PostgreSQL server and a real archive; it is exercised locally with a
disposable database copy (see the Phase 1 handoff), and the shell harness
`deploy/scripts/test-backup.sh` covers the script logic with fake executables in
CI.

Production restore (unchanged procedure, run from an SSM session):

```bash
sudo -i
cd /opt/trade-recommender
aws s3 ls "s3://$(sed -n 's/^BACKUP_BUCKET=//p' .env)/postgres/"
CONFIRM_RESTORE=yes ./restore.sh \
  s3://<backup-bucket>/postgres/20260821T120000Z-<attempt_id>.sql.gz
curl --fail "https://$(sed -n 's/^PUBLIC_HOST=//p' .env)/health/ready/"
```

Restore stops application writers, streams one dump into PostgreSQL in a single
transaction, reapplies migrations, and restarts the stack. Run
`restore-check.sh` on the chosen archive first. Continuous WAL archiving,
point-in-time recovery, SNS, paid monitoring, and a separate restore
environment are deferred at this pre-production budget level.

## Container isolation, capacity, and image provenance

The web container no longer mounts the host root filesystem. Its only bind
mount is the empty, read-only directory `/var/lib/trade-recommender/host-health`
(created by the host bootstrap and by `remote-deploy.sh`) at `/host-health`,
which sits on the single root filesystem and therefore yields the same
`statvfs` signal for `READINESS_DISK_PATH=/host-health`. No service is
privileged and none mounts the Docker socket; `test-production-compose.sh`
asserts all of this on the rendered Compose configuration.

The Operations page reports host capacity cheaply and without shelling out:
disk free/total from one `statvfs`, memory from `/proc/meminfo` (visible from
the container), swap total, the web process start time, and the container's
PID 1 start time. Thresholds are conservative and configurable: disk warns
below `CAPACITY_DISK_WARNING_FREE_GB` (5 GB) and readiness fails below
`READINESS_MIN_FREE_GB` (2 GB); memory warns below
`CAPACITY_MEMORY_WARNING_PERCENT` (20 %) and is critical below
`CAPACITY_MEMORY_CRITICAL_PERCENT` (10 %). Memory pressure is visibility only —
it never fails readiness, and no swap is added to hide it. Restart counts are
not observable without the Docker socket; use `docker compose ps` over SSM.

Stale images: `remote-deploy.sh` runs `docker image prune -f`, which removes
only dangling layers. Tagged images stay available for rollback. To reclaim
space safely, list images with `docker image ls`, keep the current
`current-image` and the previous SHA you might roll back to, and remove older
tags explicitly with `docker image rm <repository>:<sha>`; never run
`docker system prune -a` on the host.

Image provenance: the Dockerfile accepts `SOURCE_REVISION`, `BUILD_CREATED`,
`SOURCE_URL`, and `IMAGE_VERSION` build args and writes them to the OCI labels
`org.opencontainers.image.revision/created/source/version`, to the
`APP_SOURCE_REVISION`/`APP_BUILD_CREATED` environment, and to `/app/build-info`.
CI supplies the commit SHA and UTC build time and prints the immutable manifest
digest after the push (`docker buildx imagetools inspect`); the digest is also
visible in the ECR console or via `aws ecr describe-images`. On the host,
`remote-deploy.sh` records `current-image`, `current-image-digest`, and
`current-image-revision`. A build without the args produces an honest
`unknown`, which the Operations page and `/health/ready/` show as such:

```bash
docker build --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  --build-arg BUILD_CREATED="$(date -u +%FT%TZ)" -t trade-recommender:local .
docker image inspect trade-recommender:local \
  --format '{{json .Config.Labels}}'
```

## Rollback note for Phase 1 schema changes

Migrations `market.0028`, `operations.0006`, and `forecasts.0017` add nullable
or defaulted columns and new tables, so the previous image starts against the
new schema. One behaviour is intentionally not backward compatible: technical
snapshots are append-only at the database level, so a rolled-back image's
in-place `update_or_create` of a snapshot fails visibly during live ingestion
until the Phase 1 image is redeployed. Nothing is corrupted by that failure.

`market.0028` is **forward-only once live observations exist**. Unapplying it
would drop `market_candleobservation` (the append-only provider-view ledger)
and would fail while re-creating `unique_technical_snapshot` once appended
recalculations share an `as_of`. Its reverse preflight therefore refuses with
an explicit `RuntimeError` while the ledger holds any row or while any
`(instrument, granularity, as_of)` holds more than one snapshot, before any
object is dropped: the schema stays at 0028 and nothing is unapplied. Never
run `manage.py migrate market 0027` on a database that has ingested live
candles under Phase 1; the only rollback path for the application is
redeploying the Phase 1 image. Reversal remains possible only on a database
with an empty ledger and unique snapshot `as_of` values (for example a fresh
test database).
