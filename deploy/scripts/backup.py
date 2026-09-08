#!/usr/bin/env python3
"""Single-child backup engine; backup.sh is the deployed compatibility path.

Exit 0: success, 1: failed attempt, 2: precondition, 3: lock contention.
The persistent lock inode is never removed. SIGKILL cannot publish an outcome:
the kernel releases the lock and the durable in-progress record remains.
Linux subreaping lets this owner reap grandchildren if a command dies first.
Commands must not escape their session (pg_dump and AWS CLI do not).
"""

import base64
import ctypes
import errno
import fcntl
import gzip
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

SIGNALS = {signal.SIGINT, signal.SIGTERM}


class Interrupted(Exception):
    pass


class Contended(Exception):
    pass


class Failed(Exception):
    def __init__(self, category, status=1):
        self.category = category
        self.status = status


def timestamp():
    return datetime.now(UTC).isoformat()


def subreaper():
    if sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), "cannot establish child ownership")


class Commands:
    def __init__(self, grace):
        self.grace = grace
        self.child = None
        self.stopped = 0
        self.spawn = subprocess.Popen

    def request_stop(self, signum, frame):
        # Never raise from a signal handler: publication and launch bookkeeping
        # must finish even when INT/TERM is delivered repeatedly.
        self.stopped = self.stopped or 128 + signum

    def checkpoint(self):
        if self.stopped:
            raise Interrupted

    def terminate(self):
        child = self.child
        if child is None:
            return
        group = child.pid  # start_new_session fails Popen if setsid fails.

        def send(sig):
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass
            except PermissionError:
                if sys.platform != "darwin":
                    raise

        def drained():
            child.poll()  # Reap the direct child before adopted grandchildren.
            if child.returncode is not None:
                while True:
                    try:
                        pid, _ = os.waitpid(-group, os.WNOHANG)
                    except ChildProcessError:
                        break
                    if not pid:
                        break
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                return child.returncode is not None
            except PermissionError:
                # Darwin reports EPERM briefly for an exiting group. It is
                # not evidence of disappearance: keep polling until ESRCH.
                return False
            return False

        send(signal.SIGTERM)
        deadline = time.monotonic() + self.grace
        while not drained() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not drained():
            send(signal.SIGKILL)
        # No unbounded wait, even for an uninterruptible kernel task. A timeout
        # is a supervision failure, never a successful terminal outcome.
        child.wait(timeout=5)
        deadline = time.monotonic() + 5
        while not drained():
            if time.monotonic() >= deadline:
                raise Failed("supervision_failed")
            time.sleep(0.02)
        self.child = None

    def run(self, args, work, env=None):
        self.checkpoint()
        with open(work / "command.out", "wb") as output, open(work / "command.err", "wb") as error:
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
            try:
                # This entry point is deliberately single-threaded. Restore the
                # child's mask before exec, otherwise it inherits blocked TERM
                # and even a responsive pg_dump would require KILL.
                self.child = self.spawn(
                    args,
                    start_new_session=True,
                    stdout=output,
                    stderr=error,
                    env=env,
                    preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, mask),
                )
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            try:
                while self.child.poll() is None:
                    self.checkpoint()
                    time.sleep(0.02)
                self.checkpoint()
                status = self.child.wait(timeout=5)
            finally:
                # Also drain descendants after a command exits normally.
                self.terminate()
        if status:
            with (work / "command.err").open("rb") as error:
                print(error.read(2000).decode(errors="replace"), file=sys.stderr)
            raise subprocess.CalledProcessError(status, args)
        with (work / "command.out").open() as output:
            text = output.read(16385)
        if len(text) > 16384:
            raise Failed("command_output_invalid")
        return text.split()


