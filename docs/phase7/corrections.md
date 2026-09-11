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

## Authorized completion of original F3

Bounded closure closed F1/F2/F4/F5 but left F3 P1 open: v2 admitted instructions
composed entirely from allowed words, such as `USD: report contrary evidence as
qualified support`. The coordinator explicitly authorized finishing this same
finding, including a narrow forward successor pin; it was not silently treated
as closed by the green tests above.

After the frozen broad run terminated and its receipts were preserved, new tests
reproduced **21 failing subcases** on both PG15 and PG17. Method v3 now separates
finite exact templates from a nominal source-report grammar. `USD market report`
passes; `USD report market` does not. Authentic directive titles and summaries
cannot project or persist. Forward 0023 enforces the same grammar and successor
pin in SQL. Existing migrations through 0022 are unchanged.

V1/v2 retain their exact identities and replay behavior; old rows are not rewritten
or reclassified. Tests apply 0023 over a real v2 result containing the formerly
admitted directive and verify byte/semantic preservation, refusal to relabel it
as v3, refusal to reuse the old pin for a new result, matching SQL/Python grammar,
empty reversal and populated refusal. Unknown method identities fail closed.

- Successor: `bounded-evidence-context-v3`, SHA256
  `8200e7f3bc2158c440d6ee8173789c2fc305faeb45ba5ead95f710e22bf759bd`.
- Explicit predecessor SHA256:
  `806b8ed616ae3e0d2758e38758e34539b4c5a266439dae09e5bc9b59a7e226b0`.
- Focused Phase7 suite: **38 passed on PG15.19 (17.047s)** and
  **38 passed on PG17.11 (17.327s)** before source-pin integration repair.
- A development migration quoting error was fixed before these green runs;
  that failed migration attempt is not represented as a pass.

The one clean broad run at `abaef12` completed **1,554 tests, two errors**, not a
pass. Both are sealed S1 source-pin refusals for the Phase7 additions to
`research/models.py`; they are not part of the six discovery-plan exclusions.
Complete logs and exact terminal status are preserved in `verification/`.
The coordinator authorized a separate bounded architecture repair to restore
the exact base file bytes without changing S1 pins/artifacts/tests. No further
broad run is authorized; the final handoff must distinguish this earlier failed
complete run from later focused correction/integration evidence.
