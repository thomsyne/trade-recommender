# Dedicated Phase 5.5 EC2 worker

The owner approved this infrastructure and execution. See
[the current launch record](../../docs/phase5.5/worker-launch.md) for revision 6,
its 72-hour limit, progress checks, verification and preserved startup failure.
The original host-only proposal below is retained as preparation history.

This is a separate Terraform root with local state. It does not import production
resources, use the production Terraform backend, deploy the app or start a batch.
AWS resource creation and artifact upload require explicit owner approval of the
launch configuration below.

## Launch configuration for approval

- `us-east-1`, On-Demand `m7i.2xlarge`: 8 vCPUs, 32 GiB RAM.
- Amazon Linux 2023 x86-64; the reviewed plan pins the selected AMI.
- New VPC/subnet/security group, no peering or inbound ports. SSM administration;
  the security group allows outbound HTTPS for bootstrap and artifact transfer.
- Encrypted 100-GiB gp3 root/data volume, retained if the instance is terminated.
- New private, encrypted, versioned S3 artifact bucket. No automatic deletion.
- New worker role scoped to that bucket. Parameter Store reads and Secrets Manager
  are explicitly denied, including permissions otherwise supplied by SSM core.
- IMDSv2 required. No production instance role, secrets, database or backup bucket.

AWS Pricing API returned USD 0.4032/hour for Linux shared-tenancy On-Demand compute
on 2026-09-11: USD 9.6768 for 24 hours. Budget roughly USD 11–12 for the first day
including baseline storage and an ephemeral public IPv4 address, excluding taxes
and unusual transfer charges. Storage/S3 charges persist after compute stops.
There is no automatic instance shutdown implemented by this host-only preparation;
`instance_initiated_shutdown_behavior = "stop"` controls what a later OS shutdown
does, not when it occurs. Completion/cleanup control must be set before the batch.

## Validation and review, without creating resources

Use Terraform 1.12 or newer. Run commands only from this directory:

```sh
terraform init -backend=false
terraform fmt -check
terraform validate
terraform test
terraform plan -var aws_account_id=APPROVED_ACCOUNT_ID -out=/private/path/worker.tfplan
```

The tests use a mock AWS provider and plan-time values. They do not contact AWS or
create resources, and preserve the real destruction guards. A real plan must contain only new worker resources, with zero
changes/deletions to existing infrastructure. Do not apply until its destination,
cost and permissions are approved. Never commit local state or the binary plan.

## Batch start remains a separate integrity gate

1. Prepare a development-only execution package from authenticated frozen metadata.
   Transfer warm-up/development payloads only; no sealed historical holdout payloads,
   `.env.local`, provider tokens, AWS credential files or production configuration.
2. Transfer the exact unpushed local code checkpoint privately, without pushing a
   branch, deploying the app, running migrations or seeding any database.
3. Inspect and pin the actual Linux/Python/dependency/timezone runtime. Freeze and
   commit an explicit successor to revision 4, preserving prior registrations,
   formulas, costs, thresholds, dates and sealed-manifest identity. Do not fake the
   Mac runtime fingerprint or rewrite revision 4.
4. Run synthetic seal/projection tests and a small registered equivalence check.
   Only then start the full development batch under an unprivileged service with
   persistent checkpoints and network access denied for the scientific process.
5. Preserve progress, failures and final report hashes independently of the SSH/SSM
   session. Review at 24 hours after actual batch start; this is not a deadline that
   turns incomplete output into success or authorizes a holdout release.
6. Stop dedicated compute after completion and artifact preservation. Retain data
   until explicit cleanup approval. No destructive auto-cleanup of evidence.

No batch, timer, monitoring schedule, upload or remote execution is installed by
the current bootstrap. Independent engineering for later phases can continue;
result-dependent strategy promotion and independent acceptance remain blocked.
