#!/usr/bin/env bash
# Create machine-global Kismet capture + conf directories (no per-user ~ paths).
set -euo pipefail

CAPTURE_ROOT="${KISMET_CAPTURE_ROOT:-/var/lib/kismet/captures}"
CONF_DIR="${KISMET_CONF_DIR:-/etc/kismet}"
HOMEDIR="${KISMET_HOMEDIR:-/var/lib/kismet}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_CONF="${SOURCE_KISMET_CONF:-/home/adonis/kismet/conf}"
# Prefer the live sensor conf if present; fall back to repo examples.
if [[ ! -d "$SOURCE_CONF" ]]; then
  SOURCE_CONF="/home/adonis/kismet/conf"
fi

echo "Creating ${CAPTURE_ROOT} and ensuring ${HOMEDIR} exists..."
sudo mkdir -p "$CAPTURE_ROOT" "$HOMEDIR"
sudo chown -R kismet:kismet "$HOMEDIR"
sudo chmod 2770 "$CAPTURE_ROOT"

echo "Installing conf into ${CONF_DIR}..."
sudo mkdir -p "$CONF_DIR"
if [[ -d "$SOURCE_CONF" ]]; then
  sudo cp -a "$SOURCE_CONF"/. "$CONF_DIR"/
else
  echo "WARNING: source conf dir not found at $SOURCE_CONF — copy conf manually."
fi
sudo chown -R root:kismet "$CONF_DIR"
sudo chmod 755 "$CONF_DIR"
sudo find "$CONF_DIR" -type f -exec chmod 644 {} \;

echo
echo "Done. Set these absolute paths in server/.env (never use ~ here):"
echo "  KISMET_CAPTURE_ROOT=${CAPTURE_ROOT}"
echo "  KISMET_CONF_DIR=${CONF_DIR}"
echo "  KISMET_HOMEDIR=${HOMEDIR}"
echo
echo "Then restart the sensor:"
echo "  sudo systemctl restart kismet-sensor.service"
