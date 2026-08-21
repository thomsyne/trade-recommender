#!/bin/bash
set -Eeuo pipefail
: "${INSTANCE_ID:?}" "${PUBLIC_HOST:?}" "${EXPECTED_IP:?}" "${ACME_EMAIL:?}" "${BACKUP_BUCKET:?}" "${ENV_PARAMETER:?}" "${IMAGE_URI:?}" "${AWS_REGION:?}"

aws s3 cp deploy/compose.production.yaml "s3://${BACKUP_BUCKET}/deployment/compose.production.yaml" --region "$AWS_REGION" --sse AES256 --only-show-errors
aws s3 cp deploy/Caddyfile "s3://${BACKUP_BUCKET}/deployment/Caddyfile" --region "$AWS_REGION" --sse AES256 --only-show-errors
aws s3 cp deploy/scripts/restore.sh "s3://${BACKUP_BUCKET}/deployment/restore.sh" --region "$AWS_REGION" --sse AES256 --only-show-errors
aws s3 cp deploy/scripts/remote-deploy.sh "s3://${BACKUP_BUCKET}/deployment/remote-deploy.sh" --region "$AWS_REGION" --sse AES256 --only-show-errors

dns_ready=false
for _ in $(seq 1 60); do
  if getent ahostsv4 "$PUBLIC_HOST" | awk -v expected="$EXPECTED_IP" '$1 == expected { found = 1 } END { exit !found }'; then
    dns_ready=true
    break
  fi
  sleep 10
done
[ "$dns_ready" = true ] || { echo "$PUBLIC_HOST did not resolve to $EXPECTED_IP within 10 minutes" >&2; exit 1; }

for _ in $(seq 1 30); do
  ping="$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=${INSTANCE_ID}" --query 'InstanceInformationList[0].PingStatus' --output text --region "$AWS_REGION")"
  [ "$ping" = "Online" ] && break
  sleep 10
done
[ "${ping:-}" = "Online" ] || { echo "instance did not become available in SSM" >&2; exit 1; }

python3 - <<'PY'
import json, os, shlex
values = {key: os.environ[key] for key in ("IMAGE_URI", "PUBLIC_HOST", "EXPECTED_IP", "ACME_EMAIL", "BACKUP_BUCKET", "ENV_PARAMETER", "AWS_REGION")}
exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in values.items())
command = f"aws s3 cp s3://{values['BACKUP_BUCKET']}/deployment/remote-deploy.sh /tmp/remote-deploy.sh --region {values['AWS_REGION']} --only-show-errors && chmod 700 /tmp/remote-deploy.sh && {exports} /tmp/remote-deploy.sh"
with open("ssm-command.json", "w") as stream:
    json.dump({"DocumentName": "AWS-RunShellScript", "InstanceIds": [os.environ["INSTANCE_ID"]], "Parameters": {"commands": [command]}, "TimeoutSeconds": 900}, stream)
PY
command_id="$(aws ssm send-command --cli-input-json file://ssm-command.json --region "$AWS_REGION" --query Command.CommandId --output text)"
rm -f ssm-command.json
for _ in $(seq 1 90); do
  status="$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$INSTANCE_ID" --region "$AWS_REGION" --query Status --output text 2>/dev/null || true)"
  case "$status" in
    Success|Cancelled|TimedOut|Failed|Cancelling) break ;;
  esac
  sleep 10
done
aws ssm get-command-invocation --command-id "$command_id" --instance-id "$INSTANCE_ID" --region "$AWS_REGION" --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}'
[ "$status" = "Success" ]
