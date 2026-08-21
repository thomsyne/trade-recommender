#!/bin/sh
set -eu

backup_once() {
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  key="postgres/${timestamp}.sql.gz"
  temporary="$(mktemp)"
  trap 'rm -f "$temporary"' EXIT INT TERM
  PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --host="$POSTGRES_HOST" --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
    --clean --if-exists --no-owner --no-acl | gzip -9 > "$temporary"
  aws s3 cp "$temporary" "s3://${BACKUP_BUCKET}/${key}" \
    --region "$AWS_REGION" --sse AES256 --only-show-errors
  date -u +%FT%TZ > /var/lib/trade-recommender/last-backup
  rm -f "$temporary"
  trap - EXIT INT TERM
  echo "backup uploaded: ${key}"
}

if [ "${1:-once}" = "loop" ]; then
  while true; do
    backup_once || true
    sleep 21600
  done
else
  backup_once
fi
