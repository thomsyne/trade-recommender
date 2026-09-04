import json

from django.core.management.base import BaseCommand, CommandError

from research.failed_break_v2_s1_execution import (
    authorization_readiness_v2_s1,
    execute_authorized_v2_s1,
)


class Command(BaseCommand):
    help = "Verify the fixed v2 S1 runner; persistent execution is separately governed"

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="request the separately governed all-or-nothing persistent operation",
        )

    def handle(self, *args, **options):
        try:
            result = (
                execute_authorized_v2_s1(
                    lambda instrument, completed, total: self.stderr.write(
                        f"progress instrument={instrument} h1={completed}/{total}"
                    )
                )
                if options["execute"]
                else authorization_readiness_v2_s1()
            )
        except (TimeoutError, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(result, sort_keys=True))
