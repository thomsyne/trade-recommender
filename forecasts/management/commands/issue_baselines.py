from django.core.management.base import BaseCommand

from forecasts.services import issue_all_baselines, issue_baselines
from market.models import Instrument


class Command(BaseCommand):
    help = "Issue immutable mechanical macro and tactical control forecasts"

    def add_arguments(self, parser):
        parser.add_argument("instrument", nargs="?", choices=Instrument.Code.values)

    def handle(self, *args, **options):
        if options["instrument"]:
            issued = [issue_baselines(Instrument.objects.get(code=options["instrument"]))]
        else:
            issued = issue_all_baselines()
        forecast_ids = [forecast.pk for pair in issued for forecast in pair]
        self.stdout.write(self.style.SUCCESS(f"baseline forecasts ready: {forecast_ids}"))
