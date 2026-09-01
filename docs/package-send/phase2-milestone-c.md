# Phase 2 Milestone C — Client Versioning

Date: 2026-09-01

## Changed

- Added `client/version.json` with the initial application version `1.0.0`.
- Added `get_client_version()` and included `client_version` plus `platform` in registration data.
- Added a client heartbeat loop that emits `HEARTBEAT` frames every 30 seconds with `client_version`, platform, and timestamp while the connection is active.
- Added `client_version` and `client_version_updated_at` columns to the schema and database migration helper.
- Server registration now persists and keeps the live in-memory `client_version` value.
- Server post-registration routing accepts heartbeat frames and persists the reported version/time.
- Client list/detail API payloads expose the installed client version and last version report time.
- GUI client list and client detail views display the installed client version.

## Tested

- Changed Python modules compile successfully with `py_compile`.
- Server registration, action framework, and package transport tests: **27 tests passed**.
- GUI production build (`npm run build`) and `git diff --check` are included in the final verification pass.

## Environment limitation

The client identity test module could not import because the current managed Python runtime does not have the client dependency `psutil`. The code path is syntax-checked, and the server-side tests pass; run the client test suite in the project virtual environment after installing `client/requirements.txt` to complete runtime verification.

## Physical verification still required

A restarted client must be connected to a running server/database to confirm that registration and live heartbeat updates appear in the deployed server view. That cannot be completed from this local source workspace alone.
