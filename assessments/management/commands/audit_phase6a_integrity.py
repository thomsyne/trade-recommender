import json

from django.core.management.base import BaseCommand, CommandError

from assessments.services import audit_integrity


class Command(BaseCommand):
    help = "Run a bounded read-only Phase 6A replay audit"

    def add_arguments(self, parser):
        parser.add_argument("--after-id", type=int, default=0)
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        try:
            result = audit_integrity(after_id=options["after_id"], limit=options["limit"])
        except Exception as exc:
            raise CommandError("phase6a_integrity_audit_failed") from exc
        self.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
        if result["violations"]:
            raise CommandError("phase6a_integrity_violations")
