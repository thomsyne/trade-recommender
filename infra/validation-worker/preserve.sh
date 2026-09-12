#!/usr/bin/env bash
set -euo pipefail
umask 077
root=/var/lib/phase55/work/.candidate-data/phase55-v1
stamp=$(date -u +%Y%m%dT%H%M%SZ)
archive="/var/lib/phase55/development-$stamp.tar.gz"
# This service runs only after all scientific processes have stopped. The root
# volume is retained even if transfer fails. A timeout/failure is never a pass.
systemctl show phase55-batch.service -p Result -p ExecMainStatus -p ExecMainStartTimestamp -p ExecMainExitTimestamp > "$root/service-result.txt"
tar --exclude=acquisition.sqlite3 -czf "$archive" -C "$root" .
sha256sum "$archive" > "$archive.sha256"
aws s3 cp --only-show-errors "$archive" "s3://$PHASE55_BUCKET/outputs/$stamp/development.tar.gz"
aws s3 cp --only-show-errors "$archive.sha256" "s3://$PHASE55_BUCKET/outputs/$stamp/development.tar.gz.sha256"
sync
# Successful preservation, not scientific acceptance. Storage remains billable.
systemctl poweroff
