import json

from django.core.management.base import BaseCommand, CommandError

from market.historical_acquisition import register_historical_dataset
from market.services import DatasetQualityError


class Command(BaseCommand):
    help = "Verify and immutably register one completed failed-break historical dataset"

    def add_arguments(self, parser):
        parser.add_argument("--dataset-id", type=int, required=True)
        parser.add_argument("--plan-sha256", required=True)

    def handle(self, *args, **options):
        try:
            registration = register_historical_dataset(
                options["dataset_id"], options["plan_sha256"]
            )
        except DatasetQualityError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                {
                    "dataset_registration_id": registration.pk,
                    "report_sha256": registration.report_sha256,
                    "row_counts": registration.row_counts,
                },
                sort_keys=True,
            )
        )
