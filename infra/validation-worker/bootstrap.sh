#!/usr/bin/env bash
set -euo pipefail

# Host preparation only. No application deployment, migrations, provider access,
# artifact download or scientific batch is started by instance boot.
dnf install -y python3.11 python3.11-pip git
if ! id phase55 >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /var/lib/phase55 --shell /sbin/nologin phase55
fi
install -d -m 0700 -o phase55 -g phase55 /var/lib/phase55
systemctl enable --now amazon-ssm-agent
printf 'Phase5.5 isolated host prepared; awaiting registered development-only package.\n'
