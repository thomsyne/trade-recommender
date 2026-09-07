"""Safe, structured task-failure diagnostics.

Failures are recorded as stable codes, categories, stages and bounded,
redacted summaries. Raw exception text of unclassified exception types is
never persisted: only its type name and a fixed statement that details were
withheld. Credentials, tokens, environment-like assignments and URL userinfo
are redacted from every summary that is persisted or rendered.
"""

import re
from contextlib import contextmanager
from dataclasses import dataclass

import httpx
from django.core.exceptions import ValidationError
from django.db import DatabaseError

REDACTED = "[redacted]"
SUMMARY_LIMIT = 240
STAGE_ATTRIBUTE = "_task_stage"

_REDACTION_PATTERNS = (
    # URL userinfo: scheme://user:password@host
    (re.compile(r"(?<=://)[^/\s@]+:[^/\s@]+@"), f"{REDACTED}@"),
    # Bearer / token-style assignments: "Authorization: Bearer x", "token=x", "api_key: x"
    (
        re.compile(
            r"(?i)\b(authorization|bearer|token|api[_-]?key|apikey|secret|password|passwd|"
            r"pgpassword|x-api-key|access[_-]?key|session|cookie)\b\s*[:=]?\s*[^\s,;]+"
        ),
        rf"\1={REDACTED}",
    ),
    # Environment-like assignments: NAME=value
    (re.compile(r"\b[A-Z][A-Z0-9_]{2,}=[^\s,;]+"), f"[env]={REDACTED}"),
    # Well-known credential shapes
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"), REDACTED),
    # Long opaque tokens
    (re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"), REDACTED),
)


def redact(text, limit=SUMMARY_LIMIT):
    """Return a bounded single-line rendering of ``text`` with secrets removed."""
    if text is None:
        return ""
    value = " ".join(str(text).split())
    for pattern, replacement in _REDACTION_PATTERNS:
        value = pattern.sub(replacement, value)
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    return value


@dataclass(frozen=True)
class FailureDiagnostic:
    code: str
    category: str
    stage: str
    exception_type: str
    summary: str
    retryable: bool


_KNOWN_MESSAGE_PREFIXES = (
    ("Recommendation batch incomplete", "batch_incomplete", "provider", True),
    ("Anthropic request failed", "provider_http", "provider", True),
    ("Anthropic response", "provider_response_invalid", "provider", False),
    ("OANDA returned HTTP", "provider_http", "provider", True),
    ("OANDA account instruments response", "provider_response_invalid", "provider", False),
)


def classify_failure(error, *, stage=""):
    """Map an exception onto a stable, safe diagnostic.

    Only exception types whose messages are authored by this repository (or
    by tightly bounded provider adapters) contribute a redacted message. Any
    other exception contributes its type name only.
    """
    stage = stage or getattr(error, STAGE_ATTRIBUTE, "") or ""
    exception_type = type(error).__name__
    message = str(error)
    if isinstance(error, ValueError) and message.endswith("is not configured"):
        return FailureDiagnostic(
            "configuration_missing",
            "configuration",
            stage or "configure",
            exception_type,
            redact(message),
            False,
        )
    if isinstance(error, ValueError) and message.endswith("is disabled"):
        return FailureDiagnostic(
            "feature_disabled",
            "policy",
            stage or "configure",
            exception_type,
            redact(message),
            False,
        )
    if isinstance(error, ValueError) and message.startswith("Unknown task"):
        return FailureDiagnostic(
            "unknown_task",
            "configuration",
            stage or "dispatch",
            exception_type,
            redact(message),
            False,
        )
    if isinstance(error, ValidationError):
        detail = "; ".join(error.messages) if hasattr(error, "messages") else message
        return FailureDiagnostic(
            "validation_rejected",
            "validation",
            stage or "validate",
            exception_type,
            redact(detail),
            False,
        )
    if isinstance(error, DatabaseError):
        return FailureDiagnostic(
            "database_error",
            "database",
            stage or "persist",
            exception_type,
            f"{exception_type}: details withheld",
            True,
        )
    if isinstance(error, MemoryError):
        return FailureDiagnostic(
            "resource_memory",
            "resource",
            stage,
            exception_type,
            "MemoryError: details withheld",
            True,
        )
    failure_kind = getattr(error, "failure_kind", None)
    if exception_type == "OandaError":
        code = f"provider_oanda_{failure_kind}" if failure_kind else "provider_oanda"
        return FailureDiagnostic(
            code,
            "provider",
            stage or "provider_fetch",
            exception_type,
            redact(message),
            failure_kind not in {"auth", "malformed"},
        )
    if isinstance(error, httpx.TimeoutException):
        return FailureDiagnostic(
            "provider_timeout",
            "network",
            stage or "provider_fetch",
            exception_type,
            f"{exception_type}: provider request timed out",
            True,
        )
    if isinstance(error, httpx.HTTPError):
        return FailureDiagnostic(
            "provider_network",
            "network",
            stage or "provider_fetch",
            exception_type,
            f"{exception_type}: provider request failed",
            True,
        )
    for prefix, code, category, retryable in _KNOWN_MESSAGE_PREFIXES:
        if message.startswith(prefix):
            return FailureDiagnostic(
                code, category, stage or "provider", exception_type, redact(message), retryable
            )
    return FailureDiagnostic(
        "unclassified_exception",
        "unclassified",
        stage,
        exception_type,
        f"{exception_type}: details withheld (unclassified exception)",
        True,
    )


@contextmanager
def task_stage(name):
    """Annotate any exception escaping the block with the stage it failed in."""
    try:
        yield
    except BaseException as error:
        if not getattr(error, STAGE_ATTRIBUTE, ""):
            try:
                setattr(error, STAGE_ATTRIBUTE, name)
            except (AttributeError, TypeError):  # pragma: no cover - exotic exception types
                pass
        raise


def record_task_failure(occurrence, error, *, attempt_number, terminal, now):
    """Append one immutable failure record for ``occurrence`` and return it."""
    from operations.models import TaskFailure

    diagnostic = classify_failure(error)
    failure, _ = TaskFailure.objects.get_or_create(
        occurrence=occurrence,
        attempt_number=attempt_number,
        defaults={
            "task_name": occurrence.task_name,
            "error_code": diagnostic.code,
            "category": diagnostic.category,
            "stage": diagnostic.stage,
            "exception_type": diagnostic.exception_type,
            "summary": diagnostic.summary,
            "terminal": terminal,
            "occurred_at": now,
        },
    )
    return failure, diagnostic
