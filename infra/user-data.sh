#!/bin/bash
set -Eeuo pipefail
install -d -m 755 /usr/local/sbin
printf '%s' '${bootstrap_script_base64}' | base64 --decode \
  >/usr/local/sbin/trade-recommender-bootstrap
chmod 700 /usr/local/sbin/trade-recommender-bootstrap
BOOTSTRAP_FROM_CLOUD_INIT=1 /usr/local/sbin/trade-recommender-bootstrap
