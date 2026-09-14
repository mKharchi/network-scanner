# Implementation Plan: Fix Observation Intervals & Server Daemon Service

## Status: ✅ IMPLEMENTED (2026-09-14)

## Goal Description

Resolve two operational issues affecting the server:

1. **Observation Intervals & Recent Device Activity**:
   - Prevent the automated 10-minute cycle (`kismet_interval_processor.py run-cycle`) from processing 144 intervals (the whole 24-hour day) all at once.
   - Fix the timing and margin check that was skipping the immediate just-closed 10-minute interval (e.g. at 2:05/2:10 PM, skipping the 2:00 interval).
   - Ensure the recurring cycle processes strictly the just-closed interval(s) in real time without lag, while preserving `--lookback 144` for explicit manual backfill commands.
2. **Server Daemon Service (`network-scanner-server.service`)**:
   - Fix the root cause of why the daemon was crashing in an infinite loop (restart counter at 933) with `OSError: [Errno 99] Cannot assign requested address`.
   - Update `SERVER_HOST` and socket binding to `0.0.0.0` so the server starts reliably at boot even before Wi-Fi or DHCP finishes assigning a dynamic IP.
   - Fix relative path configurations in `server/.env` so client connections and connection alerts function reliably under systemd supervision.

---

## Root Cause Analysis

### Issue 1: 24-Hour Interval Storm & Skipped Recent Intervals

1. **Hardcoded 144-interval lookback in recurring cycle**:
   - `kismet-cycle.timer` invokes `kismet-cycle.service` every 10 minutes (`*:00,10,20,30,40,50:00`).
   - `kismet_interval_processor.py run-cycle` hardcoded `lookback = getattr(args, "lookback", 144)`.
   - `cmd_process_completed` searched backwards for up to 144 intervals (24 hours). If the system was off or unmonitored earlier, it queued up to 80+ missing intervals from midnight and processed them all sequentially.
2. **Timing Margin Skips the Most Recent Interval**:
   - In `cmd_process_completed`:
     ```python
     if candidate_end_ms + margin * 1000 > now_ms:
         continue
     ```
   - When the timer triggered at `14:10:05`, the interval that just closed at `14:10:00` had `candidate_end_ms + 30s = 14:10:30 > 14:10:05`, so the code considered the interval **not yet closed** and skipped it.
   - Because `cmd_run_cycle` already rotates the Kismet log in Step 1 (`rotator.rotate()`), the file is already sealed — no margin wait is necessary.

### Issue 2: Daemon Service Crash Loop & Missing Alerts

1. **`OSError: [Errno 99] Cannot assign requested address`**:
   - `server/.env` defined `SERVER_HOST="172.16.1.238"`.
   - At boot, `wlp0s20f3` was not yet associated / DHCP had not assigned `172.16.1.238`.
   - `server.bind((HOST, PORT))` failed → systemd restarted every 5s → 930+ crash loops.
   - Because the service was in a restart loop, port 5000 was never open → clients couldn't connect → no registration → no connection alerts.
2. **Why manual execution worked**: Running manually in the terminal happens after login when Wi-Fi is already up and the IP is assigned.

---

## Changes Implemented

### `server/kismet_interval_processor.py`

- **`cmd_run_cycle` (line 317)**: `lookback=144, margin=30` → `lookback=1, margin=0`
- **`build_parser()` run-cycle subparser (line 510)**: `default=144` → `default=1`, updated help text to mention `process-completed --lookback 144` for manual backfill

### `server/.env`

- `SERVER_HOST="172.16.1.238"` → `SERVER_HOST="0.0.0.0"` — binds on all interfaces, survives boot before DHCP
- `NETWORK_SCAN_STORAGE_DIR="./server/storage/network_scans"` → absolute path `/home/adonis/network-scanner/server/storage/network_scans`

---

## Verification

- Service confirmed `active (running)` immediately after restart.
- Client `DESKTOP-E4KIQ7T` connected and alert fired: `[!] ALERT: Client connected — DESKTOP-E4KIQ7T (E4:FD:45:BA:86:05)`.
- Interval cycle confirmed: each 10-minute tick now processes exactly 1 interval (the one that just closed).
