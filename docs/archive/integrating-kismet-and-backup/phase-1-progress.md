# Phase 1 Progress — Bounded Raw-File Retention & Storage Pruning

## Phase Objective

Implement bounded, configurable retention and automatic pruning of raw packet files (`client/storage/passive_packets/` and `client/storage/network_telemetry/<date>/packets/`) to prevent unbounded storage growth while ensuring that in-progress, pending, or failed captures are strictly preserved for recovery.

---

## Status

- **Status:** COMPLETED
- **Date:** 2026-09-05
- **Modules Created/Modified:**
  - [`client/app/retention_manager.py`](file:///home/adonis/network-scanner/client/app/retention_manager.py)
  - [`client/retention_manager.py`](file:///home/adonis/network-scanner/client/retention_manager.py)
  - [`client/app/client.py`](file:///home/adonis/network-scanner/client/app/client.py)
  - [`client/tests/test_retention_manager.py`](file:///home/adonis/network-scanner/client/tests/test_retention_manager.py)

---

## Implementation Details

### 1. Lifecycle State Machine

Implemented formal lifecycle state management:

```text
RAW FILE ──► PENDING ──► PROCESSING ──► SUCCESS ──► PROCESSED ──► RETENTION WINDOW ──► DELETE
                │
                └──────► FAILED ──► KEEP FILE (NEVER DELETED) ──► RETRY
```

- States tracked via `FileProcessingState` (`PENDING`, `PROCESSING`, `SUCCESS`, `FAILED`, `DELETED`).
- Persistent state tracking via `RetentionStateTracker` in `storage/retention_state.json`.

### 2. Configurable Policies

- `RAW_CAPTURE_RETENTION_HOURS`: Configurable retention period (default: `48.0` hours).
- `RAW_CAPTURE_CLEANUP_INTERVAL_SECONDS`: Background pruning interval (default: `3600.0`s / 1 hour).
- `RAW_CAPTURE_CLEANUP_DRY_RUN`: Dry-run mode (`0` or `1`, default: `0`).
- Active file write grace period (`write_grace_seconds`, default: `300.0`s) prevents touching files currently being written.

### 3. Deletion & Safety Rules

A raw packet file is pruned **only** when all of the following conditions are met:

1. File age has exceeded `RAW_CAPTURE_RETENTION_HOURS`.
2. Flow processing for the date partition is verified as successful.
3. The file/date is not marked `FAILED`, `PENDING`, or `PROCESSING`.
4. The file was not modified within the active write grace period.
5. In dry-run mode, actions are evaluated and logged without deleting files.
6. Empty `packets/` subdirectories are automatically cleaned up when all packet files inside are pruned.

### 4. Background Service Integration

- `RetentionManager` is integrated directly into `client/app/client.py`:
  - Starts as a background worker alongside `PacketObserver`.
  - Performs non-blocking periodic pruning cycles.
  - Stops cleanly during client shutdown.

---

## Validation Scenarios Verified

| Scenario | Description                                                                                          | Result |
| -------- | ---------------------------------------------------------------------------------------------------- | ------ |
| 1 & 2    | Generated V1 & V2 test capture files with successful flow processing                                 | PASS   |
| 3        | Verified files become eligible for deletion once retention window elapsed (>48h)                     | PASS   |
| 4 & 5    | Simulated failed flow computation (`FAILED` state); verified file is preserved                       | PASS   |
| 6 & 7    | Simulated active processing file (`PROCESSING` state); verified file is preserved                    | PASS   |
| 8        | Executed cleanup in Dry-Run mode; verified files remain on disk & logged accurately                  | PASS   |
| 9        | Verified detailed logs, summary counters, and error handling for missing/locked files                | PASS   |
| 10       | Executed live cleanup; verified eligible files deleted, state updated, and empty directories cleaned | PASS   |

All 28 test suites in `client/tests/` pass with 100% success.
