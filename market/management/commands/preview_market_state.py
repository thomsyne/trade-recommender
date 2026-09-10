"""Dry-run: compute one market-state payload and print it WITHOUT persisting.

Read-only preview of the descriptor output for an instrument at a cutoff. It
builds the same canonical payload the durable task would persist, but writes
nothing to the database and calls no provider.
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.models import Instrument
from market.state.compute import DESCRIPTOR_KEY, DESCRIPTOR_VERSION
from market.state.preview import cutoff_value, preview, scope_value
from market.state.tasks import DEFAULT_GRANULARITIES


class Command(BaseCommand):
    help = "Preview a market-state snapshot payload without persisting (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("instrument", choices=Instrument.Code.values)
        parser.add_argument("--cutoff", default=None, help="aware ISO-8601; defaults to now")
        parser.add_argument("--granularities", nargs="+", default=list(DEFAULT_GRANULARITIES))

    def handle(self, *args, **options):
        scope = scope_value(options["granularities"])
        cutoff = cutoff_value(options["cutoff"]) if options["cutoff"] else timezone.now()
        if options["instrument"] not in Instrument.Code.values:
            raise CommandError("invalid_instrument")
        instrument = Instrument.objects.filter(code=options["instrument"]).first()
        if instrument is None:
            raise CommandError("instrument_not_registered")
        try:
            payload, _, _, manifest_sha256, _, _, quality = preview(instrument, cutoff, scope)
        except ValueError:
            raise CommandError("preview_unavailable") from None
        self.stdout.write(
            json.dumps(
                {
                    "preview": True,
                    "definition": [DESCRIPTOR_KEY, DESCRIPTOR_VERSION],
                    "input_manifest_sha256": manifest_sha256,
                    "data_quality_status": quality,
                    "output_payload": payload,
                },
                sort_keys=True,
                indent=2,
            )
        )
