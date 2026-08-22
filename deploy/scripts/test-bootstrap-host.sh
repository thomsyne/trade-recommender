#!/bin/bash
set -Eeuo pipefail

bootstrap="$(cd "$(dirname "$0")" && pwd)/bootstrap-host.sh"
temporary="$(mktemp -d)"
trap 'rm -rf "$temporary"' EXIT INT TERM

fail() {
  echo "bootstrap test assertion failed: $*" >&2
  if [ -n "${CASE_ROOT:-}" ]; then
    for artifact in output error calls; do
      if [ -s "$CASE_ROOT/$artifact" ]; then
        echo "--- $artifact ---" >&2
        cat "$CASE_ROOT/$artifact" >&2
      fi
    done
  fi
  exit 1
}

assert_contains() {
  needle="$1"
  file="$2"
  grep -Fq -- "$needle" "$file" || fail "expected '$needle' in $file"
}

assert_not_contains() {
  needle="$1"
  file="$2"
  if grep -Fq -- "$needle" "$file"; then
    fail "did not expect '$needle' in $file"
  fi
}

assert_line() {
  expected="$1"
  file="$2"
  grep -Fxq -- "$expected" "$file" || fail "expected exact line '$expected' in $file"
}

toolbox="$temporary/toolbox"
mkdir -p "$toolbox"
for command in basename cat chmod cp dirname grep install mktemp mv rm; do
  ln -s "$(command -v "$command")" "$toolbox/$command"
done

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
  write_stub timeout <<'EOF'
#!/bin/bash
shift
"$@"
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
  if ! PATH="$MOCK_BIN:$toolbox" BOOTSTRAP_ROOT="$CASE_ROOT" \
    BOOTSTRAP_FROM_CLOUD_INIT=1 /bin/bash "$bootstrap" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
    fail "bootstrap execution failed for $(basename "$CASE_ROOT")"
  fi
  assert_contains 'host bootstrap 2026-08-22.1 ready' "$CASE_ROOT/output"
  assert_contains 'systemctl enable --now docker amazon-ssm-agent' "$CALLS"
  assert_contains 'docker info' "$CALLS"
}

prepare_case missing-docker
run_case
assert_line 'dnf install -y docker' "$CALLS"
assert_contains 'curl --fail --location --silent --show-error' "$CALLS"

prepare_case partial
cp "$DOCKER_STUB" "$MOCK_BIN/docker"
run_case
assert_not_contains 'dnf ' "$CALLS"
assert_contains 'curl --fail --location --silent --show-error' "$CALLS"

prepare_case ready
cp "$DOCKER_STUB" "$MOCK_BIN/docker"
mkdir -p "$CASE_ROOT/usr/local/lib/docker/cli-plugins"
cp "$DOCKER_STUB" "$CASE_ROOT/usr/local/lib/docker/cli-plugins/docker-compose"
run_case
assert_not_contains 'dnf ' "$CALLS"
assert_not_contains 'curl ' "$CALLS"

prepare_case cloud-init-failed
cp "$DOCKER_STUB" "$MOCK_BIN/docker"
mkdir -p "$CASE_ROOT/usr/local/lib/docker/cli-plugins"
cp "$DOCKER_STUB" "$CASE_ROOT/usr/local/lib/docker/cli-plugins/docker-compose"
write_stub cloud-init <<'EOF'
#!/bin/bash
echo 'status: error'
exit 2
EOF
if ! PATH="$MOCK_BIN:$toolbox" BOOTSTRAP_ROOT="$CASE_ROOT" \
  /bin/bash "$bootstrap" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
  fail "bootstrap did not repair after completed cloud-init failure"
fi
assert_contains 'cloud-init did not complete cleanly' "$CASE_ROOT/error"
assert_contains 'called journalctl --no-pager -u cloud-final.service -n 60' "$CALLS"
assert_contains 'host bootstrap 2026-08-22.1 ready' "$CASE_ROOT/output"

prepare_case cloud-init-running
write_stub cloud-init <<'EOF'
#!/bin/bash
exit 0
EOF
write_stub timeout <<'EOF'
#!/bin/bash
exit 124
EOF
if PATH="$MOCK_BIN:$toolbox" BOOTSTRAP_ROOT="$CASE_ROOT" \
  /bin/bash "$bootstrap" >"$CASE_ROOT/output" 2>"$CASE_ROOT/error"; then
  fail "bootstrap unexpectedly repaired while cloud-init was still running"
fi
assert_contains 'cloud-init was still running after five minutes' "$CASE_ROOT/error"
assert_not_contains 'dnf ' "$CALLS"

scripts="$(dirname "$bootstrap")"
assert_contains 'docker compose version >/dev/null' "$scripts/remote-deploy.sh"
assert_contains 'registry_password="$(aws ecr get-login-password' "$scripts/remote-deploy.sh"
if grep -Eq 'get-login-password.*\|[[:space:]]*docker' "$scripts/remote-deploy.sh"; then
  fail "remote deploy still pipes ECR credentials into docker"
fi
assert_contains '"/tmp/bootstrap-host.sh"' "$scripts/send-deployment.sh"
assert_contains 'generated SSM command exceeds the 24,000-byte limit' "$scripts/send-deployment.sh"

echo "host bootstrap simulations passed"
