from django.core.management.base import BaseCommand

from forecasts.experiments import refresh_all_experiments


class Command(BaseCommand):
    help = "Append dependence-aware health assessments for active experiment eras"

    def handle(self, *args, **options):
        assessments = refresh_all_experiments()
        self.stdout.write(f"refreshed {len(assessments)} experiment assessment(s)")
