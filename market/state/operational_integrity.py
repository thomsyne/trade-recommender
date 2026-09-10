"""Bounded static codes for the feature-only, unscheduled Phase4 boundary."""

import ast
from pathlib import Path

from django.conf import settings
from django.core.management.base import CommandError
from django.db.models import Q

from market.models import Instrument
from market.state.preview import cutoff_value, scope_value
from operations.models import JobOccurrence, ScheduledJob

MAX_ROWS = 500
TASK = "market.compute_market_state"


def operational_violations():
    issues = []

    def flag(code, pk=None):
        if len(issues) < MAX_ROWS:
            issues.append({"code": code, "id": pk})

    for model in (ScheduledJob, JobOccurrence):
        rows = list(
            model.objects.filter(
                Q(task_name__startswith="market.compute_market")
                | Q(task_name__icontains="market_state")
                | Q(task_name="market.ingest_oanda")
            ).order_by("pk")[: MAX_ROWS + 1]
        )
        if len(rows) > MAX_ROWS:
            flag("operational_scan_limit")
        for row in rows[:MAX_ROWS]:
            p = row.parameters
            if row.task_name == "market.ingest_oanda":
                if (
                    isinstance(p, dict)
                    and p.get("granularity") == "M15"
                    and (
                        getattr(row, "enabled", False)
                        or getattr(row, "status", None) in ("queued", "running")
                    )
                ):
                    flag("unexpected_m15_activation", row.pk)
                continue
            if row.task_name != TASK:
                flag("phase4_task_identity_drift", row.pk)
            if model is ScheduledJob:
                flag("unexpected_phase4_schedule", row.pk)
            try:
                if (
                    not isinstance(p, dict)
                    or set(p) - {"instrument", "cutoff", "granularities"}
                    or p.get("instrument") not in Instrument.Code.values
                ):
                    raise CommandError("invalid")
                cutoff_value(p.get("cutoff"))
                if "granularities" in p:
                    scope_value(p["granularities"])
            except (CommandError, TypeError, ValueError):
                flag("phase4_task_parameter_drift", row.pk)

    # Static source/model boundary check: do not import or execute consumers.
    # This detects direct Python imports, ORM attributes, raw-table strings and
    # declared foreign keys; dynamic/external consumers are not certified here.
    root = Path(settings.BASE_DIR) / "forecasts"
    paths = sorted(p for p in root.rglob("*.py") if not {"tests", "migrations"} & set(p.parts))
    if len(paths) > MAX_ROWS:
        flag("consumer_scan_limit")
    needles = (
        "market.state",
        "MarketStateSnapshot",
        "market_marketstatesnapshot",
        "market_state_snapshots",
    )
    for path in paths[:MAX_ROWS]:
        with path.open("rb") as source:
            body = source.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            flag("consumer_scan_limit")
            continue
        try:
            tree = ast.parse(body)
        except (SyntaxError, ValueError):
            flag("consumer_scan_unavailable")
            continue
        if any(any(n in ast.dump(node) for n in needles) for node in tree.body):
            flag("unexpected_phase4_consumer")
    return issues
