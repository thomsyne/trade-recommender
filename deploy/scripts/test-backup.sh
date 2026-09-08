#!/bin/bash
# Exercises deploy/scripts/backup.sh and restore-check.sh with fake
# executables, temporary directories and no network. Every case asserts the
# honest state files, marker behaviour and temporary-file cleanup.
set -Eeuo pipefail

scripts="$(cd "$(dirname "$0")" && pwd)"
backup="$scripts/backup.sh"
restore_check="$scripts/restore-check.sh"
temporary="$(mktemp -d)"
trap 'rm -rf "$temporary"' EXIT INT TERM

fail() {
  echo "backup test assertion failed: $*" >&2
  if [ -n "${CASE_ROOT:-}" ]; then
    for artifact in output error calls; do
      if [ -s "$CASE_ROOT/$artifact" ]; then
        echo "--- $artifact ---" >&2
        cat "$CASE_ROOT/$artifact" >&2
      fi
    done
    for state in backup-last-attempt backup-last-success backup-last-failure last-backup; do
      if [ -f "$CASE_ROOT/state/$state" ]; then
        echo "--- $state ---" >&2
        cat "$CASE_ROOT/state/$state" >&2
      fi
    done
  fi
  exit 1
}

assert_contains() { grep -Fq -- "$1" "$2" || fail "expected '$1' in $2"; }
assert_not_contains() { if grep -Fq -- "$1" "$2"; then fail "did not expect '$1' in $2"; fi; }
assert_line() { grep -Fxq -- "$1" "$2" || fail "expected exact line '$1' in $2"; }
assert_absent() { [ ! -e "$1" ] || fail "did not expect $1 to exist"; }
assert_present() { [ -e "$1" ] || fail "expected $1 to exist"; }
assert_empty_dir() { [ -z "$(ls -A "$1")" ] || fail "expected $1 to be empty, found: $(ls -A "$1")"; }

toolbox="$temporary/toolbox"
mkdir -p "$toolbox"
for command in basename cat chmod cp cut date dirname env grep gzip head kill ls mkdir mkfifo mktemp mv printf rm rmdir sed seq sleep tail tr wc; do
  path="$(command -v "$command" || true)"
  if [ -n "$path" ] && [ -x "$path" ]; then ln -s "$path" "$toolbox/$command"; fi
done
for digest in sha256sum shasum openssl; do
  path="$(command -v "$digest" || true)"
  if [ -n "$path" ]; then ln -s "$path" "$toolbox/$digest"; fi
done
# The macOS shasum is a perl script; make sure perl resolves.
if command -v perl >/dev/null; then ln -sf "$(command -v perl)" "$toolbox/perl"; fi
# The flock stub is a python3 script (macOS has no flock(1)); env(1) and
# python3 must resolve inside the sandbox PATH.
for command in env python3; do
  path="$(command -v "$command" || true)"
  if [ -n "$path" ]; then ln -sf "$path" "$toolbox/$command"; fi
done

write_stub() { name="$1"; shift; cat >"$MOCK_BIN/$name"; chmod 755 "$MOCK_BIN/$name"; }

good_dump() {
  # Emits a plausible plain pg_dump: header, >4 KiB body, completion marker.
  cat <<'EOF'
#!/bin/bash
echo "pg_dump $*" >>"$CALLS"
printf -- '--\n-- PostgreSQL database dump\n--\n'
for i in $(seq 1 200); do printf 'INSERT INTO market_auditevent VALUES (%d, %s);\n' "$i" "'row-data-$i-xxxxxxxxxxxxxxxx'"; done
printf -- '--\n-- PostgreSQL database dump complete\n--\n'
EOF
}

good_aws() {
  cat <<'EOF'
#!/bin/bash
echo "aws $*" >>"$CALLS"
if [ "$1" = s3 ] && [ "$2" = cp ]; then
  object_key="$4"
  cp "$3" "$FAKE_BUCKET/$(basename "$object_key")"
  # The backup attaches the local sha256 as user metadata at upload time;
  # remember it so head-object can return it for verification.
  sha=""
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "--metadata" ]; then sha="${2#sha256=}"; shift; fi
    shift
  done
  printf '%s' "$sha" >"$FAKE_BUCKET/$(basename "$object_key").sha256"
  exit 0
