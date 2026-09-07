#!/bin/sh
# Isolated restore verification for one backup archive.
#
# Restores a `postgres/<timestamp>.sql.gz` archive (local path or s3:// URI)
# into an explicitly named DISPOSABLE database and verifies schema, migration
# state, representative constraints, triggers and append-only behaviour. It
# refuses any database name that is not clearly disposable and never touches
# production. Connection details come from the standard libpq environment
# (PGHOST, PGPORT, PGUSER, PGPASSWORD); the target name comes from
# RESTORE_CHECK_DB and must contain "restore_check".
#
#   RESTORE_CHECK_DB=phase1_restore_check_20260907 \
#     deploy/scripts/restore-check.sh [--recreate] [--drop-after] \
#     [--expect-sha256 HEX] [--expect-migration app:name] ARCHIVE
#
# Exit status 0 = PASSED, 1 = FAILED (stage and category printed), 2 = usage.
set -u

recreate=0
drop_after=0
expect_sha256=""
expect_migration=""
archive=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --recreate) recreate=1 ;;
    --drop-after) drop_after=1 ;;
    --expect-sha256) shift; expect_sha256="${1:-}" ;;
    --expect-migration) shift; expect_migration="${1:-}" ;;
    -h|--help)
      sed -n '2,20p' "$0" >&2
      exit 2
      ;;
    -*) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
    *) archive="$1" ;;
  esac
  shift
done

fail() {
  # fail STAGE CATEGORY
  printf 'restore check FAILED at %s: %s (database=%s)\n' "$1" "$2" "${RESTORE_CHECK_DB:-unset}" >&2
  exit 1
}

stage=configure
target="${RESTORE_CHECK_DB:-}"
[ -n "$archive" ] || { printf 'archive path or s3:// URI is required\n' >&2; exit 2; }
[ -n "$target" ] || { printf 'RESTORE_CHECK_DB is required\n' >&2; exit 2; }
case "$target" in
  *restore_check*) ;;
  *) fail "$stage" "database name must contain 'restore_check' to be treated as disposable" ;;
esac
case "$target" in
  ''|*[!a-z0-9_]*|[!a-z]*) fail "$stage" "database name must match ^[a-z][a-z0-9_]*$" ;;
esac
for protected in trade_recommender trade_recommender_research trade_recommender_baseline postgres template0 template1; do
  [ "$target" != "$protected" ] || fail "$stage" "refusing protected database name"
done
for tool in psql createdb gzip; do
  command -v "$tool" >/dev/null 2>&1 || fail "$stage" "missing tool: ${tool}"
done

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/restore-check.XXXXXX")" || fail "$stage" "workdir_unwritable"
trap 'rm -rf "$work_dir"' EXIT INT TERM

digest_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    openssl dgst -sha256 "$1" | sed 's/^.*= //'
  fi
}

stage=fetch
case "$archive" in
  s3://*)
    command -v aws >/dev/null 2>&1 || fail "$stage" "aws cli is required for s3 archives"
    local_archive="${work_dir}/archive.sql.gz"
    aws s3 cp "$archive" "$local_archive" --only-show-errors ${AWS_REGION:+--region "$AWS_REGION"} \
      || fail "$stage" "download_failed"
    ;;
  *)
    [ -f "$archive" ] || fail "$stage" "archive not found"
    local_archive="$archive"
    ;;
esac

stage=validate
gzip -t "$local_archive" 2>/dev/null || fail "$stage" "archive_unreadable"
sha256="$(digest_file "$local_archive")"
[ "${#sha256}" -eq 64 ] || fail "$stage" "checksum_failed"
if [ -n "$expect_sha256" ] && [ "$sha256" != "$expect_sha256" ]; then
  fail "$stage" "checksum_mismatch"
fi
gzip -dc "$local_archive" 2>/dev/null | head -c 65536 | grep -q 'PostgreSQL database dump' \
  || fail "$stage" "archive_content_invalid"
gzip -dc "$local_archive" 2>/dev/null | tail -c 4096 | grep -q 'PostgreSQL database dump complete' \
  || fail "$stage" "archive_truncated"

stage=prepare
exists="$(psql -At -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '${target}'" 2>"${work_dir}/psql.err")" \
  || { head -c 2000 "${work_dir}/psql.err" >&2; fail "$stage" "cannot query server"; }
if [ "$exists" = 1 ]; then
  [ "$recreate" -eq 1 ] || fail "$stage" "database already exists; pass --recreate to replace the disposable copy"
  dropdb "$target" || fail "$stage" "drop_failed"
fi
createdb "$target" || fail "$stage" "create_failed"

stage=restore
{
  gzip -dc "$local_archive"
  printf '%s' "$?" >"${work_dir}/gzip.status"
} | psql -q -v ON_ERROR_STOP=1 --single-transaction -d "$target" >"${work_dir}/restore.out" 2>"${work_dir}/restore.err"
psql_status=$?
gzip_status="$(cat "${work_dir}/gzip.status" 2>/dev/null || printf missing)"
if [ "$gzip_status" != 0 ]; then
  fail "$stage" "decompression_failed"
fi
if [ "$psql_status" != 0 ]; then
  printf 'restore stderr (bounded):\n' >&2
  head -c 2000 "${work_dir}/restore.err" >&2
  printf '\n' >&2
  fail "$stage" "psql_failed"
fi

stage=verify
cat >"${work_dir}/verify.sql" <<'SQL'
\set ON_ERROR_STOP on
SELECT count(*) AS tables FROM information_schema.tables
 WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' \gset
