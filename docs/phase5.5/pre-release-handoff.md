# Phase 5.5 engineering handoff — historical holdout remains sealed

The complete development candidate is ready for independent pre-release review,
not independently accepted. No identity is retained or approved for trading.
The coordinator owns independent review, at most one consolidated correction
cycle, and PM traceability. Continue in the existing engineering thread; do not
archive it or open the historical holdout without explicit authorization.

## Reproducible local boundary

- Branch: `phase5.5/offline-validation`, based on merged main
  [b850c4e](https://github.com/thomsyne/trade-recommender/commit/b850c4ea618c34397e86fd8133b7255ff972f8ba).
  Local and remote main were rechecked and still matched that base.
- Revision 1 was frozen at
  [a716a52](https://github.com/thomsyne/trade-recommender/commit/a716a527d6d7ec72149c72a9d608fb70e6dc7146).
  A development-discovered Django descriptor initialization defect required the
  new immutable revision 2 at
  [231e4ad](https://github.com/thomsyne/trade-recommender/commit/231e4adbae4e4f32e179dec51fe9ca33a6529790).
  Both commits precede their logged development runs. Formula, simulator, cost,
  population and threshold choices did not change in that correction.
- Registration: `fa7b34caf25c033ee2034e145f42d7948997f1526f4ec04e43689cd19bd562e7`.
  Original Phase 5 implementation digest remains
  `e67a882b0733ac0282101fcab7b65fc8e2f9ff15f2bd6085453f8394bef69e47`.
- `evidence-index.json` lists all 33 exact changed paths, all preceding checkpoint
  commits, 62 closed private artifact hashes, and the final catalog/seal evidence.
  The commit containing this handoff is the final engineering checkpoint. Changes
  are limited to `.gitignore`, eight new validation modules, three new test files,
  and Phase 5.5 documents/evidence. Original definitions, migrations, prospective
  populations, production trees and earlier negative failed-break evidence are
  unchanged. Nothing was pushed, merged, deployed or activated.
- Use the isolated `.candidate-data/phase55-v1/venv` and the four single-thread
  numeric environment settings in `engine-runbook.md`. Do not replace this with
  the shared virtualenv. Source/runtime/manifest drift refuses admission.

## Coverage qualifies retrospective diagnostics, not execution integrity

The outcome-blind audit and owner prior-use attestation preceded development.
The canonical source-of-truth population is EUR_USD, GBP_USD, EUR_GBP, USD_CAD,
USD_JPY, AUD_USD, USD_CHF, NZD_USD, EUR_JPY, GBP_JPY, AUD_JPY and AUD_CAD.
Read-only OANDA acquisition governed 2,592 chunks / 3,828,305 final BA observations
over W/D/H4/H1/M15: 240 instrument/granularity/period groups. All groups exceeded
the registered 95% raw coverage floor. There were zero duplicate intervals and
zero unexpected regular-open intervals. The 494 outside-regular observations
remain in the raw cache and were excluded by timestamp, not outcomes. Local gaps
remain explicit and block affected decisions/executions.

No replacement dates were needed for the model-based regular-session population.
Frozen half-open UTC periods are:

| Period | Interval | Split |
|---|---|---|
| Warmup | [2017-01-01, 2019-01-07) | — |
| Development | [2019-01-07, 2025-01-06) | 2022-01-03 |
| Sealed historical holdout | [2025-01-06, 2026-09-07) | 2025-11-10 |

The holdout is 87 complete ISO weeks, with halves of 44 and 43 weeks. Owner
attestation: “I attest that no Phase 5 strategy results for that period have
previously been inspected.” Its exact metadata manifest is
`1dda2526a48919459f9c1be875fd4493a266bdec6e15886b60183c142915572b`:
456 chunks / 660,885 observations. The final metadata check matched it without
selecting price blobs. The validation catalog has **zero holdout checkpoints**.
Only authorized acquisition/integrity/coverage work accessed held-out data;
no holdout strategy outcomes were computed or inspected.

Actual acquisition clocks were retained. Final candles are later-acquired
retrospective inputs, not historical known-at evidence. Observed BA spread is
separate from modeled commission/slippage; the preregistered cost model is not
broker-observed execution. Genuine financing/rollovers, exceptional-session and
macro vintages, and carry forwards/ranking remain absent. Overnight-dependent,
range/event-clearance, macro and carry evaluations remain unavailable as required.

## All 19 identities remain inconclusive under the frozen evidence rule

Development covers all 180 baseline/instrument chains: 394,380 daily checkpoints,
2,191 days per chain. Four risk identities use the same baseline opportunities.
There are 975 verified JSON/English report pairs: 900 instrument views and 75
separately attributed aggregates. No family or risk-overlay baselines are pooled.
The report-set/proposal identity is
`e8b890b55ec507c597e94795b458ff985640d48f7930de307dc205b66e80d3b0`.
`development-proposal.json` indexes every report, both file hashes, all 19 formal
dispositions and all 75 aggregate views. Full reports remain in the private cache.

**No candidate meets the preregistered development gates.** The formal result is
19 inconclusive identities, zero qualifying candidates and zero formal rejects:
the frozen evidence-first rule assigns inconclusive before economic rejection
when mandatory evidence is incomplete. This is not a pass, and it does not hide
the negative diagnostics or failed robustness gates. This priority is an explicit
reviewable choice, not a post-outcome threshold adjustment.

The table below is rounded CAD diagnostic net, not full-population execution
return or a pooled strategy portfolio. Null means unavailable. Every row is
formally inconclusive; full precision, halves, costs, tails, missingness and other
registered fields remain in its reports.

| Baseline identity | Modeled trades | Baseline net | Adverse-cost net | Extra-interval net |
|---|---:|---:|---:|---:|
| ewmac-d-v1 | 0 | null | null | null |
| breakout-d-v1 | 0 | null | null | null |
| fast-mr-h1-v1 | 6 | 306.40 | 100.27 | -151,628.87 |
| orb-m15-wick-v1:london | 222 | -14,636.03 | -25,680.10 | -14,651.83 |
| orb-m15-confirmed-v1:london | 221 | -4,416.31 | -15,742.51 | -7,273.91 |
| orb-m15-fvg-v1:london | 9 | -2,390.51 | -2,647.29 | -2,058.94 |
| orb-m15-wick-v1:new_york | 234 | -10,287.84 | -21,516.36 | -17,105.48 |
| orb-m15-confirmed-v1:new_york | 342 | -17,777.11 | -34,180.77 | -26,007.84 |
| orb-m15-fvg-v1:new_york | 2 | 994.96 | 904.49 | 1,032.63 |
| pullback-m15-v1 | 17 | -1,760.79 | -2,848.48 | -1,092.25 |
| pullback-h1-v1 | 4 | -852.64 | -1,099.74 | -722.83 |
| phase5-sweep-reversal-v1 | 1,207 | -83,357.80 | -141,284.40 | -80,598.29 |
| phase5-acceptance-continuation-v1 | 6,425 | -422,135.76 | -718,947.84 | -418,215.08 |
| range-m15-v1 | 0 | null | null | null |
| carry-readiness-v1 | 0 | null | null | null |

The remaining four identities are `fixed-risk-v1`, `ewma-risk-v1`,
`garch-t-risk-v1` and `macro-risk-v1`: each has 15 separately attributed paired
aggregate views, all inconclusive. Fixed/EWMA/Student-t GARCH never exceed baseline;
macro is unavailable risk-only evidence, never an independent direction.

Neither FVG identity establishes a positive paired weekly increment: the matched
subset has zero total increment, with extensive unavailable/unmatched days.
New York FVG's two positive diagnostic trades do not establish survival. Fast MR
retains adverse-limit-h1-v1 and makes no executable-fill claim; its positive
six-trade baseline is inadequate and fails the extra-latency scenario. Candle
data establishes neither path, queue nor actual fills. Drawdown is realized,
not mark-to-market. UTC ISO weeks, not raw trades, are the dependence unit.

## Verification, limitations and cleanup

- Focused PG15: 99 passed. Final synthetic run: 37 passed, six database-dependent
  skips (43 total). Lint/format: passed, 549 files. Django checks, no migration
  drift and compilation passed at the unchanged source candidate.
- Complete PG17 attempt: 1,563 tests ran in 3,661.653 seconds; one class-setup error
  blocked six methods. The `DetectorV2QueryBudgetTests` legacy discovery-plan
  fixture error reproduced on merged main. The full suite is **not green**.
  The earlier PG15 broad run was interrupted and is not a pass.
- Final idle-catalog verification checked all 180 chains, body/predecessor hashes,
  independent opportunity counts and checkpoint identities. All 975 report pairs
  passed canonical bytes, identity, English text, population and seal checks.
  Actual-data replay and preloaded/ordinary exporter byte-equivalence checks
  passed. The original revision's body, real clock and 21,921 checkpoint hashes
  remain intact. Static inspection found no outside consumer imports or changed
  production trees.
- One redundant worker encountered a SQLite lock timeout during a concurrent
  full-chain read. That read was stopped, the other worker completed the chain,
  and the final idle-catalog pass succeeded. Interrupted logs remain evidence,
  not passes. Full-chain reads require idle writers or a temporary backup.
- Owned batch/report/test/tail processes, temporary report backups, disposable
  PG15/PG17 clusters, base reproduction checkout and PG17 build were cleaned.
  Private acquisition, catalogs, reports, logs and the isolated runtime are
  intentionally preserved. Shared environments and unrelated work were preserved.
- Manual offline forward-shadow capability starts 2026-09-11. It currently
  reports zero complete weeks and no collected confirmation evidence. The 8–12
  week window ends 2026-11-06 to 2026-12-04; no future evidence was invented and
  no collection or schedule was activated.

The engine deliberately has no historical holdout release option. Independent
pre-release review and explicit authorization are still required for continuation;
none of this evidence authorizes trading, production eligibility, recommendations,
orders or activation. No push, PR, merge, deployment or schedule was performed.
