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

for name, service in config["services"].items():
    if service.get("privileged"):
        raise SystemExit(f"service {name} must not be privileged")
    for volume in service.get("volumes", []):
        source = volume.get("source", "")
        target = volume.get("target", "")
        if volume.get("type") == "bind":
            if source in {"/", "/var/run/docker.sock"} or target == "/host-root":
                raise SystemExit(f"service {name} must not mount {source} at {target}")
            if "docker.sock" in source:
                raise SystemExit(f"service {name} must not mount the Docker socket")

web_binds = {
    volume["source"]: volume
    for volume in config["services"]["web"].get("volumes", [])
    if volume.get("type") == "bind"
}
health = web_binds.get("/var/lib/trade-recommender/host-health")
if health is None or health.get("target") != "/host-health" or not health.get("read_only"):
    raise SystemExit(
        "web must bind-mount /var/lib/trade-recommender/host-health read-only at /host-health"
    )
if len(web_binds) != 1:
    raise SystemExit(f"web must have exactly one bind mount, found {sorted(web_binds)}")
PY

echo "production Compose healthcheck test passed"
