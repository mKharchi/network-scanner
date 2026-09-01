# Phase 2 Milestone A — Architecture Audit

Date: 2026-09-01

This audit records the current implementation before Phase 2 feature work. Milestone A is complete; no feature code was changed as part of this milestone.

## 1. Client installation layout and guide

- The current deployment guide is `client/installation_guide.md`.
- It instructs operators to extract the client to a permanent folder such as `C:\\NetworkScanner\\client` (`client/installation_guide.md:119-133`).
- The current layout is flat at the application root. Runtime/application modules include `client.py`, `client_lib.py`, `action_framework.py`, `user_agent.py`, and the legacy `service.py`. Supporting data is under `client/data/ieee/`; local runtime storage currently contains `client/storage/device_isolation/` and `client/storage/network_neighbourhood/`.
- The guide creates `.venv` at the client root and installs the root `requirements.txt` (`client/installation_guide.md:147-183`).
- Machine configuration is documented as `client/.env` (`client/installation_guide.md:187-245`), but `client/client.py` also loads the parent repository `.env` before loading `client/.env` (`client/client.py:42-54`).
- The guide recommends the per-user scheduled task and warns not to run it together with the legacy Windows service (`client/installation_guide.md:290-361`).

## 2. Action framework and state reporting

### Client

- Action vocabulary and states are declared in `client/action_framework.py:15-56`.
- `ActionManager.register()` and `dispatch()` provide the client-side handler registry (`client/action_framework.py:114-147`).
- Handlers are registered in `client/client_lib.py:1352-1392`, and normal command messages reach `handle_command()` at `client/client_lib.py:1395-1411`.
- The live receive/dispatch loop is in `client/client.py:854-1025`. It handles special message types such as `REGISTERED`, `FORBIDDEN_PROCESSES`, and `PACKAGE_CHUNK`, then dispatches ordinary `COMMAND` frames.
- `ActionResult` and `ActionState` exist as types, but the live path still reports ordinary results through ad-hoc `RESPONSE` frames (`client/client.py:1016-1019`). There is no structured action-state event stream.

### Server

- Server action vocabulary and aggregate status helpers are in `server/server_components/action_framework.py:15-79`.
- Persistent actions and per-target rows are created and executed by `server/server_components/action_service.py:101-157` and `server/server_components/action_service.py:423-570`.
- The REST action endpoints are exposed in `server/api_server.py:257-278` and `server/api_server.py:747-799`.
- The server receives post-registration frames through the dedicated reader in `server/server_components/server_lib.py:1515-1553`. Package completion frames are routed as `PACKAGE_RESULT` messages (`server/server_components/server_lib.py:1537-1538`).
- The existing action state machine is database-backed through `actions` and `action_targets` in `server/scripts.sql:138-190`; Phase 2 should extend this vocabulary rather than introduce a parallel state system.

## 3. Phase 1 package transfer

- The current client package paths are defined in `client/client_lib.py:1035-1037` and resolved by `_default_package_paths()` at `client/client_lib.py:1046-1053`:
  - `updates/incoming/`
  - `updates/staging/`
  - `updates/current/`
- Tests can override those paths through `configure_package_paths()` (`client/client_lib.py:1072-1084`).
- Initialization receives an action/package ID, SHA-256, size, chunk size, and chunk count, then creates `<package_id>.zip.part` under `updates/incoming/` (`client/client_lib.py:1180-1246`).
- `process_package_chunk()` base64-decodes chunks, writes them to disk, updates a SHA-256 hash, renames the verified partial file, extracts to a staging directory, and atomically swaps it into `updates/current/` (`client/client_lib.py:1249-1349`).
- `safe_extract()` validates the total uncompressed size and rejects paths outside the extraction directory before extraction (`client/client_lib.py:1130-1152`). This is the current zip-slip protection boundary.
- The server streams 128 KiB `PACKAGE_CHUNK` frames and waits for the client `PACKAGE_RESULT` (`server/server_components/action_service.py:274-420`).
- Existing regression coverage is in `client/tests/test_package_deployment.py`, `server/tests/test_package_deployment.py`, and `server/tests/test_package_deployment_e2e.py`.
- The Phase 1 action is named `DEPLOY_PACKAGE` / `DEPLOY_PACKAGE_INIT`; the planned `SEND_FILE` action does not currently exist in code.

## 4. Client startup, stop, and restart

