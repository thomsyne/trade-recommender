#!/bin/sh
# Scheduled PostgreSQL backup with explicit per-stage failure detection.
#
# POSIX sh (the image runs this under dash). pg_dump streams into gzip through
# a FIFO; both are started in dedicated sessions when setsid(1) is available
# and killed as a supervised process group on interrupt, so an interrupt
# terminates pg_dump and its whole pipeline rather than leaving an orphan.
# Every attempt records honest state files in BACKUP_STATE_DIR:
#   backup-in-progress    attempt_id, started_at, attempted_at, object_key, stage
#                         (durable record written once the lock is held and
#                          BEFORE any dump/upload work; removed only after a
#                          terminal outcome has been recorded)
#   backup-last-attempt   attempt_id, attempted_at, object_key, outcome, stage, category
#                         (terminal attempts only: success or failure)
#   backup-last-success   attempt_id, completed_at, attempted_at, object_key, sha256, size_bytes
#   backup-last-failure   attempt_id, failed_at, attempted_at, object_key, stage, category, exit_status
#   last-backup           legacy readiness marker, written only on genuine success
#
# Attempts are serialized with flock(1) on a lock file in the shared
# BACKUP_STATE_DIR (.backup-lock). The scheduler's backup loop and a deploy-time
# `backup.sh once` run in different containers on the same state volume;
# flock locks are owned by the kernel, so a crashed holder (SIGKILL, host
# loss) releases the lock automatically and can never deadlock later attempts
# the way a PID-file lock can. Each attempt id is a random UUID (128 bits), so
# two attempts can never share an id or an S3 object key.
#
# An attempt commits when backup-last-attempt reports outcome=success (the
# record stage runs only after the upload was verified by size AND content
# checksum, which is attached to the S3 object as user metadata at upload
# time). The success file and legacy marker are best-effort publications made
# after that commit, and no failure is ever recorded over a committed success.
# The in-progress record is removed only once a terminal outcome exists, so a
# stale backup-in-progress file (no flock held) unambiguously means the
# previous attempt died before recording an outcome.
# Signal handlers ignore subsequent INT/TERM while running, kill the
# supervised child sessions, and record interrupted before releasing the lock.
# State files never contain credentials, command bodies or raw error output.
set -u

STATE_DIR="${BACKUP_STATE_DIR:-/var/lib/trade-recommender}"
WORK_ROOT="${BACKUP_WORK_DIR:-${TMPDIR:-/tmp}}"
MIN_BYTES="${BACKUP_MIN_BYTES:-1024}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-21600}"
LOCK_FILE="${STATE_DIR}/.backup-lock"
IN_PROGRESS_FILE="${STATE_DIR}/backup-in-progress"

work_dir=""
job_pid=""
dump_pid=""
attempt_open=0
attempt_id=""
attempted_at=""
object_key=""
stage="idle"
lock_fd=9

log() {
  printf '%s backup: %s\n' "$(date -u +%FT%TZ)" "$*"
}

log_error_excerpt() {
  # Bounded excerpt of a stage's stderr for the container log only.
  if [ -n "${1:-}" ] && [ -s "$1" ]; then
    printf 'backup %s stderr (bounded):\n' "$stage" >&2
    head -c 2000 "$1" >&2
    printf '\n' >&2
  fi
}

write_state() {
  # write_state NAME < key=value lines ; atomic replace inside STATE_DIR.
  # Returns 1 when the file cannot be written (callers must abort the
  # attempt: state is mandatory, not best-effort).
  target="${STATE_DIR}/$1"
  temporary="${target}.tmp.$$"
  if cat >"$temporary" && mv -f "$temporary" "$target"; then
    return 0
  fi
  rm -f "$temporary"
  return 1
}

require_tools() {
  # The backup must fail loudly, not degrade, when its safety primitives are
  # missing. flock(1) comes from util-linux in the production image.
  if ! command -v flock >/dev/null 2>&1; then
    log "flock(1) is required for backup serialization"
    return 1
  fi
  return 0
}

