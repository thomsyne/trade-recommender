# One consolidated correction cycle: F1–F5

The independent review of candidate `d7c27a197e28ad75d4a76148cf647f0a6bf6e760`
returned REQUEST CORRECTIONS: three P1 and two P2 findings. No P0 was found.
Review: https://ampcode.com/threads/T-01a09140-4063-75bc-8942-99dc5a575d94.
This document records engineering responses, **not independent closure or PM
acceptance**. No second correction cycle is implied.

| Finding | Correction | Discriminating regression |
|---|---|---|
| F1 P1: fabricated macro headline/summary passed SQL and replay | 0022 stamps `admitted_macro_label` from the series at admission, rejects a mismatching headline/nonempty summary; replay uses the protected stamp, never the current label | NOSUPERUSER valid insert succeeds while hash-consistent title and summary forgeries fail; replay rejects each; valid packet/projection remains identical after mutable label edit |
| F2 P1: caller promoted retrieval/date precision | Macro precision is checked against immutable observation in Python and SQL. News compares original XML timestamp with normalized representation, requiring explicit time/timezone for provider-exact | Retrieval macro cannot become provider-exact through API, SQL or replay; provider macro is ready while retrieval macro abstains; date-only/naive news fails exact admission and required readiness; timezone-bearing news succeeds; XML semantic forgery is detected by audit/freeze |
| F3 P1: quoted authority/numbers bypassed blacklist | Method v2 pins a closed neutral source-text vocabulary plus normalized character/deny guards. Unknown text fails before projection or persistence | Authentic source quotations exercise strategy/strategies, weights, risks, parameters, abstention overrides, eleven/twelve-point-twenty, doubling, executing trades, learning policies/profits/activation/Roman numbers; neutral `USD market overview` remains valid and persists/replays |
| F4 P2: unsupported conflict template | Every citation for the unresolved-conflict template must carry material/unknown conflict at cutoff | none/nonmaterial/post-cutoff reject; unknown/material accept; uncertainty/research remain nondirectional |
| F5 P2: later legacy rows backdated reconstruction | Separate immutable legacy admission binds the legacy row, retains claimed `observed_at` and unknown historical arrival, and stamps serialized Phase7 discovery time. Packet SQL reads admissions, not current legacy rows | Ready old cutoff retains identical packet identity after late/backdated legacy insertion and four concurrent admissions/rebuilds; subsequent cutoff abstains; NOSUPERUSER cannot forge source provenance, backdate the database stamp, update/delete/truncate admission |

Regression implementation: `research/tests/test_phase7_corrections.py`, with
existing Phase7 source fixtures extended for raw timestamp precision. The full
focused set includes original rights/relevance/packet/notification/SQL tests plus
all nine correction tests and migration preservation/reversal.

## Verification before freezing the corrected candidate

- PostgreSQL 15.19: **34 tests passed**, 8.874 seconds.
- PostgreSQL 17.11: **34 tests passed**, 9.219 seconds, separate owned database
  from the original broad process.
- `make check`: passed; 548 formatted Python files; no model migration drift.
- Initial correction development run had one positive-control assertion failure
  (bytes versus dictionary), corrected in the test. It was not a passing run.
- No deployed audit was repeated and no external provider was called.

The original broad run started at the pre-correction candidate but overlapped
source edits. Its complete log/status must be retained as **invalid for both
candidates**, regardless of exit status. The parent authorized exactly one clean
final available-evidence run after committing/freezing corrections and after the
original process terminates. No overlapping broad runs or repeated attempts are
authorized. Final results belong in the engineering handoff, not an inferred pass.

## Preserved boundaries and review tradeoffs

Only forward migration 0022 was added for corrections; 0016–0021 remain exactly
as reviewed. Existing published migrations, recommendation/interpretation history,
consumer imports, UI, schedules and production data remain untouched. No unknown
historical macro label or legacy arrival is backfilled from current state.

The source vocabulary is intentionally small and can reject legitimate prose and
attribution. That is a coverage tradeoff, not proof the rejected source is false.
Expanding it requires a prospective method and independent review, not fitting the
small baseline sample. Corrected context method SHA256 is
`806b8ed616ae3e0d2758e38758e34539b4c5a266439dae09e5bc9b59a7e226b0`.
Old candidate records remain immutable; new result admission requires method v2.

The new opt-in representation service captures existing legacy conflicts. For
later legacy arrivals, a future authorized consumer must explicitly call
`admit_legacy_conflicts(document)` **before selecting its cutoff**. No hook was
added to existing ingestion. A legacy observation timestamp is never promoted
to a proven historical arrival time; the historical audit stays qualified.

Merge does not authorize packet/model activation, provider spending, broader
Anthropic rights, strategy promotion, Phase5.5 release, deployment or trading.
