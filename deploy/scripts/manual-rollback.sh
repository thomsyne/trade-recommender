#!/bin/bash
set -Eeuo pipefail
: "${ROLLBACK_SHA:?A rollback image SHA is required}"
: "${PUBLIC_HOSTNAME:?}" "${ACME_EMAIL:?}"
[[ "$ROLLBACK_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "image_sha must be a full commit SHA" >&2; exit 2; }

account_id="$(aws sts get-caller-identity --query Account --output text)"
export IMAGE_URI="${account_id}.dkr.ecr.${AWS_REGION}.amazonaws.com/trade-recommender:${ROLLBACK_SHA}"
export BACKUP_BUCKET="trade-recommender-${account_id}-backups"
export ENV_PARAMETER="/trade-recommender/production-env"
export INSTANCE_ID="$(aws ec2 describe-instances --filters Name=tag:Application,Values=trade-recommender Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text --region "$AWS_REGION")"
elastic_ip="$(aws ec2 describe-addresses --filters Name=tag:Application,Values=trade-recommender --query 'Addresses[0].PublicIp' --output text --region "$AWS_REGION")"
export EXPECTED_IP="$elastic_ip"
export PUBLIC_HOST="$PUBLIC_HOSTNAME"
deploy/scripts/send-deployment.sh
