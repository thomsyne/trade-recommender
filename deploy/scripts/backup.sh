#!/bin/sh
# Scheduled PostgreSQL backup with explicit per-stage failure detection.
#
# POSIX sh (the image runs this under dash). Four properties carry the design:
#
# 1. Exclusion is owned by the kernel. Attempts serialize on an flock(1) lock
#    over a PERSISTENT file in the shared state volume. The file is created once
#    and never unlinked: unlinking it while another attempt holds the lock would
#    let the next process create a fresh inode and lock that instead, so two
#    backups would run at once. A contender that loses the race touches nothing
#    at all -- not the lock, not the holder's state -- and exits 3. Because the
#    lock lives on an open file description the kernel releases it if the holder
#    dies for any reason, so a crash can never deadlock later attempts the way a
#    PID file can.
#
# 2. State is durable and mandatory. Storage and every required tool are
#    checked before any work begins. A valid backup-in-progress record commits
#    before pg_dump runs, and only the attempt named in that record may clear
#    it, after a terminal outcome has been recorded. Every state write is
#    checked; if the authoritative terminal record cannot be written the attempt
#    exits non-zero and deliberately LEAVES its in-progress evidence behind, so
#    an unresolved attempt is always visible rather than silently forgotten.
#
# 3. An upload is attested against one exact S3 object version. put-object
#    returns the VersionId and the checksum S3 itself computed; verification
#    then re-reads that specific version. A concurrent writer replacing the key
#    cannot make this attempt attest an object it did not create.
#
# 4. The dump pipeline is one supervised process group. pg_dump and gzip are
#    started by a single supervisor launched under job control, so they share a
#    process group that is provably not this shell's; an interrupt terminates
#    that group and reaps it. Signals arriving in the launch window are recorded
#    and acted on the moment the supervisor is tracked, so no child can be left
#    running untracked.
#
# State files in BACKUP_STATE_DIR:
#   backup-in-progress    attempt_id, started_at, attempted_at, object_key, stage
#   backup-last-attempt   the authoritative terminal record for an attempt
#   backup-last-success   attempt_id, completed_at, object_key, version_id, sha256, size_bytes
#   backup-last-failure   attempt_id, failed_at, object_key, stage, category, exit_status
#   last-backup           legacy readiness marker, written only on genuine success
#
# Exit codes: 0 success; 1 the attempt failed and the failure was recorded;
# 2 a precondition failed (missing tool, unusable state directory, unwritable
# state) so no attempt was made; 3 another attempt holds the lock. The loop
# treats 3 as an ordinary skip; a deploy-time `backup.sh once` treats every
# non-zero status as a reason to stop.
#
# State files never contain credentials, command bodies or raw error output.
set -u

STATE_DIR="${BACKUP_STATE_DIR:-/var/lib/trade-recommender}"
WORK_ROOT="${BACKUP_WORK_DIR:-${TMPDIR:-/tmp}}"
MIN_BYTES="${BACKUP_MIN_BYTES:-1024}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-21600}"
# How long a dump may ignore TERM before it is killed outright.
KILL_AFTER_SECONDS="${BACKUP_KILL_AFTER_SECONDS:-10}"
LOCK_FILE="${STATE_DIR}/.backup-lock"
IN_PROGRESS_FILE="${STATE_DIR}/backup-in-progress"
ATTEMPT_FILE="${STATE_DIR}/backup-last-attempt"
SUCCESS_FILE="${STATE_DIR}/backup-last-success"
FAILURE_FILE="${STATE_DIR}/backup-last-failure"
MARKER_FILE="${STATE_DIR}/last-backup"

EXIT_FAILED=1
EXIT_PRECONDITION=2
EXIT_CONTENDED=3

lock_fd=9
probe_fd=7
contender_fd=6
# Reserved for "another attempt holds the lock". Distinct from every status a
# shell, a signal or flock itself produces for an operational failure.
FLOCK_CONTENTION_CODE=97
lock_held=0
work_dir=""
supervisor_pid=""
group=""
attempt_open=0
attempt_id=""
attempted_at=""
object_key=""
version_id=""
stage="idle"
launching=0
pending_signal=""
self_group=""
flock_conflict_code=""
fail_category=""
fail_status=0

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
  # Returns 1 when the file cannot be written. Every caller checks it: state is
  # mandatory, never best effort.
  target="${STATE_DIR}/$1"
  temporary="${target}.tmp.$$"
  if cat >"$temporary" && mv -f "$temporary" "$target"; then
    return 0
  fi
  rm -f "$temporary" 2>/dev/null || true
  return 1
}

