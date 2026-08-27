import json

from django.core.management.base import BaseCommand

from research.signal_count import SIGNAL_COUNT_IDENTITY, SignalCountOutput, stable_hash


class Command(BaseCommand):
    help = "Expose a bounded, dry-by-default return-blind S1 signal-count interface"

    def add_arguments(self, parser):
        parser.add_argument("--dataset-id", type=int)
        parser.add_argument("--max-setups", type=int, default=100)

    def handle(self, *args, **options):
        config = {"dataset_id": options["dataset_id"], "maximum_setups": options["max_setups"]}
        output = SignalCountOutput(
            SIGNAL_COUNT_IDENTITY,
            "S1",
            {"setups_processed": 0},
            {"mode": "dry", "dataset_read": False},
            stable_hash(config),
        )
        self.stdout.write(json.dumps(output.as_dict(), sort_keys=True))