fi
if [ "$1" = s3api ] && [ "$2" = head-object ]; then
  key=""
  query=""
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --key ]; then shift; key="$1"; fi
    if [ "$1" = --query ]; then shift; query="$1"; fi
    shift
  done
  object="$FAKE_BUCKET/$(basename "$key")"
  if [ "$query" = ContentLength ]; then
    wc -c <"$object" | tr -d ' '
    exit 0
  fi
  if [ "$query" = "Metadata.sha256" ]; then
    cat "$object.sha256" 2>/dev/null || true
    exit 0
  fi
fi
exit 0
EOF
}

prepare_case() {
  case_name="$1"
  export CASE_ROOT="$temporary/$case_name"
  export MOCK_BIN="$CASE_ROOT/bin"
  export CALLS="$CASE_ROOT/calls"
  export FAKE_BUCKET="$CASE_ROOT/bucket"
  export STATE="$CASE_ROOT/state"
  export WORK="$CASE_ROOT/work"
  mkdir -p "$MOCK_BIN" "$FAKE_BUCKET" "$STATE" "$WORK"
  : >"$CALLS"
  good_dump | write_stub pg_dump
  good_aws | write_stub aws
  good_flock | write_stub flock
  if command -v setsid >/dev/null 2>&1; then ln -sf "$(command -v setsid)" "$MOCK_BIN/setsid"; fi
  if command -v uuidgen >/dev/null 2>&1; then ln -sf "$(command -v uuidgen)" "$MOCK_BIN/uuidgen"; fi
}

good_flock() {
  # macOS has no flock(1); emulate the util-linux fd semantics with Python's
  # fcntl. The lock applies to the open file description shared with the
  # backup shell through the inherited descriptor, so it persists until the
  # backup closes that descriptor (the real flock behaves identically).
  cat <<'EOF'
#!/usr/bin/env python3
import fcntl
import os
import sys

fd = int(sys.argv[-1])
unlock = "-u" in sys.argv
if unlock:
    fcntl.flock(fd, fcntl.LOCK_UN)
    sys.exit(0)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(1)
sys.exit(0)
EOF
}

run_backup() {
  # run_backup MODE [extra env assignments...]; captures output/error, records status.
  mode="$1"; shift
  set +e
  env -i PATH="$MOCK_BIN:$toolbox" HOME="$CASE_ROOT" TMPDIR="$WORK" CALLS="$CALLS" FAKE_BUCKET="$FAKE_BUCKET" \
    POSTGRES_HOST=db POSTGRES_USER=app POSTGRES_DB=app POSTGRES_PASSWORD=not-a-real-secret \
    BACKUP_BUCKET=fake-bucket AWS_REGION=us-east-1 BACKUP_STATE_DIR="$STATE" BACKUP_WORK_DIR="$WORK" \
    BACKUP_MIN_BYTES=1024 "$@" /bin/sh "$backup" "$mode" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"
  status=$?
  set -e
  return $status
}