preflight() {
  # Everything the attempt depends on, verified before it can half-run.
  if [ ! -d "$STATE_DIR" ] || [ ! -w "$STATE_DIR" ]; then
    log "state directory ${STATE_DIR} is not writable; cannot record backup state"
    return 1
  fi
  for tool in flock pg_dump gzip aws mktemp mkfifo date; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      log "required tool ${tool} is missing"
      return 1
    fi
  done
  if ! command -v sha256sum >/dev/null 2>&1 \
     && ! command -v shasum >/dev/null 2>&1 \
     && ! command -v openssl >/dev/null 2>&1; then
    log "no SHA-256 implementation is available"
    return 1
  fi
  if ! command -v openssl >/dev/null 2>&1 && ! command -v base64 >/dev/null 2>&1; then
    log "no base64 implementation is available for checksum verification"
    return 1
  fi
  # A probe write proves the directory is usable, not merely mode-writable.
  if ! printf 'probe\n' | write_state .backup-preflight; then
    log "cannot write state files in ${STATE_DIR}"
    return 1
  fi
  rm -f "${STATE_DIR}/.backup-preflight" 2>/dev/null || true
  self_group="$(process_group $$)"
  if ! detect_flock_conflict_code; then
    # Fail closed. Without a dedicated conflict status every failure would have
    # to be read as "another backup is running", and a genuinely broken lock
    # would look like a healthy skip for ever. util-linux flock provides it;
    # the production image ships that implementation.
    log "flock(1) does not report a dedicated conflict exit status; refusing to guess"
    return 1
  fi
  return 0
}

detect_flock_conflict_code() {
  # Establish, by experiment rather than by reading help text, that this flock
  # reports contention with a dedicated exit status. Help output is localized
  # and an implementation that silently ignores an unknown option would look
  # like it honoured it; only a real conflict answers with the reserved code.
  #
  # This shell takes the probe lock, then a child contends for it through its
  # own descriptor. A child is a separate process, so the kernel genuinely
  # denies it, and only an implementation honouring -E exits with
  # FLOCK_CONTENTION_CODE.
  flock_conflict_code=""
  probe="${STATE_DIR}/.backup-lock-probe.$$"
  if ! : >"$probe" 2>/dev/null; then
    return 1
  fi
  if ! eval "exec ${probe_fd}>>\"\$probe\"" 2>/dev/null; then
    rm -f "$probe" 2>/dev/null || true
    return 1
  fi
  if flock -n "$probe_fd" 2>/dev/null; then
    ( eval "exec ${contender_fd}>>\"\$probe\"" \
      && flock -n -E "$FLOCK_CONTENTION_CODE" "$contender_fd" ) >/dev/null 2>&1
    if [ $? -eq "$FLOCK_CONTENTION_CODE" ]; then
      flock_conflict_code="$FLOCK_CONTENTION_CODE"
    fi
  fi
  eval "exec ${probe_fd}>&-" 2>/dev/null || true
  rm -f "$probe" 2>/dev/null || true
  [ -n "$flock_conflict_code" ]
}

acquire_lock() {
  # 0 acquired, 3 another attempt holds the lock, 2 the lock could not be
  # evaluated. Reporting an operational failure as contention would let a
  # broken lock look like a healthy skip forever, so the two are kept apart:
  # a descriptor that will not open is an error, and where flock supports -E
  # only its conflict status counts as contention.
  if ! eval "exec ${lock_fd}>>\"\$LOCK_FILE\"" 2>/dev/null; then
    log "cannot open the attempt lock file ${LOCK_FILE}"
    return 2
  fi
  flock -n -E "$flock_conflict_code" "$lock_fd" 2>/dev/null
  lock_status=$?
  if [ "$lock_status" -eq 0 ]; then
    lock_held=1
    return 0
  fi
  eval "exec ${lock_fd}>&-" 2>/dev/null || true
  if [ "$lock_status" -ne "$flock_conflict_code" ]; then
    # Anything that is not the reserved contention status is an operational
    # failure. A losing contender has touched nothing: it never held the lock
    # and never opened any state file.
    log "attempt lock could not be evaluated (flock exited ${lock_status})"
    return 2
  fi
  return 3
}

