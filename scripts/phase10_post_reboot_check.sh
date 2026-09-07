#!/usr/bin/env bash
# Read-only Phase 10 startup verification for the current Linux sensor.
set -u

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "=== Kismet service ==="
systemctl show kismet-sensor.service \
  -p ActiveState -p SubState -p MainPID -p ExecMainStatus -p User -p Group --no-pager

echo "=== Capture interface ==="
ip link show wlp0s20f3mon

echo "=== Required listeners ==="
ss -ltn | grep -E '127\.0\.0\.1:(8080|2501)\b'

echo "=== Application sensor health ==="
curl --fail --silent --show-error \
  http://127.0.0.1:8080/api/v1/sensors/wifi/health
echo

echo "=== Retention dry-run ==="
python3 scripts/kismet_retention.py