# ---------------------------------------------------------------- success
prepare_case success
run_backup once || fail "successful backup exited non-zero"
assert_contains 'backup uploaded: postgres/' "$CASE_ROOT/output"
assert_contains 'aws s3 cp' "$CALLS"
assert_contains '--sse AES256' "$CALLS"
assert_contains 'aws s3api head-object' "$CALLS"
assert_contains 'pg_dump --host=db --username=app --dbname=app --clean --if-exists --no-owner --no-acl' "$CALLS"
assert_not_contains 'not-a-real-secret' "$CALLS"
assert_present "$STATE/last-backup"
assert_line 'outcome=success' "$STATE/backup-last-attempt"
assert_contains 'object_key=postgres/' "$STATE/backup-last-success"
assert_contains 'sha256=' "$STATE/backup-last-success"
assert_contains 'size_bytes=' "$STATE/backup-last-success"
assert_absent "$STATE/backup-last-failure"
assert_absent "$STATE/backup-in-progress"
[ ! -e "$STATE/.backup-lock" ] || fail "attempt lock survived a successful backup"
# The attempt record, success file and object key share one attempt identity.
attempt_id="$(sed -n 's/^attempt_id=//p' "$STATE/backup-last-attempt")"
[ -n "$attempt_id" ] || fail "attempt record lacks an attempt_id"
assert_contains "attempt_id=${attempt_id}" "$STATE/backup-last-success"
assert_contains "$attempt_id" "$CASE_ROOT/output"
assert_empty_dir "$WORK"
grep -rq 'not-a-real-secret' "$STATE" && fail "state files must never contain the password"
uploaded="$(ls "$FAKE_BUCKET"/*.sql.gz 2>/dev/null | head -1)"
[ -n "$uploaded" ] || fail "no object was uploaded"
gzip -t "$uploaded" || fail "uploaded archive is not valid gzip"
recorded_sha="$(sed -n 's/^sha256=//p' "$STATE/backup-last-success")"
actual_sha="$( (sha256sum "$uploaded" 2>/dev/null || shasum -a 256 "$uploaded") | cut -d' ' -f1)"
[ "$recorded_sha" = "$actual_sha" ] || fail "recorded sha256 does not match the uploaded archive"
remote_sha="$(cat "$uploaded.sha256" 2>/dev/null || true)"
[ "$remote_sha" = "$recorded_sha" ] || fail "upload metadata sha256 does not match the recorded hash"
first_success="$(cat "$STATE/backup-last-success")"
first_marker="$(cat "$STATE/last-backup")"

# ------------------------------------------- previous success survives failure
sleep 1
write_stub pg_dump <<'EOF'
#!/bin/bash
echo "pg_dump $*" >>"$CALLS"
printf -- '--\n-- PostgreSQL database dump\n--\n'
echo "pg_dump: error: connection to server failed" >&2
exit 1
EOF
if run_backup once; then fail "failed dump must exit non-zero"; fi
assert_line 'outcome=failure' "$STATE/backup-last-attempt"
assert_line 'category=dump_failed' "$STATE/backup-last-attempt"
assert_line 'stage=dump' "$STATE/backup-last-failure"
assert_line 'exit_status=1' "$STATE/backup-last-failure"
[ "$(cat "$STATE/backup-last-success")" = "$first_success" ] || fail "last-success changed after a failed attempt"
[ "$(cat "$STATE/last-backup")" = "$first_marker" ] || fail "legacy marker changed after a failed attempt"
assert_not_contains 'aws s3 cp' "$(mktemp)" 2>/dev/null || true
[ "$(grep -c 'aws s3 cp' "$CALLS")" -eq 1 ] || fail "failed dump must not upload"
assert_empty_dir "$WORK"
assert_contains 'connection to server failed' "$CASE_ROOT/error"
grep -rq 'connection to server failed' "$STATE" && fail "raw stderr must not be persisted to state"

# ----------------------------------------------------------- pg_dump nonzero
prepare_case dump-failure
write_stub pg_dump <<'EOF'
#!/bin/bash
echo "pg_dump $*" >>"$CALLS"
printf -- '--\n-- PostgreSQL database dump\n--\n'
exit 3
EOF
if run_backup once; then fail "pg_dump failure must exit non-zero"; fi
assert_absent "$STATE/last-backup"
assert_absent "$STATE/backup-last-success"
assert_line 'category=dump_failed' "$STATE/backup-last-failure"
assert_line 'exit_status=3' "$STATE/backup-last-failure"
assert_not_contains 'aws s3 cp' "$CALLS"
assert_empty_dir "$WORK"

# ------------------------------------------------------- compression failure
prepare_case compression-failure
write_stub gzip <<'EOF'
#!/bin/bash
echo "gzip $*" >>"$CALLS"
if [ "$1" = -9 ]; then cat >/dev/null; echo "gzip: out of space" >&2; exit 1; fi
exec /usr/bin/env -u GZIP_REAL "$REAL_GZIP" "$@"
EOF
if run_backup once REAL_GZIP="$(command -v gzip)"; then fail "compression failure must exit non-zero"; fi
assert_line 'category=compression_failed' "$STATE/backup-last-failure"
assert_line 'stage=compress' "$STATE/backup-last-failure"
assert_absent "$STATE/last-backup"
assert_not_contains 'aws s3 cp' "$CALLS"
assert_empty_dir "$WORK"