release_lock() {
  # Only the owner releases, and only the descriptor is closed. The lock file
  # itself is permanent: removing it would break exclusion for everyone else.
  [ "$lock_held" -eq 1 ] || return 0
  eval "exec ${lock_fd}>&-" 2>/dev/null || true
  lock_held=0
}

clear_in_progress() {
  # Only the attempt named in the record may retire it, and only once a
  # terminal outcome has been recorded.
  [ -n "$attempt_id" ] || return 0
  if [ -f "$IN_PROGRESS_FILE" ] \
     && grep -Fqx "attempt_id=${attempt_id}" "$IN_PROGRESS_FILE" 2>/dev/null; then
    rm -f "$IN_PROGRESS_FILE" 2>/dev/null || true
  fi
}

new_attempt_id() {
  if [ -r /proc/sys/kernel/random/uuid ]; then
    cat /proc/sys/kernel/random/uuid
  elif command -v uuidgen >/dev/null 2>&1; then
    uuidgen
  else
    log "no UUID source available"
    return 1
  fi
}

digest_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    openssl dgst -sha256 "$1" | sed 's/^.*= //'
  fi
}

digest_file_base64() {
  # S3 reports checksums base64-encoded, so the local digest must be compared
  # in the same encoding rather than trusting the hex metadata alone.
  if command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 -binary "$1" 2>/dev/null | openssl base64 -A 2>/dev/null
  elif command -v sha256sum >/dev/null 2>&1 && command -v xxd >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1 | xxd -r -p | base64 | tr -d '\n'
  else
    return 1
  fi
}

record_in_progress() {
  started_at="$(date -u +%FT%TZ)"
  printf '%s\n' \
    "attempt_id=${attempt_id}" \
    "started_at=${started_at}" \
    "attempted_at=${attempted_at}" \
    "object_key=${object_key}" \
    "stage=${stage}" | write_state backup-in-progress
}

record_failure() {
  # record_failure CATEGORY EXIT_STATUS -> 0 when the terminal record committed.
  # Refuses to overwrite an attempt already committed as a success: a signal can
  # land between the commit and its publication, and the committed record is the
  # single source of truth.
  if [ -f "$ATTEMPT_FILE" ] \
     && grep -Fqx "attempt_id=${attempt_id}" "$ATTEMPT_FILE" 2>/dev/null \
     && grep -Fqx "outcome=success" "$ATTEMPT_FILE" 2>/dev/null; then
    log "attempt already committed as success; refusing to record $1 failure"
    return 0
  fi
  failed_at="$(date -u +%FT%TZ)"
  # The detail file is written first so it can never describe an attempt the
  # authoritative record does not know about. If it cannot be written it is
  # removed instead, leaving no stale detail to contradict the outcome.
  if ! printf '%s\n' \
      "attempt_id=${attempt_id}" \
      "failed_at=${failed_at}" \
      "attempted_at=${attempted_at}" \
      "object_key=${object_key}" \
      "stage=${stage}" \
      "category=$1" \
      "exit_status=$2" | write_state backup-last-failure; then
    log "state publish warning: could not write backup-last-failure"
    rm -f "$FAILURE_FILE" 2>/dev/null || true
  fi
  if ! printf '%s\n' \
      "attempt_id=${attempt_id}" \
      "attempted_at=${attempted_at}" \
      "object_key=${object_key}" \
      "outcome=failure" \
      "stage=${stage}" \
      "category=$1" | write_state backup-last-attempt; then
    log "cannot record the terminal attempt state; in-progress evidence is retained"
    return 1
  fi
  log "attempt failed: stage=${stage} category=$1 exit_status=$2 object_key=${object_key}"
  return 0
}

