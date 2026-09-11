"""Disposable worker transfer tests; no actual sealed price access."""

import gzip
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market.state.canonical import canonical_json, identity_digest


class WorkerProjectionTests(unittest.TestCase):
    def test_projection_never_reads_or_transfers_sealed_blobs(self):
        from research import validation_worker as worker

        with tempfile.TemporaryDirectory() as directory:
            source, target = [Path(directory) / name for name in ("source.db", "target.db")]
            db = sqlite3.connect(source)
            db.executescript("""
                CREATE TABLE registration(identity TEXT, body TEXT);
                CREATE TABLE chunk(identity TEXT, metadata TEXT, metadata_sha256 TEXT, blob BLOB);
            """)
            db.execute("INSERT INTO registration VALUES ('registered', '{}')")
            records = {}
            for key, period in (("open", "development"), ("sealed", "sealed_first")):
                blob = gzip.compress(key.encode(), mtime=0)
                body = {
                    "request": {"period": period},
                    "blob_sha256": hashlib.sha256(blob).hexdigest(),
                }
                digest = identity_digest(body)
                records[key] = {"metadata_sha256": digest, **body}
                db.execute(
                    "INSERT INTO chunk VALUES (?,?,?,?)", (key, canonical_json(body), digest, blob)
                )
            db.commit()
            db.close()
            audit = {"manifest": {key: row["metadata_sha256"] for key, row in records.items()}}
            original_connect = worker.connect
            reads = []

            class Guard:
                def __init__(self):
                    self.db = original_connect(source)

                def execute(self, sql, args=()):
                    if "blob" in sql.lower():
                        self_outer.assertEqual(sql, "SELECT blob FROM chunk WHERE identity=?")
                        self_outer.assertEqual(args, ("open",))
                        reads.append(args)
                    return self.db.execute(sql, args)

                def close(self):
                    self.db.close()

            self_outer = self
            with (
                patch.object(worker, "audit_cache", return_value=audit),
                patch.object(worker, "metadata", return_value=("registered", records)),
                patch.object(worker, "connect", side_effect=lambda _: Guard()),
                patch.object(gzip, "decompress", side_effect=AssertionError("NO_DECOMPRESSION")),
            ):
                result = worker.project_development(source, target)
                self.assertEqual(result["price_chunks"], 1)
                self.assertEqual(result["sealed_metadata_chunks"], 1)
                with self.assertRaises(FileExistsError):
                    worker.project_development(source, target)
            self.assertEqual(reads, [("open",)])
            projected = sqlite3.connect(target)
            self.addCleanup(projected.close)
            self.assertIsNone(
                projected.execute("SELECT blob FROM chunk WHERE identity='sealed'").fetchone()[0]
            )
            self.assertEqual(projected.execute("SELECT count(*) FROM chunk").fetchone()[0], 2)
            self.assertEqual(result["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
            with (
                patch.object(worker, "audit_cache", return_value=audit),
                patch.object(worker, "metadata", return_value=("registered", records)),
            ):
                worker.verify_projection(target, result)
                projected.close()
                target.chmod(0o600)
                projected = sqlite3.connect(target)
                for mutation in (
                    "UPDATE chunk SET blob=x'1234' WHERE identity='sealed'",
                    "UPDATE chunk SET blob=NULL WHERE identity='open'",
                ):
                    projected.execute(mutation)
                    projected.commit()
                    rehashed = {**result, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
                    with self.assertRaisesRegex(
                        ValueError, "projection_sealed_payload_or_missing_chunk"
                    ):
                        worker.verify_projection(target, rehashed)
                    projected.execute("UPDATE chunk SET blob=NULL WHERE identity='sealed'")
                    projected.commit()
                projected.close()

    def test_refused_audit_creates_no_transfer_file(self):
        from research import validation_worker as worker

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.db"
            with patch.object(
                worker,
                "audit_cache",
                side_effect=ValueError("frozen_coverage_metadata_unavailable"),
            ):
                with self.assertRaisesRegex(ValueError, "frozen_coverage_metadata_unavailable"):
                    worker.project_development("unused", target)
            self.assertFalse(target.exists())

    def test_work_groups_cover_exact_baselines_without_duplicate_ownership(self):
        from research.validation_batch import OVERLAYS
        from research.validation_registration import STRATEGIES
        from research.validation_worker import GROUPS

        assigned = [strategy for group in GROUPS for strategy in group]
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertEqual(set(assigned), set(STRATEGIES) - set(OVERLAYS))
        for group in GROUPS:
            for strategy in group:
                if strategy.startswith("orb-m15-fvg"):
                    self.assertIn(strategy.replace("orb-m15-fvg", "orb-m15-confirmed"), group)
