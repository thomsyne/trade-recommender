"""Private, append-only, return-blind OANDA acquisition for Phase5.5 only.

No Django initialization, market writes, strategy imports or outcome loader.
The stored candles are later-acquired retrospective inputs, never historical PIT.
"""

import argparse
import ast
import fcntl
import gzip
import hashlib
import json
import os
import re
import shlex
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from market.oanda import OandaClient, _parse_live_candle
from market.quality import live_interval_is_aligned, registered_candle_completion
from market.state.canonical import canonical_json, identity_digest
from research.validation_audit import PERIODS

ROOT = Path(__file__).resolve().parents[1]
DAYS = {"W": 365, "D": 365, "H4": 180, "H1": 90, "M15": 28}
MAX_BODY = 4 * 1024 * 1024


def canonical_pairs():
    """Read the source-of-truth tuple without importing or executing its seeder."""
    source = ROOT / "market/management/commands/seed_canonical.py"
    assignments = [
        node.value
        for node in ast.parse(source.read_text()).body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "INSTRUMENTS" for t in node.targets)
    ]
    if len(assignments) != 1:
        raise ValueError("canonical_population_ambiguous")
    pairs = tuple(row.elts[0].attr for row in assignments[0].elts)
    if (
        len(pairs) != 12
        or len(set(pairs)) != 12
        or any(not re.fullmatch(r"[A-Z]{3}_[A-Z]{3}", p) for p in pairs)
    ):
        raise ValueError("canonical_population_drift")
    return pairs


def plan():
    return {
        "schema": "phase55/acquisition-v3",
        "accepted_predecessor": predecessor_plan(),
        "instruments": canonical_pairs(),
        "periods": PERIODS,
        "chunk_days": DAYS,
        "source": "oanda-v20-practice-BA-unsmoothed-NY17-Friday",
        "mode": "later_acquired_retrospective_not_historical_PIT",
        "source_hashes": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "research/validation_acquisition.py",
                "research/validation_audit.py",
                "market/oanda.py",
                "market/quality.py",
                "market/management/commands/seed_canonical.py",
            )
        },
    }


def predecessor_plan():
    return json.loads((ROOT / "docs/phase5.5/acquisition-v2-registration.json").read_text())


def chunks():
    for period, a, b in PERIODS:
        for instrument in canonical_pairs():
            for granularity, days in DAYS.items():
                start, end = (
                    datetime.fromisoformat(a).replace(tzinfo=UTC),
                    datetime.fromisoformat(b).replace(tzinfo=UTC),
                )
                while start < end:
                    stop = min(start + timedelta(days=days), end)
                    yield {
                        "period": period,
                        "instrument": instrument,
                        "granularity": granularity,
                        "start": start.isoformat(),
                        "end": stop.isoformat(),
                    }
                    start = stop


