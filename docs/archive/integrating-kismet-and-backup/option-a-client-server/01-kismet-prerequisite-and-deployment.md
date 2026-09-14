# Kismet Prerequisite and Deployment Gate

## Purpose

This phase must complete before any Option A TCP implementation. It proves that the target client/sensor environment can install, run, capture, persist, and later query real wireless observations. A `KismetListener` that starts and searches a directory is not evidence that Kismet is installed or capturing.

## Repository findings

The current repository does not provision Kismet:

- `client/app/kismet_listener.py` is a Python background poller for an existing local database directory. It does not launch `kismet`, `kismet_server`, or `kismet_cap`.
- `client/app/client.py` creates `KismetListener()` with the default `client/storage/kismet` path and no observation callback. It does not manage a Kismet process or call a Kismet API.
- No client code generates `kismet.conf`, configures a capture interface, sets monitor mode, checks a Kismet service, or invokes a Kismet REST endpoint.
- `client/requirements.txt`, `client/app/requirements.txt`, `client/NetworkScannerClient.spec`, and `scripts/build_test_update_package.py` package Python client code only. They do not install or ship Kismet binaries, capture drivers, configuration, or databases.
- Existing client installation documentation is Windows-oriented, using PowerShell, Task Scheduler, Windows Firewall, and `C:\NetworkScanner\client`.
- Existing Kismet operational documentation and the pilot report describe a separate Linux sensor with monitor interface `wlp0s20f3mon`.
- Current tests create synthetic `.kismet` SQLite files. They do not launch Kismet, verify a capture source, call Kismet's API, or prove live persistence.

Therefore the current status is **not deployment-ready for client-side Kismet capture**. The existing plan must not assume that a production client has a Kismet database.

## Evidence already available

`docs/integrating-kismet-and-backup/KISMET_SENSOR_PILOT.md` records one successful standalone Linux pilot:

- Kismet `2026.09.0-e24ee9be2`;
- Intel AX201/Killer AX1650i adapter with `iwlwifi`;
- managed interface `wlp0s20f3` and monitor interface `wlp0s20f3mon`;
- Radiotap DLT 127;
- 41.23 minutes of capture;
- 81,969 packets and 104 distinct wireless devices;
- 86 MB `.kismet` SQLite database;
- no capture errors.

This proves the pilot host can capture. It does **not** prove that the managed Windows client fleet can do so, that the pilot database is available to a client agent, or that every target device has compatible hardware and permissions.

A current development-host check found Kismet executables at `/usr/local/bin/kismet`, `/usr/local/bin/kismet_server`, and `/usr/local/bin/kismet_cap_linux_wifi`, but no running Kismet process and no repository `.kismet` capture files. This is an environment observation, not a production-client verification.

## Deployment models to evaluate

### Model A: client agent starts Kismet

Use only if the client operating system, permissions, packaging, capture driver, configuration, and process supervision can support it. The agent would need explicit lifecycle, privilege, crash, upgrade, logging, and storage ownership behavior. The current client architecture has none of these capabilities.

### Model B: Kismet runs independently

A dedicated Linux sensor or separately managed service owns the Kismet daemon and capture interface. The network-scanner client either runs on that sensor or receives the resulting data through a defined local/shared storage arrangement. This matches the current pilot evidence and the repository's existing separation between a Wi-Fi sensor and the Windows client agent.

### Model C: agent ensures an independently installed Kismet service

The agent performs health checks and optionally requests restart through an OS service manager, but does not install or configure Kismet. This is a possible later operational model after ownership and supported platforms are established.

**Provisional recommendation:** use Model B for the first real deployment: a dedicated Linux Kismet sensor, with a clearly defined placement of the client query component and capture directory. Do not silently mount or assume a shared directory. Revisit Model C only after service ownership and permissions are documented. Do not implement Model A without a separate platform feasibility decision.

## Phase 0 verification procedure

Run this procedure on every supported deployment class, separately for the Linux sensor and Windows managed client if both are involved.

### 1. Installation and version

Record:

```text
OS and version:
Kernel or Windows build:
Kismet version:
Capture binary/version:
Package or installation source:
Configuration file path:
Service/unit/task name:
```

Linux checks should include `command -v kismet`, `kismet --version`, package metadata, and the actual configured binary. Windows checks must identify the supported Kismet/capture architecture; do not assume the Linux `kismet_server` binary can run on Windows. If Windows is not a supported Kismet host, document the external Linux sensor and how it is associated with a managed client.

### 2. Configuration and startup

Identify the real startup owner: systemd, init/service manager, container, scheduled task, or manual command. Inspect the effective configuration, including:

