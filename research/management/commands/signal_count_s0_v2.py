import json

from django.core.management.base import BaseCommand, CommandError

from research.failed_break_v2_s0 import V2S0Error, execute_v2_s0_once
from research.failed_break_v2_s0_governance import (
    V2S0GovernanceRefusal,
    v2_s0_code_readiness,
)


class Command(BaseCommand):
    help = "Prepare or execute the exact return-blind failed-break v2 S0 boundary"

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Persist the exact preregistered v2 strategy and S0 JobRun once",
        )

    def handle(self, *args, **options):
        try:
            if not options["execute"]:
                self.stdout.write(json.dumps(v2_s0_code_readiness(), sort_keys=True))
                return
            output, job, strategy = execute_v2_s0_once()
        except (V2S0Error, V2S0GovernanceRefusal, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                {
                    "status": "PERSISTED_PENDING_SEPARATE_OUTCOME_ACCEPTANCE",
                    "job_run_id": job.pk,
                    "strategy_version_id": strategy.pk,
                    "strategy_identity": strategy.version,
                    "strategy_content_sha256": strategy.content_hash,
                    "configuration_sha256": job.config_hash,
                    "report_sha256": output.report_sha256,
                    "v2_s1_execution_authorized": False,
                },
                sort_keys=True,
            )
        )
