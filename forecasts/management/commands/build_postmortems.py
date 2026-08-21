from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from forecasts.models import ReviewCohort
from forecasts.reviews import build_due_review_cohort, reassess_review_cohort
from market.models import Instrument


class Command(BaseCommand):
    help = "Freeze due deterministic postmortems or explicitly assess a later correction"

    def add_arguments(self, parser):
        parser.add_argument("--instrument")
        parser.add_argument("--reassess-cohort", type=int)

    def handle(self, *args, **options):
        if options["instrument"] and options["reassess_cohort"]:
            raise CommandError("Choose an instrument or a correction reassessment, not both")
        if options["reassess_cohort"]:
            cohort = ReviewCohort.objects.get(pk=options["reassess_cohort"])
            created = reassess_review_cohort(cohort, correction_as_of=timezone.now())
            self.stdout.write(f"{len(created)} superseding review assessment(s) created")
            return
        instrument = None
        if options["instrument"]:
            instrument = Instrument.objects.get(code=options["instrument"], active=True)
        cohort = build_due_review_cohort(instrument=instrument)
        self.stdout.write(
            f"frozen review cohort {cohort.pk}" if cohort else "no terminal outcomes are due"
        )