- capture source definition and driver (`linuxwifi` or actual platform equivalent);
- interface/device identifier;
- log prefix and database output directory;
- rotation and retention settings;
- Kismet HTTP/API bind address and authentication;
- user/group and required capabilities;
- stderr/stdout and Kismet log location.

Start Kismet using the supported mechanism. Verify the process remains alive beyond startup and record exit status, logs, warnings, and restart behavior. Do not treat `KismetListener.start()` as Kismet startup evidence.

### 3. Capture-interface capability

Record the physical adapter, driver, interface names, bands, channels, monitor-mode support, and whether the adapter can remain connected normally while a separate monitor interface captures. On Linux, use `iw dev`, `iw list`, interface state, and driver/firmware logs. On Windows, determine whether the adapter and supported capture driver provide the required 802.11 monitor capability; Npcap used by other client listeners is not automatically equivalent to Kismet support.

Prefer:

```text
normal connectivity interface
        +
dedicated compatible capture adapter/interface
```

Do not assume that a normal Windows Wi-Fi interface can passively capture all 802.11 frames.

### 4. Runtime and API health

Verify:

- the configured capture source is listed by Kismet;
- the source is enabled and not repeatedly restarting;
- Kismet logs show frames or device activity;
- runtime status/API, if enabled, reports the source as active;
- API access is bound to an approved local/private address and protected by authentication where applicable.

The Kismet API is an operational health and live-data candidate, not automatically the historical source. Record which endpoints and authentication method are actually available before choosing to use it.

### 5. Real capture proof

Run a controlled capture for at least 30 minutes, preferably 60, while known Wi-Fi devices are active. Record their MAC addresses and expected activity. Verify new wireless activity in Kismet, not only in the network-scanner process. Confirm representative frames such as beacons, probes, data, and control frames where the adapter/source supports them.

Collect:

```text
capture start/end UTC:
packets or devices observed:
source/interface:
frame types:
RSSI/signal values:
frequency/channel values:
capture errors:
```

### 6. Persistence proof

Determine the actual output format and location from the effective Kismet configuration and observed files. For the pilot configuration, verify `.kismet` SQLite files and inspect them read-only:

```text
file name and rotation pattern:
directory owner/permissions:
SQLite schema/version:
packets table:
ts_sec/ts_usec:
sourcemac/destmac/transmac:
signal/frequency/packet_len:
datasource/dlt/packet/hash:
datasources table:
```

Confirm that rows are added while Kismet continues running, timestamps are current UTC epoch values, and rows remain queryable after rotation and after Kismet stops. Determine whether WAL/sidecar files exist and when a file is safe to query or archive. Measure MB/hour and retention/rotation behavior.

If the deployed Kismet version uses a different store, API-only history, or a schema incompatible with these fields, stop the `.kismet` query design and update the data-layer plan to the discovered source. Do not create a compatibility assumption.

### 7. Client data-source access

Prove how the future client query component reaches the real source:

```text
Kismet runtime
  -> capture interface
  -> actual persistence/API
  -> query component location
  -> historical query
```

The query component must have read access to the actual database/API from the same machine or through an explicitly designed secure sensor boundary. A server path such as `server/storage/kismet` is not proof of client-local data. A fixed `client/storage/kismet` path is not proof that Kismet writes there.

## Acceptance gate

Option A cannot proceed to TCP protocol implementation until all are true:

- Kismet is installed on the supported sensor environment and its version is recorded.
- Kismet starts through a documented startup mechanism and remains running.
- A real compatible capture source is identified and accessible.
- Monitor/capture mode and required permissions are proven.
- New wireless frames are observed during a controlled run.
- Timestamps and required MAC/RSSI/frequency/frame fields are present.
- The actual persistence format, path, schema, rotation, and retention are documented.
- Records increase during capture and remain available for a historical window.
- The query component can access the actual source without assuming nonexistent files.
- Windows-client versus Linux-sensor ownership is explicitly resolved.
- The Kismet API decision is documented: use for health/live data, historical data, both, or neither, with reasons.

Synthetic SQLite unit tests do not satisfy this gate.

## Phase outcomes

- **Pass:** freeze the discovered runtime/storage contract and continue to the client integration phase.
- **Blocked:** do not implement TCP Kismet requests. Resolve installation, source, permissions, storage, or platform ownership first.
- **Different source discovered:** revise the historical query design before any protocol work.

## Related evidence

- `docs/fix_kismet/readme.md` describes the current zero-database failure and manual Linux Kismet command.
- `docs/integrating-kismet-and-backup/KISMET_SENSOR_PILOT.md` records the successful Linux pilot.
- `docs/integrating-kismet-and-backup/plan.md` contains the earlier standalone sensor and retention plan.
- `client/installation_guide.md` documents the current Windows client installation but not Kismet installation.
