"""Manual development-only worker; no provider, ORM, cloud or scheduling APIs."""

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from market.state.canonical import canonical_json, identity_digest
from research.validation_acquisition import ROOT
from research.validation_data import audit_cache, connect, metadata

# Disjoint checkpoint ownership; paired ORB comparators stay in the same catalog.
GROUPS = (
    ("phase5-sweep-reversal-v1", "phase5-acceptance-continuation-v1"),
    ("pullback-m15-v1", "range-m15-v1"),
    ("pullback-h1-v1", "fast-mr-h1-v1", "ewmac-d-v1", "breakout-d-v1", "carry-readiness-v1"),
    (
        "orb-m15-confirmed-v1:london",
        "orb-m15-wick-v1:london",
        "orb-m15-fvg-v1:london",
        "orb-m15-confirmed-v1:new_york",
        "orb-m15-wick-v1:new_york",
        "orb-m15-fvg-v1:new_york",
    ),
)


def project_development(source, destination):
    """Copy authenticated open blobs only, retaining sealed metadata with NULL blobs.

    Never SQLite-backup/ATTACH the source: that would copy sealed database pages.
    No decompression is needed. Preserve original metadata/acquisition timestamps.
    """
    audit = audit_cache(source)
    destination = Path(destination)
    with destination.open("xb"):
        pass
    destination.chmod(0o600)
    original = target = None
    try:
        original = connect(source)
        original.execute("BEGIN")
        _, records = metadata(original)
        if {k: v["metadata_sha256"] for k, v in records.items()} != audit["manifest"]:
            raise ValueError("projection_manifest_drift")
        target = sqlite3.connect(destination)
        target.executescript("""
            CREATE TABLE registration(identity TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE chunk(identity TEXT PRIMARY KEY, metadata TEXT NOT NULL,
                metadata_sha256 TEXT NOT NULL, blob BLOB);
        """)
        target.executemany(
            "INSERT INTO registration VALUES (?,?)",
            original.execute("SELECT identity,body FROM registration"),
        )
        price_chunks = sealed_chunks = 0
        for key, item in sorted(records.items()):
            period = item["request"]["period"]
            blob = None
            if period in {"warmup", "development"}:
                blob = original.execute(
                    "SELECT blob FROM chunk WHERE identity=?", (key,)
                ).fetchone()[0]
                if hashlib.sha256(blob).hexdigest() != item["blob_sha256"]:
                    raise ValueError("projection_open_blob_corrupt")
                price_chunks += 1
            elif period in {"sealed_first", "sealed_second"}:
                sealed_chunks += 1
            else:
                raise ValueError("projection_period_invalid")
            body = {k: v for k, v in item.items() if k != "metadata_sha256"}
            target.execute(
                "INSERT INTO chunk VALUES (?,?,?,?)",
                (key, canonical_json(body), item["metadata_sha256"], blob),
            )
        target.commit()
        target.close()
        target = None
        destination.chmod(0o400)
        return {
            "schema": "phase55/development-transfer-v1",
            "audit_sha256": identity_digest(audit),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "price_chunks": price_chunks,
            "sealed_metadata_chunks": sealed_chunks,
            "holdout_payloads": "physically_absent",
            "created_at": datetime.now(UTC).isoformat(),
        }
    except BaseException:
        if target is not None:
            target.close()
        destination.unlink(missing_ok=True)
        raise
    finally:
        if original is not None:
            original.close()


def verify_projection(path, binding):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != binding["sha256"]:
        raise ValueError("projection_bytes_mismatch")
    audit = audit_cache(path)
    if identity_digest(audit) != binding["audit_sha256"]:
        raise ValueError("projection_audit_mismatch")
    db = connect(path)
    try:
        _, records = metadata(db)
        present = {r[0] for r in db.execute("SELECT identity FROM chunk WHERE blob IS NOT NULL")}
        expected = {
            k for k, v in records.items() if v["request"]["period"] in {"warmup", "development"}
        }
        if (
            present != expected
            or len(present) != binding["price_chunks"]
            or len(records) - len(present) != binding["sealed_metadata_chunks"]
        ):
            raise ValueError("projection_sealed_payload_or_missing_chunk")
    finally:
        db.close()


def run_group(group):
    from research.validation_batch import run
    from research.validation_registration import VALIDATION_REVISION, Catalog
    from research.validation_reports import export_population, publish_immutable

    root = ROOT / ".candidate-data/phase55-v1"
    frozen = json.loads(
        (ROOT / f"docs/phase5.5/frozen-registration-v{VALIDATION_REVISION}.json").read_text()
    )
    binding = json.loads((ROOT / "docs/phase5.5/worker-transfer.json").read_text())
    verify_projection(root / "acquisition.sqlite3", binding)
    catalog = Catalog(root / f"worker-{group}.sqlite3")
    try:
        identity, registration = catalog.register(audit_cache(root / "acquisition.sqlite3"))
        if identity != frozen["identity"] or registration != frozen["body"]:
            raise ValueError("worker_registration_mismatch")
        start, end = map(datetime.fromisoformat, registration["development"])
        strategies = GROUPS[group]
        # Alternate the two descriptor-heavy identities to reuse causal inputs.
        batches = [strategies] if group == 0 else [(strategy,) for strategy in strategies]
        for batch in batches:
            for instrument in registration["instruments"]:
                cursors = {}
                for strategy in batch:
                    last = catalog.db.execute(
                        """SELECT max(json_extract(body,'$.key.end')) FROM checkpoint
                        WHERE registration_id=? AND json_extract(body,'$.key.strategy')=?
                        AND json_extract(body,'$.key.instrument')=?""",
                        (identity, strategy, instrument),
                    ).fetchone()[0]
                    cursors[strategy] = datetime.fromisoformat(last) if last else start
                while any(day < end for day in cursors.values()):
                    for strategy, day in list(cursors.items()):
                        if day >= end:
                            continue
                        until = min(day + timedelta(days=32), end)
                        run(
                            catalog,
                            identity,
                            root / "acquisition.sqlite3",
                            strategy,
                            instrument,
                            day,
                            until,
                        )
                        cursors[strategy] = until
                        print(
                            canonical_json(
                                {
                                    "at": datetime.now(UTC).isoformat(),
                                    "strategy": strategy,
                                    "instrument": instrument,
                                    "through": until.isoformat(),
                                }
                            ),
                            flush=True,
                        )
            for strategy in batch:
                reports = export_population(
                    catalog, identity, strategy, root / f"reports-v{VALIDATION_REVISION}"
                )
                if len(reports) != 65 or len(set(reports)) != 65:
                    raise ValueError("worker_report_population_incomplete")
                publish_immutable(
                    root / f"completed-{strategy.replace(':', '-')}.json",
                    canonical_json(
                        {
                            "registration": identity,
                            "strategy": strategy,
                            "reports": reports,
                            "holdout": "sealed_not_evaluated",
                            "activation": "forbidden",
                        }
                    ),
                )
                print(
                    canonical_json({"completed_strategy": strategy, "reports": len(reports)}),
                    flush=True,
                )
    finally:
        catalog.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", required=True, type=int, choices=range(len(GROUPS)))
    args = parser.parse_args()
    run_group(args.group)


if __name__ == "__main__":
    main()
