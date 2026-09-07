#!/bin/sh
# Scheduled PostgreSQL backup with explicit per-stage failure detection.
#
# POSIX sh (the image runs this under dash). The dump/compress pipeline reports
# pg_dump's own exit status through a status file written inside the left side
# of the pipeline, so a failed dump can never fall through to the success
# marker. Every attempt records honest state files in BACKUP_STATE_DIR:
#   backup-last-attempt   attempted_at, object_key, outcome, stage, category
#   backup-last-success   completed_at, attempted_at, object_key, sha256, size_bytes
#   backup-last-failure   failed_at, attempted_at, object_key, stage, category, exit_status
#   last-backup           legacy readiness marker, written only on genuine success
# State files never contain credentials, command bodies or raw error output.
set -u

STATE_DIR="${BACKUP_STATE_DIR:-/var/lib/trade-recommender}"
WORK_ROOT="${BACKUP_WORK_DIR:-${TMPDIR:-/tmp}}"
MIN_BYTES="${BACKUP_MIN_BYTES:-1024}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-21600}"

work_dir=""
job_pid=""
dump_pid=""
attempt_open=0
attempted_at=""
object_key=""
stage="idle"

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
  target="${STATE_DIR}/$1"
  temporary="${target}.tmp.$$"
  if cat >"$temporary" && mv -f "$temporary" "$target"; then
    return 0
  fi
  rm -f "$temporary"
  return 1
}

record_failure() {
  # record_failure CATEGORY EXIT_STATUS
  failed_at="$(date -u +%FT%TZ)"
  write_state backup-last-failure <<EOS
failed_at=${failed_at}
attempted_at=${attempted_at}
object_key=${object_key}
stage=${stage}
category=$1
exit_status=$2
EOS
  write_state backup-last-attempt <<EOS
attempted_at=${attempted_at}
object_key=${object_key}
outcome=failure
stage=${stage}
category=$1
EOS
  log "attempt failed: stage=${stage} category=$1 exit_status=$2 object_key=${object_key}"
}

record_success() {
  # record_success SHA256 SIZE_BYTES
  completed_at="$(date -u +%FT%TZ)"
  write_state backup-last-success <<EOS || return 1
completed_at=${completed_at}
attempted_at=${attempted_at}
object_key=${object_key}
sha256=$1
size_bytes=$2
EOS
  write_state backup-last-attempt <<EOS || return 1
attempted_at=${attempted_at}
object_key=${object_key}
outcome=success
stage=record
category=none
EOS
  printf '%s\n' "$completed_at" >"${STATE_DIR}/last-backup.tmp.$$" \
    && mv -f "${STATE_DIR}/last-backup.tmp.$$" "${STATE_DIR}/last-backup"
}

cleanup_work() {
  if [ -n "$work_dir" ]; then
    rm -rf "$work_dir"
    work_dir=""
  fi
}

kill_children() {
  for pid in "$dump_pid" "$job_pid"; do
    if [ -n "$pid" ]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  dump_pid=""
  job_pid=""
}

on_signal() {
  # $1 = exit status to use (130 INT, 143 TERM)
  trap - INT TERM
  kill_children
  if [ "$attempt_open" -eq 1 ]; then
    record_failure interrupted "$1"
    attempt_open=0
  fi
  cleanup_work
  exit "$1"
}

