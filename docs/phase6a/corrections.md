# Phase 6A consolidated correction trace

Status: **corrected engineering candidate; independent acceptance remains open**.
This is the single reserved correction cycle for original candidate commit
`28fb56a0b695328fa46357d0519ea9a46c059046`, tree
`58409d97bdff612168f697c217b0f35c6126702c`. The original design, handoff,
verification receipt, and source manifest remain unchanged. The correction is a
forward-only successor method (`1.1.0`) and migration (`0003`); it does not
rewrite the applied v1 migrations.

## Conservative production boundary

No authoritative Phase 5.5 eligibility record, immutable exact cost source, or
frozen capacity-policy source exists in the merged source tree. Method 1.1.0
therefore admits only the exact canonical empty eligibility set and rejects all
nonempty eligibility, cost, capacity, and candidate appends in both Python and
SQL. It also rejects every Phase 7 packet because the method pins an empty
strategy requirement map. Positive candidate behavior remains a pure,
deterministic contract fixture; there is deliberately no production bypass.
A future positive production path requires a separately reviewed successor
method and authoritative upstream records.

## Finding-to-correction matrix

| Finding | Correction | Discriminating verification |
|---|---|---|
| F1 fabricated assessment/candidate | SQL computes the only admissible empty-set assessment from the frozen Phase 4 payload and requires exact JSON equality, exact input manifest and hashes. Candidate insert is prospectively impossible without authoritative eligibility. | First hash-consistent available/empty-gate assessment insert fails; malformed candidate variants fail. SQL projection equals Python bytes. |
| F2 self-attested eligibility/era | Exact empty era and three canonical provenance digests are pinned. Any nonempty set, alternate era/hash, expiry, or caller backdating is rejected. | Service and raw-SQL wrong-era, wrong-hash, and invented nonempty admission attacks fail. |
| F3 retroactive costs/capacity | Append services and SQL inserts fail closed because no authoritative immutable source exists. Historical envelope checks test database recording time before refusing unavailable authority. | Backdated/provider-exact/fabricated source and policy attacks fail through service and raw SQL. |
| F4 incomplete semantic identity | Pure candidate identity now includes Phase 5 evaluation identity, evaluation evidence/output hashes, and predecessor terminal state in addition to full geometry and frozen dependency identities. | Evidence-only, evaluation-identity-only, and predecessor-terminal changes produce distinct semantic identities. |
| F5 multiple same-direction setups | Exactly one originatable M15 setup is required; any second setup, including same-direction asymmetric geometry, closes as `conflicting_eligible_setups`. | Opposite- and same-direction fixture tests close without a candidate. |
| F6 packet/predecessor parity | One packet validator is shared by assess and replay. SQL allows no packet under the empty requirement map. SQL supersession scope and deferred bidirectional pairing guards are added; replay/audit reject historical bypass fixtures. | Future/cross-instrument/unrequired packets fail service and SQL; trigger-bypassed packet/predecessor fixtures fail replay/audit and arbitrary supersession fails SQL. |
| F7 gate order/reason inference | Engine initializes exactly one gate per reason in canonical `REASONS` order. Explicit Phase 5 reason sets replace substring inference. SQL uses the same ordered tuple. | Exact tuple/count parity and pending/rejected/invalidated/expired fixtures pass. |

## Unchanged boundaries

The active recommendation, lifecycle, portfolio, paper, sizing, task, schedule,
notification, provider/model, and Phase 5.5 files remain source-pinned and do not
import Phase 6A. No schedule, consumer, activation, UI, execution semantics, or
provider/model call is introduced. Original historical records are not mutated;
the v2 audit reports unsafe or v1-only rows rather than relabeling them as v2.

Independent review should focus on SQL/Python empty projection parity, the
prospective authority closures, forward migration behavior with populated v1
tables, exact gate order/mapping, packet replay parity, and candidate/supersession
scope. Engineering completion is not self-acceptance or permission to trade.