# ------------------------------------------------- archive validation failures
prepare_case archive-too-small
write_stub pg_dump <<'EOF'
#!/bin/bash
echo "pg_dump $*" >>"$CALLS"
printf -- '--\n-- PostgreSQL database dump\n--\n-- PostgreSQL database dump complete\n--\n'
EOF
if run_backup once; then fail "tiny archive must fail validation"; fi
assert_line 'category=archive_too_small' "$STATE/backup-last-failure"
assert_line 'stage=validate' "$STATE/backup-last-failure"
assert_absent "$STATE/last-backup"
assert_not_contains 'aws s3 cp' "$CALLS"
assert_empty_dir "$WORK"

prepare_case archive-truncated
write_stub pg_dump <<'EOF'
#!/bin/bash
echo "pg_dump $*" >>"$CALLS"
printf -- '--\n-- PostgreSQL database dump\n--\n'
for i in $(seq 1 200); do printf 'INSERT INTO market_auditevent VALUES (%d, %s);\n' "$i" "'row-data-$i-xxxxxxxxxxxxxxxx'"; done
EOF
if run_backup once; then fail "truncated dump (no completion marker) must fail validation"; fi
assert_line 'category=archive_content_invalid' "$STATE/backup-last-failure"
assert_absent "$STATE/last-backup"
assert_not_contains 'aws s3 cp' "$CALLS"
assert_empty_dir "$WORK"

prepare_case archive-corrupt
write_stub gzip <<'EOF'
#!/bin/bash
echo "gzip $*" >>"$CALLS"
if [ "$1" = -9 ]; then cat >/dev/null; head -c 4096 /dev/zero; exit 0; fi
exec "$REAL_GZIP" "$@"
EOF
if run_backup once REAL_GZIP="$(command -v gzip)"; then fail "corrupt archive must fail validation"; fi
assert_line 'category=archive_unreadable' "$STATE/backup-last-failure"
assert_absent "$STATE/last-backup"
assert_not_contains 'aws s3 cp' "$CALLS"
assert_empty_dir "$WORK"

# ------------------------------------------------------------ upload failure
prepare_case upload-failure
write_stub aws <<'EOF'
#!/bin/bash
echo "aws $*" >>"$CALLS"
echo "upload failed: AccessDenied" >&2
exit 1
EOF
if run_backup once; then fail "upload failure must exit non-zero"; fi
assert_line 'category=upload_failed' "$STATE/backup-last-failure"
assert_line 'stage=upload' "$STATE/backup-last-failure"
assert_absent "$STATE/last-backup"
assert_absent "$STATE/backup-last-success"
assert_empty_dir "$WORK"
grep -rq 'AccessDenied' "$STATE" && fail "raw upload error must not be persisted to state"

prepare_case upload-size-mismatch
write_stub aws <<'EOF'
#!/bin/bash
echo "aws $*" >>"$CALLS"
if [ "$1" = s3 ] && [ "$2" = cp ]; then
  cp "$3" "$FAKE_BUCKET/$(basename "$4")"
  exit 0
fi
if [ "$1" = s3api ]; then
  # Report the object's real size but a wrong checksum: the size check
  # passes and the checksum verification must fail.
  if [ "$(echo "$*" | tr ' ' '\n' | grep -A1 '^--query$' | tail -1)" = ContentLength ]; then
    key="$(echo "$*" | tr ' ' '\n' | grep -A1 '^--key$' | tail -1)"
    wc -c <"$FAKE_BUCKET/$(basename "$key")" | tr -d ' '
    exit 0
  fi
  printf '%064d' 0
  exit 0
