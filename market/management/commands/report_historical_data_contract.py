import json

from django.core.management.base import BaseCommand, CommandError

from market.historical_discovery import REPLACEMENT_DATA_IDENTITY
from market.models import HistoricalDataContract
from market.provider_observed_acquisition import (
    replacement_supersession_lineage_report,
)
from market.services import DatasetQualityError


class Command(BaseCommand):
    help = (
        "Render the governed historical data-contract manifest and its"
        " supersession/lineage report deterministically (read-only)"
    )

    def add_arguments(self, parser):
        parser.add_argument("--output", default=None)

    def handle(self, *args, **options):
        contract = HistoricalDataContract.objects.filter(identity=REPLACEMENT_DATA_IDENTITY).first()
        if contract is None:
            raise CommandError("no governed historical data contract exists")
        try:
            lineage = replacement_supersession_lineage_report(contract)
        except DatasetQualityError as error:
            raise CommandError(str(error)) from error
        report = {
            "identity": contract.identity,
            "data_contract_sha256": contract.sha256,
            "payload": contract.payload,
            "supersession_lineage": lineage,
        }
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if options["output"]:
            with open(options["output"], "w", encoding="utf-8") as handle:
                handle.write(rendered)
        self.stdout.write(rendered)