acquire_lock() {
  # Exclusive attempt lock via flock on a shared file. Opening the descriptor
  # here and locking it from the (child) flock process works because the lock
  # belongs to the open file description both share: it persists until this
  # shell closes the descriptor, and the kernel releases it automatically if
  # this process dies. Non-blocking, so a running backup is skipped loudly.
  if ! require_tools; then
    return 2
  fi
  eval "exec ${lock_fd}>\"\$LOCK_FILE\"" 2>/dev/null
  if flock -n "$lock_fd" 2>/dev/null; then
    return 0
  fi
  eval "exec ${lock_fd}>&-"
  return 1
}

release_lock() {
  # Close the lock descriptor (releasing the flock) and remove this attempt's
  # in-progress record, which is only correct once a terminal outcome has been
  # recorded and published by the caller. Removing the lock file is safe only
  # after the flock is dropped: a contender that opened it first keeps its own
  # lock on the unlinked inode, and a fresh file serializes later attempts.
  eval "exec ${lock_fd}>&-" 2>/dev/null || true
  rm -f "$IN_PROGRESS_FILE" 2>/dev/null || true
  rm -f "$LOCK_FILE" 2>/dev/null || true
}

new_attempt_id() {
  # 128-bit random identity; every state record and S3 object key of one
  # attempt carries the same id and no two attempts share one.
  if [ -r /proc/sys/kernel/random/uuid ]; then
    cat /proc/sys/kernel/random/uuid
  elif command -v uuidgen >/dev/null 2>&1; then
    uuidgen
  else
    log "no UUID source available"
    return 1
  fi
}

record_failure() {
  # record_failure CATEGORY EXIT_STATUS
  # Refuse to overwrite an attempt that has already committed as a success for
  # this attempt_id: a signal can land between the commit and the success
  # publication, and the committed record is the single source of truth.
  if [ -f "${STATE_DIR}/backup-last-attempt" ] \
     && grep -Fqx "attempt_id=${attempt_id}" "${STATE_DIR}/backup-last-attempt" \
     && grep -Fqx "outcome=success" "${STATE_DIR}/backup-last-attempt"; then
    log "attempt already committed as success; refusing to record $1 failure"
    return 0
  fi
  failed_at="$(date -u +%FT%TZ)"
  write_state backup-last-failure <<EOS
attempt_id=${attempt_id}
failed_at=${failed_at}
attempted_at=${attempted_at}
object_key=${object_key}
stage=${stage}
category=$1
exit_status=$2
EOS
  write_state backup-last-attempt <<EOS
attempt_id=${attempt_id}
attempted_at=${attempted_at}
object_key=${object_key}
outcome=failure
stage=${stage}
category=$1
EOS
  log "attempt failed: stage=${stage} category=$1 exit_status=$2 object_key=${object_key}"
}

record_in_progress() {
  # Durable in-progress record published after the lock is held and before any
  # dump or upload work begins. A failed write aborts the attempt: dumping
  # without a durable state record would make an interrupted attempt
  # indistinguishable from "no attempt". The file is removed only by
  # release_lock after a terminal outcome has been recorded.
  started_at="$(date -u +%FT%TZ)"
  write_state backup-in-progress <<EOS
attempt_id=${attempt_id}
started_at=${started_at}
attempted_at=${attempted_at}
object_key=${object_key}
stage=${stage}
EOS
}

record_success() {
  # record_success SHA256 SIZE_BYTES
  # The attempt record is the commit: it is written first and, once on disk,
  # nothing may turn this attempt into a failure. The success file and the
  # legacy marker are projections published after the commit and are
  # best-effort only -- a publication failure never flips the committed
  # outcome. Only a failure to write the commit itself returns non-zero.
  # The in-progress record is deliberately kept until release_lock, so the
  # commit is visible as an outcome before the in-progress marker disappears.
  completed_at="$(date -u +%FT%TZ)"
  if ! printf '%s\n' \
      "attempt_id=${attempt_id}" \
      "attempted_at=${attempted_at}" \
      "object_key=${object_key}" \
      "outcome=success" \
      "stage=record" \
      "category=none" | write_state backup-last-attempt; then
    return 1
  fi
  attempt_open=0
  if ! printf '%s\n' \
      "attempt_id=${attempt_id}" \
      "completed_at=${completed_at}" \
      "attempted_at=${attempted_at}" \
      "object_key=${object_key}" \
      "sha256=$1" \
      "size_bytes=$2" | write_state backup-last-success; then
    log "state publish warning: could not write backup-last-success; committed attempt stands"
  fi
  if ! printf '%s\n' "$completed_at" >"${STATE_DIR}/last-backup.tmp.$$"; then
    log "state publish warning: could not write last-backup; committed attempt stands"
  elif ! mv -f "${STATE_DIR}/last-backup.tmp.$$" "${STATE_DIR}/last-backup"; then
    rm -f "${STATE_DIR}/last-backup.tmp.$$"
    log "state publish warning: could not publish last-backup; committed attempt stands"
  fi
}

