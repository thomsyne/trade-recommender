"""Return-blind inventory and sealed, manifest-bound development data access."""

import gzip
import hashlib
import json
import sqlite3
from collections import defaultdict
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
from research.validation_acquisition import chunks, plan, predecessor_plan
from research.validation_audit import PERIODS


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
    """May inspect sealed timestamps only; never expose a price or calculate outcomes."""
    connection = connect(path)
    try:
        registration, records = metadata(connection)
        groups = defaultdict(list)
        for key, item in records.items():
            request = item["request"]
            groups[(request["period"], request["instrument"], request["granularity"])].append(key)
        summary = []
        for (period, instrument, granularity), keys in sorted(groups.items()):
            timestamps, acquisition_times, excluded = [], [], []
            for key in keys:
                # Deliberate audit-only projection, including holdout; no rows leave this scope.
                timestamps.extend(
                    r["timestamp"] for r in _verified_blob(connection, key, records[key])
                )
                acquisition_times.append(records[key]["acquired_at"])
                excluded.extend(records[key]["period_boundary_exclusions"])
            _, a, b = next(p for p in PERIODS if p[0] == period)
            start, end = (
                datetime.fromisoformat(a).replace(tzinfo=UTC),
                datetime.fromisoformat(b).replace(tzinfo=UTC),
            )
            expected = set(expected_times(start, end, granularity))
            actual = set(timestamps)
            missing, unexpected = sorted(expected - actual), sorted(actual - expected)
            summary.append(
                {
                    "period": period,
                    "instrument": instrument,
                    "granularity": granularity,
                    "rows": len(timestamps),
                    "distinct_intervals": len(actual),
                    "duplicate_intervals": len(timestamps) - len(actual),
                    "first_timestamp": min(actual) if actual else None,
                    "last_timestamp": max(actual) if actual else None,
                    "first_acquired": min(acquisition_times),
                    "last_acquired": max(acquisition_times),
                    "nominal_expected_intervals": len(expected),
                    "nominal_missing_intervals": len(missing),
                    "missing_timestamp_sha256": identity_digest(missing),
                    "unexpected_intervals": len(unexpected),
                    "unexpected_regular_open_intervals": sum(
                        regular_open(datetime.fromisoformat(at), granularity) for at in unexpected
                    ),
                    "outside_regular_model_intervals": sum(
                        not regular_open(datetime.fromisoformat(at), granularity)
                        for at in unexpected
                    ),
                    "unexpected_timestamp_sha256": identity_digest(unexpected),
                    "period_boundary_exclusions": sorted(excluded),
                    "expected_calendar": "regular_NY_FX_model_not_exception_attestation",
                    "bid_available": len(timestamps),
                    "ask_available": len(timestamps),
                    "mid": "derived_only",
                    "revisions": "single_acquisition_final_snapshot_no_historical_vintage_claim",
                    "manifest_sha256": identity_digest(
                        {key: records[key]["metadata_sha256"] for key in sorted(keys)}
                    ),
                }
            )
        return {
            "schema": "phase55/acquired-coverage-v1",
            "acquisition_registration": registration,
            "manifest": {key: item["metadata_sha256"] for key, item in sorted(records.items())},
            "groups": summary,
            "holdout": "sealed_metadata_only",
            "mandatory_unavailable": [
                "historical_financing_rollovers",
                "exceptional_session_vintages",
                "macro_event_vintages",
                "carry_forwards_ranking",
            ],
            "prior_use": "owner_attested_no_phase5_results_2025-01-06_to_2026-09-07",
        }
    finally:
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
