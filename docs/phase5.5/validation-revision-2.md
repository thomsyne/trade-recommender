# Validation runner revision 2 — development-discovered initialization defect

Revision 1 was frozen in [the registration checkpoint](https://github.com/thomsyne/trade-recommender/commit/a716a52) before development and remains preserved
in `frozen-registration.json`, its local catalog registration and daily checkpoints.
Its first development run stopped when the liquidity lifecycle helper imported
`market.state.compute.DESCRIPTOR_DEFINITION`, which imports Django model classes.
An uninitialized standalone process cannot import those classes. No holdout
outcome was opened or computed; no incomplete run is a pass.

Revision 2 initializes only the market model registry, with Django's nonfunctional
dummy database backend, when standalone retrospective liquidity descriptors need
it. Existing initialized test/prospective contexts are not reconfigured. The
descriptor is still the unchanged original implementation; no historical snapshot
or production persistence function is invoked. A fresh-process synthetic test
must exercise the real lifecycle constant import and verify the dummy backend.

The new registration binds all first-party market-state source modules and the
market app/model declarations, including the formerly implicit lifecycle policy
dependency. It explicitly supersedes the first registration; the old registration
and evidence are never rewritten. Reports identify validation revision 2.

This is a runner initialization/source-binding correction, not a new trading
hypothesis. All original Phase5 formula/simulator digests, instrument population,
dates, cost assumptions, filters, thresholds, opportunities, missingness and
retention gates remain unchanged. Restart the full development population under
the new identity; do not merge partial revision-1 checkpoints into revision 2.
Freeze the new executable registration before its development run. The holdout
stays sealed with no release option. Independent pre-release review has not begun.
