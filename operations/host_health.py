"""Cheap, safe host and backup visibility.

Every reader here is O(1): small state files, one ``statvfs`` call, one read
of ``/proc/meminfo`` and one read of ``/proc/1/stat``. Nothing shells out to
Docker and nothing requires privileges. Values are parsed defensively because
state files live on a shared volume written by the backup container.
"""

import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from django.utils import timezone

STATE_FILES = {
    "last_attempt": "backup-last-attempt",
    "last_success": "backup-last-success",
    "last_failure": "backup-last-failure",
    "in_progress": "backup-in-progress",
}
LEGACY_MARKER = "last-backup"
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:/+\-]{0,200}$")
_ALLOWED_KEYS = {
    "attempt_id",
    "attempted_at",
    "started_at",
    "completed_at",
    "failed_at",
    "object_key",
    "outcome",
    "stage",
    "category",
    "exit_status",
    "sha256",
    "size_bytes",
    "version_id",
    "interval_seconds",
}
PROCESS_STARTED_AT = timezone.now()


def _parse_state_file(path):
    """Parse ``key=value`` lines; unknown keys and unsafe values are dropped."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    values = {}
    for line in text.splitlines()[:40]:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in _ALLOWED_KEYS and _SAFE_KEY.match(key) and _SAFE_VALUE.match(value):
            values[key] = value
    return values


def _parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class BackupState:
    last_attempt: dict | None
    last_success: dict | None
    last_failure: dict | None
    in_progress: dict | None
    legacy_marker_at: datetime | None
    state_dir: str

    @property
    def last_success_at(self):
        if self.last_success:
            return _parse_timestamp(self.last_success.get("completed_at"))
        return self.legacy_marker_at

    @property
    def last_attempt_at(self):
        if self.last_attempt:
            return _parse_timestamp(self.last_attempt.get("attempted_at"))
        return self.last_success_at

    @property
    def last_failure_at(self):
        if self.last_failure:
            return _parse_timestamp(self.last_failure.get("failed_at"))
        return None

    @property
    def last_attempt_outcome(self):
        if self.last_attempt:
            return self.last_attempt.get("outcome", "unknown")
        if self.legacy_marker_at is not None:
            return "success"
        return "unknown"

    @property
    def in_progress_since(self):
        """When the current attempt started, from its durable in-progress record."""
        if self.in_progress:
            return _parse_timestamp(self.in_progress.get("started_at"))
        return None

    @property
    def source(self):
        if self.last_success:
            return "state_file"
        if self.legacy_marker_at is not None:
            return "legacy_marker"
        return "none"


def read_backup_state(state_dir, marker_path=""):
    """Read the backup state files; tolerate absence, partial writes and legacy markers."""
    directory = Path(state_dir) if state_dir else None
    last_attempt = last_success = last_failure = in_progress = None
    if directory is not None:
        last_attempt = _parse_state_file(directory / STATE_FILES["last_attempt"])
        last_success = _parse_state_file(directory / STATE_FILES["last_success"])
        last_failure = _parse_state_file(directory / STATE_FILES["last_failure"])
        in_progress = _parse_state_file(directory / STATE_FILES["in_progress"])
    legacy_at = None
    marker = (
        Path(marker_path)
        if marker_path
        else (directory / LEGACY_MARKER if directory is not None else None)
    )
    if marker is not None:
        try:
            legacy_at = datetime.fromtimestamp(marker.stat().st_mtime, UTC)
        except OSError:
            legacy_at = None
    return BackupState(
        last_attempt=last_attempt,
        last_success=last_success,
        last_failure=last_failure,
        in_progress=in_progress,
        legacy_marker_at=legacy_at,
        state_dir=str(directory) if directory is not None else "",
    )


def _published_success_is_contradicted(state):
    """True when the published success belongs to an attempt recorded as failed.

    Pre-fix backup.sh could publish backup-last-success and then have an
    interrupt overwrite the attempt record with outcome=failure for the same
    attempt. A success file contradicted by the commit record (the attempt
    file) or by a failure record of the same attempt is not genuine. Records
    written since the fix carry an attempt_id, so identities are compared by
    that id; pre-fix records (no attempt_id) fall back to the attempted_at key
    they shared.
    """
    success = state.last_success
    if not success:
        return False
    attempt = state.last_attempt
    if attempt and _same_attempt(success, attempt) and attempt.get("outcome") != "success":
        return True
    failure = state.last_failure
    if failure and _same_attempt(success, failure):
        return True
    return False


def _success_is_uncommitted(state):
    """True when the published success belongs to an attempt still in progress."""
    if not state.last_success or not state.in_progress:
        return False
    return _same_attempt(state.last_success, state.in_progress)


def _same_attempt(first, second):
    """True when two state records describe the same backup attempt.

    Identity is the attempt_id carried by every record the current backup.sh
    writes. Only when neither record has an id (pre-fix state files) is the
    second-resolution attempted_at they shared used, so a same-second pair of
    distinct attempts can never be conflated.
    """
    if not second:
        return False
    first_id = first.get("attempt_id")
    second_id = second.get("attempt_id")
    if first_id or second_id:
        return bool(first_id and second_id and first_id == second_id)
    attempted_at = first.get("attempted_at")
    return bool(attempted_at and attempted_at == second.get("attempted_at"))


def _modern_state_present(state):
    """Whether any record from the current backup protocol exists at all."""
    return any(
        record is not None
        for record in (
            state.last_attempt,
            state.last_success,
            state.last_failure,
            state.in_progress,
        )
    )


def _attempt_record_is_valid(attempt):
    """Whether the authoritative terminal record is schema-valid."""
    if not attempt:
        return False
    if not attempt.get("attempt_id"):
        return False
    return attempt.get("outcome") in {"success", "failure"}


def _success_is_self_consistent(success, *, now):
    """Whether a published success stands up on its own terms."""
    completed_at = _parse_timestamp(success.get("completed_at"))
    if completed_at is None:
        return "success_malformed"
    if completed_at > now:
        return "future_dated"
    for field in ("object_key", "version_id", "sha256"):
        if not success.get(field):
            return "success_partial"
    # A backup cannot finish before it started.
    attempted_at = _parse_timestamp(success.get("attempted_at"))
    if attempted_at is not None and completed_at < attempted_at:
        return "success_incoherent"
    return None


def _success_matches_commitment(success, attempt):
    """Whether a success agrees with the authoritative record of its own attempt.

    Only applied when both records describe the same attempt. A later attempt
    does not re-open an older success: that success was corroborated when it
    committed, and an attempt that never committed is caught by its retained
    in-progress evidence instead.
    """
    if attempt.get("outcome") != "success":
        return "contradicted"
    if success.get("object_key") != attempt.get("object_key"):
        return "success_contradicted"
    return None


def backup_assessment(state, *, now, max_age_hours):
    """Return (ready, safe_detail) from a corroborated success, never an attempt.

    The legacy marker is a fallback for hosts that have not yet run the current
    protocol at all. The moment any modern record exists the marker is ignored
    entirely and the modern contract applies in full: a schema-valid
    authoritative terminal record must be present, a published success must be
    self-consistent and chronologically coherent, and where the record
    describes that same attempt the two must agree. Corrupt modern state is
    reported as corrupt rather than falling through to the marker, because a
    stale marker beside a broken producer is exactly what readiness exists to
    catch. An older committed success followed by a newer failed attempt stays
    healthy, with the failure surfaced as a warning.
    """
    in_progress_at = state.in_progress_since
    detail = {
        "source": state.source,
        "last_success_age_seconds": None,
        "last_attempt_outcome": state.last_attempt_outcome,
        "last_failure_category": (state.last_failure or {}).get("category"),
        "last_failure_stage": (state.last_failure or {}).get("stage"),
        "attempt_in_progress": in_progress_at is not None,
        "state": "missing",
    }

    def unhealthy(name):
        detail["state"] = name
        return False, detail

    if state.in_progress is not None and in_progress_at is None:
        # The file exists but carries no usable start: a partial or corrupted
        # record. It is not the same as having no record at all, and it cannot
        # be read as "no attempt is running".
        detail["attempt_in_progress"] = True
        return unhealthy("attempt_malformed")
    if in_progress_at is not None:
        attempt_age = (now - in_progress_at).total_seconds()
        detail["attempt_started_at"] = in_progress_at
        if in_progress_at > now:
            return unhealthy("future_dated")
        if attempt_age > max_age_hours * 3600:
            return unhealthy("attempt_stale")

    if not _modern_state_present(state):
        # No protocol state whatsoever: the legacy marker is all there is, and
        # is the only case in which it may be trusted on its own.
        success_at = state.last_success_at
        if success_at is None:
            return False, detail
        if success_at > now:
            return unhealthy("future_dated")
        age = (now - success_at).total_seconds()
        detail["last_success_age_seconds"] = int(age)
        if age > max_age_hours * 3600:
            return unhealthy("stale")
        detail["state"] = "fresh"
        return True, detail

    attempt = state.last_attempt
    success = state.last_success
    # From here the legacy marker is not evidence of anything: a host running
    # the current protocol must be judged by the protocol's own records, or a
    # stale marker beside a broken producer would read as healthy.
    if success is not None:
        # A published success is only a success if the protocol committed it.
        if _success_is_uncommitted(state):
            # backup.sh publishes the detail before committing the
            # authoritative record and retains its in-progress evidence when
            # that commit fails, so a success belonging to the attempt still in
            # progress has not committed.
            return unhealthy("uncommitted")
        if _published_success_is_contradicted(state):
            return unhealthy("contradicted")
        problem = _success_is_self_consistent(success, now=now)
        if problem:
            return unhealthy(problem)
        if attempt is None:
            # Absence of the commitment, not corruption of it.
            return unhealthy("success_uncommitted")
        if not _attempt_record_is_valid(attempt):
            return unhealthy("attempt_malformed")
        if _same_attempt(success, attempt):
            problem = _success_matches_commitment(success, attempt)
            if problem:
                return unhealthy(problem)
    else:
        if attempt is None:
            return unhealthy("attempt_record_missing")
        if not _attempt_record_is_valid(attempt):
            return unhealthy("attempt_malformed")
        if attempt.get("outcome") == "success":
            # Committed as successful with nothing published to corroborate it.
            return unhealthy("success_missing")

    # The published success record, never the legacy marker.
    success_at = _parse_timestamp(success.get("completed_at")) if success else None
    if success_at is None:
        return False, detail
    age = (now - success_at).total_seconds()
    detail["last_success_age_seconds"] = int(age)
    if age > max_age_hours * 3600:
        return unhealthy("stale")
    detail["state"] = "fresh"
    if state.last_failure_at is not None and state.last_failure_at > success_at:
        detail["warning"] = "last_attempt_failed"
    return True, detail


def disk_status(path, *, min_free_gb, warning_free_gb):
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return {"level": "unavailable", "free_gb": None, "total_gb": None, "percent_free": None}
    free_gb = usage.free / (1024**3)
    total_gb = usage.total / (1024**3)
    percent_free = (usage.free * 100 / usage.total) if usage.total else None
    if free_gb < min_free_gb:
        level = "critical"
    elif free_gb < warning_free_gb:
        level = "warning"
    else:
        level = "ok"
    return {
        "level": level,
        "free_gb": round(free_gb, 2),
        "total_gb": round(total_gb, 2),
        "percent_free": round(percent_free, 1) if percent_free is not None else None,
        "warning_below_gb": warning_free_gb,
        "critical_below_gb": min_free_gb,
    }


def memory_status(meminfo_path, *, warning_percent, critical_percent):
    unavailable = {
        "level": "unavailable",
        "total_mib": None,
        "available_mib": None,
        "percent_available": None,
        "swap_total_mib": None,
        "warning_below_percent": warning_percent,
        "critical_below_percent": critical_percent,
    }
    try:
        text = Path(meminfo_path).read_text()
    except OSError:
        return unavailable
    values = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(":"):
            try:
                values[parts[0][:-1]] = int(parts[1])
            except ValueError:
                continue
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return unavailable
    percent = available * 100 / total
    if percent < critical_percent:
        level = "critical"
    elif percent < warning_percent:
        level = "warning"
    else:
        level = "ok"
    return {
        "level": level,
        "total_mib": total // 1024,
        "available_mib": available // 1024,
        "percent_available": round(percent, 1),
        "swap_total_mib": (values.get("SwapTotal") or 0) // 1024,
        "warning_below_percent": warning_percent,
        "critical_below_percent": critical_percent,
    }


def process_status(now=None):
    """Start time of this web process and, on Linux, of the container's PID 1."""
    now = now or timezone.now()
    status = {
        "web_process_started_at": PROCESS_STARTED_AT,
        "web_process_uptime_seconds": int((now - PROCESS_STARTED_AT).total_seconds()),
        "container_started_at": None,
    }
    try:
        stat = Path("/proc/1/stat").read_text()
        btime_line = next(
            line for line in Path("/proc/stat").read_text().splitlines() if line.startswith("btime")
        )
        ticks = int(stat.rsplit(")", 1)[1].split()[19])
        hertz = os.sysconf("SC_CLK_TCK")
        started = int(btime_line.split()[1]) + ticks / hertz
        status["container_started_at"] = datetime.fromtimestamp(started, UTC)
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        pass
    return status
