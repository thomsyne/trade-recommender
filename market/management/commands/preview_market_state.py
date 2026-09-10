"""Dry-run: compute one market-state payload and print it WITHOUT persisting.

Read-only preview of the descriptor output for an instrument at a cutoff. It
builds the same canonical payload the durable task would persist, but writes
nothing to the database and calls no provider.
"""

import json
from datetime import UTC, datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.models import Instrument, MarketStateDefinition
from market.state.canonical import identity_digest
from market.state.compute import (
    DESCRIPTOR_DEFINITION,
    DESCRIPTOR_KEY,
    DESCRIPTOR_VERSION,
    build_market_state,
)
from market.state.tasks import DEFAULT_GRANULARITIES


class Command(BaseCommand):
    help = "Preview a market-state snapshot payload without persisting (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("instrument", choices=Instrument.Code.values)
        parser.add_argument("--cutoff", default=None, help="aware ISO-8601; defaults to now")
        parser.add_argument("--granularities", nargs="+", default=list(DEFAULT_GRANULARITIES))

    def handle(self, *args, **options):
        instrument = Instrument.objects.get(code=options["instrument"])
        if options["cutoff"]:
            cutoff = datetime.fromisoformat(options["cutoff"])
            if cutoff.tzinfo is None:
                raise CommandError("cutoff must be timezone-aware")
            cutoff = cutoff.astimezone(UTC)
        else:
            cutoff = timezone.now()
        # Read-only preview: build an in-memory, UNSAVED definition instance so
        # the command never writes a MarketStateDefinition row. build_market_state
        # only reads .key, .version, .definition and .definition_sha256.
        definition = MarketStateDefinition(
            key=DESCRIPTOR_KEY,
            version=DESCRIPTOR_VERSION,
            definition=DESCRIPTOR_DEFINITION,
            definition_sha256=identity_digest(DESCRIPTOR_DEFINITION),
        )
        payload, _scope, _manifest, manifest_sha256, _evidence, _evidence_sha, quality = (
            build_market_state(instrument, definition, cutoff, options["granularities"])
        )
        self.stdout.write(
            json.dumps(
                {
                    "preview": True,
                    "definition": [definition.key, definition.version],
                    "input_manifest_sha256": manifest_sha256,
                    "data_quality_status": quality,
                    "output_payload": payload,
                },
                sort_keys=True,
                indent=2,
            )
        )
