"""Canonical live schedule identities and bounded read-only integrity checks."""

from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from math import gcd

from market.live_acquisition import LIVE_INTERVALS
from market.models import Instrument
from operations.models import ScheduledJob

MAX_IDENTITY_DETAILS = 50
MICROSECONDS_PER_SECOND = 1_000_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def canonical_name(code, granularity):
    return f"OANDA {code} {granularity}"


def parse_schedule_identity(parameters):
    """Return a canonical key or ordered static reason codes; never render input."""
    if not isinstance(parameters, dict):
        return None, ("malformed_parameter_container",)
    reasons = []
    for field, allowed in (("instrument", Instrument.Code.values), ("granularity", LIVE_INTERVALS)):
        if field not in parameters:
            reasons.append(f"missing_{field}")
        elif not isinstance(parameters[field], str):
            reasons.append(f"wrong_type_{field}")
        elif parameters[field] not in allowed:
            reasons.append(f"unsupported_{field}")
    if parameters.keys() - {"instrument", "granularity"}:
        reasons.append("unexpected_extra_parameter")
    if reasons:
        return None, tuple(reasons)
    return (parameters["instrument"], parameters["granularity"]), ()


class ScheduleErrors(list):
    def __init__(self):
        super().__init__()
        self.identity_report = {"total": 0, "omitted": 0, "details": []}


def schedule_inventory():
    # Stream all rows to count every malformed identity while retaining bounded
    # details and at most two members of each of the 48 canonical identities.
    identities = defaultdict(list)
    errors = ScheduleErrors()
    summary = errors.identity_report
    jobs = ScheduledJob.objects.filter(task_name="market.ingest_oanda").order_by("pk")
    for job in jobs.iterator(chunk_size=256):
        key, reasons = parse_schedule_identity(job.parameters)
        if reasons:
            summary["total"] += 1
            detail = {"job_id": job.pk, "reason_codes": list(reasons)}
            # Bounded sorted insertion also makes unordered test/query inputs stable.
            summary["details"].append(detail)
            summary["details"].sort(key=lambda issue: issue["job_id"])
            del summary["details"][MAX_IDENTITY_DETAILS:]
        else:
            identities[key].append(job)
            identities[key].sort(key=lambda member: member.pk)
            del identities[key][2:]
    summary["omitted"] = summary["total"] - len(summary["details"])
    for detail in summary["details"]:
        errors.append(f"Live schedule id {detail['job_id']}: {','.join(detail['reason_codes'])}")
    if summary["total"]:
        errors.append(
            f"Malformed schedule identities: total={summary['total']} omitted={summary['omitted']}"
        )
    for key, members in sorted(identities.items()):
        if len(members) > 1:
            errors.append(f"{canonical_name(*key)}: duplicate semantic ingestion schedules")
        elif members[0].name != canonical_name(*key):
            errors.append(f"{canonical_name(*key)}: noncanonical semantic ingestion schedule")
    return identities, errors


def duplicate_schedule_errors():
    # Seed uses precisely the same parser and fail-closed inventory as reporting.
    return schedule_inventory()[1]


def deadline_microseconds(value):
    """Lossless UTC epoch offset; reject unusable deadlines without rendering them."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("invalid_deadline")
    try:
        if value.utcoffset() is None:
            raise ValueError("invalid_deadline")
        delta = value.astimezone(UTC) - EPOCH
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("invalid_deadline") from exc
    return (delta.days * 86400 + delta.seconds) * MICROSECONDS_PER_SECOND + delta.microseconds


def validate_live_schedules(instruments, *, provider_available):
    identities, errors = schedule_inventory()
    names = [canonical_name(code, g) for code in Instrument.Code.values for g in LIVE_INTERVALS]
    by_name = {j.name: j for j in ScheduledJob.objects.filter(name__in=names)}
    per_identity = defaultdict(list)
    recurrences = []
    for code in Instrument.Code.values:
        instrument = instruments.get(code)
        for granularity, interval in LIVE_INTERVALS.items():
            key = code, granularity
            job = by_name.get(canonical_name(*key))
            issues = per_identity[key]
            if not job:
                issues.append("missing canonical schedule")
                continue
            identity, reasons = parse_schedule_identity(job.parameters)
            if len(identities.get(key, [])) != 1:
                issues.append("expected exactly one semantic schedule")
            if (
                job.task_name != "market.ingest_oanda"
                or reasons
                or identity != key
                or (
                    job.interval_seconds,
                    job.schedule_type,
                    job.missed_run_policy,
                    job.timezone_name,
                    job.local_time,
                )
                != (interval, "interval", "latest", "UTC", None)
            ):
                issues.append("canonical schedule policy/parameters drift")
            if job.enabled and (
                not instrument or not instrument.ingestion_enabled or not provider_available
            ):
                issues.append("enabled schedule without collection availability")
            if not job.enabled or job.task_name != "market.ingest_oanda" or identity != key:
                continue
            if (
                type(job.interval_seconds) is not int
                or job.interval_seconds <= 0
                or job.schedule_type != "interval"
            ):
                issues.append(f"invalid_recurrence: job id {job.pk}")
                continue
            try:
                deadline = deadline_microseconds(job.next_run_at)
            except ValueError:
                issues.append(f"invalid_deadline: job id {job.pk}")
                continue
            recurrences.append(
                (key, job.pk, deadline, job.interval_seconds * MICROSECONDS_PER_SECOND)
            )
    for first, second in combinations(sorted(recurrences), 2):
        key_a, id_a, deadline_a, interval_a = first
        key_b, id_b, deadline_b, interval_b = second
        # Positive integer recurrences intersect iff their phase difference is
        # divisible by the gcd. A common solution can always advance past both starts.
        if (deadline_a - deadline_b) % gcd(interval_a, interval_b) == 0:
            label = f"recurring_collision: job ids {id_a},{id_b} ({canonical_name(*key_a)} / {canonical_name(*key_b)})"
            per_identity[key_a].append(label)
            per_identity[key_b].append(label)
            errors.append(label)
    for key, issues in sorted(per_identity.items()):
        errors.extend(
            f"{canonical_name(*key)}: {issue}"
            for issue in issues
            if not issue.startswith("recurring_collision:")
        )
    errors.sort()
    return by_name, per_identity, errors
