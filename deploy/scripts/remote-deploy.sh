#!/bin/bash
set -Eeuo pipefail
umask 077

: "${IMAGE_URI:?}" "${PUBLIC_HOST:?}" "${EXPECTED_IP:?}" "${ACME_EMAIL:?}" "${BACKUP_BUCKET:?}" "${ENV_PARAMETER:?}" "${AWS_REGION:?}"
for prerequisite in aws curl docker; do
  command -v "$prerequisite" >/dev/null || {
    echo "missing host prerequisite: $prerequisite" >&2
    exit 1
  }
done
docker info >/dev/null
docker compose version >/dev/null

install -d -m 700 /opt/trade-recommender
cd /opt/trade-recommender
aws s3 cp "s3://${BACKUP_BUCKET}/deployment/compose.production.yaml" . --region "$AWS_REGION" --only-show-errors
aws s3 cp "s3://${BACKUP_BUCKET}/deployment/Caddyfile" . --region "$AWS_REGION" --only-show-errors
aws s3 cp "s3://${BACKUP_BUCKET}/deployment/restore.sh" . --region "$AWS_REGION" --only-show-errors
chmod 700 restore.sh

aws ssm get-parameter --name "$ENV_PARAMETER" --with-decryption \
  --query Parameter.Value --output text --region "$AWS_REGION" > .env.next
cat >> .env.next <<EOF
IMAGE_URI=${IMAGE_URI}
PUBLIC_HOST=${PUBLIC_HOST}
PUBLIC_URL=https://${PUBLIC_HOST}
ACME_EMAIL=${ACME_EMAIL}
DJANGO_SETTINGS_MODULE=config.settings_production
POSTGRES_HOST=db
BACKUP_BUCKET=${BACKUP_BUCKET}
AWS_REGION=${AWS_REGION}
READINESS_BACKUP_MARKER=/var/lib/trade-recommender/last-backup
READINESS_DISK_PATH=/host-root
EOF
mv .env.next .env

registry="${IMAGE_URI%%/*}"
registry_password="$(aws ecr get-login-password --region "$AWS_REGION")"
docker login --username AWS --password-stdin "$registry" <<<"$registry_password"
unset registry_password
docker pull "$IMAGE_URI"
previous="$(cat current-image 2>/dev/null || true)"
docker compose --env-file .env -f compose.production.yaml up -d db
docker compose --env-file .env -f compose.production.yaml run --rm backup /app/deploy/scripts/backup.sh once
docker compose --env-file .env -f compose.production.yaml stop worker scheduler
docker compose --env-file .env -f compose.production.yaml run --rm web python manage.py migrate --noinput
docker compose --env-file .env -f compose.production.yaml run --rm web python manage.py seed_canonical
docker compose --env-file .env -f compose.production.yaml up -d --remove-orphans

healthy=false
for _ in $(seq 1 30); do
  if curl --fail --silent --show-error --resolve "${PUBLIC_HOST}:443:${EXPECTED_IP}" \
    "https://${PUBLIC_HOST}/health/ready/" >/dev/null; then
    healthy=true
    break
  fi
  sleep 10
done
if [ "$healthy" != true ]; then
  if [ -n "$previous" ]; then
    sed -i "s|^IMAGE_URI=.*|IMAGE_URI=${previous}|" .env
    docker pull "$previous"
    docker compose --env-file .env -f compose.production.yaml up -d --remove-orphans
  fi
  echo "deployment failed readiness; previous image restored when available" >&2
  exit 1
fi
printf '%s\n' "$IMAGE_URI" > current-image
docker image prune -f >/dev/null
