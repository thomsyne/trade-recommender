#!/bin/sh
# Keep the CI entry point; all process and fault injection is Python-native.
exec python3 "$(dirname "$0")/test_backup.py" "$@"
