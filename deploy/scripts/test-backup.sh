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
for command in basename cat chmod cp cut date dirname env grep gzip head kill ls mktemp mv printf rm sed seq sleep tail tr wc; do
  path="$(command -v "$command" || true)"
  if [ -n "$path" ] && [ -x "$path" ]; then ln -s "$path" "$toolbox/$command"; fi
done
for digest in sha256sum shasum openssl; do
  path="$(command -v "$digest" || true)"
  if [ -n "$path" ]; then ln -s "$path" "$toolbox/$digest"; fi
done
# The macOS shasum is a perl script; make sure perl resolves.
if command -v perl >/dev/null; then ln -sf "$(command -v perl)" "$toolbox/perl"; fi

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
  cp "$3" "$FAKE_BUCKET/$(basename "$4")"
  exit 0
fi
if [ "$1" = s3api ] && [ "$2" = head-object ]; then
  key=""
  while [ "$#" -gt 0 ]; do [ "$1" = --key ] && { shift; key="$1"; }; shift; done
  wc -c <"$FAKE_BUCKET/$(basename "$key")" | tr -d ' '
  exit 0
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
assert_empty_dir "$WORK"
grep -rq 'not-a-real-secret' "$STATE" && fail "state files must never contain the password"
uploaded="$(ls "$FAKE_BUCKET")"
[ -n "$uploaded" ] || fail "no object was uploaded"
gzip -t "$FAKE_BUCKET/$uploaded" || fail "uploaded archive is not valid gzip"
recorded_sha="$(sed -n 's/^sha256=//p' "$STATE/backup-last-success")"
actual_sha="$( (sha256sum "$FAKE_BUCKET/$uploaded" 2>/dev/null || shasum -a 256 "$FAKE_BUCKET/$uploaded") | cut -d' ' -f1)"
[ "$recorded_sha" = "$actual_sha" ] || fail "recorded sha256 does not match the uploaded archive"
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
if [ "$1" = s3api ]; then echo 1; exit 0; fi
exit 0
EOF
if run_backup once; then fail "size mismatch after upload must exit non-zero"; fi
assert_line 'category=upload_size_mismatch' "$STATE/backup-last-failure"
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
sleep 30
EOF
env -i PATH="$MOCK_BIN:$toolbox" HOME="$CASE_ROOT" TMPDIR="$WORK" CALLS="$CALLS" FAKE_BUCKET="$FAKE_BUCKET" \
  POSTGRES_HOST=db POSTGRES_USER=app POSTGRES_DB=app POSTGRES_PASSWORD=not-a-real-secret \
  BACKUP_BUCKET=fake-bucket AWS_REGION=us-east-1 BACKUP_STATE_DIR="$STATE" BACKUP_WORK_DIR="$WORK" \
  /bin/sh "$backup" loop >"$CASE_ROOT/output" 2>"$CASE_ROOT/error" &
loop_pid=$!
for _ in $(seq 1 40); do
  if grep -q pg_dump "$CALLS" 2>/dev/null; then break; fi
  sleep 0.25
done
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
assert_empty_dir "$WORK"
pkill -f "sleep 30" 2>/dev/null || true

# -------------------------------------------------------------- restore-check
prepare_case restore-check-refusals
export RESTORE_CHECK_DB=trade_recommender
if RESTORE_CHECK_DB=trade_recommender /bin/sh "$restore_check" "$temporary/success/bucket/$uploaded" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
  fail "restore-check must refuse a non-disposable database name"
fi
assert_contains "must contain 'restore_check'" "$CASE_ROOT/error"
if RESTORE_CHECK_DB="Bad-restore_check" /bin/sh "$restore_check" "$temporary/success/bucket/$uploaded" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
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
