"""Read-only semantic-integrity report over persisted market-state snapshots.

Recomputes every bound hash and rechecks causal invariants without mutating
anything, prints a bounded JSON report, and exits nonzero when any violation is
found. Availability/freshness/coverage are separate axes and not reported here.
"""

import json

from django.core.management.base import BaseCommand

from market.models import MarketStateSnapshot
from market.state.integrity import verify_snapshots


class Command(BaseCommand):
    help = "Verify semantic integrity of persisted market-state snapshots (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--instrument", default=None)
        parser.add_argument("--after-id", type=int, default=0)

    def handle(self, *args, **options):
        snapshots = MarketStateSnapshot.objects.all()
        if options["after_id"]:
            snapshots = snapshots.filter(pk__gt=options["after_id"])
        if options["instrument"]:
            snapshots = snapshots.filter(instrument__code=options["instrument"])
        report = verify_snapshots(snapshots)
        self.stdout.write(json.dumps(report, sort_keys=True, indent=2))
        if report["violation_count"]:
            raise SystemExit(1)
