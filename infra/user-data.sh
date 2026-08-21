#!/bin/bash
set -euxo pipefail
dnf install -y docker curl
systemctl enable --now docker amazon-ssm-agent
install -d -m 755 /usr/local/lib/docker/cli-plugins
curl --fail --location --silent --show-error \
  https://github.com/docker/compose/releases/download/v2.39.2/docker-compose-linux-aarch64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod 755 /usr/local/lib/docker/cli-plugins/docker-compose
usermod -aG docker ec2-user
cat >/etc/ssh/sshd_config.d/99-trade-recommender.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
EOF
systemctl restart sshd
install -d -m 700 /opt/trade-recommender