def fetch(client, request):
    """One bounded, fixed GET; parse only candle fields, never provider error text."""
    start, end = datetime.fromisoformat(request["start"]), datetime.fromisoformat(request["end"])
    include_first = live_interval_is_aligned(start, request["granularity"])
    params = {
        "price": "BA",
        "granularity": request["granularity"],
        "from": request["start"],
        "to": request["end"],
        "smooth": "false",
        "dailyAlignment": "17",
        "alignmentTimezone": "America/New_York",
        "weeklyAlignment": "Friday",
        "includeFirst": "true" if include_first else "false",
    }
    started = datetime.now(UTC)
    with client.client.stream(
        "GET", f"/instruments/{request['instrument']}/candles", params=params
    ) as response:
        if response.status_code != 200:
            raise ValueError(
                "provider_auth"
                if response.status_code in (401, 403)
                else f"provider_http_{response.status_code}"
            )
        body = bytearray()
        for part in response.iter_bytes():
            if len(body) + len(part) > MAX_BODY:
                raise ValueError("provider_body_bound")
            body.extend(part)
        acquired = datetime.now(UTC)
        provider_id = response.headers.get("RequestID", "")
        if not re.fullmatch(r"[A-Za-z0-9-]{0,128}", provider_id):
            raise ValueError("provider_id_malformed")
    payload = json.loads(body)
    if (
        set(payload) != {"instrument", "granularity", "candles"}
        or payload["instrument"] != request["instrument"]
        or payload["granularity"] != request["granularity"]
        or type(payload["candles"]) is not list
        or len(payload["candles"]) > 4999
    ):
        raise ValueError("provider_envelope_mismatch")
    normalized, timestamps, boundary_exclusions = [], [], []
    period_end = datetime.fromisoformat(
        next(b for name, _, b in PERIODS if name == request["period"])
    ).replace(tzinfo=UTC)
    previous_timestamp = None
    for item in payload["candles"]:
        if set(item) != {"time", "complete", "volume", "bid", "ask"} or any(
            set(item[side]) != {"o", "h", "l", "c"} for side in ("bid", "ask")
        ):
            raise ValueError("provider_candle_shape")
        candle = _parse_live_candle(item)
        if candle.volume < 0 or not start <= candle.timestamp < end:
            raise ValueError("provider_interval_or_completeness")
        if previous_timestamp is not None and candle.timestamp <= previous_timestamp:
            raise ValueError("provider_duplicate_or_unordered")
        previous_timestamp = candle.timestamp
        for side in ("bid", "ask"):
            opening, high, low, close = [
                getattr(candle, f"{side}_{field}") for field in ("open", "high", "low", "close")
            ]
            if not 0 < low <= min(opening, close) <= max(opening, close) <= high:
                raise ValueError("provider_ohlc_geometry")
        if any(
            getattr(candle, f"bid_{field}") > getattr(candle, f"ask_{field}")
            for field in ("open", "high", "low", "close")
        ):
            raise ValueError("provider_crossed_quotes")
        timestamp = candle.timestamp.isoformat()
        if registered_candle_completion(candle.timestamp, request["granularity"]) > period_end:
            boundary_exclusions.append(timestamp)
            continue
        if not candle.complete:
            raise ValueError("provider_interval_or_completeness")
        timestamps.append(timestamp)
        normalized.append(
            {
                "timestamp": timestamp,
                "volume": candle.volume,
                **{
                    f"{side}_{field}": str(getattr(candle, f"{side}_{field}"))
                    for side in ("bid", "ask")
                    for field in ("open", "high", "low", "close")
                },
            }
        )
    data = canonical_json(normalized).encode()
    metadata = {
        "request": request,
        "include_first": include_first,
        "period_boundary_exclusions": boundary_exclusions,
        "request_started_at": started.isoformat(),
        "acquired_at": acquired.isoformat(),
        "provider_request_id": provider_id,
        "http_status": 200,
        "rows": len(normalized),
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "timestamp_sha256": identity_digest(timestamps),
        "duplicate_intervals": 0,
        "bid_available": len(normalized),
        "ask_available": len(normalized),
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "content_sha256": hashlib.sha256(data).hexdigest(),
        "revision_semantics": "provider_final_at_acquisition_no_historical_revision_claim",
    }
    return metadata, gzip.compress(data, mtime=0)


