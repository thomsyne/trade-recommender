import json
import re

from django.core.management.base import BaseCommand, CommandError

from market.discovery_waves import build_wave_manifest


class Command(BaseCommand):
    help = (
        "Render the deterministic Gate 4 wave manifest for the 131 remaining"
        " provider-observed discovery chunks without database or provider access"
    )

    def add_arguments(self, parser):
        parser.add_argument("--canary-semantic-inventory-sha256", required=True)

    def handle(self, *args, **options):
        semantic_sha = options["canary_semantic_inventory_sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", semantic_sha):
            raise CommandError("canary semantic inventory sha must be 64 lowercase hex")
        self.stdout.write(json.dumps(build_wave_manifest(semantic_sha), indent=2, sort_keys=True))
