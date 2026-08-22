#!/bin/bash
set -Eeuo pipefail

rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT

APP_ENV_FILE=production.env.example docker compose \
  --env-file deploy/production.env.example \
  -f deploy/compose.production.yaml config --format json >"$rendered"

python3 - "$rendered" <<'PY'
import json
import sys

with open(sys.argv[1]) as stream:
    config = json.load(stream)

actual = config["services"]["web"]["healthcheck"]["test"]
expected = [
    "CMD",
    "curl",
    "--fail",
    "--silent",
    "--header",
    "Host: fx-forecast.thomsyne.dev",
    "--header",
    "X-Forwarded-Proto: https",
    "http://localhost:8000/health/ready/",
]
if actual != expected:
    raise SystemExit(
        "production web healthcheck must send the allowed public Host and HTTPS proxy headers\n"
        f"expected: {expected!r}\n"
        f"actual:   {actual!r}"
    )
PY

echo "production Compose healthcheck test passed"
