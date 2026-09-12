from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from research.evidence_quality import canonical
from research.evidence_store import audit_integrity


class Command(BaseCommand):
    help = "Read-only Phase7 identity and semantic replay audit; no activation or provider calls."

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    cursor.execute("SET LOCAL statement_timeout = '60s'")
                    cursor.execute("SET LOCAL lock_timeout = '2s'")
                counts = audit_integrity()
            self.stdout.write(canonical({"status": "replay_verified", "counts": counts}))
        except Exception:
            raise CommandError("phase7_integrity_failed") from None
