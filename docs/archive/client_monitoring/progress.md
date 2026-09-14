# Client Reliability & Monitoring Fix Plan — Progress

> **Last updated:** 2026-09-06
>
> **Reference:** [plan.md](file:///home/adonis/network-scanner/docs/client_monitoring/plan.md)

---

## Summary

| Phase | Description | Status | Progress |
|-------|-------------|--------|----------|
| 0 | Debugging baseline / Diagnostics | 🟢 Complete | 100% |
| 1 | File persistence / Flow Aggregator — WinError 5 | 🟢 Complete | 100% |
| 2 | Client activity/event logging | 🟢 Complete | 100% |
| 3 | Updater reliability | 🟢 Complete | 100% |
| 4 | Screenshot capture (cross-session) | 🟢 Complete | 100% |
| 5 | Kismet listener + observation query | 🟢 Complete | 100% |
| 6 | Integration testing | 🟢 Complete | 100% |
| 7 | Automated regression tests | 🟢 Complete | 100% |

---

## Phase 0 — Establish a debugging baseline

### 0.1 Client diagnostic structure — 🟢 Complete

- **Created [diagnostics.py](file:///home/adonis/network-scanner/client/app/diagnostics.py):**
  - Standardized component categories: `PERSISTENCE`, `UPDATER`, `EVENT_MONITOR`, `SCREENSHOT`, `KISMET`, `FLOW_AGGREGATOR`, `PASSIVE_LISTENER`, `PROCESS_MONITOR`, `CLIENT_CORE`.
  - Implemented `component_log(logger, component, operation, **context)` producing structured key-value log entries:
    `[{component}] {operation} key1=val1 key2=val2`

### 0.2 Environment information capture — 🟢 Complete

- **Implemented `capture_environment()` in [diagnostics.py](file:///home/adonis/network-scanner/client/app/diagnostics.py):**
  - Captures platform OS, Python version, agent version (from `version.json`), installation directory, storage directory, current user, process PID, hostname, service detection (Session 0 / parent process check), session ID, working directory, and executable path.
  - Degrades gracefully with default fallback values if any OS query fails.
  - Implemented `log_startup_diagnostics(logger)` to output structured snapshot at startup.
- **Integrated into [client.py](file:///home/adonis/network-scanner/client/app/client.py):**
  - `log_startup_diagnostics(LOG)` and `check_storage_permissions(STORAGE_DIR)` invoked on startup.

---

## Phase 1 — File persistence / Flow Aggregator

### 1.1 Detailed failure diagnostics — 🟢 Complete

- Enhanced `FlowAggregator._finalize_flow` in [flow_aggregator.py](file:///home/adonis/network-scanner/client/app/flow_aggregator.py#L306):
  - On persistence failure, logs: `flow_id`, target path, exact error type, error message, current execution user, process PID, storage existence, and storage write permission flags.

### 1.2 Storage permissions check — 🟢 Complete

- Implemented `check_storage_permissions()` in [diagnostics.py](file:///home/adonis/network-scanner/client/app/diagnostics.py):
  - Verifies existence, read access, write access, and owner information.
  - Integrated into client startup check in [client.py](file:///home/adonis/network-scanner/client/app/client.py).

### 1.3/1.5 Recoverable persistence & retry logic — 🟢 Complete

- Implemented `atomic_write_json_with_retry()` in [telemetry_storage.py](file:///home/adonis/network-scanner/client/app/telemetry_storage.py#L143):
  - Retries transient `OSError` / WinError 5 / file lock errors up to 3 times with exponential backoff (`base_delay * 2 ** attempt`).
  - Logs detailed `[PERSISTENCE]` retry warnings before re-attempting.
  - Wired into `RotatingJSONAppendStore.append_many()`.

---

## Phase 2 — Client activity/event logging

### 2.1 Event taxonomy & schema — 🟢 Complete

- **Created [event_monitor.py](file:///home/adonis/network-scanner/client/app/event_monitor.py):**
  - Defined taxonomy:
    - Application events: `APP_INSTALLED`, `APP_UNINSTALLED`, `APP_UPDATED`, `APP_STARTED`, `APP_STOPPED`
    - File events: `FILE_CREATED`, `FILE_MODIFIED`, `FILE_DELETED`, `FILE_RENAMED`
    - Client events: `CLIENT_STARTED`, `CLIENT_STOPPED`, `CLIENT_UPDATED`, `CLIENT_UPDATE_FAILED`, `CLIENT_CONFIG_CHANGED`
  - Created `ClientEvent` dataclass with `to_dict()` JSON serialization matching Plan §2.5 schema:
    `{ "event_type": ..., "timestamp": ..., "client_id": ..., "path": ..., "application": ..., "version": ..., "user": ..., "source": ... }`

### 2.2 Application uninstall & install detection — 🟢 Complete

- Implemented `get_installed_applications_windows()` in [event_monitor.py](file:///home/adonis/network-scanner/client/app/event_monitor.py):
  - Queries Windows registry uninstall hives (`HKLM`, `HKCU`, and `Wow6432Node`).
  - Diffs against baseline to detect explicit uninstalls (`APP_UNINSTALLED`), new installs (`APP_INSTALLED`), and version changes (`APP_UPDATED`).

### 2.3 Filesystem event monitoring — 🟢 Complete

- Implemented `_scan_directory_state()` and `check_file_changes()` in [event_monitor.py](file:///home/adonis/network-scanner/client/app/event_monitor.py):
  - Monitors configured application and client directories.
  - Detects created, modified, and deleted files.

### 2.4 Event storm prevention — 🟢 Complete

- **Noise filtering:** Ignores temporary and cache files (`.tmp`, `.log`, `.partial`, `~*`, `__pycache__`, `.git`, `.venv`, `Temp`).
- **Deduplication:** `EventDeduplicator` suppresses identical events within configurable window (default 3.0s).
- **Rate limiting:** `EventRateLimiter` sliding window prevents bursts from exceeding thresholds (default 30 events / 10s).

### 2.5 Local persistence and alert delivery — 🟢 Complete

- Implemented `_persist_event()` writing day-scoped records to `client/storage/events/<YYYY-MM-DD>.json`.
- Integrated `EventMonitor` into [client.py](file:///home/adonis/network-scanner/client/app/client.py) with alert callback forwarding to server.

---

## Phase 3 — Updater reliability

### 3.1 Lifecycle & State Machine — 🟢 Complete

- Added explicit update lifecycle states to [updater.py](file:///home/adonis/network-scanner/client/updater/updater.py):
  `STATE_IDLE`, `STATE_PACKAGE_VALIDATING`, `STATE_PACKAGE_VALIDATED`, `STATE_CLIENT_STOPPING`, `STATE_CLIENT_STOPPED`, `STATE_BACKUP_CREATED`, `STATE_FILES_REPLACED`, `STATE_DEPENDENCIES_INSTALLING`, `STATE_CLIENT_STARTING`, `STATE_VERSION_VERIFYING`, `STATE_UPDATE_CONFIRMED`.
- Failure states: `STATE_VALIDATION_FAILED`, `STATE_STOP_FAILED`, `STATE_FILE_REPLACEMENT_FAILED`, `STATE_DEPENDENCY_FAILED`, `STATE_START_FAILED`, `STATE_VERSION_MISMATCH`, `STATE_ROLLBACK_COMPLETED`, `STATE_ROLLBACK_FAILED`.
- State transitions are recorded to `client/storage/updates/current_state.json`.

### 3.2 Distinguish expected exit from crash — 🟢 Complete

- Updated `_start_application()` in [updater.py](file:///home/adonis/network-scanner/client/updater/updater.py#L166):
  - Exit code 0 within startup window is treated as normal launch (e.g. child process spawned or service handed off).
  - Non-zero exit code is recorded as a genuine crash with PID and returncode.
  - Process remaining running after timeout is logged and confirmed healthy.

### 3.4 Version verification — 🟢 Complete

- `apply_update()` now checks `app_root / "version.json"` after file replacement and verifies it matches the package manifest version.
- Version mismatch triggers automatic rollback and records `STATE_VERSION_MISMATCH`.

---

## Phase 4 — Screenshot session awareness

### 4.1 Session topology diagnostics — 🟢 Complete

- Added `SessionTopology` dataclass and `get_session_topology()` to [screenshot_manager.py](file:///home/adonis/network-scanner/client/app/screenshot_manager.py):
  - Collects `agent_user`, `agent_session_id`, `active_session_id`, `interactive_user`, `window_station`, `desktop_name`, `is_active_session`, `can_capture`, `reason`.
  - Windows API integration: `WTSGetActiveConsoleSessionId`, `ProcessIdToSessionId`, `WTSQuerySessionInformationW`, `GetProcessWindowStation`, `GetThreadDesktop`.

### 4.2/4.3 Session-aware capture — 🟢 Complete

- `ScreenshotManager.capture()` inspects session topology prior to capture.
- Emits structured `[SCREENSHOT]` diagnostic log.
- Detects Case B (Session 0 service vs Session 1 interactive console): blocks invalid capture with actionable diagnostic explaining service desktop isolation, and reports session details in all errors.

---

## Phase 5 — Kismet listener & observation query

### 5.1/5.2 Client-side Kismet Listener — 🟢 Complete

- **Created [kismet_listener.py](file:///home/adonis/network-scanner/client/app/kismet_listener.py):**
  - Standard lifecycle logging: `KISMET_LISTENER_STARTING`, `KISMET_CONNECTED`, `KISMET_LISTENING`, `KISMET_EVENT_RECEIVED`, `KISMET_EVENT_PARSED`, `KISMET_OBSERVATION_STORED`, `KISMET_DISCONNECTED`, `KISMET_RECONNECTING`, `KISMET_ERROR`, `KISMET_STOPPED`.
  - Health reporting via `get_health()`:
    `{ "listener": "kismet", "status": "active", "connected": true, "last_event": "...", "events_received": N, "observations_stored": N, "last_error": null }`.
  - Polls local `.kismet` SQLite databases, extracts 802.11 metadata, deduplicates by packet hash.
  - Integrated into [client.py](file:///home/adonis/network-scanner/client/app/client.py).

### 5.3/5.4 15-Minute Lookback Query Bug Fix — 🟢 Complete

- **Fixed in [kismet_service.py](file:///home/adonis/network-scanner/server/server_components/kismet_service.py#L320):**
  - Identified root cause: `if start_time is not None or end_time is not None:` skipped the time filter whenever `lookback_minutes` (e.g. 15m) was used, returning yesterday's database records.
  - Fixed query to apply `ts_sec >= ? AND ts_sec <= ?` bounds whenever lookback is requested.
  - Added unit test `test_time_filter_excludes_out_of_window_records` verifying out-of-window records are strictly excluded.

---

## Phase 6 & 7 — Regression & Test Suite Verification

### Test Results

| Test Module | Test Count | Result | Key Coverage |
|-------------|:----------:|:------:|--------------|
| `tests.test_event_monitor` | 8 | ✅ Pass | App install/uninstall/update, file created/modified/deleted, storm filtering, deduplication, persistence |
| `tests.test_kismet_listener` | 5 | ✅ Pass | Lifecycle, health status, packet polling, hash deduplication, start/stop |
| `tests.test_screenshot_manager` | 9 | ✅ Pass | Session topology, Session 0 service blocking, matching session capture, cleanup |
| `tests.test_flow_aggregator` | 7 | ✅ Pass | Flow aggregation, idle sweeps, flush, multi-packet conversations |
| `tests.test_telemetry_storage` | 11 | ✅ Pass | Atomic writes, retry on failure, rotation, day directories |
| `updater.test_updater` | 8 | ✅ Pass | State machine recording, clean exit handling, rollback on failure/mismatch, hash verification |
| `server.tests.test_kismet_investigation_service` | 10 | ✅ Pass | Time filter strict bounds, noise filtering, REST API endpoints, sensor listing |
| **Complete Client Test Suite** | **255** | **✅ Pass** | All existing + new client unit tests passing cleanly |
