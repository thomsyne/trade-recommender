"""Canonical live schedule identities and read-only integrity checks."""

from collections import defaultdict

from market.live_acquisition import LIVE_INTERVALS
from market.models import Instrument
from operations.models import ScheduledJob

MAX_LIVE_JOBS = 1000


def canonical_name(code, granularity):
    return f"OANDA {code} {granularity}"


def schedule_inventory():
    jobs = list(
        ScheduledJob.objects.filter(task_name="market.ingest_oanda").order_by("pk")[
            : MAX_LIVE_JOBS + 1
        ]
    )
    by_identity = defaultdict(list)
    for job in jobs:
        parameters = job.parameters if isinstance(job.parameters, dict) else {}
        code, granularity = parameters.get("instrument"), parameters.get("granularity")
        if isinstance(code, str) and isinstance(granularity, str):
            by_identity[code, granularity].append(job)
    return jobs, by_identity


def duplicate_schedule_errors():
    jobs, identities = schedule_inventory()
    errors = ["Live schedule inventory exceeds bounded limit"] if len(jobs) > MAX_LIVE_JOBS else []
    for (code, granularity), members in identities.items():
        if len(members) > 1:
            errors.append(f"{code} {granularity}: duplicate semantic ingestion schedules")
        elif (
            code in Instrument.Code.values
            and granularity in LIVE_INTERVALS
            and members[0].name != canonical_name(code, granularity)
        ):
            errors.append(f"{code} {granularity}: noncanonical semantic ingestion schedule")
    return errors


def validate_live_schedules(instruments, *, provider_available):
    jobs, identities = schedule_inventory()
    errors = duplicate_schedule_errors()
    # Name lookup also catches jobs with the correct name but a wrong task.
    names = [canonical_name(code, g) for code in Instrument.Code.values for g in LIVE_INTERVALS]
    by_name = {j.name: j for j in ScheduledJob.objects.filter(name__in=names)}
    per_identity = defaultdict(list)
    phases = defaultdict(list)
    for code in Instrument.Code.values:
        instrument = instruments.get(code)
        for granularity, interval in LIVE_INTERVALS.items():
            key = code, granularity
            job = by_name.get(canonical_name(*key))
            issues = per_identity[key]
            if not job:
                issues.append("missing canonical schedule")
                continue
            if len(identities.get(key, [])) != 1:
                issues.append("expected exactly one semantic schedule")
            if (
                job.task_name,
                job.parameters,
                job.interval_seconds,
                job.schedule_type,
                job.missed_run_policy,
                job.timezone_name,
                job.local_time,
            ) != (
                "market.ingest_oanda",
                {"instrument": code, "granularity": granularity},
                interval,
                "interval",
                "latest",
                "UTC",
                None,
            ):
                issues.append("canonical schedule policy/parameters drift")
            if job.enabled and (
                not instrument or not instrument.ingestion_enabled or not provider_available
            ):
                issues.append("enabled schedule without collection availability")
            # Existing deadlines must survive reseeding. Only exact simultaneous
            # due instants are diagnosed; no invented phase anchor for legacy jobs.
            if job.enabled:
                phases[job.next_run_at].append(key)
    for keys in phases.values():
        if len(keys) > 1:
            for key in keys:
                per_identity[key].append("duplicate enabled schedule staggering")
    for key, issues in per_identity.items():
        errors.extend(f"{key[0]} {key[1]}: {issue}" for issue in issues)
    for job in jobs:
        params = job.parameters if isinstance(job.parameters, dict) else {}
        if (
            params.get("instrument") not in Instrument.Code.values
            or params.get("granularity") not in LIVE_INTERVALS
        ):
            errors.append(f"Live schedule id {job.pk}: unsupported semantic identity")
    return by_name, per_identity, errors
