#!/bin/bash
set -Eeuo pipefail

: "${BACKUP_BUCKET:?Backup bucket name is required}"

head_error="$(mktemp)"
trap 'rm -f "$head_error"' EXIT INT TERM

if aws s3api head-bucket --bucket "$BACKUP_BUCKET" 2>"$head_error"; then
  state_resources="$(terraform -chdir=infra state list)"
  if grep -Fxq "aws_s3_bucket.backups" <<< "$state_resources"; then
    resource_state="$(terraform -chdir=infra state show aws_s3_bucket.backups)"
    if head -n 1 <<< "$resource_state" | grep -Fq "(tainted)"; then
      echo "Clearing partial-create taint from the existing backup bucket"
      terraform -chdir=infra untaint aws_s3_bucket.backups
    fi
  else
    echo "Importing existing backup bucket into Terraform state"
    terraform -chdir=infra import -input=false aws_s3_bucket.backups "$BACKUP_BUCKET"
  fi
elif ! grep -Eq '\(404\)|Not Found' "$head_error"; then
  cat "$head_error" >&2
  exit 1
fi