cleanup_work() {
  if [ -n "$work_dir" ]; then
    rm -rf "$work_dir"
    work_dir=""
  fi
}

kill_children() {
  # Terminate the supervised child sessions and wait for each tracked child to
  # be reaped before clearing the PIDs. Each long-lived child is started with
  # setsid when available, so a negative PID kills its whole session (pg_dump
  # and any process it spawned); the fallback kills the direct child.
  for pid in "$dump_pid" "$job_pid"; do
    if [ -n "$pid" ]; then
      kill "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$dump_pid" "$job_pid"; do
    if [ -n "$pid" ]; then
      wait "$pid" 2>/dev/null || true
    fi
  done
  dump_pid=""
  job_pid=""
}

on_signal() {
  # $1 = exit status to use (130 INT, 143 TERM)
  # Further INT/TERM are ignored while the handler runs so a second signal
  # cannot interrupt failure publication or the lock/work cleanup; the handler
  # exits with the original status so the EXIT trap still fires afterwards.
  trap 'trap - INT TERM' INT TERM
  kill_children
  if [ "$attempt_open" -eq 1 ]; then
    record_failure interrupted "$1"
    attempt_open=0
  fi
  release_lock
  cleanup_work
  exit "$1"
}

trap 'on_signal 130' INT
trap 'on_signal 143' TERM
trap 'release_lock; cleanup_work' EXIT

digest_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    openssl dgst -sha256 "$1" | sed 's/^.*= //'
  fi
}