class Store:
    """Single-writer private artifact cache; SQLite transaction is the checkpoint."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = open(str(self.path) + ".lock", "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.db = sqlite3.connect(self.path, timeout=5)
            os.chmod(self.path, 0o600)
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS registration (identity TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chunk (identity TEXT PRIMARY KEY, metadata TEXT NOT NULL,
                    metadata_sha256 TEXT NOT NULL, blob BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS failure (id INTEGER PRIMARY KEY, request_identity TEXT NOT NULL,
                    acquired_at TEXT NOT NULL, reason TEXT NOT NULL);
            """)
            for table in ("registration", "chunk", "failure"):
                for action in ("UPDATE", "DELETE"):
                    self.db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_acquisition'); END"
                    )
            self.registration = identity_digest(plan())
            rows = self.db.execute("SELECT identity,body FROM registration").fetchall()
            accepted = {identity_digest(p): canonical_json(p) for p in (predecessor_plan(), plan())}
            if any(accepted.get(key) != body for key, body in rows):
                raise ValueError("acquisition_registration_drift")
            self.requests = {
                canonical_json(request): identity_digest(
                    {"registration": self.registration, "request": request}
                )
                for request in chunks()
            }
            self.chunk_registrations = {}
            for key, body, digest in self.db.execute(
                "SELECT identity,metadata,metadata_sha256 FROM chunk"
            ):
                item = json.loads(body)
                request = canonical_json(item["request"])
                if (
                    request not in self.requests
                    or request in self.chunk_registrations
                    or item["registration"] not in dict(rows)
                    or identity_digest(item) != digest
                    or key
                    != identity_digest(
                        {"registration": item["registration"], "request": item["request"]}
                    )
                ):
                    raise ValueError("acquisition_lineage_corrupt")
                self.requests[request] = key
                self.chunk_registrations[request] = item["registration"]
            with self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO registration VALUES (?,?)",
                    (self.registration, canonical_json(plan())),
                )
        except BaseException:
            if hasattr(self, "db"):
                self.db.close()
            self.lock.close()
            raise

    def close(self):
        self.db.close()
        self.lock.close()

    def identity(self, request):
        key = canonical_json(request)
        if key not in self.requests:
            raise ValueError("unregistered_chunk")
        return self.requests[key]

    def contains(self, request):
        row = self.db.execute(
            "SELECT metadata,metadata_sha256,blob FROM chunk WHERE identity=?",
            (self.identity(request),),
        ).fetchone()
        if row:
            metadata = json.loads(row[0])
            if (
                identity_digest(metadata) != row[1]
                or metadata["request"] != request
                or metadata["registration"]
                != self.chunk_registrations.get(canonical_json(request), self.registration)
                or hashlib.sha256(row[2]).hexdigest() != metadata["blob_sha256"]
            ):
                raise ValueError("acquisition_chunk_corrupt")
        return row is not None

    def acquire(self, client, request):
        if self.contains(request):
            return False
        metadata, blob = fetch(client, request)
        metadata["registration"] = self.registration
        metadata["blob_sha256"] = hashlib.sha256(blob).hexdigest()
        with self.db:
            self.db.execute(
                "INSERT INTO chunk VALUES (?,?,?,?)",
                (self.identity(request), canonical_json(metadata), identity_digest(metadata), blob),
            )
        return True

    def inventory(self):
        result = []
        for key, body, digest in self.db.execute(
            "SELECT identity,metadata,metadata_sha256 FROM chunk ORDER BY identity"
        ):
            item = json.loads(body)
            if identity_digest(item) != digest or self.identity(item["request"]) != key:
                raise ValueError("acquisition_metadata_corrupt")
            result.append({"identity": key, "metadata_sha256": digest, **item})
        return {
            "registration": self.registration,
            "planned_chunks": sum(1 for _ in chunks()),
            "completed_chunks": len(result),
            "chunks": result,
            "holdout": "sealed",
        }


def practice_token(path):
    """Allowlisted dotenv parsing, no shell evaluation or environment dumps."""
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key.strip().lower() == "oanda_api_key_test":
            words = shlex.split(value, comments=True)
            if len(words) != 1 or key.strip().lower() in values:
                raise ValueError("practice_credential_invalid")
            values[key.strip().lower()] = words[0]
    if not values.get("oanda_api_key_test"):
        raise ValueError("practice_credential_missing")
    return values["oanda_api_key_test"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "acquire", "inventory"))
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.action == "plan":
        print(canonical_json({"plan": plan(), "chunks": sum(1 for _ in chunks())}))
        return
    if not 1 <= args.limit <= 10000:
        raise ValueError("acquisition_limit")
    store = Store(ROOT / ".candidate-data/phase55-v1/acquisition.sqlite3")
    try:
        if args.action == "inventory":
            print(canonical_json(store.inventory()))
            return
        count = 0
        with OandaClient(practice_token(ROOT / ".env.local"), environment="practice") as client:
            for request in chunks():
                if store.contains(request):
                    continue
                for attempt in range(3):
                    try:
                        store.acquire(client, request)
                        break
                    except Exception as error:
                        # Only locally generated reason codes, never exception/provider text.
                        reason = (
                            str(error)
                            if type(error) is ValueError
                            and re.fullmatch(r"provider_[a-z0-9_]+", str(error))
                            else "acquisition_failed"
                        )
                        with store.db:
                            store.db.execute(
                                "INSERT INTO failure(request_identity,acquired_at,reason) VALUES (?,?,?)",
                                (store.identity(request), datetime.now(UTC).isoformat(), reason),
                            )
                        if reason == "provider_auth" or attempt == 2:
                            print(
                                canonical_json(
                                    {"status": "stopped", "reason": reason, "request": request}
                                )
                            )
                            raise SystemExit(1) from None
                        time.sleep(2**attempt)
                count += 1
                if count % 20 == 0:
                    print(
                        canonical_json({"acquired_this_run": count, "last_request": request}),
                        flush=True,
                    )
                if count >= args.limit:
                    break
                time.sleep(0.1)
        print(canonical_json({"status": "bounded_run_complete", "acquired_this_run": count}))
    finally:
        store.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"status":"failed","reason":"local_acquisition_error_details_suppressed"}')
        raise SystemExit(1) from None
