# Revision 6 reconciled engineering handoff — holdout sealed

Engineering reconciliation is complete for the completed development publication.
This is a candidate for independent correction-closure review, **not acceptance,
holdout release, strategy retention, Phase 6 promotion or trading authorization**.
No historical outcome replay, historical solver refit or market-data provider
request was made.

## Source and artifact boundary

- Branch: `phase5.5/offline-validation` in the original Mac checkout. Its merged
  Phase 5 base remains [b850c4e](https://github.com/thomsyne/trade-recommender/commit/b850c4ea618c34397e86fd8133b7255ff972f8ba).
  This branch was not rebased onto the subsequently advanced local `main`.
- Scientific source: [1db619f](https://github.com/thomsyne/trade-recommender/commit/1db619f03ed9bdd8553c325a3e9d26e74fed1d34),
  frozen before outcomes at [eda52d7](https://github.com/thomsyne/trade-recommender/commit/eda52d784e533c26d080f65a5989718ebcf83654).
  Registration remains
  `c64f5731ea8d0e77a9d6ae4889eaffec8135288881e75d039a58d30c7a566237`.
- New read-only reconciliation tools/tests are checkpointed at
  [684ce6a](https://github.com/thomsyne/trade-recommender/commit/684ce6ab27f3cde6d77e24ae99bb2a57e018cae2).
  They inspect persisted decisions and amounts; they do not invoke `Catalog`,
  strategy evaluation, simulation, acquisition, or report publication. Their
  observations cannot confer a verified report identity or acceptance.
- No registered scientific source or report behavior changed in reconciliation.
  All 46 revision-6 source hashes match; all six registration identities and their
  formula/simulator population, manifests, dates, costs and thresholds remain
  unchanged. No revision 7 or replacement report identity was minted.
- The successful worker run ended `2026-09-11T20:02:36Z`, after 5h54m17s.
  Original archive: `outputs/20260911T200236Z/development.tar.gz` in the private
  `phase55-validation-590759815902-20260911132955760100000001` bucket.
  Its local `revision6-completed.tar.gz` SHA256 is
  `ae99296cf07ccf3bbb9d7a97378d2517371c8f2f60aaea83ac207919173043d1`.
  Worker success/exit-0/completion-marker receipts are preserved completion
  evidence, distinct from the newly executed semantic checks below.

Private evidence is under `.candidate-data/phase55-v1/reconciliation-v6/`.
`reconciliation-index-v2.json` indexes 22 observations/logs by hash and size;
its SHA256 is `35f8f2440fe2bed36bc743e27a71b88ef6a13929915a6010d9c0bb28d4bb309c`.
It adds the independent revision-2 metric check without overwriting the first
index, `82d1122fffde4e375111418a5c3bc6dc298eafff5babd0e51bf35032924c0e49`.
No raw reports, catalogs, source rows, credentials or provider payloads are committed.

## The entire population reconciles, including unavailable and losing results

The frozen population is 15 baseline/readiness identities, each with its own four
risk-overlay views, over the 12 canonical instruments plus its attributable
aggregate: **975 reports = 900 instrument views + 75 aggregates**. These cover all
19 Phase 5 identities without pooling families or overlay baselines. Every expected
cell is present exactly once; zero report cells are excluded, duplicated or missing.
Unavailable opportunity populations remain inside their reports, not filtered out.

All four catalogs were opened read-only after catalog-type/period controls.
All **394,380 checkpoints / 180 chains / 2,191 days per chain** passed stored-byte,
registration, attribution, UTC chronology, predecessor, decision/state, occupancy,
end-state and modeled gross-minus-cost/net-account-return checks. Every report and
same-session comparator terminal binding matches its complete chain. This checks
stored decisions against stored results; it does not repeat their market-data
evaluation or supersede the original replay-at-publication evidence.

Independent arithmetic checked **2,925 scenario views** against the saved modeled
amounts and risk multipliers: trade counts, every money category, account
denominators, duration, ISO-week dependence components, halves, side/volatility
strata, concentration, remove-best instrument/month, weekly tails, realized
drawdown, concurrent positions and shared-currency overlap. A second full
decision-population pass checked states and exact unavailable-reason counts.
Leaf-to-aggregate counts, groups, halves, weekly and money sums reconcile without
silent filtering or double counting. Aggregates allocate 12 independent CAD
100,000 accounts; they are not one pooled trading portfolio.

Decimal amounts are checked at 80-digit precision, retaining nonzero leaf-sum
rounding deltas. The only permitted discrepancy is an explicit operation-count
bound derived from Decimal34 summation precision and magnitude, not a fixed
economic tolerance. Individual checkpoint gross-cost-net accounting uses the
registered operation order and exact equality. No reported cent-scale difference
was waived as rounding.

All **975 English files** match canonical JSON round trips and reversed scenario
dictionaries. Independent checks cover scenario order, opportunities/trades,
costs, missingness and halves; the structured checks validate attribution,
limitations, units, period and every threshold gate underlying the remaining
rendered statements. All three scenarios, adverse results, paired comparators and
gate failures are retained. No English file or original report was rewritten.

## Exact pairing remains incomplete evidence, not an inferred advantage

All **2,418 paired scenario views** reconcile by exact baseline, instrument,
session and opportunity, including null/missing and occupied outcomes. The ORB
check inspected 75,120 FVG/confirmed opportunity keys, rejecting duplicate or
missing same-session comparator keys. Both sides use the same registration,
calendar, cost scenario and account terms. Fixed/EWMA/GARCH/macro remain paired
views of their own baseline population, never independent directional strategies.

London FVG has 368 matched opportunities and 18,412 unavailable/unmatched per
scenario; New York has 185 and 18,595 respectively. Their exact paired increments
are zero in all three scenarios, not positive. The frozen positive-FVG-increment
gate therefore fails; these are not incremental survivors. Unavailable FVG days
were not recoded as zero-return no-setup days. The synthetic pairing check uses
asymmetric candidate/comparator amounts (-7 versus +3) so self-comparison cannot
pass it. It rejects duplicate/missing-session inputs and distinguishes an
unavailable opportunity from a zero-return matched opportunity.

## All prior revisions are accounted for; only GARCH report metrics changed

`revision-coverage.json` enumerates every one of the 180 expected chains for each
revision, including absent chains and exact partial cutoffs. Partial runs have no
complete publication/disposition; absent evidence is not assigned a zero result.

| Revision | Main-run checkpoints | Complete / partial / absent chains | Published reports |
|---|---:|---:|---:|
| 1 | 21,921 | 10 / 1 / 169 | 0 |
| 2 | 394,380 | 180 / 0 / 0 | 975 |
| 3 | 48,125 | 20 / 4 / 156 | 0 |
| 4 | 64 | 0 / 2 / 178 | 0 |
| 5 | 4,012 | 0 / 5 / 175 | 0 |
| 6 | 394,380 | 180 / 0 / 0 | 975 |

Revision 5's separately retained 64-checkpoint Linux equivalence catalog is not
pooled into its main run. It also matched revision 6 on its 15 setup opportunities.
The 64 saved Mac reference checkpoints exactly match the scanned revision-4
catalog. The revision-5 partial archive was retrieved read-only from its existing
S3 object; SHA256 `9baaa50ddc3159b4da69fe3499e0e32c3f31725a28c3592fad40e780cac86347`
matches the preserved receipt. Its main validation catalog is empty; the four
worker catalogs provide the 4,012 checkpoints above. No partial report set exists
to substitute for a full publication.

All 975 revision-2 → revision-6 dispositions are **inconclusive → inconclusive**.
`report-reconciliation.json` records each exact strategy/instrument/baseline view,
both report identities, and every changed scenario/comparator/gate field:
909 views unchanged, 66 GARCH views changed (57 instrument views and 9 aggregates),
with 9,355 changed nested fields. Eight views have changed gates, but no changed
formal disposition. All other baseline/fixed/EWMA/macro report metrics match.
The same independent metric checker also reconciles all 2,925 prior revision-2
scenario views against their own saved modeled results, rather than accepting
their metrics on hash evidence alone.

| Prior revision | Setup opportunities compared with revision 6 | Unchanged | Changed, GARCH only |
|---|---:|---:|---:|
| 1 | 775 | 445 | 330 |
| 2 | 35,827 | 30,402 | 5,425 |
| 3 | 6,233 | 6,089 | 144 |
| 4 | 15 | 15 | 0 |
| 5 main run | 213 | 213 | 0 |

These comparisons cover every persisted setup opportunity in the earlier runs,
including unavailable and occupied scenario outcomes, not just modeled trades.
Decisions, baseline execution results, evidence references and other overlays
match; every difference is a saved GARCH multiplier or nonconvergence status.
Within the same Mac runtime, revisions 1/3/4 exactly match revision 2 on all their
overlapping setup opportunities. The Linux revision-5 main/equivalence prefixes
match revision 6. This isolates the observed changes to the registered numerical
runtime transition, not R1–R5 formula/cost/data changes or the descriptor cache.

For revision 2 → 6, 4,606 GARCH outputs changed multiplier while remaining
available; 398 became available and 421 became unavailable. Among opportunities
with any modeled scenario, 559 changed available multipliers, 51 lost availability
and 51 gained availability. Every affected report metric is derived from these
saved changes, including modeled counts and adverse/latency results. The exact
solver/backend numerical mechanism has **not** been established by a new fit;
package-version pins do not establish cross-OS bitwise equivalence.

The frozen runtime changed from Darwin/Python 3.11.4 to Linux/Python 3.11.16;
the scientific package versions remained pinned. This limitation is not evidence
of different strategy formulas, nor a claim of universal deterministic results
across different registered runtimes. No rerun or numerical tuning was used to
make the two populations agree.

The following shows baseline-scenario aggregate CAD diagnostics to four decimal
places for readability; exact values and all three scenarios are retained in
`aggregate-dispositions.json` and the full transition table, not rounded in evidence.

| GARCH paired baseline | Revision 2 net CAD | Revision 6 net CAD | Trades, old → new |
|---|---:|---:|---:|
| Fast MR H1 | 415.8126 | 415.8121 | 6 → 6 |
| London confirmed ORB | 2,422.8362 | 1,919.9769 | 35 → 34 |
| New York confirmed ORB | -3,064.4414 | -3,045.3083 | 91 → 92 |
| London wick ORB | -755.6523 | -1,258.5152 | 32 → 31 |
| New York wick ORB | 1,298.2648 | 1,050.3630 | 48 → 50 |
| Acceptance continuation | -49,767.2472 | -46,726.4596 | 557 → 560 |
| Sweep reversal | -9,756.4741 | -10,012.6551 | 99 → 99 |
| Pullback H1 | -852.4324 | -852.4325 | 4 → 4 |
| Pullback M15 | -1,565.4026 | -1,565.4146 | 16 → 16 |

For example, GARCH/fast-MR extra-latency net worsens from -138,534.1315 to
-140,392.0160 CAD (842 → 838 modeled trades); GARCH/acceptance adverse-cost net
changes from -76,807.4371 to -73,705.2295 CAD. Positive baseline snippets do not
override adverse results, unavailable populations, execution limits or thin samples.

## Reproduction uses saved evidence only

Run from the original checkout with the isolated interpreter. Output paths must
be new files; do not overwrite indexed receipts. Never pass the acquisition
database to these tools.

```sh
P=.candidate-data/phase55-v1/venv/bin/python
R=.candidate-data/phase55-v1/reconciliation-v6
$P -m research.validation_reconciliation "$R/reports-v6" \
  .candidate-data/phase55-v1/reports docs/phase5.5/frozen-registration-v6.json \
  "$R/new-report-check.json"
$P -m research.validation_reconciliation_checkpoints "$R/worker-0.sqlite3" \
  docs/phase5.5/frozen-registration-v6.json "$R/new-checkpoints-0.json"
```

The checkpoint command was executed for workers 0–3 and each retained earlier
catalog under its own registration. `check_metrics(reports, receipts, registration)`
in `research.validation_reconciliation_metrics` takes `read_reports` output and
those compact checkpoint receipts. `check_populations(reports, rows)` was then
run over every persisted row from the four already-checked development catalogs,
using `sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)` and
`SELECT body FROM checkpoint ORDER BY rowid`. No simulator is called by either
function. `metric-population-check.json` records their combined result.

The complete published transition matrix compares `scenarios`,
`paired_comparator`, `proposal` and `development_gates` recursively for all 975
attribution keys. Earlier setup receipts are joined by exact strategy/instrument/
opportunity; only registration-specific hash fields are excluded from the saved
execution comparison. All changes, including signs, counts, missingness, reasons,
weekly/half metrics and adverse/latency values, remain in the private delta tables.

## Verification, boundaries and remaining review

Newly executed: 75 focused synthetic/disposable tests, **69 passed and six explicit
PostgreSQL-DSN skips**; lint, formatting, diff checks, Django system checks and
in-memory-SQLite migration-drift checks passed. The new auditor initially compared
timestamp spellings rather than instants at expired occupancy. That auditor-only
defect failed the artifact scan; an asymmetric microsecond-spelling regression
reproduces it red and passes the corrected comparison. No scientific outcome or
registered source was changed to resolve it.

Preserved, not rerun: PG15 and PG17 targeted correction checks each passed 116
tests. The earlier complete PG17 suite ran 1,580 tests and failed with two errors;
it remains **not a suite pass**. Discovery-plan failure reproduced on merged base;
the observation future-timestamp failure did not. Observed clock skew is consistent
with the second error but is not proven causal. See `correction-verification.md`.

The original acceptance matrix remains the requirement source:

| Requirements | Reconciliation traceability |
|---|---|
| A1–A4 | Original outcome-blind audit, acquisition clocks, canonical population and owner attestation preserved; no re-audit of sealed payloads. |
| B1–B3 | Six immutable registrations and 46 current source hashes checked; period/manifest/cost/threshold equality; archive and checkpoint seal controls. |
| C1–C2 | All stored causal chains checked; focused restart/admission tests; no new consumer, schedule, eligibility or production path. |
| D1–D6 | Daily mapping remains financing-blocked in real data; all 19 identities separately reported; exact overlay/FVG pairing; macro/range/carry mandatory gaps retained. |
| E1–E2 | No acquisition or new scientific replay; original provenance/model labels and execution limitations preserved; stored cost accounting checked. |
| F1–F5 | Full grid, text, every gate, counts, money, dependence, robustness summaries, exact pairing, prior transitions and all adverse/missing outcomes reconciled. |
| G1 | Offline future-shadow capability unchanged; no invented elapsed future evidence, activation or schedule. |
| G2–G3 | New focused checks and private hashed receipts separated from preserved PG receipts; clean local checkpoint and independent-review handoff. |

Formal development result: **19 inconclusive identities, zero qualifying candidates,
zero formal rejects, zero retains**. The frozen evidence-first rule takes precedence
over economic rejection when integrity/coverage is missing; inconclusive is not a
pass. Genuine financing, exceptional-session/calendar and macro vintages, range
clearance, carry forwards/rollovers/ranking remain missing. Thin samples, adverse
results and numerical-runtime sensitivity remain visible, not repaired by tuning.

Holdout remains [2025-01-06, 2026-09-07), split 2025-11-10, 87 complete ISO weeks.
No holdout prices, outcomes, new labels or tuning were accessed. The reconciliation
archive contains no acquisition database; the worker's development-only projection
has no sealed price blobs. Original Mac holdout data remain behind the unchanged
sealed loader, not claimed physically deleted. No holdout checkpoint exists.

The dedicated instance `i-06a84e1ebe6467381` was freshly confirmed **stopped** with
a read-only EC2 metadata request. No compute was started. All owned reconciliation
processes finished; disposable test directories/connections closed. Private raw
receipts remain for review. Phase6A and Phase7 worktrees were not changed. No push,
PR, merge, deployment, activation, schedule, recommendation, order or trade occurred.

Independent review should close R1–R5 against the unchanged frozen scientific
candidate, assess the new reconciliation methods/receipts and GARCH runtime
limitation, verify the complete grid/pairing/revision delta attribution, and retain
the PG17 limitations. Review must not open the historical holdout. The coordinator
owns subsequent PM traceability and any explicit release decision.
