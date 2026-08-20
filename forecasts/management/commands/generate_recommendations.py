from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from forecasts.recommendations import generate_recommendation
from market.models import Instrument


class Command(BaseCommand):
    help = "Generate governed recommendations from the latest immutable pair evidence"

    def add_arguments(self, parser):
        parser.add_argument("instrument", nargs="?")
        parser.add_argument("--allow-fixture", action="store_true", help="Development/test only")

    def handle(self, *args, **options):
        instruments = Instrument.objects.filter(active=True)
        if options["instrument"]:
            instruments = instruments.filter(code=options["instrument"])
        if not instruments.exists():
            raise CommandError("No matching active instrument")
        for instrument in instruments:
            try:
                recommendation = generate_recommendation(
                    instrument, allow_fixture=options["allow_fixture"]
                )
            except (RuntimeError, ValueError, ValidationError) as error:
                raise CommandError(str(error)) from error
            self.stdout.write(
                self.style.SUCCESS(
                    f"{instrument.code}: {recommendation.action} "
                    f"({recommendation.confidence_percent}%)"
                )
            )
