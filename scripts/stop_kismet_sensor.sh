#!/usr/bin/env bash
# Stop the server-owned Kismet sensor through systemd.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_ENV="${KISMET_CONFIG_FILE:-${SCRIPT_DIR}/../server/.env}"
if [[ -f "${SERVER_ENV}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${SERVER_ENV}"
    set +a
fi

echo "=== Stopping Kismet Sensor Service ==="
sudo systemctl stop kismet-sensor.service
