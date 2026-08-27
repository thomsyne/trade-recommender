import json

from django.core.management.base import BaseCommand, CommandError

from market.historical_acquisition import create_historical_dataset_plan, load_plan


class Command(BaseCommand):
    help = "Register an offline, bounded W/D/H1 failed-break acquisition plan"

    def add_arguments(self, parser):
        parser.add_argument("--plan-file", required=True)

    def handle(self, *args, **options):
        try:
            plan, dataset = create_historical_dataset_plan(load_plan(options["plan_file"]))
        except (ValueError, OSError, json.JSONDecodeError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                {
                    "dataset_id": dataset.pk,
                    "dataset_manifest_sha256": dataset.manifest_sha256,
                    "logical_chunk_count": plan.chunks.count(),
                    "plan_id": plan.pk,
                    "plan_sha256": plan.sha256,
                },
                sort_keys=True,
            )
        )
