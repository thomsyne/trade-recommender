import time

from django.core.management.base import BaseCommand

from operations.services import enqueue_due_jobs


class Command(BaseCommand):
    help = "Enqueue durable occurrences for due scheduled jobs"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        while True:
            created = enqueue_due_jobs()
            if created:
                self.stdout.write(f"queued {len(created)} job(s)")
            if options["once"]:
                return
            time.sleep(15)
