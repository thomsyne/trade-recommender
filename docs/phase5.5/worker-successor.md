# Dedicated Linux development worker, revision 5

The owner approved the isolated EC2 configuration and private transfer/run on
2026-09-11. This is neither production deployment nor holdout release. Revision 5
explicitly supersedes revision 4 to bind the actual Linux runtime and worker
source. Earlier registrations, checkpoints and publications remain immutable.
No formula, simulator, cost assumption, threshold, period or population changes.

The transfer is a new SQLite database, never a backup of the acquisition database.
It contains authenticated warm-up/development compressed blobs and the unchanged
frozen metadata for every chunk. Sealed price blobs are physically absent (NULL).
The metadata-only audit runs before projection, and the worker checks the exact
projection byte hash and metadata manifest before any replay. Original provider
provenance and actual acquisition timestamps are preserved. Transfer creation
time is separate, not a historical known-at timestamp.

Four disjoint strategy groups own separate append-only catalogs. The two M15
structure identities alternate bounded chunks to reuse existing pure causal
descriptors; their decisions, attribution and outcomes remain independent. ORB
comparators share a catalog. All 15 baseline/readiness identities and their four
paired overlay views cover the original 12 instruments (975 reports including
aggregates). No successful subset can substitute for a complete publication grid.
Restart traverses the existing verified causal-prefix API. Volatile proofs never
become persisted resume authority. Prior partial Mac catalogs are not imported.

The scientific service runs unprivileged, with no network, no credentials, a
read-only code/input mount, four single-threaded numeric workers and a 28-GiB
memory limit. A 24-hour runtime cap preserves partial checkpoints; expiry is not
completion or acceptance. No automatic scientific retry is configured. The
separate host preservation service archives idle outputs to the new private S3
bucket and stops compute after successful transfer. A failed transfer leaves
the retained volume and instance available for recovery. No service is enabled
at boot and no strategy/recommendation/production scheduler is installed.

Freeze and commit revision 5 before a small fixed Linux/Mac equivalence check,
then start the full batch only if that check and focused synthetic tests pass.
The later 24-hour review concerns progress and available development evidence.
Missing financing, calendar/event vintages, range clearance and carry evidence
remain unavailable. The historical holdout remains technically inaccessible;
all diagnostic evidence remains model-based, not broker-observed execution.