fi
exit 0
EOF
if run_backup once; then fail "checksum mismatch after upload must exit non-zero"; fi
assert_line 'category=upload_checksum_mismatch' "$STATE/backup-last-failure"
assert_line 'stage=verify_upload' "$STATE/backup-last-failure"
assert_absent "$STATE/last-backup"
assert_empty_dir "$WORK"

# ------------------------------------------------------- missing configuration
prepare_case missing-configuration
if run_backup once BACKUP_BUCKET=; then fail "missing BACKUP_BUCKET must exit non-zero"; fi
assert_line 'category=configuration_missing' "$STATE/backup-last-failure"
assert_line 'stage=configure' "$STATE/backup-last-failure"
assert_not_contains 'pg_dump' "$CALLS"
assert_absent "$STATE/last-backup"
assert_contains 'required configuration BACKUP_BUCKET is missing' "$CASE_ROOT/output"
assert_empty_dir "$WORK"

prepare_case invalid-min-bytes
if run_backup once BACKUP_MIN_BYTES=lots; then fail "invalid BACKUP_MIN_BYTES must exit non-zero"; fi
assert_line 'category=configuration_invalid' "$STATE/backup-last-failure"
assert_not_contains 'pg_dump' "$CALLS"

# ---------------------------------------------------------- loop continues
prepare_case loop-after-failure
write_stub pg_dump <<'EOF'
#!/bin/bash
echo "pg_dump $*" >>"$CALLS"
count="$(grep -c pg_dump "$CALLS")"
printf -- '--\n-- PostgreSQL database dump\n--\n'
if [ "$count" -eq 1 ]; then echo "transient failure" >&2; exit 1; fi
for i in $(seq 1 200); do printf 'INSERT INTO market_auditevent VALUES (%d, %s);\n' "$i" "'row-data-$i-xxxxxxxxxxxxxxxx'"; done
printf -- '--\n-- PostgreSQL database dump complete\n--\n'
EOF
env -i PATH="$MOCK_BIN:$toolbox" HOME="$CASE_ROOT" TMPDIR="$WORK" CALLS="$CALLS" FAKE_BUCKET="$FAKE_BUCKET" \
  POSTGRES_HOST=db POSTGRES_USER=app POSTGRES_DB=app POSTGRES_PASSWORD=not-a-real-secret \
  BACKUP_BUCKET=fake-bucket AWS_REGION=us-east-1 BACKUP_STATE_DIR="$STATE" BACKUP_WORK_DIR="$WORK" \
  BACKUP_INTERVAL_SECONDS=1 /bin/sh "$backup" loop >"$CASE_ROOT/output" 2>"$CASE_ROOT/error" &
loop_pid=$!
for _ in $(seq 1 40); do
  if [ -f "$STATE/backup-last-success" ]; then break; fi
  sleep 0.25
done
kill -TERM "$loop_pid" 2>/dev/null || true
wait "$loop_pid" 2>/dev/null || true
[ "$(grep -c pg_dump "$CALLS")" -ge 2 ] || fail "loop did not attempt again after a failure"
assert_contains 'next attempt in 1 seconds; the failed attempt was not marked successful' "$CASE_ROOT/output"
assert_present "$STATE/backup-last-success"
assert_line 'outcome=success' "$STATE/backup-last-attempt"
assert_line 'category=dump_failed' "$STATE/backup-last-failure"
assert_empty_dir "$WORK"

