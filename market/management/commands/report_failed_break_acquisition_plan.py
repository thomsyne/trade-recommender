import json

from django.core.management.base import BaseCommand, CommandError

from market.historical_acquisition import (
    create_historical_dataset_plan,
    load_plan,
    offline_acquisition_report,
)


class Command(BaseCommand):
    help = "Recompute the deterministic offline Phase 2B.1 acquisition report"

    def add_arguments(self, parser):
        parser.add_argument("--plan-file", required=True)

    def handle(self, *args, **options):
        try:
            plan, dataset = create_historical_dataset_plan(load_plan(options["plan_file"]))
        except (ValueError, OSError, json.JSONDecodeError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                offline_acquisition_report(plan, dataset),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
