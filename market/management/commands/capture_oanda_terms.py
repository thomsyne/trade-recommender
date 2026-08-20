from django.core.management.base import BaseCommand

from operations.tasks import capture_oanda_terms


class Command(BaseCommand):
    help = "Capture prospective account-specific OANDA financing and commission terms"

    def handle(self, *args, **options):
        snapshots = capture_oanda_terms()
        supplied = sum(snapshot.commission_supplied for snapshot in snapshots)
        self.stdout.write(
            self.style.SUCCESS(
                f"captured {len(snapshots)} OANDA instrument term snapshot(s); "
                f"commission supplied for {supplied}"
            )
        )