trap 'on_signal 130' INT
trap 'on_signal 143' TERM
trap 'cleanup_work' EXIT

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
  attempted_at="$(date -u +%FT%TZ)"
  object_key="postgres/$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
  attempt_open=1
  stage=configure
  for name in POSTGRES_HOST POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD BACKUP_BUCKET AWS_REGION; do
    eval "value=\${$name:-}"
    if [ -z "$value" ]; then
      log "required configuration ${name} is missing"
      record_failure configuration_missing 2
      attempt_open=0
      return 1
    fi
  done
  case "$MIN_BYTES" in
    ''|*[!0-9]*)
      log "BACKUP_MIN_BYTES must be a non-negative integer"
      record_failure configuration_invalid 2
      attempt_open=0
      return 1
      ;;
  esac
  if [ ! -d "$STATE_DIR" ] || [ ! -w "$STATE_DIR" ]; then
    log "state directory ${STATE_DIR} is not writable; cannot record backup state"
    attempt_open=0
    return 1
  fi
  if ! work_dir="$(mktemp -d "${WORK_ROOT}/backup.XXXXXX" 2>/dev/null)"; then
    work_dir=""
    record_failure workdir_unwritable 1
    attempt_open=0
    return 1
  fi
  archive="${work_dir}/archive.sql.gz"

  stage=dump
  {
    PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --host="$POSTGRES_HOST" --username="$POSTGRES_USER" \
      --dbname="$POSTGRES_DB" --clean --if-exists --no-owner --no-acl 2>"${work_dir}/dump.err" &
    printf '%s' "$!" >"${work_dir}/dump.pid"
    wait "$!"
    printf '%s' "$?" >"${work_dir}/dump.status"
  } | gzip -9 >"$archive" 2>"${work_dir}/gzip.err" &
  job_pid=$!
  wait "$job_pid"
  gzip_status=$?
  job_pid=""
  dump_pid=""
  dump_status="$(cat "${work_dir}/dump.status" 2>/dev/null || printf missing)"
  if [ "$dump_status" != 0 ]; then
    log_error_excerpt "${work_dir}/dump.err"
    record_failure dump_failed "$dump_status"
    attempt_open=0
    cleanup_work
    return 1
  fi
  stage=compress
  if [ "$gzip_status" != 0 ]; then
    log_error_excerpt "${work_dir}/gzip.err"
    record_failure compression_failed "$gzip_status"
    attempt_open=0
    cleanup_work
    return 1
  fi

  stage=validate
  if ! gzip -t "$archive" 2>"${work_dir}/gzip-test.err"; then
    log_error_excerpt "${work_dir}/gzip-test.err"
    record_failure archive_unreadable 1
    attempt_open=0
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
    cleanup_work
    return 1
  fi
  if ! gzip -dc "$archive" 2>/dev/null | head -c 65536 | grep -q 'PostgreSQL database dump'; then
    record_failure archive_content_invalid 1
    attempt_open=0
    cleanup_work
    return 1
  fi
  if ! gzip -dc "$archive" 2>/dev/null | tail -c 4096 | grep -q 'PostgreSQL database dump complete'; then
    log "archive lacks the pg_dump completion marker; treating as truncated"
    record_failure archive_content_invalid 1
    attempt_open=0
    cleanup_work
    return 1
  fi

  stage=checksum
  sha256="$(digest_file "$archive" 2>/dev/null || true)"
  if [ "${#sha256}" -ne 64 ]; then
    record_failure checksum_failed 1
    attempt_open=0
    cleanup_work
    return 1
  fi

  stage=upload
  aws s3 cp "$archive" "s3://${BACKUP_BUCKET}/${object_key}" \
    --region "$AWS_REGION" --sse AES256 --only-show-errors 2>"${work_dir}/upload.err" &
  job_pid=$!
  wait "$job_pid"
  upload_status=$?
  job_pid=""
  if [ "$upload_status" != 0 ]; then
    log_error_excerpt "${work_dir}/upload.err"
    record_failure upload_failed "$upload_status"
    attempt_open=0
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
    cleanup_work
    return 1
  fi
  if [ "$remote_size" != "$size" ]; then
    log "uploaded object size ${remote_size} does not match local ${size}"
    record_failure upload_size_mismatch 1
    attempt_open=0
    cleanup_work
    return 1
  fi

  stage=record
  if ! record_success "$sha256" "$size"; then
    record_failure state_write_failed 1
    attempt_open=0
    cleanup_work
    return 1
  fi
  attempt_open=0
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
