# Phase 2 design and invariants

`Instrument.active` remains decision eligibility. A single `ingestion_enabled` Boolean
owns live acquisition eligibility. The migration preserves identities and active states,
enabling collection for the twelve canonical codes and existing active rows; unknown
inactive rows default disabled. Seeding preserves explicit operator collection disables.
No historical acquisition or frozen research contract reads the new flag.

Canonical seed repairs metadata and job identity fields only when different, preserves
existing deadlines, and staggers new jobs in deterministic instrument/granularity slots.
Existing operational missed-run policy remains authoritative; canonical defaults stay
latest-only. Task execution rechecks collection eligibility and source availability,
including jobs queued before disablement. Successful ingestion invokes decision work
only for active instruments. Direct decision creation entrypoints also reject inactive
instruments before evidence or provider work. Downstream consumers retain active filters.

The read-only onboarding command emits 32 bounded series records, checks registry and
schedule integrity and forbidden artifact roots, and reuses live freshness semantics.
No UI, prompts, strategies, historical evidence, or production activation changes.
