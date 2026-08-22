#!/bin/bash
set -Eeuo pipefail

readonly BOOTSTRAP_VERSION="2026-08-22.1"
readonly COMPOSE_VERSION="2.39.2"
readonly COMPOSE_SHA256="54488fffb60782f3c8787a48b95ed15f49f5a3a85f4105304bd46db5edd9db61"
readonly ROOT="${BOOTSTRAP_ROOT:-}"
readonly COMPOSE_PLUGIN="${ROOT}/usr/local/lib/docker/cli-plugins/docker-compose"
readonly SSH_CONFIG="${ROOT}/etc/ssh/sshd_config.d/99-trade-recommender.conf"
readonly APP_DIR="${ROOT}/opt/trade-recommender"
readonly STATE_DIR="${ROOT}/var/lib/trade-recommender"

diagnose_cloud_init() {
  echo "cloud-init did not complete cleanly; continuing with idempotent repair" >&2
  cloud-init status --long >&2 || true
  systemctl --no-pager --full status cloud-final.service >&2 || true
  journalctl --no-pager -u cloud-final.service -n 60 >&2 || true
}

wait_for_cloud_init() {
  [ "${BOOTSTRAP_FROM_CLOUD_INIT:-0}" = 1 ] && return
  command -v cloud-init >/dev/null || return

  set +e
  timeout 300 cloud-init status --wait --long
  status=$?
  set -e
  if [ "$status" -eq 124 ]; then
    echo "cloud-init was still running after five minutes; refusing concurrent repair" >&2
    diagnose_cloud_init
    exit 1
  elif [ "$status" -ne 0 ]; then
    diagnose_cloud_init
  fi
}

install_prerequisites() {
  source "${ROOT}/etc/os-release"
  if [ "${ID:-}" != "amzn" ] || [[ "${VERSION_ID:-}" != 2023* ]]; then
    echo "host bootstrap supports only Amazon Linux 2023" >&2
    exit 1
  fi

  packages=()
  command -v docker >/dev/null || packages+=(docker)
  command -v aws >/dev/null || packages+=(awscli-2)
  command -v curl >/dev/null || packages+=(curl-minimal)
  systemctl cat amazon-ssm-agent.service >/dev/null 2>&1 || packages+=(amazon-ssm-agent)
  if [ "${#packages[@]}" -gt 0 ]; then
    dnf install -y "${packages[@]}"
  fi

  command -v docker >/dev/null
  command -v aws >/dev/null
  command -v curl >/dev/null
  systemctl enable --now docker amazon-ssm-agent
  systemctl is-active --quiet docker amazon-ssm-agent
}

install_compose() {
  architecture="$(uname -m)"
  [ "$architecture" = "aarch64" ] || {
    echo "expected aarch64 host, found $architecture" >&2
    exit 1
  }

  if [ -x "$COMPOSE_PLUGIN" ] && docker compose version --short | grep -Fxq "$COMPOSE_VERSION"; then
    return
  fi

  install -d -m 755 "$(dirname "$COMPOSE_PLUGIN")"
  temporary="$(mktemp "${COMPOSE_PLUGIN}.XXXXXX")"
  trap 'rm -f "$temporary"' RETURN
  curl --fail --location --silent --show-error \
    "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-aarch64" \
    -o "$temporary"
  printf '%s  %s\n' "$COMPOSE_SHA256" "$temporary" | sha256sum --check --status
  chmod 755 "$temporary"
  mv "$temporary" "$COMPOSE_PLUGIN"
  trap - RETURN
  docker compose version --short | grep -Fxq "$COMPOSE_VERSION"
}

harden_host() {
  if getent passwd ec2-user >/dev/null; then
    usermod -aG docker ec2-user
  fi

  install -d -m 755 "$(dirname "$SSH_CONFIG")"
  cat >"$SSH_CONFIG" <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
EOF
  sshd -t
  systemctl restart sshd
  install -d -m 700 "$APP_DIR" "$STATE_DIR"
  printf '%s\n' "$BOOTSTRAP_VERSION" >"${STATE_DIR}/bootstrap-version"
}

main() {
  if [ -z "$ROOT" ] && [ "$EUID" -ne 0 ]; then
    echo "host bootstrap must run as root" >&2
    exit 1
  fi
  wait_for_cloud_init
  install_prerequisites
  install_compose
  harden_host
  aws --version
  docker info >/dev/null
  docker compose version
  echo "host bootstrap $BOOTSTRAP_VERSION ready"
}

main "$@"
