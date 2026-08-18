import time

from django.core.management.base import BaseCommand

from operations.services import claim_next_job, finish_job
from operations.tasks import execute_task


class Command(BaseCommand):
    help = "Run the durable database-backed worker"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        while True:
            occurrence = claim_next_job()
            if occurrence:
                try:
                    execute_task(occurrence.task_name, occurrence.parameters)
                except Exception as error:
                    finish_job(occurrence, error)
                    self.stderr.write(f"job {occurrence.pk} failed: {error}")
                else:
                    finish_job(occurrence)
            if options["once"]:
                return
            if not occurrence:
                time.sleep(5)
