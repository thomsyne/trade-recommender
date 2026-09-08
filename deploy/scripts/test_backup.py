"""Backup engine tests. Stubs are new regular files in a private temporary directory."""

import errno
import gzip
import hashlib
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("backup", Path(__file__).with_name("backup.py"))
backup = importlib.util.module_from_spec(spec)
sys.modules["backup"] = backup
if Path(spec.origin).exists():
    spec.loader.exec_module(backup)


STUB = """#!/usr/bin/env python3
import base64, hashlib, os, signal, sys, time
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ['STUB_ROOT'])
mode = os.environ.get('STUB_MODE', '')
dump = Path(sys.argv[0]).name == 'pg_dump'
stage = 'dump' if dump else args[1]
with (root / 'calls').open('a') as f: f.write(' '.join(sys.argv) + '\\n')
if dump and mode == 'fail-once' and not (root / 'failed-once').exists():
    (root / 'failed-once').touch()
    sys.exit(3)
if mode == stage + '-fail': sys.exit(3)
if mode.startswith(stage + '-wait'):
    if 'resist' in mode: signal.signal(signal.SIGTERM, signal.SIG_IGN)
    else:
        def stop(*args):
            (root / 'term-received').touch()
            sys.exit(0)
        signal.signal(signal.SIGTERM, stop)
    if 'descendant' in mode:
        pid = os.fork()
        if pid == 0:
            (root / 'grandchild').write_text(str(os.getpid()))
            while True: time.sleep(.01)
    (root / 'child').write_text(str(os.getpid()))
    while True: time.sleep(.01)
if dump:
    path = Path(next(a.split('=', 1)[1] for a in args if a.startswith('--file=')))
    content = b'-- PostgreSQL database dump\\n' + bytes(range(256)) * 1000
    if mode != 'truncated': content += b'\\n-- PostgreSQL database dump complete\\n'
    path.write_bytes(content)
elif stage == 'put-object':
    body = Path(args[args.index('--body') + 1]).read_bytes()
    (root / 'archive.sql.gz').write_bytes(body)
    checksum = base64.b64encode(hashlib.sha256(body).digest()).decode()
    print('null' if mode == 'unversioned' else 'version-1',
          'wrong' if mode == 'put-checksum' else checksum)
else:
    assert args[args.index('--version-id') + 1] == 'version-1'
    body = (root / 'archive.sql.gz').read_bytes()
    sha = hashlib.sha256(body)
    print(len(body) + (mode == 'head-size'),
          'wrong' if mode == 'head-checksum' else base64.b64encode(sha.digest()).decode(),
          'wrong' if mode == 'head-metadata' else sha.hexdigest())
"""


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="backup-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state, self.work = self.root / "state", self.root / "work"
        self.state.mkdir()
        self.work.mkdir()
        tools = self.root / "bin"
        tools.mkdir()
        for name in ("pg_dump", "aws"):
            path = tools / name
            path.write_text(STUB)
            path.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{tools}:{os.environ['PATH']}",
            STUB_ROOT=str(self.root),
            BACKUP_STATE_DIR=str(self.state),
            BACKUP_WORK_DIR=str(self.work),
            POSTGRES_HOST="stub",
            POSTGRES_USER="stub",
            POSTGRES_DB="stub",
            POSTGRES_PASSWORD="test-only",
            BACKUP_BUCKET="stub",
            AWS_REGION="stub",
            BACKUP_MIN_BYTES="1",
            BACKUP_KILL_AFTER_SECONDS="0.2",
        )

    def run_backup(self, **env):
        return subprocess.run(
            ["/bin/sh", str(Path(__file__).with_name("backup.sh")), "once"],
            env={**self.env, **env},
            capture_output=True,
            timeout=10,
        )

    def state_record(self, name):
        return dict(line.split("=", 1) for line in (self.state / name).read_text().splitlines())

    def test_success_and_failure_matrix(self):
        self.assertEqual(self.run_backup().returncode, 0)
        success = self.state_record("backup-last-success")
        self.assertEqual(success, self.state_record("backup-last-attempt"))
        self.assertEqual(self.run_backup().returncode, 0)
        second = self.state_record("backup-last-success")
        self.assertNotEqual(success["attempt_id"], second["attempt_id"])
        self.assertNotEqual(success["object_key"], second["object_key"])
        success = second
        self.assertNotIn(self.env["POSTGRES_PASSWORD"], (self.root / "calls").read_text())
        self.assertEqual((self.state / "backup-last-success").stat().st_mode & 0o777, 0o644)
        archive = self.root / "archive.sql.gz"
        self.assertEqual(success["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertIn(b"PostgreSQL database dump complete", gzip.decompress(archive.read_bytes()))
        inode = (self.state / ".backup-lock").stat().st_ino
        for mode, category in (
            ("dump-fail", "dump_failed"),
            ("truncated", "archive_content_invalid"),
            ("put-object-fail", "upload_failed"),
            ("unversioned", "upload_unversioned"),
            ("put-checksum", "upload_checksum_mismatch"),
            ("head-object-fail", "upload_unverified"),
            ("head-size", "upload_checksum_mismatch"),
            ("head-checksum", "upload_checksum_mismatch"),
            ("head-metadata", "upload_checksum_mismatch"),
        ):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_backup(STUB_MODE=mode).returncode, 1)
                self.assertEqual(self.state_record("backup-last-failure")["category"], category)
                self.assertEqual(self.state_record("backup-last-success"), success)
                self.assertFalse((self.state / "backup-in-progress").exists())
                self.assertEqual(list(self.work.iterdir()), [])
                self.assertEqual((self.state / ".backup-lock").stat().st_ino, inode)
        self.assertEqual(self.run_backup(BACKUP_MIN_BYTES="100000000").returncode, 1)
        self.assertEqual(self.state_record("backup-last-failure")["category"], "archive_too_small")

    def test_state_faults_and_repeated_signals_during_commit(self):
        for failure_at in (
            "backup-in-progress",
            "backup-last-attempt",
            "backup-last-success",
            "backup-last-failure",
            "last-backup",
            None,
        ):
            with (
                self.subTest(failure_at=failure_at),
                tempfile.TemporaryDirectory(prefix="state-fault-") as root,
            ):
                directory = Path(root)
                commands = backup.Commands(0.2)
                instance = backup.Backup(commands)
                instance.directory = directory
                real = backup.write_state
                commits = []

                def write(path, name, values):
                    if name == "backup-last-attempt":
                        commits.append(values.copy())
                        commands.request_stop(signal.SIGTERM, None)
                        commands.request_stop(signal.SIGINT, None)
                    if name == failure_at:
                        raise OSError(errno.ENOSPC, "injected")
                    return real(path, name, values)

                def perform(work, record):
                    if failure_at == "backup-last-failure":
                        raise backup.Failed("dump_failed")
                    return {**record, "outcome": "success", "completed_at": backup.timestamp()}

                with (
                    patch.dict(os.environ, self.env),
                    patch.object(backup, "write_state", write),
                    patch.object(instance, "perform", perform),
                ):
                    status = instance.once()
                self.assertEqual(
                    status,
                    2
                    if failure_at == "backup-in-progress"
                    else (
                        1
                        if failure_at
                        in {"backup-last-attempt", "backup-last-success", "backup-last-failure"}
                        else 0
                    ),
                )
                self.assertLessEqual(len(commits), 1)
                self.assertEqual(
                    (directory / "backup-in-progress").exists(),
                    failure_at
                    in {"backup-last-attempt", "backup-last-success", "backup-last-failure"},
                )

    def test_in_process_faults(self):
        for target, category in (
            ("gzip.open", "compression_failed"),
            ("hashlib.sha256", "checksum_failed"),
        ):
            with (
                self.subTest(target=target),
                patch.dict(os.environ, self.env),
                patch("backup." + target, side_effect=OSError("injected")),
            ):
                instance = backup.Backup(backup.Commands(0.2))
                self.assertEqual(instance.once(), 1)
                self.assertEqual(self.state_record("backup-last-failure")["category"], category)

    def test_operational_lock_errors_are_not_contention(self):
        for code in (errno.EAGAIN, errno.EIO, errno.EBADF, errno.ENOLCK):
            with (
                self.subTest(errno=code),
                patch.dict(os.environ, self.env),
                patch.object(backup.fcntl, "flock", side_effect=OSError(code, "injected")),
            ):
                self.assertEqual(
                    backup.Backup(backup.Commands(0.2)).once(), 3 if code == errno.EAGAIN else 2
                )
        self.assertFalse((self.state / "backup-in-progress").exists())

    def test_preconditions_and_configuration(self):
        for env, category in (
            ({"BACKUP_BUCKET": ""}, "configuration_missing"),
            ({"BACKUP_MIN_BYTES": "lots"}, "configuration_invalid"),
            ({"BACKUP_WORK_DIR": str(self.root / "absent")}, "workdir_unwritable"),
        ):
            with self.subTest(env=env):
                self.assertEqual(self.run_backup(**env).returncode, 1)
                self.assertEqual(self.state_record("backup-last-attempt")["category"], category)
                self.assertFalse((self.root / "calls").exists())
        with (
            patch.dict(os.environ, self.env),
            patch.object(backup.shutil, "which", return_value=None),
        ):
            self.assertEqual(backup.Backup(backup.Commands(0.2)).once(), 2)
        self.assertEqual(self.run_backup(BACKUP_STATE_DIR=str(self.root / "absent")).returncode, 2)
        (self.state / "backup-in-progress").write_text("unresolved")
        self.assertEqual(self.run_backup().returncode, 2)
        self.assertEqual((self.state / "backup-in-progress").read_text(), "unresolved")

    def test_cleanup_failure_retains_blocker(self):
        commands = backup.Commands(0.2)
        instance = backup.Backup(commands)

        def fail(work, record):
            commands.child = object()  # Model a wait/cleanup failure, not a real leaked process.
            raise backup.Failed("supervision_failed")

        with patch.dict(os.environ, self.env), patch.object(instance, "perform", fail):
            instance.directory = self.state
            self.assertEqual(instance.once(), 1)
        self.assertEqual(self.run_backup().returncode, 2)
        self.assertTrue((self.state / "backup-in-progress").exists())

    def test_sigkill_releases_lock_but_retains_evidence(self):
        code = """
import os, signal, sys
sys.path.insert(0, sys.argv[1])
from backup import Backup, Commands
b = Backup(Commands(.2))
def crash(work, record):
    os.kill(os.getpid(), signal.SIGKILL)
b.perform = crash
b.once()
"""
        process = subprocess.run(
            [sys.executable, "-c", code, str(Path(__file__).parent)], env=self.env, timeout=5
        )
        self.assertEqual(process.returncode, -signal.SIGKILL)
        # No command was launched; no child is abandoned by this deliberate crash.
        self.assertFalse((self.root / "calls").exists())
        fd = backup.acquire_lock(self.state)
        os.close(fd)
        before = (self.state / "backup-in-progress").read_bytes()
        self.assertEqual(self.run_backup().returncode, 2)
        self.assertEqual((self.state / "backup-in-progress").read_bytes(), before)

    def test_compression_interruption_and_corrupt_archive(self):
        for mode in ("interrupt", "corrupt"):
            with self.subTest(mode=mode), patch.dict(os.environ, self.env):
                commands = backup.Commands(0.2)
                real = backup.gzip.open

                def open_archive(path, mode_arg, **kwargs):
                    if mode_arg == "rb":
                        Path(path).write_bytes(b"not gzip")
                    elif mode == "interrupt":
                        commands.request_stop(signal.SIGINT, None)
                    return real(path, mode_arg, **kwargs)

                with patch.object(backup.gzip, "open", open_archive):
                    self.assertEqual(
                        backup.Backup(commands).once(), 130 if mode == "interrupt" else 1
                    )
                self.assertEqual(
                    self.state_record("backup-last-attempt")["category"],
                    "interrupted" if mode == "interrupt" else "archive_unreadable",
                )
                self.assertEqual(list(self.work.iterdir()), [])

    def test_loop_retries_failure_and_has_no_sleep_child(self):
        parent = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("backup.py")), "loop"],
            env={**self.env, "STUB_MODE": "fail-once", "BACKUP_INTERVAL_SECONDS": ".2"},
            stdout=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 5
            while not (self.state / "last-backup").exists():
                self.assertIsNone(parent.poll())
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            parent.send_signal(signal.SIGTERM)
            self.assertEqual(parent.wait(timeout=3), 143)
            self.assertEqual(self.state_record("backup-last-failure")["category"], "dump_failed")
            self.assertEqual(self.state_record("backup-last-success")["outcome"], "success")
        finally:
            if parent.poll() is None:
                parent.send_signal(signal.SIGTERM)
                parent.wait(timeout=5)

    def test_restore_refusals_do_not_contact_a_database(self):
        # Even on a machine with real PostgreSQL tools these paths resolve only
        # to newly created stubs, which fail if validation ever reaches them.
        for name in ("psql", "createdb", "dropdb"):
            path = self.root / "bin" / name
            path.write_text("#!/bin/sh\necho unexpected-database-access >&2\nexit 99\n")
            path.chmod(0o755)
        corrupt = self.root / "corrupt.sql.gz"
        corrupt.write_bytes(b"invalid")
        for target, archive, diagnostic in (
            ("trade_recommender", corrupt, "must contain 'restore_check'"),
            ("Bad-restore_check", corrupt, "database name must match"),
            ("phase1_restore_check_test", self.root / "absent", "archive not found"),
            ("phase1_restore_check_test", corrupt, "archive_unreadable"),
        ):
            result = subprocess.run(
                ["/bin/sh", str(Path(__file__).with_name("restore-check.sh")), str(archive)],
                env={**self.env, "RESTORE_CHECK_DB": target, "TMPDIR": str(self.work)},
                capture_output=True,
                timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(diagnostic, result.stderr.decode())
            self.assertNotIn("unexpected-database-access", result.stderr.decode())
        self.assertEqual(list(self.work.iterdir()), [])

    def wait_file(self, name, parent):
        deadline = time.monotonic() + 5
        while not (self.root / name).exists():
            self.assertIsNone(parent.poll())
            self.assertLess(time.monotonic(), deadline, name)
            time.sleep(0.01)

    def test_signals_exclusion_and_no_zombies(self):
        for stage in ("dump", "put-object", "head-object"):
            for resistant in (False, True):
                with self.subTest(stage=stage, resistant=resistant):
                    for name in ("child", "grandchild", "term-received"):
                        (self.root / name).unlink(missing_ok=True)
                    mode = stage + "-wait" + ("-resist" if resistant else "")
                    if sys.platform == "linux":
                        mode += "-descendant"
                    parent = subprocess.Popen(
                        [sys.executable, str(Path(__file__).with_name("backup.py")), "once"],
                        env={**self.env, "STUB_MODE": mode},
                        stdout=subprocess.DEVNULL,
                    )
                    try:
                        self.wait_file("child", parent)
                        if sys.platform == "linux":
                            self.wait_file("grandchild", parent)
                        before = (self.state / "backup-in-progress").read_bytes()
                        for _ in range(2):
                            self.assertEqual(self.run_backup().returncode, 3)
                            self.assertEqual(
                                (self.state / "backup-in-progress").read_bytes(), before
                            )
                        start = time.monotonic()
                        for _ in range(10):
                            if parent.poll() is None:
                                parent.send_signal(signal.SIGTERM)
                            time.sleep(0.01)
                        self.assertEqual(parent.wait(timeout=5), 143)
                        self.assertLess(time.monotonic() - start, 3)
                        if not resistant:
                            self.assertTrue(
                                (self.root / "term-received").exists(), "TERM was inherited blocked"
                            )
                        for name in ("child", "grandchild"):
                            if (self.root / name).exists():
                                with self.assertRaises(ProcessLookupError):
                                    os.kill(int((self.root / name).read_text()), 0)
                        self.assertEqual(
                            self.state_record("backup-last-attempt")["category"], "interrupted"
                        )
                        self.assertEqual(list(self.work.iterdir()), [])
                    finally:
                        if parent.poll() is None:
                            parent.send_signal(signal.SIGTERM)
                            parent.wait(timeout=10)


class ProcessTests(unittest.TestCase):
    def test_python_engine_exists(self):
        self.assertTrue(Path(__file__).with_name("backup.py").is_file())

    def test_direct_child_reaped_after_launch_signal(self):
        with tempfile.TemporaryDirectory(prefix="backup-process-") as root:
            code = """
import os, signal, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from backup import Commands, Interrupted
c = Commands(0.2)
signal.signal(signal.SIGTERM, c.request_stop)
real = c.spawn
def spawn(*args, **kwargs):
    parent = os.getpid()
    if sys.argv[3] == 'before': os.kill(parent, signal.SIGTERM)
    if sys.argv[3] == 'during':
        restore = kwargs['preexec_fn']
        def preexec():
            os.kill(parent, signal.SIGTERM)
            restore()
        kwargs['preexec_fn'] = preexec
    child = real(*args, **kwargs)
    if sys.argv[3] == 'after': os.kill(parent, signal.SIGTERM)
    Path(sys.argv[2]).write_text(str(child.pid))
    return child
c.spawn = spawn
try:
    c.run([sys.executable, '-c', 'import time; time.sleep(60)'], Path(sys.argv[2]).parent)
except Interrupted:
    sys.exit(143)
"""
            pidfile = Path(root, "pid")
            for phase in ("before", "during", "after"):
                with self.subTest(phase=phase):
                    parent = subprocess.Popen(
                        [
                            sys.executable,
                            "-c",
                            code,
                            str(Path(__file__).parent),
                            str(pidfile),
                            phase,
                        ]
                    )
                    try:
                        self.assertEqual(parent.wait(timeout=5), 143)
                        child = int(pidfile.read_text())
                        with self.assertRaises(ProcessLookupError):
                            os.kill(child, 0)
                    finally:
                        if parent.poll() is None:
                            parent.send_signal(signal.SIGTERM)
                            parent.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
