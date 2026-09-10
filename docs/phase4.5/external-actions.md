# Authorized deployed-backup inspection and disposable restore

Date: 2026-09-10. The owner expanded access authority during Phase4.5. The least
destructive sufficient path was metadata inspection, one existing backup download,
read-only deployed SQL and two local restores. No production migration, write,
restart, teardown, access-control change, provider request or trade occurred.

## External action ledger

| Action | Result / state |
|---|---|
| Local AWS profile discovery and STS identity | Existing authenticated credentials used; no credential values displayed or changed |
| EC2 describe, filtered by Application=trade-recommender | Existing instance `i-06a17f7ac14d7b282`, us-east-1, running t4g.small; no instance provisioned |
| SSM instance-information read | Existing instance online, Amazon Linux 2023 |
| S3 list postgres prefix, then HEAD exact latest key | Selected backup timestamp 2026-09-10 11:45:43 UTC; 18,124,768 bytes, AES256 encryption, exact version below |
| S3 GET exact object version | Private local copy; gzip CRC/structure valid and SHA-256 below; no bucket object or marker written |
| SSM command `d80d8ef3-905b-4275-ad20-fbb87369e24c` | Read-only SELECT failed due shell quoting (`server_version` treated as a column); no SQL mutation attempted |
| SSM command `935be3a0-e816-4b8c-8e18-a19ac9800da2` | Corrected read succeeded: PostgreSQL 15.14, latest market recorder 0023, zero DatasetRegistration rows |
| SSM command `5d29a8cd-fce7-4dd2-86ac-ce2f8935ad0b` | After-restore confirmation in explicit READ ONLY transaction: same version, recorder head and zero registrations |

SQL ran through the existing Compose db container and its existing environment;
no environment contents, passwords, raw application rows or backup payloads were
printed. SSM retains its normal command audit records. No deployed recovery was
necessary because the deployment was never changed. Ambient scheduled ingestion
was not paused, so the selected metadata checks do not claim the entire live
database was static during this work.

## Backup identity and recovery proof

* Bucket: `trade-recommender-590759815902-backups`
* Key: `postgres/20260910T114520Z.sql.gz`
* Version: `bJsKAEBOtC4vUi.3r0rly1dPqrxqc.mM`
* Archive SHA-256: `724007ae20e33a170e2cedc2d445cf967517c012e1412bffa3e634b46b24e6d2`
* Dump source PostgreSQL 15.14; pg_dump 15.19. The exact archive restored through
  `psql -X -v ON_ERROR_STOP=1` into new local 15.14 and 17.6 databases without repair.

Both restores contain 41,699 rows in 101 non-recorder tables and 77 original
migration records. Canonically sorted per-table row hashes plus application
sequence last-value/is-called states produce the identical cross-version digest
`75797bd426c0b03b74584c07324e74ed7d6353878f501d1fa11504f880034577`.

The opt-in `market.tests.phase45_restore.verify` probe requires the explicitly
named local Unix-socket database `phase45_restore`. It applies published 0024–0026
normally, proves all existing rows/application sequences and recorder identities
unchanged, then executes original and replacement 0027 separately. Both refuse
with `Gate 8I requires the accepted complete successor acquisition`. Exact
recorder/catalog fingerprints and all row/sequence hashes remain unchanged after
each refusal; the replacement delegates once to the unchanged original operation.

This is genuine **populated-negative** proof. Neither the backup nor the current
deployment carries accepted successor acquisition or already-applied 0027 history.
It cannot close populated-success or deployed-0027-recorder/no-op proof. The
representative recorder test remains explicitly representative. A genuine accepted
restore is still a mandatory pre-rollout gate; do not acquire or fabricate a new
acceptance history merely to satisfy an engineering test.

## Cost and cleanup boundary

No new AWS compute, storage resource, deployment or OANDA activity was created.
Only normal API requests and an approximately 18.1 MB S3 download may incur
incremental request/transfer charges; actual billed cost was not measured. Existing
instance and backup-retention costs continue unchanged. The source backup/version
was not deleted or altered and remains subject to existing retention policy.

Raw backup and restored databases stay only in the permission-restricted task
scratch directory until final cleanup; no raw dump, logs, secrets or row payloads
belong in Git. Final cleanup and remote-ref state are recorded in the handoff.
