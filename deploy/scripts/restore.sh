#!/bin/sh
set -eu

if [ "${CONFIRM_RESTORE:-}" != "yes" ] || [ "$#" -ne 1 ]; then
  echo "Usage: CONFIRM_RESTORE=yes $0 s3://bucket/postgres/TIMESTAMP.sql.gz" >&2
  exit 2
fi

cd /opt/trade-recommender
AWS_REGION="$(sed -n 's/^AWS_REGION=//p' .env | tail -1)"
docker compose --env-file .env -f compose.production.yaml stop web worker scheduler backup
aws s3 cp "$1" - --region "$AWS_REGION" --only-show-errors | gunzip | \
  docker compose --env-file .env -f compose.production.yaml exec -T db \
    sh -c 'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --single-transaction'
docker compose --env-file .env -f compose.production.yaml run --rm web python manage.py migrate --noinput
docker compose --env-file .env -f compose.production.yaml up -d
