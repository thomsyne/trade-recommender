import json
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from forecasts.experiments import ensure_champion_era
from forecasts.recommendations import configured_provider


class Command(BaseCommand):
    help = (
        "Dry-run prospective v4 era registration; --register is explicit local/owner authorization."
    )

    def add_arguments(self, parser):
        parser.add_argument("--starts-at", required=True)
        parser.add_argument("--register", action="store_true")

    def handle(self, *args, **options):
        try:
            starts = datetime.fromisoformat(options["starts_at"])
            if not timezone.is_aware(starts) or starts < timezone.now():
                raise ValueError
        except ValueError as exc:
            raise CommandError("A future aware cutover timestamp is required") from exc
        result = {
            "contract_version": 4,
            "policy_version": 2,
            "starts_at": starts.isoformat(),
            "registered": False,
            "schedules_activated": False,
            "historical_rows_assigned": 0,
        }
        if options["register"]:
            era = ensure_champion_era(configured_provider(), starts_at=starts, register=True)
            result.update(registered=True, era_id=era.pk)
        self.stdout.write(json.dumps(result, sort_keys=True))
