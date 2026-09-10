# Phase 4 — acceptance superseded

Descriptor 0.11.0 and migration 0036 add the final recording/concurrency and
prerequisite-chronology corrections. The [current handoff](handoff.md) and
[verification](verification/README.md) are engineering evidence only.
**Acceptance remains superseded pending independent review.**

Descriptor 0.10.0 and migration 0035 are the engineering response to the
[eight-finding independent review](https://ampcode.com/threads/T-01a08985-818d-7698-aa9c-f843744479db).
They are **not self-accepted**. Fresh independent re-review of the committed
changes and retained evidence is required before any acceptance decision.

**Not accepted. Independent re-review is required.** Earlier acceptance and
re-acceptance records are superseded by the independent review in
[the Phase 4 review thread](https://ampcode.com/threads/T-01a088f4-0bb2-7228-b71a-8fcb7760f7d2).
Those records did not establish the complete original Phase 4 contract.

The current corrections are engineering work, not a PM acceptance decision.
Passing focused tests, matching hashes, or an engineer's self-review do not
resolve findings without discriminating evidence and independent review.

Review must cover snapshot input identity, definition/terminology governance,
semantic database enforcement, monthly feasibility, historical timing, FVG
qualification, registered coverage, zone lifecycle, breakout chronology,
complete sessions, query bounds, migration/parity isolation, and documentation.
The original scope and all thirteen findings remain the acceptance criteria.

This document authorizes no push, PR, merge, deployment, provider access,
schedule activation, production backfill, strategy use, or promotion. The
existing runtime-superuser caveat is unchanged: a database superuser can bypass
ordinary trigger protections. It does not excuse semantic forgery by ordinary
writers or missing enforcement at the application boundary.
