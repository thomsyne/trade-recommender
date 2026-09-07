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
}
LEGACY_MARKER = "last-backup"
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:/+\-]{0,200}$")
_ALLOWED_KEYS = {
    "attempted_at",
    "completed_at",
    "failed_at",
    "object_key",
    "outcome",
    "stage",
    "category",
    "exit_status",
    "sha256",
    "size_bytes",
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
    def source(self):
        if self.last_success:
            return "state_file"
        if self.legacy_marker_at is not None:
            return "legacy_marker"
        return "none"


def read_backup_state(state_dir, marker_path=""):
    """Read the backup state files; tolerate absence, partial writes and legacy markers."""
    directory = Path(state_dir) if state_dir else None
    last_attempt = last_success = last_failure = None
    if directory is not None:
        last_attempt = _parse_state_file(directory / STATE_FILES["last_attempt"])
        last_success = _parse_state_file(directory / STATE_FILES["last_success"])
        last_failure = _parse_state_file(directory / STATE_FILES["last_failure"])
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
        legacy_marker_at=legacy_at,
        state_dir=str(directory) if directory is not None else "",
    )


def backup_assessment(state, *, now, max_age_hours):
    """Return (ready, safe_detail) from genuine last success, never last attempt."""
    success_at = state.last_success_at
    detail = {
        "source": state.source,
        "last_success_age_seconds": None,
        "last_attempt_outcome": state.last_attempt_outcome,
        "last_failure_category": (state.last_failure or {}).get("category"),
        "last_failure_stage": (state.last_failure or {}).get("stage"),
        "state": "missing",
    }
    if success_at is None:
        return False, detail
    age = (now - success_at).total_seconds()
    detail["last_success_age_seconds"] = int(age)
    if age > max_age_hours * 3600:
        detail["state"] = "stale"
        return False, detail
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
