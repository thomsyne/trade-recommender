"""Coverage is not semantic integrity; absence is never neutral."""

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from market.models import Instrument, MarketStateSnapshot
from market.quality import (
    NEW_YORK,
    _market_is_open,
    live_interval_is_aligned,
    registered_candle_completion,
)
from market.state.compute import DESCRIPTOR_VERSION
from market.state.manifest import eligible_observations
from market.state.preview import cutoff_value, preview, scope_value
from market.state.tasks import DEFAULT_GRANULARITIES


def availability(value):
    """Preserve child missingness instead of treating a container as coverage."""
    states, reasons = [], set()

    def visit(node):
        if isinstance(node, dict):
            if "state" in node:
                states.append(node["state"])
            if "reason_code" in node:
                reasons.add(node["reason_code"])
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    state = (
        "partial"
        if "unavailable" in states and "available" in states
        else "unavailable"
        if "unavailable" in states or not states
        else "available"
        if "available" in states
        else "not_applicable"
    )
    return {"state": state, "reason_codes": sorted(reasons)}


class Command(BaseCommand):
    help = "Read-only coverage over at most 7 days; exit 1 on gaps/staleness only with --require-complete."

    def add_arguments(self, parser):
        parser.add_argument("--instrument", nargs="+", default=list(Instrument.Code.values))
        parser.add_argument("--since", required=True)
        parser.add_argument("--cutoff", required=True)
        parser.add_argument("--granularities", nargs="+", default=list(DEFAULT_GRANULARITIES))
        parser.add_argument("--require-complete", action="store_true")

    def handle(self, *args, **options):
        start, cutoff = cutoff_value(options["since"]), cutoff_value(options["cutoff"])
        if not timedelta(0) < cutoff - start <= timedelta(days=7):
            raise CommandError("invalid_coverage_window")
        codes = options["instrument"]
        if (
            not 1 <= len(codes) <= len(Instrument.Code.values)
            or any(c not in Instrument.Code.values for c in codes)
            or len(set(codes)) != len(codes)
        ):
            raise CommandError("invalid_instruments")
        scope = scope_value(options["granularities"])
        result = []
        for code in sorted(codes):
            instrument = Instrument.objects.filter(code=code).first()
            try:
                payload = preview(instrument, cutoff, scope)[0] if instrument else {}
            except ValueError:
                raise CommandError("coverage_computation_unavailable") from None
            for g in scope:
                # Bounded quarter-hour grid includes only complete registered
                # intervals wholly inside the requested range, including DST.
                grid_start = start.replace(
                    minute=(start.minute // 15) * 15, second=0, microsecond=0
                )
                expected = []
                for i in range(674):
                    t = grid_start + timedelta(minutes=15 * i)
                    if t >= cutoff:
                        break
                    if (
                        t >= start
                        and live_interval_is_aligned(t, g)
                        and (g in ("D", "W") or _market_is_open(t.astimezone(NEW_YORK)))
                        and registered_candle_completion(t, g) <= cutoff
                    ):
                        expected.append(t)
                observations = (
                    eligible_observations(instrument, g, cutoff, lookback=1024)
                    if instrument
                    else []
                )
                available = {o.timestamp for o in observations}
                missing = set(expected) - available
                snapshot = (
                    MarketStateSnapshot.objects.filter(
                        instrument=instrument,
                        definition__version=DESCRIPTOR_VERSION,
                        information_cutoff__lte=cutoff,
                        output_payload__requested_granularities__contains=[g],
                    )
                    .order_by("-information_cutoff", "-pk")
                    .first()
                    if instrument
                    else None
                )
                snapshot_fresh = bool(
                    snapshot
                    and (
                        not expected
                        or snapshot.information_cutoff
                        >= registered_candle_completion(expected[-1], g)
                    )
                )
                block = payload.get("granularities", {}).get(g, {})
                families = {}
                for family in ("higher_timeframe", "structure", "liquidity", "fvg", "spread"):
                    value = block.get(family, block)
                    families[family] = {
                        **availability(value),
                        "fresh": bool(expected) and expected[-1] in available,
                        "complete_registered_coverage": bool(expected) and not missing,
                    }
                result.append(
                    {
                        "instrument": code,
                        "granularity": g,
                        "expected_intervals": len(expected),
                        "missing_intervals": len(missing),
                        "complete_registered_coverage": bool(expected) and not missing,
                        "fresh": bool(expected) and expected[-1] in available,
                        "snapshot_available": snapshot is not None,
                        "snapshot_fresh": snapshot_fresh,
                        "feature_families": families,
                        "context_families": {
                            name: availability(payload.get(name, {}))
                            for name in (
                                "monthly_context",
                                "prior_extremes",
                                "opening_range",
                                "event_state",
                                "macro_regime",
                            )
                        },
                        "reason_code": "instrument_not_registered"
                        if not instrument
                        else "no_registered_intervals"
                        if not expected
                        else "registered_intervals_missing"
                        if missing
                        else "snapshot_missing"
                        if not snapshot
                        else "snapshot_stale"
                        if not snapshot_fresh
                        else None,
                    }
                )
        complete = all(r["complete_registered_coverage"] and r["snapshot_fresh"] for r in result)
        self.stdout.write(
            json.dumps(
                {
                    "axis": "coverage",
                    "since": start.isoformat(),
                    "cutoff": cutoff.isoformat(),
                    "policy": "registered-inputs-and-current-definition-snapshot-v1",
                    "complete": complete,
                    "rows": result,
                },
                sort_keys=True,
            )
        )
        if options["require_complete"] and not complete:
            raise SystemExit(1)
