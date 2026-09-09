import json
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from forecasts.integrity import report


class Command(BaseCommand):
    help = (
        "Read-only Phase3 target, lifecycle and experiment integrity; legacy counts are separate."
    )

    def add_arguments(self, parser):
        parser.add_argument("--as-of")

    def handle(self, *args, **options):
        as_of = None
        if options["as_of"]:
            try:
                as_of = datetime.fromisoformat(options["as_of"])
                if not timezone.is_aware(as_of):
                    raise ValueError
            except ValueError as exc:
                raise CommandError("An aware audit cutoff is required") from exc
        result = report(as_of=as_of)
        self.stdout.write(json.dumps(result, sort_keys=True))
        if result["total"]:
            raise CommandError("prospective_contract_violations")
