from django.core.management.base import BaseCommand

from operations.tasks import ingest_oanda


class Command(BaseCommand):
    help = "Fetch and validate one OANDA candle range"

    def add_arguments(self, parser):
        parser.add_argument("instrument", choices=("USD_CAD", "GBP_USD", "EUR_GBP", "EUR_USD"))
        parser.add_argument("granularity", choices=("D", "H4"))
        parser.add_argument("--from", dest="from_time")
        parser.add_argument("--to", dest="to_time")
        parser.add_argument("--days", type=int)

    def handle(self, *args, **options):
        parameters = {
            key: value
            for key, value in {
                "instrument": options["instrument"],
                "granularity": options["granularity"],
                "from": options["from_time"],
                "to": options["to_time"],
                "days": options["days"],
            }.items()
            if value is not None
        }
        run = ingest_oanda(parameters)
        self.stdout.write(self.style.SUCCESS(f"ingestion {run.pk}: {run.status}"))
