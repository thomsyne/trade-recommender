"""Bounded read-only offline surfaces. No persistence or task scheduling."""

import json

from django.core.management.base import BaseCommand, CommandError

from market.strategy.definitions import STRATEGIES, definition
from market.strategy.evaluate import evaluate
from market.strategy.persistence import integrity, load_snapshot, simulation_integrity
from market.strategy.reports import availability_report


class Command(BaseCommand):
    help = "Offline Phase5 definitions, exact-snapshot preview, availability or integrity; never writes."

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=("definitions", "preview", "report", "integrity", "simulation-integrity"),
        )
        parser.add_argument("--snapshot", type=int)
        parser.add_argument("--strategy", choices=STRATEGIES)
        parser.add_argument("--after-id", type=int, default=0)

    def handle(self, *args, **options):
        try:
            action = options["action"]
            if action == "definitions":
                result = [definition(s) for s in STRATEGIES]
            elif action == "preview":
                if not options["snapshot"] or not options["strategy"]:
                    raise ValueError("preview_requires_exact_snapshot_and_strategy")
                result = evaluate(load_snapshot(options["snapshot"]), options["strategy"])
            elif action == "report":
                result = availability_report(after_id=options["after_id"])
            elif action == "simulation-integrity":
                result = simulation_integrity(after_id=options["after_id"])
            else:
                result = integrity(after_id=options["after_id"])
            self.stdout.write(json.dumps(result, sort_keys=True, ensure_ascii=True))
            if action in ("integrity", "simulation-integrity") and result["violations"]:
                raise CommandError("strategy_integrity_violations")
        except (ValueError, KeyError, TypeError) as exc:
            raise CommandError("strategy_library_invalid_request_or_evidence") from exc
