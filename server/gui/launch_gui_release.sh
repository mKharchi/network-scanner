#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_BIN="$SCRIPT_DIR/src-tauri/target/release/netwatch-gui"

if [[ -x "$APP_BIN" ]]; then
  exec "$APP_BIN"
fi

# Desktop launchers and sudo do not load the user's shell profile, so make an
# NVM-installed npm available before falling back to Tauri's development mode.
if ! command -v npm >/dev/null 2>&1 && [[ -s "${HOME}/.nvm/nvm.sh" ]]; then
  # shellcheck source=/dev/null
  source "${HOME}/.nvm/nvm.sh"
fi

if command -v npm >/dev/null 2>&1; then
  echo "Built Tauri app not found at: $APP_BIN" >&2
  echo "Falling back to development mode: npm run tauri dev" >&2
  exec npm run tauri dev
fi

echo "Built Tauri app not found at: $APP_BIN" >&2
echo "npm was not found, so the GUI cannot start." >&2
exit 1
