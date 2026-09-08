"""Adversarial files, not mocked parser output; no database or network."""

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from django.test import SimpleTestCase

from operations.host_health import backup_assessment, read_backup_state


class BackupProtocolTests(SimpleTestCase):
    def test_adversarial_matrix(self):
        now = datetime.now(UTC)
        start = (now - timedelta(hours=2)).isoformat()
        end = (now - timedelta(hours=1)).isoformat()
        newer = (now - timedelta(minutes=10)).isoformat()
        success = dict(
            attempt_id=str(UUID(int=1)),
            attempted_at=start,
            completed_at=end,
            object_key="postgres/one.sql.gz",
            version_id="v1",
            sha256="a" * 64,
            size_bytes="1234",
            outcome="success",
            stage="record",
            category="none",
        )
        failure = dict(
            attempt_id=str(UUID(int=2)),
            attempted_at=newer,
            failed_at=newer,
            object_key="postgres/two.sql.gz",
            outcome="failure",
            stage="dump",
            category="dump_failed",
            exit_status="1",
        )
        progress = dict(
            attempt_id=str(UUID(int=3)),
            attempted_at=newer,
            started_at=newer,
            object_key="postgres/three.sql.gz",
            stage="dump",
        )
        base = {"backup-last-success": success, "backup-last-attempt": success}
        cases = [
            ("absent", {}, False),
            ("legacy", {"last-backup": "legacy"}, True),
            ("valid", base, True),
            ("no commitment", {"backup-last-success": success}, False),
            (
                "new failure",
                {**base, "backup-last-attempt": failure, "backup-last-failure": failure},
                True,
            ),
            ("new progress", {**base, "backup-in-progress": progress}, True),
            (
                "old terminal",
                {
                    **base,
                    "backup-last-attempt": {**failure, "attempted_at": start, "failed_at": start},
                },
                False,
            ),
            (
                "unresolved",
                {**base, "backup-in-progress": {**progress, "attempt_id": success["attempt_id"]}},
                False,
            ),
        ]
        for filename in base.keys() | {"backup-last-failure", "backup-in-progress"}:
            for content in ("", "garbage", "unreadable"):
                cases.append(
                    (
                        f"{filename} {content}",
                        {**base, "last-backup": "legacy", filename: content},
                        False,
                    )
                )
                cases.append(
                    (
                        f"legacy plus {filename} {content}",
                        {"last-backup": "legacy", filename: content},
                        False,
                    )
                )
        for filename, record in (
            ("backup-last-failure", failure),
            ("backup-in-progress", progress),
        ):
            for field in record:
                cases.append(
                    (
                        f"missing {filename} {field}",
                        {**base, filename: {k: v for k, v in record.items() if k != field}},
                        False,
                    )
                )
        for field, value in (
            ("attempted_at", "bad"),
            ("failed_at", "bad"),
            ("failed_at", (now + timedelta(hours=1)).isoformat()),
            ("attempt_id", "bad"),
            ("category", "unknown"),
            ("stage", "compress"),
            ("exit_status", "0"),
        ):
            bad = {**failure, field: value}
            cases.append(
                (
                    f"invalid terminal {field}",
                    {**base, "backup-last-attempt": bad, "backup-last-failure": bad},
                    False,
                )
            )
        for field, value in (
            ("sha256", "b" * 64),
            ("size_bytes", "4321"),
            ("version_id", "another-version"),
            ("object_key", "postgres/other.sql.gz"),
            ("attempted_at", end),
        ):
            cases.append(
                (
                    f"commit mismatch {field}",
                    {**base, "backup-last-attempt": {**success, field: value}},
                    False,
                )
            )
        cases.extend(
            [
                (
                    "future progress",
                    {
                        **base,
                        "backup-in-progress": {
                            **progress,
                            "started_at": (now + timedelta(hours=1)).isoformat(),
                        },
                    },
                    False,
                ),
                (
                    "old progress",
                    {
                        **base,
                        "backup-in-progress": {
                            **progress,
                            "attempted_at": start,
                            "started_at": start,
                        },
                    },
                    False,
                ),
                (
                    "same key different IDs",
                    {
                        **base,
                        "backup-in-progress": {**progress, "object_key": success["object_key"]},
                    },
                    False,
                ),
                ("unpublished failure", {**base, "backup-last-attempt": failure}, False),
                (
                    "unrelated success terminal",
                    {**base, "backup-last-attempt": {**success, "attempt_id": str(UUID(int=9))}},
                    False,
                ),
            ]
        )
        for field, value in (
            ("attempt_id", "bad"),
            ("failed_at", newer),
            ("sha256", "xyz"),
            ("size_bytes", "-1"),
            ("size_bytes", "0"),
            ("version_id", "null"),
            ("completed_at", start),
            ("attempted_at", "yesterday"),
            ("attempted_at", "0001-01-01T00:00:00+01:00"),
            ("completed_at", (now + timedelta(hours=1)).isoformat()),
        ):
            changed = {**success, field: value}
            if field == "completed_at" and value == start:
                changed["attempted_at"] = end
            cases.append((f"bad {field} {value}", {**base, "backup-last-success": changed}, False))
        for filename, record in base.items():
            for field in record:
                cases.append(
                    (
                        f"missing {filename} {field}",
                        {**base, filename: {k: v for k, v in record.items() if k != field}},
                        False,
                    )
                )
        for name, records, expected in cases:
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory(prefix="backup-matrix-") as root,
            ):
                for filename, content in records.items():
                    path = Path(root, filename)
                    path.write_text(
                        "\n".join(f"{k}={v}" for k, v in content.items())
                        if isinstance(content, dict)
                        else content
                    )
                    if content == "unreadable":
                        path.chmod(0)
                try:
                    ready, detail = backup_assessment(
                        read_backup_state(root), now=now, max_age_hours=8
                    )
                    # The marker mtime can be microseconds newer than the fixed clock.
                    if name == "legacy":
                        ready, detail = backup_assessment(
                            read_backup_state(root), now=datetime.now(UTC), max_age_hours=8
                        )
                    self.assertEqual(ready, expected, detail)
                finally:
                    for path in Path(root).iterdir():
                        os.chmod(path, 0o600)