record_success() {
  # record_success SHA256 SIZE_BYTES -> 0 when the terminal record committed.
  # backup-last-success is written first (it is true the moment the upload was
  # verified), then the authoritative attempt record commits the outcome. The
  # legacy marker is a projection published after the commit.
  completed_at="$(date -u +%FT%TZ)"
  if ! printf '%s\n' \
      "attempt_id=${attempt_id}" \
      "completed_at=${completed_at}" \
      "attempted_at=${attempted_at}" \
      "object_key=${object_key}" \
      "version_id=${version_id}" \
      "sha256=$1" \
      "size_bytes=$2" | write_state backup-last-success; then
    log "cannot record backup-last-success; refusing to commit the attempt as successful"
    return 1
  fi
  if ! printf '%s\n' \
      "attempt_id=${attempt_id}" \
      "attempted_at=${attempted_at}" \
      "object_key=${object_key}" \
      "outcome=success" \
      "stage=record" \
      "category=none" | write_state backup-last-attempt; then
    log "cannot record the terminal attempt state; in-progress evidence is retained"
    return 1
  fi
  if ! printf '%s\n' "$completed_at" | write_state last-backup; then
    log "state publish warning: could not publish last-backup; committed attempt stands"
  fi
  return 0
}

cleanup_work() {
  if [ -n "$work_dir" ]; then
    rm -rf "$work_dir"
    work_dir=""
  fi
}

process_group() {
  # The process group of $1. /proc is the portable source on Linux (the
  # production image has no ps(1)); ps is the fallback for development hosts.
  # The comm field can contain spaces and parentheses, so parse after its
  # closing bracket: the remaining fields are state, ppid, pgrp.
  if [ -r "/proc/$1/stat" ]; then
    sed 's/.*) //' "/proc/$1/stat" 2>/dev/null | cut -d' ' -f3
  elif command -v ps >/dev/null 2>&1; then
    ps -o pgid= -p "$1" 2>/dev/null | tr -d ' '
  fi
}

supervisor_group() {
  # The supervisor's process group, and only when it is provably not this
  # shell's: signalling our own group would kill the backup itself. When the
  # group cannot be established the caller falls back to the supervisor PID,
  # whose own handler terminates its children.
  [ -n "$supervisor_pid" ] || return 1
  pgid="$(process_group "$supervisor_pid")"
  case "$pgid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  [ "$pgid" = "$self_group" ] && return 1
  printf '%s' "$pgid"
}

signal_pipeline() {
  # signal_pipeline SIGNAL -- to the process group when one is established,
  # which reaches pg_dump, gzip and anything they spawned.
  if [ -n "$group" ]; then
    kill "-$1" "-${group}" 2>/dev/null || true
    return 0
  fi
  # No process group (a host without setsid): the supervisor's handler would
  # normally stop its children, but an escalation to KILL leaves it no chance
  # to run, so the children are signalled directly through the pids it
  # recorded. Recorded pids, never a pattern match: nothing outside this
  # attempt can be signalled by accident.
  # Children before the supervisor: reaping the supervisor first lets the
  # caller race ahead and clear the work directory, and the recorded pids would
  # be gone before they could be signalled. Stopping the children also lets a
  # healthy supervisor finish its own cleanup on its own.
  for pid_file in "${work_dir}/dump.pid" "${work_dir}/gzip.pid"; do
    [ -f "$pid_file" ] || continue
    child="$(cat "$pid_file" 2>/dev/null)"
    case "$child" in
      ''|*[!0-9]*) continue ;;
    esac
    kill "-$1" "$child" 2>/dev/null || true
  done
  kill "-$1" "$supervisor_pid" 2>/dev/null || true
}

terminate_pipeline() {
  # Terminate the whole dump pipeline and reap it. The process group carries
  # pg_dump, gzip and anything they spawned.
  #
  # The grace period is a polling deadline in this shell, not a background
  # timer. A timer would be one more process to own, signal and reap -- and the
  # previous one left its sleep(1) orphaned when it was cancelled. Polling the
  # marker the supervisor writes on every exit path costs nothing, cannot be
  # orphaned, and never blocks longer than the deadline.
  [ -n "$supervisor_pid" ] || return 0
  if ! group="$(supervisor_group)"; then
    group=""
  fi
  signal_pipeline TERM
  waited=0
  while [ "$waited" -lt "$KILL_AFTER_SECONDS" ]; do
    [ -f "${work_dir}/supervisor.done" ] && break
    sleep 1
    waited=$((waited + 1))
  done
  if [ ! -f "${work_dir}/supervisor.done" ]; then
    log "dump pipeline ignored TERM for ${KILL_AFTER_SECONDS}s; escalating to KILL"
    signal_pipeline KILL
  fi
  # Every process signalled above is this attempt's own child or a member of
  # its process group, so this reaps exactly what it owns.
  wait "$supervisor_pid" 2>/dev/null || true
  if [ -n "$group" ]; then
    kill -KILL "-${group}" 2>/dev/null || true
  fi
  supervisor_pid=""
  group=""
}

