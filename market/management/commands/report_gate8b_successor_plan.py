import json

from django.core.management.base import BaseCommand, CommandError

from market.provider_observed_successor import (
    build_gate8b_authorization,
    build_successor_discovery_plan,
    load_committed_gate8b_authorization,
    staged_discovery_membership,
)


class Command(BaseCommand):
    help = (
        "Render the offline Gate 8B successor discovery plan, its staged execution"
        " membership, or the committed authorization artifact. Read-only: this command"
        " touches no database row, builds no provider client and issues no request."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--section",
            choices=("plan", "staging", "authorization", "committed"),
            default="plan",
            help="'committed' verifies the committed artifact against regeneration.",
        )

    def handle(self, *args, **options):
        section = options["section"]
        if section == "plan":
            payload = build_successor_discovery_plan()
        elif section == "staging":
            payload = staged_discovery_membership()
        elif section == "authorization":
            payload = build_gate8b_authorization()
        else:
            try:
                payload = load_committed_gate8b_authorization()
            except (ValueError, OSError) as error:
                raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