SELECT count(*) AS migrations FROM django_migrations \gset
SELECT coalesce(max(name), '') AS latest_market FROM django_migrations WHERE app = 'market' \gset
SELECT coalesce(max(name), '') AS latest_operations FROM django_migrations WHERE app = 'operations' \gset
SELECT coalesce(max(name), '') AS latest_forecasts FROM django_migrations WHERE app = 'forecasts' \gset
DO $$
DECLARE
  missing text[] := ARRAY[]::text[];
  item text;
  phase1 boolean;
  probe_id bigint;
  mutated boolean := false;
BEGIN
  FOREACH item IN ARRAY ARRAY['market_candle','market_auditevent','market_technicalsnapshot',
      'market_ingestionrun','operations_joboccurrence','operations_scheduledjob',
      'forecasts_recommendation','forecasts_recommendationresolution','django_migrations'] LOOP
    IF to_regclass(item) IS NULL THEN missing := missing || item; END IF;
  END LOOP;
  IF array_length(missing, 1) IS NOT NULL THEN
    RAISE EXCEPTION 'missing tables: %', array_to_string(missing, ',');
  END IF;
  FOREACH item IN ARRAY ARRAY['unique_legacy_market_candle','candle_bid_not_above_ask',
      'stored_candles_complete','forecast_probabilities_sum_one'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = item)
       AND NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = item) THEN
      missing := missing || item;
    END IF;
  END LOOP;
  IF array_length(missing, 1) IS NOT NULL THEN
    RAISE EXCEPTION 'missing constraints: %', array_to_string(missing, ',');
  END IF;
  FOREACH item IN ARRAY ARRAY['market_auditevent_append_only','market_governed_candle_append_only'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = item AND NOT tgisinternal) THEN
      missing := missing || item;
    END IF;
  END LOOP;
  phase1 := EXISTS (SELECT 1 FROM django_migrations WHERE app = 'market'
                    AND name = '0028_live_candle_observation_identity');
  IF phase1 THEN
    FOREACH item IN ARRAY ARRAY['market_live_candle_protect','market_technicalsnapshot_protect',
        'market_candleobservation_append_only'] LOOP
      IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = item AND NOT tgisinternal) THEN
        missing := missing || item;
      END IF;
    END LOOP;
  END IF;
  IF array_length(missing, 1) IS NOT NULL THEN
    RAISE EXCEPTION 'missing triggers: %', array_to_string(missing, ',');
  END IF;
  -- Functional probe: the restored append-only trigger must reject an update.
  INSERT INTO market_auditevent (occurred_at, event_type, actor, subject_type, subject_id, payload)
    VALUES (now(), 'restore_check.probe', 'restore-check', 'RestoreCheck', 'probe', '{}'::jsonb)
    RETURNING id INTO probe_id;
  BEGIN
    UPDATE market_auditevent SET actor = 'mutated' WHERE id = probe_id;
    mutated := true;
  EXCEPTION WHEN OTHERS THEN
    mutated := false;
  END;
  IF mutated THEN
    RAISE EXCEPTION 'append-only audit trigger did not fire after restore';
  END IF;
  RAISE NOTICE 'restore check probe: append-only trigger enforced';
END $$;
SELECT (SELECT count(*) FROM market_candle) AS candles,
       (SELECT count(*) FROM market_auditevent) AS audit_events,
       (SELECT count(*) FROM forecasts_recommendation) AS recommendations,
       (SELECT count(*) FROM operations_joboccurrence) AS occurrences \gset
\echo tables=:tables migrations=:migrations latest_market=:latest_market latest_operations=:latest_operations latest_forecasts=:latest_forecasts candles=:candles audit_events=:audit_events recommendations=:recommendations occurrences=:occurrences
SQL
# The probe insert is rolled back: the whole verification runs in one transaction.
{
  printf 'BEGIN;\n'
  cat "${work_dir}/verify.sql"
  printf 'ROLLBACK;\n'
} >"${work_dir}/verify-wrapped.sql"
psql -q -v ON_ERROR_STOP=1 -d "$target" -f "${work_dir}/verify-wrapped.sql" >"${work_dir}/verify.out" 2>"${work_dir}/verify.err"
verify_status=$?
if [ "$verify_status" != 0 ]; then
  printf 'verification stderr (bounded):\n' >&2
  head -c 2000 "${work_dir}/verify.err" >&2
  printf '\n' >&2
  fail "$stage" "schema_or_integrity_check_failed"
fi
summary="$(grep '^tables=' "${work_dir}/verify.out" | tail -1)"
[ -n "$summary" ] || fail "$stage" "no verification summary"
if [ -n "$expect_migration" ]; then
  app="${expect_migration%%:*}"
  name="${expect_migration#*:}"
  applied="$(psql -At -d "$target" -c "SELECT 1 FROM django_migrations WHERE app = '${app}' AND name = '${name}'")"
  [ "$applied" = 1 ] || fail "$stage" "expected migration ${expect_migration} is not applied"
fi

if [ "$drop_after" -eq 1 ]; then
  stage=cleanup
  dropdb "$target" || fail "$stage" "drop_failed"
fi
printf 'restore check PASSED database=%s archive_sha256=%s %s%s\n' "$target" "$sha256" "$summary" \
  "$([ "$drop_after" -eq 1 ] && printf ' dropped=yes' || printf ' dropped=no')"
