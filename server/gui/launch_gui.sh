#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Desktop launchers and sudo do not load the user's shell profile, so make an
# NVM-installed npm available before attempting to launch the Tauri app.
if ! command -v npm >/dev/null 2>&1 && [[ -s "${HOME}/.nvm/nvm.sh" ]]; then
  # shellcheck source=/dev/null
  source "${HOME}/.nvm/nvm.sh"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found in PATH. Run this launcher as your normal user, not with sudo."
  exit 1
fi

exec npm run tauri dev
