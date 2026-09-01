import json

from django.core.management.base import BaseCommand

from market.provider_observed_successor import successor_readiness


class Command(BaseCommand):
    help = (
        "Report which successor discovery chunks may actually be executed now, and the"
        " plan's execution status: open, an attempt in progress, blocked by a failed"
        " attempt, or successfully complete. A chunk that already has an attempt is never"
        " reported as executable. Read-only: no database write, no provider client."
    )

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(successor_readiness(), sort_keys=True, separators=(",", ":")))
