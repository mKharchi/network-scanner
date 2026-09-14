#!/usr/bin/env bash
# install_server_service.sh
# Installs network-scanner-server.service on the current Linux host by
# substituting the current user's home directory and username into the
# example service file.
#
# Usage:
#   sudo bash scripts/install_server_service.sh
#
# The script must be run with sudo because it writes to /etc/systemd/system/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXAMPLE="${REPO_ROOT}/network-scanner-server.service.example"
DEST="/etc/systemd/system/network-scanner-server.service"

if [[ ! -f "${EXAMPLE}" ]]; then
  echo "ERROR: Example service file not found at ${EXAMPLE}" >&2
  exit 1
fi

# Resolve the actual login user even when running via sudo.
ACTUAL_USER="${SUDO_USER:-${USER}}"
ACTUAL_HOME="$(eval echo "~${ACTUAL_USER}")"

echo "Installing service for user '${ACTUAL_USER}' (home: ${ACTUAL_HOME})"
echo "Repository root: ${REPO_ROOT}"

sed \
  -e "s|/home/adonis|${ACTUAL_HOME}|g" \
  -e "s|User=adonis|User=${ACTUAL_USER}|g" \
  -e "s|Group=adonis|Group=${ACTUAL_USER}|g" \
  "${EXAMPLE}" \
  | tee "${DEST}" > /dev/null

chmod 0644 "${DEST}"
systemctl daemon-reload

echo ""
echo "Service installed at ${DEST}"
echo ""
echo "Next steps:"
echo "  sudo systemctl enable --now network-scanner-server.service"
echo "  sudo systemctl status network-scanner-server.service --no-pager"
