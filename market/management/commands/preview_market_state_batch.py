"""At most eight explicit canonical instrument/cutoff previews; no writes."""

import json

from django.core.management.base import BaseCommand, CommandError

from market.models import Instrument
from market.state.preview import preview, scope_value, selections
from market.state.tasks import DEFAULT_GRANULARITIES


class Command(BaseCommand):
    help = "Read-only batch preview; max 8 INSTRUMENT@aware-ISO-cutoff selections."

    def add_arguments(self, parser):
        parser.add_argument("selection", nargs="+")
        parser.add_argument("--granularities", nargs="+", default=list(DEFAULT_GRANULARITIES))

    def handle(self, *args, **options):
        selected = selections(options["selection"])
        scope = scope_value(options["granularities"])
        rows = []
        for code, cutoff in selected:
            instrument = Instrument.objects.filter(code=code).first()
            if instrument is None:
                raise CommandError("instrument_not_registered")
            try:
                payload, _, _, manifest_hash, _, evidence_hash, quality = preview(
                    instrument, cutoff, scope
                )
            except ValueError:
                raise CommandError("preview_unavailable") from None
            rows.append(
                {
                    "instrument": code,
                    "cutoff": cutoff.isoformat(),
                    "output_payload": payload,
                    "input_manifest_sha256": manifest_hash,
                    "evidence_sha256": evidence_hash,
                    "data_quality_status": quality,
                }
            )
        self.stdout.write(
            json.dumps({"preview": True, "results": rows}, sort_keys=True, ensure_ascii=True)
        )
