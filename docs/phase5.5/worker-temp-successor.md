# Private temporary storage, validation revision 6

Revision 5 passed 60 focused tests (six DB skips) and a 64-checkpoint Linux/Mac
equivalence and cold-resume check, then started at 2026-09-11T13:49:13Z. The first
health check found group 3 stopped: SciPy's optional GARCH dependency import
could not create its temporary diagnostic stream under ProtectSystem=strict.
The small equivalence slice had not exercised that import. Three other groups
were progressing; that partial run is not a pass. All workers were explicitly
stopped, and their source/catalogs/logs retained in work-v5-partial on the worker
and a separately hashed private S3 archive. Revision 5 is never overwritten.

Revision 6 changes the registered service to provide PrivateTmp and adds an
outcome-blind ExecStartPre probe. The probe verifies network/code-write denial,
private temporary file creation and actual arch/scipy.stats imports under the
scientific service's own restrictions. The full focused suite must also run
under the sandbox, not merely as the unprivileged account. It keeps all original
read-only code/input, network, numeric-thread and memory restrictions. Before
revision 6 was frozen, the owner explicitly extended the runtime maximum to
72 hours, with progress checks every 24 hours and early stop on completion.
Compute for a full 72 hours is USD 29.0304 plus storage/networking. Timeout or
failure remains incomplete, never a pass; no automatic scientific retry is added.

Worker registration/report paths now derive from the explicit immutable revision
constant. Revision 6 supersedes revision 5 without changing formulas, simulator
digests, costs, thresholds, population, period bounds or sealed-manifest identity.
It reuses the exact authenticated development-only transfer, not partial results
from revision 5. Freeze and commit the new registration before its equivalence
check and full development run. Reset the progress checks to the actual successor
start, at 24/48/72 hours, ending early when the run finishes. No historical
holdout payload exists on this worker.
