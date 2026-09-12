#!/usr/bin/env bash
set -uo pipefail
umask 077
root=/var/lib/phase55/work/.candidate-data/phase55-v1
date -u +%FT%TZ > "$root/started-at.txt"
pids=()
for group in 0 1 2 3; do
    /var/lib/phase55/venv/bin/python -m research.validation_worker --group "$group" \
        > "$root/group-$group.log" 2>&1 &
    pids+=("$!")
done
result=0
for pid in "${pids[@]}"; do
    wait "$pid" || result=1
done
printf '%s\n' "$result" > "$root/workers-exit-status.txt"
date -u +%FT%TZ > "$root/workers-finished-at.txt"
exit "$result"