on_signal() {
  # $1 = exit status to use (130 INT, 143 TERM). During the launch window the
  # signal is recorded instead of acted on, so it can never race the assignment
  # that makes the child killable.
  if [ "$launching" -eq 1 ]; then
    pending_signal="$1"
    return 0
  fi
  # Ignore further INT/TERM outright while cleaning up: re-entering this handler
  # could interrupt failure publication or the lock release.
  trap '' INT TERM
  terminate_pipeline
  if [ "$attempt_open" -eq 1 ]; then
    stage="${stage}"
    if record_failure interrupted "$1"; then
      attempt_open=0
      clear_in_progress
    fi
  fi
  release_lock
  cleanup_work
  exit "$1"
}

trap 'on_signal 130' INT
trap 'on_signal 143' TERM
trap 'release_lock; cleanup_work' EXIT

attempt_fail() {
  fail_category="$1"
  fail_status="$2"
  return 1
}

run_pipeline() {
  # One supervisor owns pg_dump | gzip through a FIFO. Job control puts it in
  # its own process group, so the group can be signalled without touching this
  # shell. The supervisor writes the pipeline's exit statuses for the caller.
  cat >"${work_dir}/pipeline.sh" <<'PIPELINE'
#!/bin/sh
set -u
work="$1"
dump_pid=""
gzip_pid=""
announce_exit() {
  # The parent polls for this instead of blocking in wait(), so it can bound
  # how long a stuck pipeline delays cleanup without forking a timer that
  # would itself need owning and reaping.
  printf '%s\n' "$1" >"$work/supervisor.done" 2>/dev/null || true
}
supervisor_cleanup() {
  trap '' INT TERM
  [ -n "$dump_pid" ] && kill -TERM "$dump_pid" 2>/dev/null
  [ -n "$gzip_pid" ] && kill -TERM "$gzip_pid" 2>/dev/null
  [ -n "$dump_pid" ] && wait "$dump_pid" 2>/dev/null
  [ -n "$gzip_pid" ] && wait "$gzip_pid" 2>/dev/null
  announce_exit interrupted
  exit 143
}
trap supervisor_cleanup INT TERM
gzip -9 <"$work/dump.fifo" >"$work/archive.sql.gz" 2>"$work/gzip.err" &
gzip_pid=$!
printf '%s\n' "$gzip_pid" >"$work/gzip.pid"
pg_dump --host="$POSTGRES_HOST" --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
  --clean --if-exists --no-owner --no-acl >"$work/dump.fifo" 2>"$work/dump.err" &
dump_pid=$!
printf '%s\n' "$dump_pid" >"$work/dump.pid"
wait "$dump_pid"
dump_status=$?
wait "$gzip_pid"
gzip_status=$?
printf '%s %s\n' "$dump_status" "$gzip_status" >"$work/pipeline.status"
announce_exit complete
PIPELINE
  # pg_dump reads the password from the environment, never from a command line
  # or a state file.
  PGPASSWORD="$POSTGRES_PASSWORD"
  export PGPASSWORD
  launching=1
  # setsid makes the supervisor a session (and process group) leader, so its
  # pid IS its pgid and one signal reaches pg_dump, gzip and anything they
  # spawn. It is never a fork here -- a shell's background child is not a
  # process group leader, which is the only case where setsid(1) forks -- so
  # $! remains the supervisor and wait still reaps it. dash's `set -m` does not
  # create process groups for background jobs, so it is not an alternative.
  # Without setsid (development hosts) the supervisor's own handler still
  # terminates its direct children; only their descendants can outlive it.
  # The lock descriptor is closed in the child: an inherited copy would keep the
  # flock held for as long as any descendant lives, so one leaked process could
  # block every future backup -- exactly the deadlock the kernel lock exists to
  # avoid.
  if command -v setsid >/dev/null 2>&1; then
    eval "setsid sh \"\${work_dir}/pipeline.sh\" \"\$work_dir\" ${lock_fd}>&- &"
  else
    eval "sh \"\${work_dir}/pipeline.sh\" \"\$work_dir\" ${lock_fd}>&- &"
  fi
  supervisor_pid=$!
  launching=0
  unset PGPASSWORD
  if [ -n "$pending_signal" ]; then
    signal="$pending_signal"
    pending_signal=""
    on_signal "$signal"
  fi
  wait "$supervisor_pid"
  supervisor_pid=""
}

