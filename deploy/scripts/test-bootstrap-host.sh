#!/bin/bash
set -Eeuo pipefail

bootstrap="$(cd "$(dirname "$0")" && pwd)/bootstrap-host.sh"
temporary="$(mktemp -d)"
trap 'rm -rf "$temporary"' EXIT INT TERM

write_stub() {
  name="$1"
  shift
  cat >"$MOCK_BIN/$name"
  chmod 755 "$MOCK_BIN/$name"
}

prepare_case() {
  case_name="$1"
  export CASE_ROOT="$temporary/$case_name"
  export MOCK_BIN="$CASE_ROOT/bin"
  export CALLS="$CASE_ROOT/calls"
  mkdir -p "$MOCK_BIN" "$CASE_ROOT/etc"
  : >"$CALLS"
  printf 'ID=amzn\nVERSION_ID=2023\n' >"$CASE_ROOT/etc/os-release"

  write_stub aws <<'EOF'
#!/bin/bash
echo "aws $*" >>"$CALLS"
EOF
  write_stub curl <<'EOF'
#!/bin/bash
echo "curl $*" >>"$CALLS"
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then
    shift
    printf 'compose-test-binary\n' >"$1"
    exit
  fi
  shift
done
EOF
  write_stub systemctl <<'EOF'
#!/bin/bash
echo "systemctl $*" >>"$CALLS"
exit 0
EOF
  write_stub dnf <<'EOF'
#!/bin/bash
echo "dnf $*" >>"$CALLS"
if [[ " $* " = *" docker "* ]]; then
  cp "$DOCKER_STUB" "$MOCK_BIN/docker"
  chmod 755 "$MOCK_BIN/docker"
fi
EOF
  for command in getent usermod sshd journalctl; do
    write_stub "$command" <<'EOF'
#!/bin/bash
echo "called $(basename "$0") $*" >>"$CALLS"
exit 0
EOF
  done
  write_stub uname <<'EOF'
#!/bin/bash
echo aarch64
EOF
  write_stub sha256sum <<'EOF'
#!/bin/bash
cat >/dev/null
exit 0
EOF

  export DOCKER_STUB="$CASE_ROOT/docker-stub"
  cat >"$DOCKER_STUB" <<'EOF'
#!/bin/bash
echo "docker $*" >>"$CALLS"
if [ "${1:-}" = compose ] && [ "${2:-}" = version ] && [ "${3:-}" = --short ]; then
  echo 2.39.2
elif [ "${1:-}" = compose ] && [ "${2:-}" = version ]; then
  echo 'Docker Compose version v2.39.2'
fi
EOF
  chmod 755 "$DOCKER_STUB"
}

run_case() {
  PATH="$MOCK_BIN:/usr/bin:/bin" BOOTSTRAP_ROOT="$CASE_ROOT" \
    BOOTSTRAP_FROM_CLOUD_INIT=1 bash "$bootstrap" >"$CASE_ROOT/output"
  grep -Fq 'host bootstrap 2026-08-22.1 ready' "$CASE_ROOT/output"
  grep -Fq 'systemctl enable --now docker amazon-ssm-agent' "$CALLS"
  grep -Fq 'docker info' "$CALLS"
}

prepare_case missing-docker
run_case
grep -Fq 'dnf install -y docker' "$CALLS"
grep -Fq 'curl --fail --location --silent --show-error' "$CALLS"
! grep -Fq ' curl ' < <(grep '^dnf ' "$CALLS")

prepare_case partial
cp "$DOCKER_STUB" "$MOCK_BIN/docker"
run_case
! grep -q '^dnf ' "$CALLS"
grep -Fq 'curl --fail --location --silent --show-error' "$CALLS"

prepare_case ready
cp "$DOCKER_STUB" "$MOCK_BIN/docker"
mkdir -p "$CASE_ROOT/usr/local/lib/docker/cli-plugins"
cp "$DOCKER_STUB" "$CASE_ROOT/usr/local/lib/docker/cli-plugins/docker-compose"
run_case
! grep -q '^dnf ' "$CALLS"
! grep -q '^curl ' "$CALLS"

prepare_case cloud-init-failed
cp "$DOCKER_STUB" "$MOCK_BIN/docker"
mkdir -p "$CASE_ROOT/usr/local/lib/docker/cli-plugins"
cp "$DOCKER_STUB" "$CASE_ROOT/usr/local/lib/docker/cli-plugins/docker-compose"
write_stub cloud-init <<'EOF'
#!/bin/bash
echo 'status: error'
exit 2
EOF
PATH="$MOCK_BIN:/usr/bin:/bin" BOOTSTRAP_ROOT="$CASE_ROOT" \
  bash "$bootstrap" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"
grep -Fq 'cloud-init did not complete cleanly' "$CASE_ROOT/error"
grep -Fq 'called journalctl --no-pager -u cloud-final.service -n 60' "$CALLS"
grep -Fq 'host bootstrap 2026-08-22.1 ready' "$CASE_ROOT/output"

prepare_case cloud-init-running
write_stub cloud-init <<'EOF'
#!/bin/bash
exit 0
EOF
write_stub timeout <<'EOF'
#!/bin/bash
exit 124
EOF
if PATH="$MOCK_BIN:/usr/bin:/bin" BOOTSTRAP_ROOT="$CASE_ROOT" \
  bash "$bootstrap" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
  echo "bootstrap unexpectedly repaired while cloud-init was still running" >&2
  exit 1
fi
grep -Fq 'cloud-init was still running after five minutes' "$CASE_ROOT/error"
! grep -q '^dnf ' "$CALLS"

scripts="$(dirname "$bootstrap")"
grep -Fq 'docker compose version >/dev/null' "$scripts/remote-deploy.sh"
grep -Fq 'registry_password="$(aws ecr get-login-password' "$scripts/remote-deploy.sh"
! grep -Eq 'get-login-password.*\|[[:space:]]*docker' "$scripts/remote-deploy.sh"
grep -Fq '"/tmp/bootstrap-host.sh"' "$scripts/send-deployment.sh"
grep -Fq 'generated SSM command exceeds the 24,000-byte limit' "$scripts/send-deployment.sh"

echo "host bootstrap simulations passed"
