# Storage Pipeline Audit

## Executive Summary

This audit investigates the existing packet capture and storage pipeline in the network monitoring client and server to determine whether raw packet capture files are required by downstream features and whether they can be safely deleted or pruned.

---

## Storage Pipeline Trace

```text
[Network Interface]
       │
       ▼ (Scapy sniff in PacketObserver)
[Normalized Packet Observation (in-memory dict)]
       ├──► DailyPacketStorage ──────────────► client/storage/passive_packets/YYYY-MM-DD.json (V1 flat log)
       ├──► TelemetryPacketWriter ──────────► client/storage/network_telemetry/<date>/packets/<proto>.json (V2 protocol logs)
       └──► FlowAggregator (in-memory)
                 │
                 ▼ (Sweep idle timeout: 45s)
            [Finalized Flow Record] ────────► client/storage/network_telemetry/<date>/flows.json
                 │
                 ▼ (Every 15 minutes)
            ActivityWindowAggregator ────────► client/storage/network_telemetry/<date>/activity/<HH-MM>_<HH-MM>.json
                 │
                 ▼
            SyncManager (Delta payload) ─────► [Central Server]
                                                     │
                                                     ▼
                                            MySQL Database:
                                            - telemetry_devices
                                            - telemetry_activity_windows
                                            - network_devices
                                            - network_device_observations
```

---

## Detailed Pipeline Audit Findings

### 1. Raw Capture Locations
- **V1 Legacy Storage:** `client/storage/passive_packets/YYYY-MM-DD.json`
- **V2 Protocol Telemetry Storage:** `client/storage/network_telemetry/<YYYY-MM-DD>/packets/<protocol>.json` (e.g. `tcp.json`, `udp.json`, `arp.json`, `mdns.json`, `llmnr.json`, `nbns.json`, `ssdp.json`, `dhcp.json`)

### 2. File Format & Naming Convention
- **Format:** UTF-8 encoded JSON.
  - V1 format: JSON object `{"date": "YYYY-MM-DD", "observer_client_id": "...", "packet_count": N, "packets": [ ... ]}`.
  - V2 format: JSON array `[ { ... }, { ... } ]` managed by `RotatingJSONAppendStore`.
- **Naming:**
  - V1: `YYYY-MM-DD.json`
  - V2: `<protocol>.json`, rotated on file size threshold (`TELEMETRY_FILE_MAX_BYTES`, default 50 MB) to `<protocol>.1.json`, `<protocol>.2.json`, etc.

### 3. Writers
- **V1:** `PacketObserver` (`client/app/packet_observer.py`) -> `DailyPacketStorage.record_observation()` (`client/app/packet_storage.py`). Flushed every 5.0 seconds or 50 packets via atomic temp file replacement.
- **V2:** `PacketObserver` (`client/app/packet_observer.py`) -> `TelemetryPacketWriter.record()` (`client/app/telemetry_packet_writer.py`) using `RotatingJSONAppendStore` (`client/app/telemetry_storage.py`).

### 4. Readers
- **Live-flush readers only:**
  - `DailyPacketStorage._flush_locked` reads `YYYY-MM-DD.json` during a flush to deserialize the array and append new observations.
  - `RotatingJSONAppendStore.append_many` reads the active file if size is under the rotation threshold to append records.
- **Post-processing readers:** **NONE**.
  - `FlowAggregator` (`client/app/flow_aggregator.py`) receives live observations directly in memory from `PacketObserver._handle_packet()`. It does **not** read raw packet files.
  - `DeviceEnrichmentJob` (`client/app/device_enrichment.py`) pulls in-memory snapshots from `PassiveProtocolListener.correlator` and `DHCPListener`. It does **not** read raw packet files.
  - `ActivityWindowAggregator` (`client/app/activity_window_aggregator.py`) only reads `flows.json` and `devices.json`.
  - `SyncManager` (`client/app/sync_manager.py`) only reads activity window files (`activity/*.json`) and `devices.json`.
  - `flow_query.py` (`client/app/flow_query.py`) only reads `flows.json` and rotated `flows.N.json`.

### 5. Flow Computation & Scheduled Jobs
- **Flow Aggregator:** In-memory tracking with a sweep thread running every 5 seconds (`DEFAULT_SWEEP_INTERVAL_SECONDS = 5.0`) that finalizes flows idle for ≥ 45 seconds (`DEFAULT_FLOW_IDLE_TIMEOUT_SECONDS = 45.0`) to `flows.json`.
- **Device Enrichment Job:** Background thread executing every 5 minutes (`DEFAULT_ENRICHMENT_INTERVAL_SECONDS = 300.0`).
- **Activity Window Aggregator:** Background thread executing every 15 minutes (`DEFAULT_WINDOW_SECONDS = 900.0`), producing per-device 15-minute summaries.
- **Delta Sync:** Triggered on activity window close (every 15 minutes).

