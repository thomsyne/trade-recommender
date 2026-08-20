from django.core.management.base import BaseCommand, CommandError

from research.models import MacroSeries, SourcePolicy
from research.services import ingest_feed, ingest_macro, ingest_official_calendar


class Command(BaseCommand):
    help = "Retrieve one configured official research feed or macro series"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--feed")
        group.add_argument("--series")
        group.add_argument("--calendar")
        parser.add_argument("--url")
        parser.add_argument("--parser")

    def handle(self, *args, **options):
        if options["feed"]:
            if not options["url"]:
                raise CommandError("--url is required with --feed")
            policy = SourcePolicy.objects.get(slug=options["feed"])
            retrieval = ingest_feed(policy, options["url"])
        elif options["series"]:
            series = MacroSeries.objects.get(code=options["series"], enabled=True)
            retrieval = ingest_macro(series)
        else:
            if not options["url"] or not options["parser"]:
                raise CommandError("--url and --parser are required with --calendar")
            policy = SourcePolicy.objects.get(slug=options["calendar"])
            retrieval = ingest_official_calendar(policy, options["parser"], options["url"])
        self.stdout.write(
            self.style.SUCCESS(
                f"stored retrieval {retrieval.pk} ({retrieval.byte_count} bytes, {retrieval.body_sha256[:12]})"
            )
        )
