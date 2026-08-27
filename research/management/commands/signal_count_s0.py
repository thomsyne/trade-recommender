import json
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from research.signal_count import (
    SIGNAL_COUNT_IDENTITY,
    SignalCountOutput,
    generate_spread_ceilings,
    stable_hash,
)


class Command(BaseCommand):
    help = "Plan return-blind S0, or calculate bounded deterministic synthetic spread ceilings"

    def add_arguments(self, parser):
        parser.add_argument("--synthetic-spreads", help='JSON object, e.g. {"EUR_USD/NY":[0.1]}')
        parser.add_argument("--pipettes", help='JSON object, e.g. {"EUR_USD/NY":0.00001}')
        parser.add_argument("--max-observations", type=int, default=10_000)

    def handle(self, *args, **options):
        raw = options["synthetic_spreads"]
        if not raw:
            self.stdout.write(
                "DRY RUN: S0 is bounded; no dataset read, download, or freeze performed"
            )
            return
        try:
            supplied = json.loads(raw, parse_float=Decimal)
            pipettes = json.loads(options["pipettes"] or "{}", parse_float=Decimal)
            if not isinstance(supplied, dict) or not isinstance(pipettes, dict):
                raise ValueError
            total = sum(len(values) for values in supplied.values())
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise CommandError(
                "synthetic spreads must be a JSON object of numeric arrays"
            ) from error
        if total > options["max_observations"]:
            raise CommandError("synthetic input exceeds --max-observations")
        try:
            ceilings = generate_spread_ceilings(supplied, pipettes)
        except ValueError as error:
            raise CommandError(str(error)) from error
        config = {"source": "synthetic", "maximum_observations": options["max_observations"]}
        output = SignalCountOutput(
            SIGNAL_COUNT_IDENTITY,
            "S0",
            {"observations": total},
            {"spread_ceilings": {key: str(value) for key, value in ceilings.items()}},
            stable_hash(config),
        )
        self.stdout.write(json.dumps(output.as_dict(), sort_keys=True))