# ------------------------------------------------------------- interruption
prepare_case interrupted
write_stub pg_dump <<'EOF'
#!/bin/bash
echo "pg_dump $*" >>"$CALLS"
printf -- '--\n-- PostgreSQL database dump\n--\n'
# Record this process's own PID (it becomes the pg_dump child after exec),
# then block so the interrupt arrives mid-dump.
echo "pg_dump_pid=$$" >>"$CALLS"
exec sleep 30
EOF
# Wrap the real gzip so the test can verify gzip itself (not only pg_dump) is
# killed and reaped when the backup is interrupted. The wrapper records both
# its own PID and the real gzip PID it execs into (exec replaces the process,
# so the tracked PID *is* the real gzip).
real_gzip="$(command -v gzip)"
cat >"$MOCK_BIN/gzip" <<EOF
#!/bin/bash
echo "gzip_pid=\$\$" >>"\$CALLS"
exec "$real_gzip" "\$@"
EOF
chmod 755 "$MOCK_BIN/gzip"
env -i PATH="$MOCK_BIN:$toolbox" HOME="$CASE_ROOT" TMPDIR="$WORK" CALLS="$CALLS" FAKE_BUCKET="$FAKE_BUCKET" \
  POSTGRES_HOST=db POSTGRES_USER=app POSTGRES_DB=app POSTGRES_PASSWORD=not-a-real-secret \
  BACKUP_BUCKET=fake-bucket AWS_REGION=us-east-1 BACKUP_STATE_DIR="$STATE" BACKUP_WORK_DIR="$WORK" \
  /bin/sh "$backup" loop >"$CASE_ROOT/output" 2>"$CASE_ROOT/error" &
loop_pid=$!
for _ in $(seq 1 40); do
  if grep -q pg_dump_pid "$CALLS" 2>/dev/null; then break; fi
  sleep 0.25
done
grep -q pg_dump_pid "$CALLS" || fail "pg_dump never started"
sleep 0.5
started="$(date +%s)"
kill -TERM "$loop_pid"
set +e
wait "$loop_pid"
exit_status=$?
set -e
elapsed=$(( $(date +%s) - started ))
[ "$exit_status" -eq 143 ] || fail "interrupted loop should exit 143, got $exit_status"
[ "$elapsed" -le 5 ] || fail "interrupted backup took ${elapsed}s to exit"
assert_line 'category=interrupted' "$STATE/backup-last-failure"
assert_line 'stage=dump' "$STATE/backup-last-failure"
assert_line 'outcome=failure' "$STATE/backup-last-attempt"
assert_absent "$STATE/last-backup"
assert_absent "$STATE/backup-in-progress"
[ ! -e "$STATE/.backup-lock" ] || fail "attempt lock survived an interrupted backup"
assert_empty_dir "$WORK"
# Both supervised children must have been terminated AND reaped with the loop:
# pg_dump (which exec'd into sleep) and the real gzip both record their PIDs.
pg_dump_pid="$(sed -n 's/^pg_dump_pid=//p' "$CALLS")"
[ -n "$pg_dump_pid" ] || fail "could not read pg_dump child pid"
if kill -0 "$pg_dump_pid" 2>/dev/null; then
  fail "pg_dump child $pg_dump_pid survived an interrupted backup"
fi
gzip_pid="$(sed -n 's/^gzip_pid=//p' "$CALLS" | tail -1)"
if [ -n "$gzip_pid" ] && kill -0 "$gzip_pid" 2>/dev/null; then
  fail "gzip child $gzip_pid survived an interrupted backup"
fi
if pkill -f "sleep 30" 2>/dev/null; then
  fail "pg_dump survived an interrupted backup"
fi

# -------------------------------------------- interrupt after the commit
# The attempt record is the single commit; it is written before the success
# file is published, and a signal in between must not flip the committed
# success into an interrupted failure. The mv stub performs the commit move
# and then blocks until the RELEASE file appears, pinning the script exactly
# in that window.
prepare_case record-window
real_mv="$(command -v mv)"
release="$CASE_ROOT/release"
write_stub mv <<STUB
#!/bin/bash
if [ "\${@: -1}" = "$STATE/backup-last-attempt" ]; then
  $real_mv "\$@"
  while [ ! -e "$release" ]; do sleep 0.05; done
  exit 0
fi
exec $real_mv "\$@"
STUB
env -i PATH="$MOCK_BIN:$toolbox" HOME="$CASE_ROOT" TMPDIR="$WORK" CALLS="$CALLS" FAKE_BUCKET="$FAKE_BUCKET" \
  POSTGRES_HOST=db POSTGRES_USER=app POSTGRES_DB=app POSTGRES_PASSWORD=not-a-real-secret \
  BACKUP_BUCKET=fake-bucket AWS_REGION=us-east-1 BACKUP_STATE_DIR="$STATE" BACKUP_WORK_DIR="$WORK" \
  /bin/sh "$backup" once >"$CASE_ROOT/output" 2>"$CASE_ROOT/error" &
