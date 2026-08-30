import json

from django.core.management.base import BaseCommand, CommandError

from market.historical_discovery import REPLACEMENT_DATA_IDENTITY
from market.models import HistoricalDataContract
from market.provider_observed_acquisition import (
    build_replacement_acquisition_payloads,
)
from market.services import DatasetQualityError


class Command(BaseCommand):
    help = (
        "Deterministically generate the replacement acquisition plan and"
        " dataset manifest from the sealed discovery inventories (read-only;"
        " creates no rows and contacts no provider)"
    )

    def add_arguments(self, parser):
        parser.add_argument("--output", default=None)

    def handle(self, *args, **options):
        contract = HistoricalDataContract.objects.filter(identity=REPLACEMENT_DATA_IDENTITY).first()
        if contract is None:
            raise CommandError("no governed historical data contract exists")
        try:
            payloads = build_replacement_acquisition_payloads(contract)
        except DatasetQualityError as error:
            raise CommandError(str(error)) from error
        rendered = json.dumps(payloads, indent=2, sort_keys=True) + "\n"
        if options["output"]:
            with open(options["output"], "w", encoding="utf-8") as handle:
                handle.write(rendered)
        self.stdout.write(rendered)
