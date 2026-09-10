# Final-boundary verification — not acceptance

Descriptor 0.11.0 / migration 0036 continues the intentional uncommitted work from
[the implementation thread](https://ampcode.com/threads/T-01a08a15-98ec-77a4-a8b6-0bcb3eb67ac6).
Starting HEAD was
[`817d5ef`](https://github.com/thomsyne/trade-recommender/commit/817d5ef1cac2de495310eed46e1baddf8b28806e),
on `phase4/deterministic-market-state`. Acceptance remains superseded pending
fresh independent review. This is engineering verification, not rollout approval.

## Evidence and reproduction

`results.json` records commands, outcomes, differential identity/cause checksums,
populated preservation, protections, cleanup and limitations. `sha256.json`
inventories this compact artifact set. Raw/gzip logs, duplicate inventories and
machine-path output have been removed. Historical evidence remains retrievable
from the starting commit, without rewriting Git history.

Run `bash docs/phase4/verification/verify.sh.txt` from the repository root with
`PG_BIN` pointing to PostgreSQL 15 executables. It creates its own UTF-8,
socket-only cluster and removes it on exit. It never uses an existing database
or `.env.local`. It retains output only when `RESULT_DIR` explicitly names a new
directory. Tests use synthetic fixtures and mocked providers.

The bootstrap normally migrates to market0026, fakes **only** the known
data-dependent0027, then normally installs the rest. This is not a fresh-install
certification. PostgreSQL15.5 was exercised; PostgreSQL17 was not.

`test_phase4_final_boundary` contains real non-superuser, multi-connection races
with lock/statement/event/future timeouts. Candle insertion first is checked
through ORM re-selection and rejection of stale raw SQL; snapshot first retains
late evidence only for later cutoff. Both research transaction orders reject
semantic edits while allowing editorial edits. Post-commit integrity is checked.
Historical fixtures alone use `legacy_state_evidence`; it disables only the new
recording trigger during synthetic legacy insertion. New-evidence/race tests
never use that helper.

For populated preservation the script archives exact starting HEAD, seeds its
0035 schema using `preservation.py.txt`, then compares all application rows
through 0035→0036→0035→0036 using `final_preservation.py.txt`. The new column is
excluded from historical row hashes but independently asserted NULL. Migration
history is excluded. Reversal with new recording facts is separately tested to
refuse before discarding evidence.

The exact historical test ordering is
`test_zzzzzzzz_live_observation_migration` followed by
`test_observation_lineage.SqlPythonParityTests`, in one command, with no parity
setup repair. Focused, affected, research and broad commands are in the script.

Compare new logs with retained verified base logs using
`python docs/phase4/verification/eight/compare_broad.py.txt BASE_LOG FINAL_LOG`.
It compares every exact failing identity, terminal exception cause and occurrence
count; only memory addresses are normalized. Results retain compact digests and
differences rather than repeating hundreds of identical irreversible-migration
tracebacks. A broad suite with inherited failures is **not green**.

Protection evidence compares the 92-file historical fingerprint inventory from
the starting commit against current bytes. Forecasts, technicals, settings,
canonical seed and schedule sources remain unchanged. Disposable schedule
inventory is not evidence about uninspected production schedules. No M15 or
descriptor activation, forecast consumer, provider access, production/AWS/OANDA
access, push, PR or deployment is authorized or performed.

Production capacity, RSS/WAL, PostgreSQL17 and exceptional-holiday calendars are
unverified. Historical performance artifacts are not republished as current
measurements. SQL does not duplicate every market formula; Python integrity
replays formulas. Superuser trigger bypass is outside runtime enforcement.
