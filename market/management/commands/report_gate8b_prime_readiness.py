import json

from django.core.management.base import BaseCommand

from market.provider_observed_successor import successor_readiness


class Command(BaseCommand):
    help = (
        "Report which successor discovery stage the governed sequence has opened, and the"
        " exact logical keys it permits. Read-only: no database write, no provider client."
    )

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(successor_readiness(), sort_keys=True, separators=(",", ":")))
