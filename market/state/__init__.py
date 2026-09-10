"""Phase 4 deterministic market-state engine.

Feature-only and causal: this package computes byte-equivalent canonical market
state for a fixed (definition version, information cutoff, frozen inputs). It
owns no candle ledger, calendar, scheduler, macro store, lifecycle projection or
evidence system of its own — it reads the existing ``market`` and ``research``
contracts. It defines no trade entry, exit or risk rule (docs/phase4/design.md).
"""
