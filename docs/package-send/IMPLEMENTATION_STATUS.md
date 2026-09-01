# Phase 2 Implementation Status

**Last Updated:** September 1, 2026

## Completed Milestones

### Milestone A: Architecture Audit ✓
- Documented client folder structure, action framework, package transfer, startup/agent mechanism, versioning, heartbeat format, dependency handling.

### Milestone B: Separate File Transfer from Update Storage ✓
- Introduced `client/storage/sent-files/` for SEND_FILE operations.
- Made destination configurable per operation type via `operation` parameter in `deploy_package_to_client()`.
- Verified SEND_FILE lands in sent-files, DEPLOY_PACKAGE extracts to current/.

### Milestone C: Client Versioning ✓
- Added `client/app/version.json` with `version` field.
- Extended registration and heartbeat messages to include `client_version`.
- Server stores and displays version per-client.

### Milestone D: New Client Folder Structure ✓
- Refactored to: `app/`, `config/`, `updater/`, `storage/(sent-files/, updates/)`, `logs/`, `venv/`.
- Updated all internal path references and installation guide.
- Verified on test PC: full manual reinstall, client starts/registers correctly.

### Milestone E: Build the Updater ✓
- Implemented `updater/updater.py` as standalone process:
  - Parse & validate `manifest.json` (version, package type, minimum_updater_version, file hashes)
  - Stop client, back up current app/, replace with staged package
  - Diff requirements.txt and install missing/changed dependencies
  - Validate startup, rollback on failure with specific reason codes
- State machine in action framework: `PENDING → RUNNING → COMPLETED/FAILED`
- Tested with deliberately broken packages (bad checksum, zip-slip, broken requirements, broken client.py start)

## Current State: Milestone F (In Progress)

### Milestone F: Single-Client UPDATE_CLIENT Wiring

**Status:** Core wiring complete, needs real hardware end-to-end test.

**What's Done:**
1. **Server-side (action_service.py)**:
   - `_sanitize_action_parameters()` strips UPDATE_CLIENT payloads before DB persistence (line 60)
   - `execute_action()` includes UPDATE_CLIENT in concurrent fan-out block (line 455+)
   - `deploy_package_to_client()` accepts `operation=ActionType.UPDATE_CLIENT.value` to route to updates/incoming

2. **Client-side (client_lib.py)**:
   - `_spawn_updater_subprocess()` function spawns updater.py as detached subprocess (lines 1441–1489)
   - `process_package_chunk()` detects UPDATE_CLIENT + final chunk, spawns updater, returns PACKAGE_RESULT with status="STAGED" (lines 1348–1368)
   - UPDATE_CLIENT registered with ACTION_MANAGER to use `_handle_deploy_package_init` (line 1477–1479)

3. **Updater (updater.py)**:
   - CLI entry point accepts `<staged_package_path>` and `<client_root>` arguments (lines 208–263)
   - Validates paths, logs startup, calls `apply_update()`, returns exit code 0/1

4. **Tests (test_update_client.py)**:
   - 6 test classes covering action creation, parameter sanitization, routing, staging, spawning, CLI
   - All syntax errors resolved, all tests pass

**What's Missing for Milestone F Acceptance Criteria (phase2.md lines 2115–2119):**
1. ~~Create test update package~~ (already have mechanism)
2. ~~Upload to server~~ (already have API)
3. **Create UPDATE_CLIENT action via server API targeting one test PC** ← ready to test
4. **Verify full real hardware flow:**
   - Package transferred, staged, updater spawned
   - App replaced, version updated in server's client registry
   - Server shows new version after success
5. **Run forced failure case (bad requirements) on test PC:**
   - Confirm rollback restores old version
   - Client continues running previous version
   - Server shows failure status

**Next Step:**
Create test data and run real hardware test:
- Build `app-v2.0.0.zip` with bumped version string
- POST to `/api/actions` with `action_type="UPDATE_CLIENT"`, target test client, package ID
- Monitor server-side status, then check client version
- Repeat with intentional breakage (bad requirements)
- Only after both pass, proceed to Milestone G

---

## Upcoming: Milestone G (Bulk Update)

**Scope:** Extend single-client update to selectable group of clients with per-client visibility.

**Key Design:**
- Create **one independent UPDATE_CLIENT action per selected client** (not one shared action)
- This gives per-client success/failure visibility
- Surface aggregate + per-client status on server

**Tasks:**
1. Add multi-select UI/API for choosing target clients (individual, group, or "all")
2. On trigger, fan out to create one action per client
3. Surface aggregate + per-client status (e.g., "18/20 updated, 2 failed")
4. Test on 3–5 test machines with at least one deliberately failing target

---

## Known Limitations & Notes

- **Physical hardware test required for Milestone F sign-off:** Current tests are unit/integration with mocks. Real network transfer, updater spawning, and version update must be verified on actual test PC(s).
- **No automatic version polling from client:** Client version is only updated when client registers or sends heartbeat. Version changes are not pushed from server to client in real time (expected behavior).
- **Updater must be standalone process:** Running while parent process can exit, so app can't replace its own files. This is by design and tested.
- **No partial/delta updates:** Full package replacement only. Efficient for small app codebases, may need optimization for large ones.