loop_pid=$!
for _ in $(seq 1 200); do
  if grep -q '^outcome=success$' "$STATE/backup-last-attempt" 2>/dev/null; then break; fi
  sleep 0.05
done
grep -q '^outcome=success$' "$STATE/backup-last-attempt" || fail "attempt never committed"
assert_absent "$STATE/backup-last-success"
kill -TERM "$loop_pid"
: >"$release"
set +e
wait "$loop_pid"
exit_status=$?
set -e
[ "$exit_status" -eq 143 ] || fail "interrupt after commit should exit 143, got $exit_status"
assert_line 'outcome=success' "$STATE/backup-last-attempt"
assert_absent "$STATE/backup-last-failure"
assert_absent "$STATE/backup-last-success"
assert_absent "$STATE/last-backup"
assert_absent "$STATE/backup-in-progress"
[ ! -e "$STATE/.backup-lock" ] || fail "attempt lock survived an interrupted backup"
assert_empty_dir "$WORK"

# --------------------------------------- unwritable state must abort the dump
# The state directory is mandatory: a backup that cannot publish durable state
# before dumping must abort rather than run silently.
prepare_case state-unwritable
chmod 500 "$STATE"
if run_backup once; then
  chmod 700 "$STATE"
  fail "an unwritable state directory must abort the backup"
fi
chmod 700 "$STATE"
assert_contains 'state directory' "$CASE_ROOT/output"
assert_contains 'not writable' "$CASE_ROOT/output"
assert_not_contains 'pg_dump' "$CALLS"
assert_absent "$STATE/last-backup"
assert_empty_dir "$WORK"

# ------------------------------------------- concurrent attempts serialize
# The scheduler's backup loop and a deploy-time `backup once` share the state
# volume; the exclusive attempt lock must make one of two overlapping backups
# skip instead of letting both run (which could suppress a real failure and
# overwrite the same S3 object key in the same started_at second).
prepare_case concurrent
write_stub pg_dump <<EOF
#!/bin/bash
echo "pg_dump \$*" >>"\$CALLS"
printf -- '--\n-- PostgreSQL database dump\n--\n'
# Signal that the dump has genuinely started (and the holder's in-progress
# record and lock exist), then hold until RELEASE so the second attempt
# overlaps this one.
echo started >"$CASE_ROOT/dump-started"
while [ ! -e "$CASE_ROOT/release" ]; do sleep 0.05; done
for i in \$(seq 1 200); do printf 'INSERT INTO market_auditevent VALUES (%d, %s);\n' "\$i" "'row-data-\$i-xxxxxxxxxxxxxxxx'"; done
printf -- '--\n-- PostgreSQL database dump complete\n--\n'
EOF
env -i PATH="$MOCK_BIN:$toolbox" HOME="$CASE_ROOT" TMPDIR="$WORK" CALLS="$CALLS" FAKE_BUCKET="$FAKE_BUCKET" \
  POSTGRES_HOST=db POSTGRES_USER=app POSTGRES_DB=app POSTGRES_PASSWORD=not-a-real-secret \
  BACKUP_BUCKET=fake-bucket AWS_REGION=us-east-1 BACKUP_STATE_DIR="$STATE" BACKUP_WORK_DIR="$WORK" \
  /bin/sh "$backup" once >"$CASE_ROOT/output-first" 2>"$CASE_ROOT/error-first" &
first_pid=$!
for _ in $(seq 1 60); do
  if [ -f "$CASE_ROOT/dump-started" ]; then break; fi
  sleep 0.05
done
assert_present "$CASE_ROOT/dump-started"
for _ in $(seq 1 60); do
  if [ -f "$STATE/backup-in-progress" ] 2>/dev/null; then break; fi
  sleep 0.05
