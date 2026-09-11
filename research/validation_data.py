"""Return-blind inventory and sealed, manifest-bound development data access."""

import gzip
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from market.quality import (
    NEW_YORK,
    _market_is_open,
    live_interval_is_aligned,
    registered_candle_completion,
    registered_successor,
)
from market.state.canonical import canonical_json, identity_digest
from research.validation_acquisition import ROOT, chunks, plan, predecessor_plan


def connect(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def regular_open(at, granularity):
    return live_interval_is_aligned(at, granularity) and (
        granularity == "W" or _market_is_open(at.astimezone(NEW_YORK))
    )


def expected_times(start, end, granularity, *, completed=True):
    cursor = start
    # At most one week to find the first registered open, including W Friday.
    while not regular_open(cursor, granularity):
        cursor += timedelta(minutes=15)
        if cursor >= end:
            return
    while cursor < end:
        if not completed or registered_candle_completion(cursor, granularity) <= end:
            yield cursor.isoformat()
        cursor = registered_successor(cursor, granularity)


def metadata(connection):
    rows = connection.execute("SELECT identity,body FROM registration").fetchall()
    expected_plan = plan()
    registration = identity_digest(expected_plan)
    accepted = {identity_digest(p): canonical_json(p) for p in (predecessor_plan(), expected_plan)}
    if registration not in dict(rows) or any(accepted.get(k) != b for k, b in rows):
        raise ValueError("acquisition_registration_drift")
    expected = {canonical_json(r) for r in chunks()}
    seen = set()
    result = {}
    for key, body, digest in connection.execute(
        "SELECT identity,metadata,metadata_sha256 FROM chunk ORDER BY identity"
    ):
        item = json.loads(body)
        request = canonical_json(item["request"])
        if (
            identity_digest(item) != digest
            or request not in expected
            or request in seen
            or item["registration"] not in dict(rows)
            or key
            != identity_digest({"registration": item["registration"], "request": item["request"]})
        ):
            raise ValueError("acquisition_metadata_corrupt")
        seen.add(request)
        result[key] = {"metadata_sha256": digest, **item}
    if seen != expected:
        raise ValueError("acquisition_incomplete")
    return registration, result


def _verified_blob(connection, key, meta):
    # This gate precedes even a SELECT. Metadata projection after decoding is
    # not a seal. Only the frozen warmup/development requests may reach a blob.
    try:
        request = meta["request"]
        start, end = map(datetime.fromisoformat, (request["start"], request["end"]))
        allowed = (
            request["period"] in {"warmup", "development"}
            and start.utcoffset() == end.utcoffset() == timedelta(0)
            and datetime(2017, 1, 1, tzinfo=UTC) <= start < end <= datetime(2025, 1, 6, tzinfo=UTC)
        )
    except (KeyError, TypeError, ValueError):
        allowed = False
    if not allowed:
        raise ValueError("sealed_or_invalid_blob_request") from None
    stored = connection.execute(
        "SELECT metadata,metadata_sha256 FROM chunk WHERE identity=?", (key,)
    ).fetchone()
    try:
        actual = json.loads(stored[0])
        authenticated = (
            identity_digest(actual) == stored[1]
            and meta == {"metadata_sha256": stored[1], **actual}
            and key == identity_digest({"registration": actual["registration"], "request": request})
        )
    except (TypeError, KeyError, ValueError):
        authenticated = False
    if not authenticated:
        raise ValueError("blob_metadata_identity_mismatch") from None
    blob = connection.execute("SELECT blob FROM chunk WHERE identity=?", (key,)).fetchone()[0]
    if hashlib.sha256(blob).hexdigest() != meta["blob_sha256"]:
        raise ValueError("acquisition_blob_corrupt")
    data = gzip.decompress(blob)
    if hashlib.sha256(data).hexdigest() != meta["content_sha256"]:
        raise ValueError("acquisition_content_corrupt")
    rows = json.loads(data)
    if (
        len(rows) != meta["rows"]
        or identity_digest([r["timestamp"] for r in rows]) != meta["timestamp_sha256"]
    ):
        raise ValueError("acquisition_timestamp_corrupt")
    return rows


def audit_cache(path):
    """Post-freeze coverage audit: authenticate metadata, never read price blobs."""
    connection = None
    try:
        connection = connect(path)
        connection.set_authorizer(
            lambda action, table, column, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_READ and table == "chunk" and column == "blob"
                else sqlite3.SQLITE_OK
            )
        )
        registration, records = metadata(connection)
        frozen = json.loads((ROOT / "docs/phase5.5/frozen-registration-v2.json").read_text())
        audit = json.loads((ROOT / "docs/phase5.5/acquired-coverage.json").read_text())
        if (
            identity_digest(frozen["body"]) != frozen["identity"]
            or identity_digest(audit) != frozen["body"]["audit_sha256"]
            or registration != audit["acquisition_registration"]
            or {k: v["metadata_sha256"] for k, v in records.items()} != audit["manifest"]
        ):
            raise ValueError("frozen_coverage_mismatch")
        return audit
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        # Never echo provider metadata, malformed JSON contents or DB errors.
        raise ValueError("frozen_coverage_metadata_unavailable") from None
    finally:
        if connection is not None:
            connection.close()


def load_development(path, manifest, instrument, granularity):
    """No release parameter: historical holdout is impossible through this loader."""
    connection = connect(path)
    try:
        _, records = metadata(connection)
        if manifest != {key: item["metadata_sha256"] for key, item in sorted(records.items())}:
            raise ValueError("registered_manifest_mismatch")
        result = []
        for key, item in records.items():
            request = item["request"]
            if request["period"] not in {"warmup", "development"}:
                continue  # Refuse before blob SELECT/decompression, not after loading outcomes.
            if request["instrument"] != instrument or request["granularity"] != granularity:
                continue
            for row in _verified_blob(connection, key, item):
                if not regular_open(datetime.fromisoformat(row["timestamp"]), granularity):
                    continue  # Timestamp-only model exclusion; retained in raw audit/cache.
                end = registered_candle_completion(
                    datetime.fromisoformat(row["timestamp"]), granularity
                )
                if end > datetime(2025, 1, 6, tzinfo=UTC):
                    raise ValueError("sealed_boundary_overlap")
                result.append(
                    {
                        **row,
                        "acquired_at": item["acquired_at"],
                        "chunk_identity": key,
                        "granularity": granularity,
                        "end": end.isoformat(),
                    }
                )
        result.sort(key=lambda row: row["timestamp"])
        if not result or len({r["timestamp"] for r in result}) != len(result):
            raise ValueError("development_missing_or_duplicate")
        return result
    finally:
        connection.close()
