# Outcome-blind acquisition qualification, 2026-09-11

All 2,592 registered requests completed: 3,828,305 final BA candle observations,
12 canonical instruments, W/D/H4/H1/M15, 240 instrument/granularity/period groups.
The canonical population is EUR_USD, GBP_USD, EUR_GBP, USD_CAD, USD_JPY,
AUD_USD, USD_CHF, NZD_USD, EUR_JPY, GBP_JPY, AUD_JPY, AUD_CAD.
`acquired-coverage.json` binds every chunk's original metadata digest, acquisition
clock, observed bounds/counts, nominal missingness, duplicates and exclusions.
No strategy result was computed or inspected in producing this qualification.

Acquisition v2 completed 2,364 chunks. It refused an incomplete W candle starting
2026-09-04 whose registered completion lies beyond the sealed end. Acquisition
v3 excludes that boundary candle before enforcing in-period completeness and
completed the remaining 228 chunks. Its explicit predecessor registration retains
v2 identities, metadata, compressed bytes, source digests and acquisition clocks
unchanged. Neither failed attempts nor previous registrations were deleted.
Nine focused acquisition tests passed, including this boundary and lineage case.

The initial regular-calendar comparison identified 494 extra observations: 116
in warmup and 378 in development. Timestamp-only classification found all 494
outside the NY regular-session model, and **zero unexpected regular-open
intervals and zero duplicates**. These observations remain in the raw private
cache and metadata audit. The new retrospective loader excludes them by timestamp,
not by prices/results, and does not assert that they were broker errors or holidays.
Weekly Friday alignment is separate from the daily/intraday market-open rule.

The protocol's raw coverage floor is 95% per group after these exclusions, plus
192 warmup daily observations. Every group exceeds the floor; all local missing
intervals still block affected decisions/executions. A regular-calendar model is
not genuine exceptional-session clearance. No calendar vintage was backdated.

## Dates selected without outcomes

No replacement is necessary for the regular-session retrospective diagnostic
population. Freeze the proposed UTC half-open periods:

- Warmup: [2017-01-01, 2019-01-07).
- Development: [2019-01-07, 2025-01-06), split at 2022-01-03.
- Historical holdout: [2025-01-06, 2026-09-07), split at 2025-11-10:
  87 complete UTC ISO weeks, halves 44 and 43.

Owner attestation, verbatim: “I attest that no Phase 5 strategy results for that
period have previously been inspected.” This supplements the earlier metadata,
code/history audit; it is not a claim to know every person's activity from SQL.
The historical holdout remains sealed. Only acquisition/integrity/timestamp
coverage operations accessed its cache. No holdout strategy calculation is
authorized by this document. Executable registration and independent pre-release
review remain outstanding.

## Evidence limitations remain mandatory

Observed BA spread is separate from the published-reference modeled commission
reserve and spread-scaled slippage scenarios in `validation-contract.md`.
No genuine historical financing/rollover series, exceptional-session vintages,
macro event vintages or carry forwards/ranking were established. Intraday
diagnostics are model-based retrospective, never broker-observed execution or
integrity-clean retention. Overnight-dependent, macro, carry and range clearance
remain unavailable. General human market knowledge does not negate the attestation.
