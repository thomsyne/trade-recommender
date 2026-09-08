#!/bin/sh
# Compatibility entry point used by Compose and deployment scripts.
exec python3 "$(dirname "$0")/backup.py" "$@"
