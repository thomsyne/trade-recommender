# Phase 6A dormant ledger runbook

## Safety status

Merge is not activation. Phase 6A has no scheduler, task registration, provider or
model transport, Recommendation adapter, portfolio/lifecycle/paper/sizing hook,
notification, UI, or execution consumer. It creates no records at migration or
startup. Do not treat an assessment or eligible trade-intent candidate as permission
to trade.

The canonical initial eligibility set is empty. This repository intentionally has
no management command for appending eligibility. `append_reviewed_eligibility` is a
future owner seam that must only be called by a separately reviewed append operation
after Phase 5.5 acceptance; Phase 6A itself does not accept or translate Phase 5.5
outcomes. Never use the test fixtures as production admission evidence.

## Read-only integrity audit

Against an explicitly selected database:

```console
python manage.py audit_phase6a_integrity --after-id 0 --limit 20
```

The command starts a read-only transaction, applies 60-second statement and
2-second lock timeouts, authenticates upstream Phase 4/5/7 records, and replays the
stored assessment/candidate bytes. It is bounded to 100 rows per call. Continue from
`next_after_id` while `has_more` is true. A nonempty `violations` array is a hard
review stop; the command never repairs, supersedes, or activates anything.

## Assessment preconditions

The explicit Python service `assess(snapshot_id, eligibility_id,
evaluation_ids=..., cost_id=..., capacity_id=..., evidence_packet_id=...)` is the
only write seam. It accepts row identities, not caller booleans or mutable policy.
Use it only after all input records already exist and are immutable. It verifies:

- exact Phase 4 descriptor and candle/evidence manifests;
- semantic Phase 5 replay and same-snapshot attribution;
- eligibility instrument, validity, database admission time, Phase 5 definition,
  role, era and Phase 5.5 hashes;
- exact known-at/stale cost components and frozen capacity currency legs;
- exact Phase 7 packet replay only when the method requires one.

Retries and concurrent identical calls return one canonical assessment. A repeated
semantically unchanged intent creates a closed assessment with
`unchanged_duplicate_intent`, not another candidate. Material geometry/disposition
changes create a candidate with an append-only predecessor/supersession record.

## Conservative v1 tradeoffs

- Only exact Phase 5 M15 setup outputs can originate. H1 setup output closes as
  `m15_confirmation_unavailable`/`unsupported_intent_shape` until a separately
  versioned H1-to-M15 entry adapter exists. Continuous forecasts, overlays and
  readiness outputs never originate.
- Existing Phase 4 event coverage is explicitly `unattested`; v1 therefore closes
  with `event_state_unknown` even if a future eligibility admission exists. This is
  deliberate rather than treating an empty observed event list as safe.
- None of the 19 current Phase 5 strategy versions requires a Phase 7 packet. The
  v1 method pins every requirement to empty and refuses caller-supplied packets or
  eligibility-level required IDs. A future strategy/method version must define that
  requirement prospectively.
- Monthly is only `monthly_context` derived from complete D sessions. Missing
  monthly/M15 data closes. M1 is neither inferred nor required.
- Costs are exact frozen price-unit assumptions, not an executable quote. Capacity
  is consumed from a frozen assessment and is never reconstructed from current
  legacy portfolio state.

## Migration safety

Migrations are forward-only in populated environments. SQL enforces hashes, closed
schemas, relational provenance, database timestamps, append-only mutation guards,
and no truncate. Reversal succeeds only while every Phase 6A table is empty; once
any method/input/assessment exists it raises `phase6a_populated_reverse_refused`
before dropping guards or tables.
