# Phase 6A corrected candidate verification receipt

Date: 2026-09-11. Scope: the single consolidated F1–F7 correction cycle only.
Original candidate commit/tree and its receipts remain preserved at
`28fb56a0b695328fa46357d0519ea9a46c059046` /
`58409d97bdff612168f697c217b0f35c6126702c`.

## Focused PostgreSQL verification

- PostgreSQL server: `15.19 (Debian 15.19-0+deb12u1)`.
- `POSTGRES_CONN_MAX_AGE=0 .venv/bin/python manage.py test assessments.tests --verbosity 1`
  — 32 tests passed in 7.077s.
- Coverage includes exact SQL/Python empty projection parity, first-insert
  fabricated available assessment refusal, candidate forgery variants,
  canonical empty eligibility and chronology, wrong era/hash/nonempty admission,
  unavailable cost/capacity authorities, packet assess/replay/SQL/audit parity,
  arbitrary predecessor and missing supersession pairing, immutable ledgers,
  exact gate order and explicit reason mapping, same-direction conflict,
  evaluation/evidence/terminal semantic identity, concurrency/idempotency,
  source pins, bilateral import isolation, and migration reversal/forward safety.
- Local migration `0002 → 0003`, empty `0003 → 0002 → 0003`, and populated-v1
  forward preservation passed. Populated correction reversal is deliberately
  refused.
- Read-only audit after applying `0003`:
  `{"checked":0,"has_more":false,"next_after_id":0,"violations":[]}`.

PostgreSQL 17 was unavailable in the orb: only PostgreSQL 15 is installed, and
the Docker client has no daemon socket. No substitute version claim is made.

## Static and integrity verification

- `make check` passed: Ruff checks passed, all 581 files formatted, Django system
  check clean, no migration drift, and compileall clean.
- Implementation pin, successor method digest, and migration SQL method pin agree:
  `9ce72ba4fa5032d010266c06ce2928650bd31338398dee223b477c11c363d3fc`.
- `git diff --check` passed.
- Diff scope check found no changes under active `forecasts`, `operations`,
  `market`, `research`, `config`, `Makefile`, or `assessments/source_pins.py`.
- Corrected source hashes are frozen in `corrected-source-manifest.json`; the
  original `source-manifest.json` and applied migrations `0001`/`0002` are
  byte-preserved.

No broad suite was run. No provider/model was called, and nothing was pushed,
deployed, activated, scheduled, merged, or opened as a pull request. This receipt
is engineering evidence, not independent acceptance or permission to trade.
