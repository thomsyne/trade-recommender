# Private AWS research deployment

## Shape and cost boundary

Slice 6 runs one ARM `t4g.small` in `us-east-1` with a 25 GB encrypted gp3
root volume, an attached Elastic IP, and Docker Compose. Caddy terminates TLS
for `fx-forecast.thomsyne.dev`; Terraform manages an A record in the owner's
existing public Route 53 hosted zone. Only 80/443 and explicitly configured
key-only SSH CIDRs enter the host. SSM Session Manager remains the emergency
access path. PostgreSQL, web, worker, scheduler, backup, and Caddy containers
all restart unless stopped. There is no load balancer, NAT gateway, RDS,
Secrets Manager, a new hosted zone, Tailscale, extra EBS volume, or paid monitoring.

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
- `SSH_PUBLIC_KEY`: the owner's **public** key. Omit to disable SSH entirely.
- `SSH_CIDRS_JSON`: JSON such as `["203.0.113.10/32"]`. It defaults to `[]`.
  During travel, `["0.0.0.0/0"]` is supported only as an explicit decision.
  That exposes key-only SSH to the Internet; password, keyboard-interactive,
  and root login remain disabled. Prefer updating narrow CIDRs or using SSM.

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

## Deployment and rollback behavior

The workflow uploads only non-secret deployment manifests to the private backup
bucket, updates the one SSM SecureString, and invokes the host through SSM. The
host pulls the exact SHA image using its instance role, starts PostgreSQL, makes
and uploads a compressed pre-migration dump, migrates, restarts services, and
waits for the Route 53 A record to converge before allowing Caddy to request or
renew a trusted certificate, then checks HTTPS directly against the EIP using
the custom hostname for TLS validation. If readiness fails, it restores
the previously recorded image and exits unsuccessfully. Database migrations are
not automatically reversed, so migrations must remain backward compatible.

For an explicit rollback, run the workflow with `operation=rollback` and a full
40-character commit SHA that still exists in ECR. It also takes a pre-migration
backup before restarting that image.

## Backups, health, and restore

The backup container runs `pg_dump`, gzip-compresses it, and uploads it every six
hours to `s3://<backup-bucket>/postgres/` using the instance role. S3 encryption,
versioning, public access blocking, and 35-day lifecycle expiration are enabled.
Readiness fails for an unavailable database, unapplied migration, stale running
job heartbeat, less than 2 GB free disk, or a missing/older-than-eight-hour
successful backup marker. Liveness deliberately checks only the web process so
the orchestrator does not confuse dependency failure with process death.

List and restore a selected backup from an SSM session:

```bash
sudo -i
cd /opt/trade-recommender
aws s3 ls "s3://$(sed -n 's/^BACKUP_BUCKET=//p' .env)/postgres/"
CONFIRM_RESTORE=yes ./restore.sh \
  s3://<backup-bucket>/postgres/20260821T120000Z.sql.gz
curl --fail "https://$(sed -n 's/^PUBLIC_HOST=//p' .env)/health/ready/"
```

Restore stops application writers, streams one dump into PostgreSQL in a single
transaction, reapplies migrations, and restarts the stack. Test restore
periodically before relying on retention. Continuous WAL archiving, point-in-
time recovery, SNS, paid monitoring, and a separate restore environment are
deferred at this pre-production budget level.
