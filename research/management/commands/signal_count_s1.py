import json

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from research.signal_count import run_s1


class Command(BaseCommand):
    help = "Expose a bounded, dry-by-default return-blind S1 signal-count interface"

    def add_arguments(self, parser):
        parser.add_argument("--dataset-id", type=int, required=True)
        parser.add_argument("--strategy-version-id", type=int, required=True)
        parser.add_argument("--as-of", required=True)
        parser.add_argument("--max-setups", type=int, default=100)

    def handle(self, *args, **options):
        try:
            as_of = parse_datetime(options["as_of"])
            if as_of is None:
                raise ValueError("--as-of must be an ISO-8601 timestamp")
            output = run_s1(
                dataset_id=options["dataset_id"],
                strategy_version_id=options["strategy_version_id"],
                maximum_setups=options["max_setups"],
                as_of=as_of,
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(output.as_dict(), sort_keys=True))