### 6. Database Persistence
- Server persists:
  - Device inventory & discovery state in `telemetry_devices` and `network_devices`.
  - 15-minute activity summaries in `telemetry_activity_windows` (storing `flow_count`, `packet_count`, `bytes`, `protocols_json`, `ports_json`, `connections_json`, `unique_destinations`).
- Server does **not** persist individual raw packets or individual flow rows in MySQL.
- Full flow details remain on client storage (`flows.json`) and are fetched on demand via the REST API endpoint `GET /api/v1/clients/{client_id}/devices/{mac}/flows?window=...`.

### 7. Downstream Feature Requirements
- The flow model (`_ActiveFlow` -> `flow.to_record()`) captures 26 key attributes:
  - Identifiers: `flow_id`, `observer_client_id`
  - Timestamps: `first_seen`, `last_seen`, `duration`
  - Network 5-tuple: `src_mac`, `src_ip`, `dst_mac`, `dst_ip`, `src_port`, `dst_port`, `protocol`
  - Classification: `application_protocol`, `direction`
  - Metrics: `packet_count`, `bytes`, `avg_packet_size`, `min_packet_size`, `max_packet_size`, `avg_inter_arrival_time`
  - TCP flags: `tcp_syn`, `tcp_fin`, `tcp_rst`
  - Directional breakdown: `inbound_packets`, `outbound_packets`, `inbound_bytes`, `outbound_bytes`
- This retains all data required by downstream activity aggregation, telemetry sync, and analyst investigations.

### 8. Failure Behavior & Retry Capabilities
- **Packet Observer -> Flow Aggregator:** Fail-safe `try...except` prevents sniffer crashes if flow aggregation encounters transient errors.
- **Flow Persistence:** `FlowAggregator` logs warnings on disk errors.
- **Activity Window / Sync:** `SyncManager` persists pending delta payloads to `storage/network_telemetry/sync_pending/<window_hash>.json` and performs exponential backoff retries with durable state on restart (`retry_pending()`).

### 9. Storage Size & Growth Rate
- **Current test folder size:** ~0 MB (test environment).
- **Estimated operational growth rate (active production client @ 50–200 packets/sec):**
  - Raw packet logs (V1/V2): ~2 to 5 GB / day / client.
  - Finalized flows (`flows.json`): ~10 to 50 MB / day / client.
  - Activity windows (`activity/*.json`): ~1 to 2 MB / day / client (96 small JSON files).
- **Storage Risk:** Unbounded accumulation of raw packet files will rapidly consume disk space across deployed endpoints (e.g. 25 clients × 3 GB/day = 75 GB/day).

---

## Formal Audit Questionnaire

| Item | Question | Audit Answer |
|---|---|---|
| 1 | Raw capture location | `client/storage/passive_packets/` and `client/storage/network_telemetry/<date>/packets/` |
| 2 | Raw file format | UTF-8 JSON (V1 root object with `packets` array; V2 raw JSON array) |
| 3 | Raw file naming convention | `YYYY-MM-DD.json` (V1) / `<protocol>.json`, `<protocol>.<N>.json` (V2) |
| 4 | Writer | `PacketObserver` (`DailyPacketStorage` and `TelemetryPacketWriter`) |
| 5 | Reader | Internal flush-append routines only; **no external readers** |
| 6 | Flow computation job | `FlowAggregator` in-memory real-time streaming pipeline |
| 7 | Flow interval | 45-second idle timeout, 5-second sweep, 15-minute activity window aggregation |
| 8 | Database persistence | MySQL `telemetry_activity_windows`, `telemetry_devices`, `network_devices` |
| 9 | Post-processing readers | None |
| 10 | Forensic / replay usage | None |
| 11 | API / UI usage | None (API queries `flows.json` via `flow_query.py`) |
| 12 | File uploads to server | None (raw packets never sent across network) |
| 13 | Downstream sufficiency | Flow model fully retains all necessary conversation and protocol metadata |
| 14 | Failure behavior | In-memory exception handling; durable pending queue in `SyncManager` |
| 15 | Safe retry ability | Flow aggregation is real-time stream; delta sync is fully durable and idempotent |
| 16 | Current storage size | Minimal in testbed; unbounded in production without cleanup |
| 17 | Estimated daily growth | ~2–5 GB/day raw packets per client vs ~15–50 MB/day for flows and activity windows |

---

## Conclusion

```text
SAFE TO DELETE AFTER SUCCESSFUL PROCESSING: YES
```

**Justification:**
Raw packet files (`client/storage/passive_packets/*.json` and `client/storage/network_telemetry/<date>/packets/*.json`) are intermediate write-only capture artifacts. The flow generation engine computes flow metrics in real-time in memory as packets are sniffed. All downstream services (Device Enrichment, Activity Window Aggregator, Delta Sync Manager, REST Flow Query API, Central Server MySQL) consume `flows.json`, `devices.json`, or `activity/*.json`. Raw packet files are never referenced by any analytical, forensic, API, UI, or synchronization component. Implementing bounded retention and automated cleanup for raw capture files is safe and necessary to prevent disk exhaustion.
