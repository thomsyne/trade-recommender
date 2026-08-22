#!/bin/bash
set -Eeuo pipefail

script="deploy/scripts/remote-deploy.sh"
stop_line="$(awk '/stop worker scheduler/ { print NR; exit }' "$script")"
migrate_line="$(awk '/python manage.py migrate --noinput/ { print NR; exit }' "$script")"
seed_line="$(awk '/python manage.py seed_canonical/ { print NR; exit }' "$script")"
services_line="$(awk '/up -d --remove-orphans/ { print NR; exit }' "$script")"

if [ -z "$stop_line" ] || [ -z "$migrate_line" ] || [ -z "$seed_line" ] || [ -z "$services_line" ]; then
  echo "remote deployment must stop workers, migrate, seed canonical data, and restart services" >&2
  exit 1
fi
if [ "$stop_line" -ge "$migrate_line" ] || [ "$migrate_line" -ge "$seed_line" ] || [ "$seed_line" -ge "$services_line" ]; then
  echo "remote deployment must stop workers before migrations and seed before restarting services" >&2
  exit 1
fi

echo "remote canonical bootstrap invocation test passed"