- `client/user_agent.py:12-21` changes to the client directory and calls `start_client(agent_role="combined")`.
- `client/install_user_logon_task.ps1:22-42` creates the `NetworkClientUserAgent` scheduled task at interactive user logon, using the selected `pythonw.exe` and the client directory as working directory.
- `client/service.py:9-34` contains the legacy `NetworkClient` Windows service and calls `start_client(..., agent_role="service")`.
- The main reconnecting client loop is `client/client.py:691-1059`. It connects, registers, starts listeners/monitors after receiving configuration, and reconnects after socket loss.
- Stop handling uses a stop event, `DISCONNECT`, `KeyboardInterrupt`, service stop, and teardown of listeners/background threads (`client/client.py:1023-1058`).
- There is no separate updater process yet. A running client currently only reconnects; it does not replace its own application files.

## 5. Registration and heartbeat/telemetry

- Registration is built by `client/client_lib.py:create_registration_message()` (`client/client_lib.py:1430-1442`). The current payload contains system identity from `get_system_info()`, `agent_role`, and an optional cached location.
- The server accepts the `REGISTER` frame in `server/server.py:33-81` and calls `register_client()` in `server/server_components/server_lib.py:1132-1227`.
- The server persists hostname, IP, MAC, and operating-system fields through `update_client_db()` (`server/server_components/server_lib.py:1007-1051`).
- The `clients` table is defined in `server/scripts.sql:28-62`. It has OS version fields, but no application `client_version`, updater version, or heartbeat timestamp field.
- The client has no periodic `HEARTBEAT` message sender. The only keepalive-like action currently registered is `PING` (`client/client_lib.py:1021-1022`), which must be requested by the server. Post-registration server routing has no heartbeat branch (`server/server_components/server_lib.py:1515-1553`).
- The GUI client detail API reads the OS version as `os.version`; it does not expose an installed client application version (`server/server_components/api_service.py:1054-1137`, `server/gui/src/pages/ClientDetail.tsx`).

## 6. Requirements and virtual-environment handling

- The current application dependencies are listed in `client/requirements.txt`: `psutil`, `python-dotenv`, `scapy`, and `Pillow`.
- The installation guide creates `.venv` at the current client root and installs the application requirements in one operation (`client/installation_guide.md:147-183`).
- `service.py` imports `win32service`/`win32serviceutil`, but `pywin32` is not listed in `client/requirements.txt`; the guide recommends the scheduled-task path rather than the legacy service.
- No separate updater dependency set exists.
- The PyInstaller spec (`client/NetworkScannerClient.spec`) is for the current flat `client.py` entry point and does not document or package the planned updater/config/storage structure.

## Open questions and gaps

1. No `version.json` or equivalent application version source exists.
2. Registration has no `client_version` or explicit platform field beyond the existing OS data.
3. No periodic heartbeat/telemetry frame exists, and the server has no heartbeat handler or live version update path.
4. No server database field or GUI field represents the installed client application version.
5. `SEND_FILE`, `UPDATE_CLIENT`, and `DEPLOY_APPLICATION` are not implemented; the only package action is `DEPLOY_PACKAGE`.
6. Package storage is hardcoded to the update-oriented `updates/{incoming,staging,current}` paths; there is no `client/storage/sent-files/` destination.
7. `ActionState`/`ActionResult` declarations are not used for structured client-side state reporting.
8. Package chunk validation does not explicitly enforce sequence ordering, duplicate detection, or `total_size` consistency; interrupted `.part` files can remain until a later initialization clears the same package ID.
9. The current layout has no `app/`, `config/`, `updater/`, `logs/`, or `storage/updates/history/` separation, so Milestone D will require a compatibility-aware structural refactor.
10. Configuration loading includes the parent repository `.env`; the future update system must ensure machine-specific configuration is never overwritten or implicitly relocated.
11. The installation guide currently describes the flat layout and root `.venv`, so it must be updated only during the structural milestone.
12. A physical/test client is required to verify the later installation, transfer, heartbeat, and update milestones; this local audit cannot validate those network/hardware conditions.

## Milestone A verification

- Read `docs/package-send/phase2.md`.
- Scanned the complete `client/` and `server/` source/test trees and the server GUI integration points.
- Inspected the installation guide, action framework, package transport, startup paths, registration flow, database schema, server routing, API, and package deployment UI.
- No feature code was changed for Milestone A.
