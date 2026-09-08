"""Cheap, safe host and backup visibility.

Every reader here is O(1): small state files, one ``statvfs`` call, one read
of ``/proc/meminfo`` and one read of ``/proc/1/stat``. Nothing shells out to
Docker and nothing requires privileges. Values are parsed defensively because
state files live on a shared volume written by the backup container.
"""

import os
import re
import shutil
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from django.utils import timezone

STATE_FILES = {
    "last_attempt": "backup-last-attempt",
    "last_success": "backup-last-success",
    "last_failure": "backup-last-failure",
    "in_progress": "backup-in-progress",
}
LEGACY_MARKER = "last-backup"
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:/+=\-]{0,1024}$")
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
    """None means genuinely absent; {} means present but unusable.

    Inspect existence independently of reading. Reject links/non-regular files,
    including dangling links, and mode-000 files even when the reader is root.
    Never let an inaccessible directory or malformed record enable fallback.
    """
    try:
        metadata = Path(path).lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return {}
    if not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o444:
        return {}
    try:
        with Path(path).open(encoding="utf-8") as stream:
            text = stream.read(16385)
    except (OSError, UnicodeError):
        return {}
    if len(text) > 16384:
        return {}
    values = {}
    for line in text.splitlines():
        if "=" not in line:
            return {}
        key, value = line.split("=", 1)
        if key in values or key not in _ALLOWED_KEYS or not _SAFE_VALUE.fullmatch(value):
            return {}
        values[key] = value
    return values


def _parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


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
    if marker is not None and all(
        record is None for record in (last_attempt, last_success, last_failure, in_progress)
    ):
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
    file) or by a failure record of the same attempt is not genuine.
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
    """Modern identity is always UUID-based, never a second-resolution time."""
    return bool(
        first
        and second
        and first.get("attempt_id")
        and first["attempt_id"] == second.get("attempt_id")
    )


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


_STAGES = {
    "configure",
    "dump",
    "compress",
    "validate",
    "checksum",
    "upload",
    "verify_upload",
    "record",
}
_CATEGORIES = {
    "configuration_missing": "configure",
    "configuration_invalid": "configure",
    "workdir_unwritable": "configure",
    "dump_failed": "dump",
    "compression_failed": "compress",
    "archive_unreadable": "validate",
    "archive_too_small": "validate",
    "archive_content_invalid": "validate",
    "checksum_failed": "checksum",
    "upload_failed": "upload",
    "upload_unversioned": "upload",
    "upload_unverified": "verify_upload",
    "state_failed": "record",
}


def _record_problem(record, kind, now):
    """Explicit schemas produced by backup.py (terminal projections are identical)."""
    malformed = "success_partial" if kind == "success" else f"{kind}_malformed"
    if not record:
        return malformed
    try:
        if str(UUID(record.get("attempt_id", ""))) != record["attempt_id"]:
            return malformed
    except (ValueError, KeyError):
        return malformed
    if not record.get("object_key", "").startswith("postgres/") or not record[
        "object_key"
    ].endswith(".sql.gz"):
        return malformed
    if record.get("stage") not in _STAGES:
        return malformed
    outcome = record.get("outcome")
    if kind != "progress" and outcome not in {"success", "failure"}:
        return malformed
    if kind in {"success", "failure"} and outcome != kind:
        return malformed
    finish = (
        "started_at"
        if kind == "progress"
        else ("completed_at" if outcome == "success" else "failed_at")
    )
    start, end = (_parse_timestamp(record.get(key)) for key in ("attempted_at", finish))
    if start is None or end is None:
        return "success_malformed" if kind == "success" else malformed
    if start > now or end > now:
        return "future_dated"
    if end < start:
        return "success_incoherent" if kind == "success" else malformed
    fields = {"attempt_id", "attempted_at", "object_key", "stage", finish}
    if kind == "progress":
        return None if set(record) == fields else malformed
    fields |= {"outcome", "category"}
    if outcome == "success":
        fields |= {"version_id", "sha256", "size_bytes"}
        if record.get("stage") != "record" or record.get("category") != "none":
            return malformed
        if not re.fullmatch(r"[0-9a-f]{64}", record.get("sha256", "")):
            return malformed
        if not re.fullmatch(r"[1-9][0-9]*", record.get("size_bytes", "")):
            return malformed
        if not record.get("version_id") or record["version_id"] in {"None", "null"}:
            return malformed
    else:
        fields.add("exit_status")
        category, stage = record.get("category"), record["stage"]
        if category == "upload_checksum_mismatch":
            valid = stage in {"upload", "verify_upload"}
        else:
            valid = (
                category in {"interrupted", "supervision_failed", "command_output_invalid"}
                or _CATEGORIES.get(category) == stage
            )
        if not valid or not re.fullmatch(r"-?[1-9][0-9]*", record.get("exit_status", "")):
            return malformed
    return None if set(record) == fields else malformed


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
        "attempt_in_progress": state.in_progress is not None,
        "state": "missing",
    }

    def unhealthy(name):
        detail["state"] = name
        return False, detail

    # Keep the specific contradiction/unresolved diagnostics, but never use
    # these checks to skip validation of another present record.
    if _success_is_uncommitted(state):
        return unhealthy("uncommitted")
    if _published_success_is_contradicted(state):
        return unhealthy("contradicted")
    for kind, record in (
        ("success", state.last_success),
        ("attempt", state.last_attempt),
        ("failure", state.last_failure),
        ("progress", state.in_progress),
    ):
        if record is not None:
            problem = _record_problem(record, kind, now)
            if problem:
                return unhealthy(
                    "attempt_malformed" if problem == "progress_malformed" else problem
                )

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
        if attempt is None:
            # Absence of the commitment, not corruption of it.
            return unhealthy("success_uncommitted")
        if _same_attempt(success, attempt):
            if success != attempt:
                return unhealthy("success_contradicted")
        elif attempt["outcome"] != "failure" or _parse_timestamp(
            attempt["attempted_at"]
        ) < _parse_timestamp(success["completed_at"]):
            return unhealthy("success_uncommitted")
    else:
        if attempt is None:
            return unhealthy("attempt_record_missing")
        if attempt.get("outcome") == "success":
            # Committed as successful with nothing published to corroborate it.
            return unhealthy("success_missing")

    failure, progress = state.last_failure, state.in_progress
    records = [record for record in (success, attempt, failure, progress) if record]
    for index, first in enumerate(records):
        for second in records[index + 1 :]:
            if not _same_attempt(first, second) and first["object_key"] == second["object_key"]:
                return unhealthy("attempt_incoherent")
    if failure:
        if attempt is None:
            return unhealthy("attempt_record_missing")
        if _same_attempt(failure, attempt):
            if failure != attempt:
                return unhealthy("failure_contradicted")
        elif _parse_timestamp(failure["failed_at"]) > _parse_timestamp(attempt["attempted_at"]):
            return unhealthy("failure_contradicted")
    if attempt and attempt["outcome"] == "failure" and not _same_attempt(attempt, failure):
        return unhealthy("failure_missing")
    if progress:
        if _same_attempt(progress, attempt):
            return unhealthy("uncommitted")
        terminal_at = (
            _parse_timestamp(attempt.get("completed_at") or attempt.get("failed_at"))
            if attempt
            else None
        )
        if terminal_at and _parse_timestamp(progress["attempted_at"]) < terminal_at:
            return unhealthy("attempt_incoherent")
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
    elif progress:
        detail["warning"] = "attempt_in_progress"
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