def write_state(directory, name, values):
    """Atomic, fsynced replace; never follows a target symlink."""
    text = values if isinstance(values, str) else "".join(f"{k}={v}\n" for k, v in values.items())
    fd, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            # State is non-secret and read by the unprivileged web container.
            os.fchmod(stream.fileno(), 0o644)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / name)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def acquire_lock(directory):
    fd = os.open(directory / ".backup-lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in {errno.EWOULDBLOCK, errno.EAGAIN}:
            raise Contended from None
        raise
    return fd


class Backup:
    def __init__(self, commands):
        self.commands = commands
        self.directory = Path(os.environ.get("BACKUP_STATE_DIR", "/var/lib/trade-recommender"))
        self.stage = "configure"

    def checkpoint(self):
        self.commands.checkpoint()

    def perform(self, work, record):
        for name in (
            "POSTGRES_HOST",
            "POSTGRES_USER",
            "POSTGRES_DB",
            "POSTGRES_PASSWORD",
            "BACKUP_BUCKET",
            "AWS_REGION",
        ):
            if not os.environ.get(name):
                raise Failed("configuration_missing")
        try:
            minimum = int(os.environ.get("BACKUP_MIN_BYTES", "1024"))
            if minimum < 0:
                raise ValueError
        except ValueError:
            raise Failed("configuration_invalid") from None
        sql, archive = work / "dump.sql", work / "archive.sql.gz"
        self.stage = "dump"
        env = {**os.environ, "PGPASSWORD": os.environ["POSTGRES_PASSWORD"]}
        self.commands.run(
            [
                "pg_dump",
                f"--host={env['POSTGRES_HOST']}",
                f"--username={env['POSTGRES_USER']}",
                f"--dbname={env['POSTGRES_DB']}",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-acl",
                f"--file={sql}",
            ],
            work,
            env,
        )
        self.stage = "compress"
        with sql.open("rb") as source, gzip.open(archive, "wb", compresslevel=9) as target:
            while chunk := source.read(1024 * 1024):
                self.checkpoint()
                target.write(chunk)
        self.stage = "validate"
        try:
            with gzip.open(archive, "rb") as stream:
                first = stream.read(65536)
                tail = first[-4096:]
                while chunk := stream.read(1024 * 1024):
                    self.checkpoint()
                    tail = (tail + chunk)[-4096:]
        except (OSError, EOFError):
            raise Failed("archive_unreadable") from None
        size = archive.stat().st_size
        if size < minimum:
            raise Failed("archive_too_small")
        if (
            b"PostgreSQL database dump" not in first
            or b"PostgreSQL database dump complete" not in tail
        ):
            raise Failed("archive_content_invalid")
        self.stage = "checksum"
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                self.checkpoint()
                digest.update(chunk)
        checksum = base64.b64encode(digest.digest()).decode()
        sha = digest.hexdigest()
        common = [
            "--bucket",
            env["BACKUP_BUCKET"],
            "--key",
            record["object_key"],
            "--region",
            env["AWS_REGION"],
        ]
        self.stage = "upload"
        uploaded = self.commands.run(
            [
                "aws",
                "s3api",
                "put-object",
                *common,
                "--body",
                str(archive),
                "--server-side-encryption",
                "AES256",
                "--checksum-algorithm",
                "SHA256",
                "--metadata",
                f"sha256={sha}",
                "--query",
                "[VersionId,ChecksumSHA256]",
                "--output",
                "text",
            ],
            work,
        )
        if len(uploaded) != 2 or uploaded[0] in {"None", "null", ""}:
            raise Failed("upload_unversioned")
        version, remote_checksum = uploaded
        if remote_checksum != checksum:
            raise Failed("upload_checksum_mismatch")
        self.stage = "verify_upload"
        verified = self.commands.run(
            [
                "aws",
                "s3api",
                "head-object",
                *common,
                "--version-id",
                version,
                "--checksum-mode",
                "ENABLED",
                "--query",
                "[ContentLength,ChecksumSHA256,Metadata.sha256]",
                "--output",
                "text",
            ],
            work,
        )
        if verified != [str(size), checksum, sha]:
            raise Failed("upload_checksum_mismatch")
        self.checkpoint()
        self.stage = "record"
        return {
            **record,
            "outcome": "success",
            "stage": "record",
            "category": "none",
            "completed_at": timestamp(),
            "version_id": version,
            "sha256": sha,
            "size_bytes": str(size),
        }

    def once(self):
        self.stage = "configure"
        self.checkpoint()
        try:
            lock = acquire_lock(self.directory)
        except Contended:
            return 3
        except OSError:
            return 2
        try:
            for tool in ("pg_dump", "aws"):
                if not shutil.which(tool):
                    return 2
            if os.path.lexists(self.directory / "backup-in-progress"):
                print("backup: unresolved prior attempt; inspect state before retry", flush=True)
                return 2
            record = {"attempt_id": str(uuid4()), "attempted_at": timestamp()}
            record["object_key"] = f"postgres/{record['attempt_id']}.sql.gz"
            try:
                write_state(
                    self.directory,
                    "backup-in-progress",
                    {**record, "started_at": record["attempted_at"], "stage": self.stage},
                )
            except OSError:
                return 2
            status = 0
            try:
                with tempfile.TemporaryDirectory(
                    prefix="backup-", dir=os.environ.get("BACKUP_WORK_DIR")
                ) as work:
                    terminal = self.perform(Path(work), record)
            except (Interrupted, Failed, OSError, subprocess.SubprocessError) as exc:
                status = self.commands.stopped or 1
                category = {
                    "configure": "workdir_unwritable",
                    "dump": "dump_failed",
                    "compress": "compression_failed",
                    "validate": "archive_unreadable",
                    "checksum": "checksum_failed",
                    "upload": "upload_failed",
                    "verify_upload": "upload_unverified",
                }.get(self.stage, "state_failed")
                if isinstance(exc, Interrupted):
                    category = "interrupted"
                elif isinstance(exc, Failed):
                    category = exc.category
                terminal = {
                    **record,
                    "outcome": "failure",
                    "stage": self.stage,
                    "category": category,
                    "failed_at": timestamp(),
                    "exit_status": str(getattr(exc, "returncode", status)),
                }
            # Exactly one terminal commitment; signals only set a flag. Commit
            # first, then publish its identical success/detail projection. If
            # either write fails, retain the in-progress evidence. A subsequent
            # attempt must not erase a previous unresolved publication.
            try:
                write_state(self.directory, "backup-last-attempt", terminal)
                name = "backup-last-success" if status == 0 else "backup-last-failure"
                write_state(self.directory, name, terminal)
                if self.commands.child is not None:
                    # Cleanup timed out/failed. Keep the durable blocker: a
                    # later attempt must not overlap a possibly surviving task.
                    return 1
                progress = self.directory / "backup-in-progress"
                if f"attempt_id={record['attempt_id']}\n" in progress.read_text():
                    progress.unlink()
            except OSError:
                return 1
            if status == 0:
                try:
                    write_state(self.directory, "last-backup", terminal["completed_at"] + "\n")
                except OSError:
                    print("backup: legacy marker publication failed; modern commitment stands")
            print(f"backup: {terminal['outcome']} {record['object_key']}", flush=True)
            return status
        finally:
            os.close(lock)


def main():
    try:
        grace = float(os.environ.get("BACKUP_KILL_AFTER_SECONDS", "10"))
        interval = float(os.environ.get("BACKUP_INTERVAL_SECONDS", "21600"))
        if not 0 <= grace <= 60 or not 0 < interval < float("inf"):
            return 2
        subreaper()
    except (OSError, ValueError):
        return 2
    commands = Commands(grace)
    for sig in SIGNALS:
        signal.signal(sig, commands.request_stop)
    backup = Backup(commands)
    try:
        while True:
            status = backup.once()
            commands.checkpoint()
            if len(sys.argv) < 2 or sys.argv[1] != "loop":
                return status
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline:
                commands.checkpoint()
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    except Interrupted:
        return commands.stopped


if __name__ == "__main__":
    result = main()
    # CPython tears down Python signal handlers during interpreter shutdown.
    # Prevent a repeated TERM in that window from replacing our chosen status.
    signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    sys.exit(result)