backup_once() {
  if [ ! -d "$STATE_DIR" ] || [ ! -w "$STATE_DIR" ]; then
    log "state directory ${STATE_DIR} is not writable; cannot record backup state"
    return 1
  fi
  if ! acquire_lock; then
    status=$?
    if [ "$status" -eq 2 ]; then
      log "backup aborted: required locking tools are missing"
    else
      log "another backup holds the attempt lock; skipping this attempt"
    fi
    return 1
  fi
  attempted_at="$(date -u +%FT%TZ)"
  attempt_id="$(new_attempt_id)" || {
    release_lock
    return 1
  }
  object_key="postgres/$(date -u +%Y%m%dT%H%M%SZ)-${attempt_id}.sql.gz"
  attempt_open=1
  stage=configure
  for name in POSTGRES_HOST POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD BACKUP_BUCKET AWS_REGION; do
    eval "value=\${$name:-}"
    if [ -z "$value" ]; then
      log "required configuration ${name} is missing"
      record_failure configuration_missing 2
      attempt_open=0
      release_lock
      return 1
    fi
  done
  case "$MIN_BYTES" in
    ''|*[!0-9]*)
      log "BACKUP_MIN_BYTES must be a non-negative integer"
      record_failure configuration_invalid 2
      attempt_open=0
      release_lock
      return 1
      ;;
  esac
  if ! record_in_progress; then
    log "cannot write backup-in-progress in ${STATE_DIR}; aborting attempt"
    attempt_open=0
    release_lock
    return 1
  fi
  if ! work_dir="$(mktemp -d "${WORK_ROOT}/backup.XXXXXX" 2>/dev/null)"; then
    work_dir=""
    record_failure workdir_unwritable 1
    attempt_open=0
    release_lock
    return 1
  fi
  archive="${work_dir}/archive.sql.gz"

  stage=dump
  if ! mkfifo "${work_dir}/dump.fifo" 2>"${work_dir}/mkfifo.err"; then
    record_failure dump_failed 1
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi
  if command -v setsid >/dev/null 2>&1; then
    setsid gzip -9 <"${work_dir}/dump.fifo" >"$archive" 2>"${work_dir}/gzip.err" &
    job_pid=$!
    PGPASSWORD="$POSTGRES_PASSWORD" setsid pg_dump --host="$POSTGRES_HOST" \
      --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --clean --if-exists \
      --no-owner --no-acl >"${work_dir}/dump.fifo" 2>"${work_dir}/dump.err" &
    dump_pid=$!
  else
    gzip -9 <"${work_dir}/dump.fifo" >"$archive" 2>"${work_dir}/gzip.err" &
    job_pid=$!
    PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --host="$POSTGRES_HOST" \
      --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --clean --if-exists \
      --no-owner --no-acl >"${work_dir}/dump.fifo" 2>"${work_dir}/dump.err" &
    dump_pid=$!
  fi
  wait "$dump_pid"
  dump_status=$?
  dump_pid=""
  wait "$job_pid"
  gzip_status=$?
  job_pid=""
  if [ "$dump_status" != 0 ]; then
    log_error_excerpt "${work_dir}/dump.err"
    record_failure dump_failed "$dump_status"
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi
  stage=compress
  if [ "$gzip_status" != 0 ]; then
    log_error_excerpt "${work_dir}/gzip.err"
    record_failure compression_failed "$gzip_status"
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi

  stage=validate
  if ! gzip -t "$archive" 2>"${work_dir}/gzip-test.err"; then
    log_error_excerpt "${work_dir}/gzip-test.err"
    record_failure archive_unreadable 1
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi
  size="$(wc -c <"$archive" | tr -d ' ')"
  case "$size" in
    ''|*[!0-9]*) size=0 ;;
  esac
  if [ "$size" -lt "$MIN_BYTES" ]; then
    log "archive is ${size} bytes; minimum is ${MIN_BYTES}"
    record_failure archive_too_small 1
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi
  if ! gzip -dc "$archive" 2>/dev/null | head -c 65536 | grep -q 'PostgreSQL database dump'; then
    record_failure archive_content_invalid 1
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi
  if ! gzip -dc "$archive" 2>/dev/null | tail -c 4096 | grep -q 'PostgreSQL database dump complete'; then
    log "archive lacks the pg_dump completion marker; treating as truncated"
    record_failure archive_content_invalid 1
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi

  stage=checksum
  sha256="$(digest_file "$archive" 2>/dev/null || true)"
  if [ "${#sha256}" -ne 64 ]; then
    record_failure checksum_failed 1
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi

  stage=upload
  aws s3 cp "$archive" "s3://${BACKUP_BUCKET}/${object_key}" \
    --region "$AWS_REGION" --sse AES256 --only-show-errors \
    --metadata "sha256=${sha256}" 2>"${work_dir}/upload.err" &
  job_pid=$!
  wait "$job_pid"
  upload_status=$?
  job_pid=""
  if [ "$upload_status" != 0 ]; then
    log_error_excerpt "${work_dir}/upload.err"
    record_failure upload_failed "$upload_status"
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi

  stage=verify_upload
  remote_size="$(aws s3api head-object --bucket "$BACKUP_BUCKET" --key "$object_key" \
    --region "$AWS_REGION" --query ContentLength --output text 2>"${work_dir}/head.err")"
  head_status=$?
  if [ "$head_status" != 0 ]; then
    log_error_excerpt "${work_dir}/head.err"
    record_failure upload_unverified "$head_status"
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi
  remote_sha="$(aws s3api head-object --bucket "$BACKUP_BUCKET" --key "$object_key" \
    --region "$AWS_REGION" --query "Metadata.sha256" --output text 2>>"${work_dir}/head.err")"
  if [ "$remote_size" != "$size" ] || [ "$remote_sha" != "$sha256" ]; then
    log "uploaded object size ${remote_size}/sha ${remote_sha} does not match local ${size}/${sha256}"
    record_failure upload_checksum_mismatch 1
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi

  stage=record
  if ! record_success "$sha256" "$size"; then
    record_failure state_write_failed 1
    attempt_open=0
    release_lock
    cleanup_work
    return 1
  fi
  attempt_open=0
  release_lock
  cleanup_work
  log "backup uploaded: ${object_key} sha256=${sha256} size_bytes=${size}"
  return 0
}

if [ "${1:-once}" = "loop" ]; then
  while :; do
    if ! backup_once; then
      log "next attempt in ${INTERVAL} seconds; the failed attempt was not marked successful"
    fi
    sleep "$INTERVAL" &
    job_pid=$!
    wait "$job_pid"
    job_pid=""
  done
else
  backup_once
fi