run_attempt() {
  stage=configure
  for name in POSTGRES_HOST POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD BACKUP_BUCKET AWS_REGION; do
    eval "value=\${$name:-}"
    if [ -z "$value" ]; then
      log "required configuration ${name} is missing"
      attempt_fail configuration_missing 2
      return 1
    fi
  done
  case "$MIN_BYTES" in
    ''|*[!0-9]*)
      log "BACKUP_MIN_BYTES must be a non-negative integer"
      attempt_fail configuration_invalid 2
      return 1
      ;;
  esac
  if ! work_dir="$(mktemp -d "${WORK_ROOT}/backup.XXXXXX" 2>/dev/null)"; then
    work_dir=""
    attempt_fail workdir_unwritable 1
    return 1
  fi
  archive="${work_dir}/archive.sql.gz"

  stage=dump
  if ! mkfifo "${work_dir}/dump.fifo" 2>"${work_dir}/mkfifo.err"; then
    attempt_fail dump_failed 1
    return 1
  fi
  run_pipeline
  if [ ! -f "${work_dir}/pipeline.status" ]; then
    log_error_excerpt "${work_dir}/dump.err"
    attempt_fail dump_failed 1
    return 1
  fi
  read -r dump_status gzip_status <"${work_dir}/pipeline.status"
  if [ "$dump_status" != 0 ]; then
    log_error_excerpt "${work_dir}/dump.err"
    attempt_fail dump_failed "$dump_status"
    return 1
  fi
  stage=compress
  if [ "$gzip_status" != 0 ]; then
    log_error_excerpt "${work_dir}/gzip.err"
    attempt_fail compression_failed "$gzip_status"
    return 1
  fi

  stage=validate
  if ! gzip -t "$archive" 2>"${work_dir}/gzip-test.err"; then
    log_error_excerpt "${work_dir}/gzip-test.err"
    attempt_fail archive_unreadable 1
    return 1
  fi
  size="$(wc -c <"$archive" | tr -d ' ')"
  case "$size" in
    ''|*[!0-9]*) size=0 ;;
  esac
  if [ "$size" -lt "$MIN_BYTES" ]; then
    log "archive is ${size} bytes; minimum is ${MIN_BYTES}"
    attempt_fail archive_too_small 1
    return 1
  fi
  if ! gzip -dc "$archive" 2>/dev/null | head -c 65536 | grep -q 'PostgreSQL database dump'; then
    attempt_fail archive_content_invalid 1
    return 1
  fi
  if ! gzip -dc "$archive" 2>/dev/null | tail -c 4096 | grep -q 'PostgreSQL database dump complete'; then
    log "archive lacks the pg_dump completion marker; treating as truncated"
    attempt_fail archive_content_invalid 1
    return 1
  fi

  stage=checksum
  sha256="$(digest_file "$archive" 2>/dev/null || true)"
  if [ "${#sha256}" -ne 64 ]; then
    attempt_fail checksum_failed 1
    return 1
  fi
  expected_checksum="$(digest_file_base64 "$archive" 2>/dev/null || true)"
  if [ -z "$expected_checksum" ]; then
    attempt_fail checksum_failed 1
    return 1
  fi

  stage=upload
  # put-object (not `s3 cp`) because it returns the VersionId and the checksum
  # S3 computed, which is what binds this attempt to one immutable object.
  if ! aws s3api put-object --bucket "$BACKUP_BUCKET" --key "$object_key" \
      --body "$archive" --region "$AWS_REGION" --server-side-encryption AES256 \
      --checksum-algorithm SHA256 --metadata "sha256=${sha256}" \
      --query '[VersionId,ChecksumSHA256]' --output text \
      >"${work_dir}/upload.out" 2>"${work_dir}/upload.err"; then
    log_error_excerpt "${work_dir}/upload.err"
    attempt_fail upload_failed 1
    return 1
  fi
  read -r version_id upload_checksum <"${work_dir}/upload.out"
  case "${version_id:-}" in
    ''|None|null)
      log "upload returned no object version; the bucket must have versioning enabled"
      version_id=""
      attempt_fail upload_unversioned 1
      return 1
      ;;
  esac
  if [ "${upload_checksum:-}" != "$expected_checksum" ]; then
    log "upload checksum does not match the archive"
    attempt_fail upload_checksum_mismatch 1
    return 1
  fi

  stage=verify_upload
  # Re-read the exact version just written. A concurrent writer replacing the
  # key produces a different VersionId, so it cannot satisfy this check.
  if ! aws s3api head-object --bucket "$BACKUP_BUCKET" --key "$object_key" \
      --version-id "$version_id" --checksum-mode ENABLED --region "$AWS_REGION" \
      --query '[ContentLength,ChecksumSHA256,Metadata.sha256]' --output text \
      >"${work_dir}/head.out" 2>"${work_dir}/head.err"; then
    log_error_excerpt "${work_dir}/head.err"
    attempt_fail upload_unverified 1
    return 1
  fi
  read -r remote_size remote_checksum remote_sha <"${work_dir}/head.out"
  if [ "${remote_size:-}" != "$size" ] \
     || [ "${remote_checksum:-}" != "$expected_checksum" ] \
     || [ "${remote_sha:-}" != "$sha256" ]; then
    log "stored object version does not match the archive that was uploaded"
    attempt_fail upload_checksum_mismatch 1
    return 1
  fi

  stage=record
  archive_sha256="$sha256"
  archive_size="$size"
  return 0
}

