# Kismet Passive Wireless Investigation — Pipeline Audit & Fix Report

> **Status:** Bugs identified and fixed. All 11 unit tests passing.
> **Branch:** `fix/Client_Monitoring`
> **Date:** 2026-09-06

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [End-to-End Pipeline Architecture](#end-to-end-pipeline-architecture)
3. [Layer 1 — Kismet Capture Daemon](#layer-1--kismet-capture-daemon)
4. [Layer 2 — Client Kismet Listener](#layer-2--client-kismet-listener)
5. [Layer 3 — Server Investigation Service](#layer-3--server-investigation-service)
6. [Layer 4 — REST API and React UI](#layer-4--rest-api-and-react-ui)
7. [Root Cause Analysis — Why No Observations Appear](#root-cause-analysis--why-no-observations-appear)
8. [Fixes Applied in This Session](#fixes-applied-in-this-session)
9. [How to Run Kismet and Populate Data](#how-to-run-kismet-and-populate-data)
10. [Verification Checklist](#verification-checklist)
11. [File Reference Map](#file-reference-map)

---

## Executive Summary

The **Kismet Passive Wireless Investigation** window on the Device Detail page shows
"No wireless observations in time window" regardless of the time filter selected.
This is not a UI bug. The failure happens before the UI even gets a chance to display
data — **there are zero `.kismet` SQLite database files on disk** for the server to
query, and several secondary bugs would have prevented correct results even if files
did exist.

### Root causes (priority order)

| # | Root Cause | Severity |
|---|-----------|----------|
| 1 | Kismet daemon has never been run; no `.kismet` files exist | **Critical** |
| 2 | Server did not search `client/storage/kismet` (where the listener writes) | High |
| 3 | SQLite MAC comparison is case-sensitive; Kismet uses lowercase MACs | High |
| 4 | Default 15-minute lookback filters out historical captures | Medium |

All bugs except #1 (which requires actually running Kismet) have been fixed in code.

---

## End-to-End Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│KISMET PACKET PIPELINE   │
│ │
│  LAYER 1 — Kismet Capture Daemon  (wlp0s20f3mon / monitor mode)│
│ │
│  kismet_server --source=wlp0s20f3:type=linuxwifi   │
│   | │
│   └──► writes *.kismet SQLite DBs ──► storage/kismet/  │
│ |   │
│  LAYER 2 — Client KismetListener  (client/app/kismet_listener.py)  │
│ │
│  Polls kismet_db_dir for new *.kismet files every 5 s  │
│  Decodes rows from packets table│
│  Calls observation_callback(dict) if set (currently None)  │
│  Reports health: NOT_STARTED / RUNNING / FAILED│
│ │
│  (INDEPENDENT — does NOT forward packets to server over TCP)   │
│ │
│  LAYER 3 — Server KismetInvestigationService   │
│(server/server_components/kismet_service.py)│
│ │
│  find_kismet_database_files()   │
│   searches: /home/adonis/kismet │
│ /home/adonis │
│ server/storage/kismet│
│ client/storage/kismet  (added in fix)   │
│ storage/kismet (added in fix)   │
│ /var/log/kismet(added in fix)   │
│ $KISMET_CAPTURE_DIRS env var│
│ │
│  resolve_device(mac_or_id) -> MySQL -> fallback JSON -> direct MAC │
│ │
│  query_wireless_observations(mac, time_window)  │
│   opens each *.kismet file in read-only SQLite  │
│   SELECT … FROM packets WHERE sourcemac = ? COLLATE NOCASE …   │
│   applies time-range filter (or "all" = no filter)  │
│   decodes 802.11 frame headers from raw bytes   │
│   returns normalized observation dicts  │
│   | │
│  LAYER 4 — REST API + React UI  │
│ │
│  GET /api/v1/devices/{mac}/wireless-observations│
│   ?lookback=15m | 30m | 1h | 6h | 24h | 7d | all   │
│ │
│  WirelessInvestigationPanel.tsx │
│   renders timeline, RSSI chart, frame-type breakdown   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key architectural note

Layers 2 and 3 are **independent and decoupled**. The `KismetListener` on the client
does not forward packets to the server over the TCP socket. Instead:

- The **client listener** reads `.kismet` files locally for optional real-time
  callbacks (`observation_callback=None` in `client/app/client.py` — future enhancement).
- The **server investigation service** also reads `.kismet` files directly from disk.
- Both sides must be able to reach the same `.kismet` files (shared filesystem or by
  placing files in a path both can access).

---

## Layer 1 — Kismet Capture Daemon

### What it is

Kismet is an open-source passive 802.11 wireless sniffer. When running, it:

1. Places the wireless interface into **monitor mode** (`wlp0s20f3mon`).
2. Captures all 802.11 management, control, and data frames over the air.
3. Writes everything to a **`.kismet` SQLite database** in its current working
   directory (or the `log_prefix` from `kismet_logging.conf`).

### Schema of the `packets` table (inside a `.kismet` file)

```sql
CREATE TABLE packets (
ts_sec  INTEGER,   -- Unix epoch seconds of capture
ts_usec INTEGER,   -- Microsecond component
phyname TEXT,  -- Physical layer ("IEEE802.11")
sourcemac   TEXT,  -- Source MAC address (LOWERCASE: "aa:bb:cc:dd:ee:ff")
destmac TEXT,  -- Destination MAC address (lowercase)
transmacTEXT,  -- Transmitter MAC address (lowercase)
signal  REAL,  -- RSSI in dBm (negative, e.g. -57.0)
frequency   REAL,  -- Channel frequency in kHz (e.g. 5220000.0)
packet_len  INTEGER,   -- Raw frame length in bytes
datasource  TEXT,  -- Capture interface name ("wlp0s20f3mon")
dlt INTEGER,   -- Data link type (127 = LINKTYPE_IEEE802_11_RADIOTAP)
packet  BLOB,  -- Raw frame bytes including Radiotap header
hashINTEGER-- Packet content hash
);
```

> **Important:** Kismet stores MAC addresses in **lowercase** (`aa:bb:cc:dd:ee:ff`).
> This is non-negotiable — it is how Kismet formats all MAC fields in its SQLite output.

### Where Kismet writes its files

By default, Kismet writes `.kismet` files into the **current working directory** when
`kismet_server` is launched. This is controlled by `/usr/local/etc/kismet_logging.conf`:

```ini
log_prefix=./
```

To write into a known location that the server can find:

```bash
sudo kismet_server \
  --source=wlp0s20f3:type=linuxwifi \
  --override "log_prefix=/home/adonis/network-scanner/client/storage/kismet/"
```

Or set the environment variable:

```bash
export KISMET_CAPTURE_DIRS=/home/adonis/network-scanner/client/storage/kismet
```

---

## Layer 2 — Client Kismet Listener

**File:** `client/app/kismet_listener.py`

### What it does

`KismetListener` is a background thread that:

1. Watches `kismet_db_dir` (default: `client/storage/kismet`) for new `.kismet` files.
2. Opens each file in read-only SQLite mode.
3. Reads rows from the `packets` table in a sliding cursor (tracking which rows it
   has already processed via an in-memory offset per file).
4. Optionally calls `observation_callback(dict)` for each new packet.
5. Reports lifecycle states: `NOT_STARTED → STARTING → RUNNING → STOPPED/FAILED`.

### Lifecycle states

```
NOT_STARTED
 |
 v  start()
STARTING
 |  (db_dir exists, files found)
 v
RUNNING ──────────────────────────────► STOPPING ──► STOPPED
 |   ^
 |  (error: db_dir missing, corrupt db)  | stop()
 v   |
FAILED ─────────────────────────────────────────────┘
```

### Current wiring in `client/app/client.py`

```python
kismet_listener = KismetListener()   # observation_callback=None (not connected yet)
```

The listener is instantiated but the callback is not connected — real-time forwarding
is a future enhancement (Phase 5 of the integration plan). The primary investigation
path is the server querying `.kismet` files directly (Layer 3).

---

## Layer 3 — Server Investigation Service

**File:** `server/server_components/kismet_service.py`

### What it does

`KismetInvestigationService` provides on-demand wireless investigation by:

1. **`find_kismet_database_files()`** — Scans all configured directories for `*.kismet`.
2. **`resolve_device(identifier)`** — Converts a device MAC, ID, or IP into a canonical
   uppercase MAC address (MySQL lookup → fallback JSON scan → direct MAC parse).
3. **`query_wireless_observations(mac, time_window)`** — Queries the `packets` table in
   every discovered `.kismet` file and returns normalized observation dicts.

### Capture directory search order (after fix)

```python
[
Path("/home/adonis/kismet"),
Path("/home/adonis"),
server_root / "storage" / "kismet",
repo_root / "client" / "storage" / "kismet",   # ADDED
repo_root / "storage" / "kismet",   # ADDED
Path("/var/log/kismet"),# ADDED
]
```

Override all paths via environment variable:

```bash
export KISMET_CAPTURE_DIRS="/data/kismet,/backup/kismet"
```

### Time window resolution

| API parameter | Effect |
|---|---|
| `lookback=15m` | `start = now − 15 min` (default) |
| `lookback=all` | No time filter — returns every packet in file |
| `start=<ISO>&end=<ISO>` | Explicit absolute time range |
| `start=<epoch>&end=<epoch>` | Epoch seconds also accepted |

---

## Layer 4 — REST API and React UI

### Endpoint

```
GET /api/v1/devices/{deviceMac}/wireless-observations
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `lookback` | string | `15m` | `15m`, `30m`, `1h`, `6h`, `24h`, `7d`, `all` |
| `start` | string | — | ISO 8601 or epoch seconds |
| `end` | string | — | ISO 8601 or epoch seconds |
| `include_noise` | bool | `false` | Include ACK/CTS/RTS/Block Ack control frames |
| `limit` | int | `500` | Max observations returned (cap: 2000) |

**Route:** `server/api_server.py` (~line 503)
**Handler:** `server/server_components/api_service.py` → `KismetInvestigationService.

query_wireless_observations`

### React UI

**File:** `server/gui/src/components/WirelessInvestigationPanel.tsx`
**Mounted in:** `server/gui/src/pages/DeviceDetail.tsx` (tab: `investigation`)

The panel calls `api.getDeviceWirelessObservations(deviceMac, { lookback, ... })`,
then renders a signal timeline, frame-type donut chart, and observation table.

---

## Root Cause Analysis — Why No Observations Appear

### Bug #1 — CRITICAL: No `.kismet` files exist on disk

**Symptom:** Any time filter selected → "No wireless observations in time window".

**Root cause:** `find_kismet_database_files()` returns an empty list because no
`.kismet` files have ever been written to any searched directory. Kismet must be
actively running (or a previous capture file must be placed in a known directory)
to produce them.

**Evidence:**

```bash
$ find / -name "*.kismet" 2>/dev/null
# (no output — zero files found anywhere on the system)

$ ls /home/adonis/kismet # directory does not exist
$ ls client/storage/kismet   # directory does not exist
$ ls /var/log/kismet # directory does not exist
```

**Fix required:** Run Kismet as described in the section below.

---

### Bug #2 — HIGH: Server did not search the client listener's output directory

**Symptom:** Even after Kismet runs, if it writes files into `client/storage/kismet`
(the `KismetListener` default), the server would not find them.

**Root cause:** The original `capture_dirs` list was missing `client/storage/kismet`.

**Fix applied:** Added `repo_root / "client" / "storage" / "kismet"` to the search list.

---

### Bug #3 — HIGH: SQLite case-sensitive MAC comparison

**Symptom:** Zero results even when `.kismet` files exist and contain the target device.

**Root cause:** Kismet stores MACs in lowercase (`aa:bb:cc:dd:ee:ff`). The server
resolves device MACs to uppercase (`AA:BB:CC:DD:EE:FF`). In SQLite, text `=`
comparison is **case-sensitive by default**.

```sql
-- BEFORE (broken)
WHERE (sourcemac = ? OR destmac = ? OR transmac = ?)
-- Query: 'AA:BB:CC:DD:EE:FF' vs stored: 'aa:bb:cc:dd:ee:ff' → NO MATCH

-- AFTER (fixed)
WHERE (sourcemac = ? COLLATE NOCASE
OR destmac   = ? COLLATE NOCASE
OR transmac  = ? COLLATE NOCASE)
-- Query: 'AA:BB:CC:DD:EE:FF' vs stored: 'aa:bb:cc:dd:ee:ff' → MATCH
```

**Test added:** `test_case_insensitive_mac_matching` in
`server/tests/test_kismet_investigation_service.py`

---

### Bug #4 — MEDIUM: 15-minute lookback filters out historical captures

**Symptom:** Pilot capture from 2026-09-05 shows 0 results with `lookback=15m`.

**Root cause:** The default lookback computes `start = now − 15min`. A packet from
yesterday has `ts_sec` far outside this window and is excluded.

**Fix applied:** Added `'All Available Captures'` (value=`all`) as the first option
in the time filter dropdown. Selecting it disables the time filter entirely.

---

## Fixes Applied in This Session

### 1. `server/server_components/kismet_service.py`

**a) Expanded `capture_dirs`:**

```python
server_root = Path(__file__).resolve().parents[1]
repo_root = Path(__file__).resolve().parents[2]
self.capture_dirs = [
Path("/home/adonis/kismet"),
Path("/home/adonis"),
server_root / "storage" / "kismet",
repo_root / "client" / "storage" / "kismet",   # added
repo_root / "storage" / "kismet",   # added
Path("/var/log/kismet"),# added
]
```

**b) Added `COLLATE NOCASE` to MAC comparisons:**

```sql
WHERE (sourcemac = ? COLLATE NOCASE
OR destmac   = ? COLLATE NOCASE
OR transmac  = ? COLLATE NOCASE)
```

### 2. `server/gui/src/components/WirelessInvestigationPanel.tsx`

```typescript
const LOOKBACK_OPTIONS = [
  { label: 'All Available Captures', value: 'all' },   // added
  { label: 'Last 15 Minutes (Default)', value: '15m' },
  ...
]
```

### 3. `server/tests/test_kismet_investigation_service.py`

Added `test_case_insensitive_mac_matching` to verify uppercase query matches
lowercase stored MAC.

### Test results

```
$ python3 -m unittest server/tests/test_kismet_investigation_service.py

Ran 11 tests in 0.569s

OK
```

---

## How to Run Kismet and Populate Data

### Step 1 — Create the storage directory

```bash
mkdir -p /home/adonis/network-scanner/client/storage/kismet
```

### Step 2 — Run Kismet (directs output to the known search path)

```bash
sudo kismet_server \
  --source=wlp0s20f3:type=linuxwifi \
  --override "log_prefix=/home/adonis/network-scanner/client/storage/kismet/" \
  --no-ncurses
```

Kismet will create files like:

```
client/storage/kismet/Kismet-20260906-14-30-00-1.kismet
```

### Step 3 — Verify the file is found by the server

```python
import sys; sys.path.insert(0, 'server')
from server_components.kismet_service import KismetInvestigationService
svc = KismetInvestigationService()
print(svc.find_kismet_database_files())
# Expected: [PosixPath('.../client/storage/kismet/Kismet-....kismet')]
```

### Step 4 — Open the Device Detail page

1. Navigate to any device that was on the Wi-Fi network during capture.
2. Click the **Kismet Passive Wireless Investigation** tab.
3. Select **All Available Captures** from the time filter dropdown.
4. Click **Run Investigation**.

### Alternative — Use the existing pilot capture

The pilot session from 2026-09-05 captured 81,969 packets in an 86 MB `.kismet` file.
Copy it into any of the search directories:

```bash
cp /path/to/Kismet-20260905-12-14-56-1.kismet \
   /home/adonis/network-scanner/client/storage/kismet/
```

Then query device `B0:3C:DC:95:39:36` (Pilot Host, 96,372 packets) with
**All Available Captures**.

---

## Verification Checklist

After placing a `.kismet` file in a known directory:

- [ ] `svc.find_kismet_database_files()` returns at least one path
- [ ] `GET /api/v1/devices/{mac}/wireless-observations?lookback=all` returns `observation_count > 0`
- [ ] UI shows observations when **All Available Captures** is selected
- [ ] Querying with uppercase MAC matches Kismet lowercase MAC rows (COLLATE NOCASE fix)
- [ ] Time filter `lookback=1h` correctly limits to recent packets during a live capture
- [ ] `include_noise=true` adds ACK/CTS/Block Ack frames to the results

---

## File Reference Map

| Component | File |
|---|---|
| Kismet capture daemon config | `/usr/local/etc/kismet_logging.conf` |
| Client Kismet listener | `client/app/kismet_listener.py` |
| Client wiring | `client/app/client.py` |
| Server investigation service | `server/server_components/kismet_service.py` |
| API route registration | `server/api_server.py` |
| API service handler | `server/server_components/api_service.py` |
| React panel component | `server/gui/src/components/WirelessInvestigationPanel.tsx` |
| DeviceDetail page (tab mount) | `server/gui/src/pages/DeviceDetail.tsx` |
| Investigation service tests | `server/tests/test_kismet_investigation_service.py` |
| Integration plan | `docs/integrating-kismet-and-backup/plan.md` |
| MAC correlation report | `docs/integrating-kismet-and-backup/KISMET_MAC_CORRELATION.md` |
| Pilot sensor report | `docs/integrating-kismet-and-backup/KISMET_SENSOR_PILOT.md` |
