import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Inspect or, after a separate governed authorization, execute v2 exploratory returns"

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        from research.exploratory_return_runner_v2 import (
            RunnerRefusal,
            execute_persistent,
            readiness,
        )
        from research.exploratory_return_runner_v2_governance import RunnerGovernanceRefusal

        if not options["execute"]:
            state = readiness()
            self.stdout.write(
                "status={status} events={events} outcome_queries={queries} writes={writes}".format(
                    status=state["status"],
                    events=state["governed_physical_events"],
                    queries=state["outcome_query_count"],
                    writes=state["persistent_write_count"],
                )
            )
            return
        try:
            payload = execute_persistent(
                progress=lambda stage, completed, total: self.stderr.write(
                    f"stage={stage} completed={completed} total={total}"
                )
            )
        except (RunnerGovernanceRefusal, RunnerRefusal) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