done
assert_present "$STATE/backup-in-progress"
assert_contains 'attempt_id=' "$STATE/backup-in-progress"
assert_contains 'started_at=' "$STATE/backup-in-progress"
assert_contains 'object_key=postgres/' "$STATE/backup-in-progress"
# Second backup overlaps the first: it must skip (lock held), never upload.
env -i PATH="$MOCK_BIN:$toolbox" HOME="$CASE_ROOT" TMPDIR="$WORK" CALLS="$CALLS" FAKE_BUCKET="$FAKE_BUCKET" \
  POSTGRES_HOST=db POSTGRES_USER=app POSTGRES_DB=app POSTGRES_PASSWORD=not-a-real-secret \
  BACKUP_BUCKET=fake-bucket AWS_REGION=us-east-1 BACKUP_STATE_DIR="$STATE" BACKUP_WORK_DIR="$WORK" \
  /bin/sh "$backup" once >"$CASE_ROOT/output-second" 2>"$CASE_ROOT/error-second" &
second_pid=$!
for _ in $(seq 1 60); do
  if grep -q 'another backup holds the attempt lock' "$CASE_ROOT/output-second" 2>/dev/null; then break; fi
  sleep 0.05
done
grep -q 'another backup holds the attempt lock' "$CASE_ROOT/output-second" \
  || fail "a second backup while one is running must skip, not proceed"
: >"$CASE_ROOT/release"
set +e
wait "$second_pid"
second_status=$?
wait "$first_pid"
first_status=$?
set -e
[ "$second_status" -ne 0 ] || fail "a skipped concurrent backup must exit non-zero"
[ "$first_status" -eq 0 ] || fail "the first backup should succeed after the second was skipped"
assert_absent "$STATE/backup-in-progress"
[ ! -e "$STATE/.backup-lock" ] || fail "attempt lock survived a serialized pair of backups"
assert_present "$STATE/last-backup"
assert_line 'outcome=success' "$STATE/backup-last-attempt"
assert_absent "$STATE/backup-last-failure"
assert_empty_dir "$WORK"
# One upload only: the skipped attempt must not have created a second object.
[ "$(grep -c 'aws s3 cp' "$CALLS")" -eq 1 ] || fail "a skipped concurrent backup must not upload"
[ "$(ls "$FAKE_BUCKET"/*.sql.gz 2>/dev/null | wc -l | tr -d ' ')" -eq 1 ] \
  || fail "concurrent backups collided on the object key"

# -------------------------------------------------------------- restore-check
prepare_case restore-check-refusals
export RESTORE_CHECK_DB=trade_recommender
restore_archive="$temporary/success/bucket/$(basename "$uploaded")"
if RESTORE_CHECK_DB=trade_recommender /bin/sh "$restore_check" "$restore_archive" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
  fail "restore-check must refuse a non-disposable database name"
fi
assert_contains "must contain 'restore_check'" "$CASE_ROOT/error"
if RESTORE_CHECK_DB="Bad-restore_check" /bin/sh "$restore_check" "$restore_archive" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
  fail "restore-check must refuse an unsafe database name"
fi
if /bin/sh "$restore_check" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
  fail "restore-check without arguments must fail"
fi
[ "$?" -eq 0 ] || true
if RESTORE_CHECK_DB=phase1_restore_check_x /bin/sh "$restore_check" "$CASE_ROOT/does-not-exist.sql.gz" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
  fail "restore-check must fail for a missing archive"
fi
assert_contains 'archive not found' "$CASE_ROOT/error"
printf 'garbage' >"$CASE_ROOT/bad.sql.gz"
mkdir -p "$CASE_ROOT/bin2"
for t in psql createdb dropdb; do printf '#!/bin/bash\nexit 0\n' >"$CASE_ROOT/bin2/$t"; chmod 755 "$CASE_ROOT/bin2/$t"; done
if PATH="$CASE_ROOT/bin2:$toolbox" RESTORE_CHECK_DB=phase1_restore_check_x /bin/sh "$restore_check" "$CASE_ROOT/bad.sql.gz" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
  fail "restore-check must reject an unreadable archive"
fi
assert_contains 'archive_unreadable' "$CASE_ROOT/error"
unset RESTORE_CHECK_DB

echo "backup script simulations passed"