backup_once() {
  attempt_id=""
  version_id=""
  fail_category=""
  fail_status=0
  if ! preflight; then
    log "backup aborted before any work: preconditions are not met"
    return "$EXIT_PRECONDITION"
  fi
  acquire_lock
  lock_outcome=$?
  if [ "$lock_outcome" -eq "$EXIT_CONTENDED" ]; then
    log "another backup holds the attempt lock; skipping this attempt"
    return "$EXIT_CONTENDED"
  fi
  if [ "$lock_outcome" -ne 0 ]; then
    log "backup aborted: the attempt lock is not usable"
    return "$EXIT_PRECONDITION"
  fi
  attempted_at="$(date -u +%FT%TZ)"
  if ! attempt_id="$(new_attempt_id)"; then
    release_lock
    return "$EXIT_PRECONDITION"
  fi
  object_key="postgres/$(date -u +%Y%m%dT%H%M%SZ)-${attempt_id}.sql.gz"
  stage=configure
  if ! record_in_progress; then
    log "cannot write backup-in-progress in ${STATE_DIR}; aborting attempt"
    attempt_id=""
    release_lock
    return "$EXIT_PRECONDITION"
  fi
  attempt_open=1

  if run_attempt; then
    if ! record_success "$archive_sha256" "$archive_size"; then
      attempt_open=0
      release_lock
      cleanup_work
      return "$EXIT_FAILED"
    fi
    attempt_open=0
    clear_in_progress
    release_lock
    cleanup_work
    log "backup uploaded: ${object_key} version_id=${version_id} sha256=${archive_sha256} size_bytes=${archive_size}"
    return 0
  fi

  if record_failure "$fail_category" "$fail_status"; then
    attempt_open=0
    clear_in_progress
  fi
  release_lock
  cleanup_work
  return "$EXIT_FAILED"
}

if [ "${1:-once}" = "loop" ]; then
  while :; do
    backup_once
    status=$?
    case "$status" in
      0) ;;
      "$EXIT_CONTENDED") log "another attempt is running; this cycle was skipped" ;;
      *) log "next attempt in ${INTERVAL} seconds; the failed attempt was not marked successful" ;;
    esac
    eval "sleep \"\$INTERVAL\" ${lock_fd}>&- &"
    sleep_pid=$!
    wait "$sleep_pid"
  done
else
  backup_once
fi
