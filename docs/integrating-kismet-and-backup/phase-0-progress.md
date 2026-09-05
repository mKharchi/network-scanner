# Phase 0 Progress — Storage Pipeline Audit

## Phase Objective

Determine exactly what happens to the existing raw packet files after they are consumed by the flow-generation pipeline. Ensure no destructive code changes are made prior to complete verification.

---

## Status

- **Status:** COMPLETED
- **Date:** 2026-09-05
- **Deliverable:** [`STORAGE_PIPELINE_AUDIT.md`](file:///home/adonis/network-scanner/docs/integrating-kismet-and-backup/STORAGE_PIPELINE_AUDIT.md)

---

## Key Findings & Verification

1. **Storage Locations Identified:**
   - V1 flat packet capture: `client/storage/passive_packets/YYYY-MM-DD.json`
   - V2 per-protocol packet storage: `client/storage/network_telemetry/<YYYY-MM-DD>/packets/<protocol>.json` (with numbered rotations e.g. `<protocol>.1.json` at 50 MB threshold)

2. **Flow Computation Decoupled from Disk:**
   - Packet capture in `PacketObserver` (`client/app/packet_observer.py`) directly feeds normalized observation records into in-memory `FlowAggregator` (`client/app/flow_aggregator.py`).
   - `FlowAggregator` does **not** read raw packet files from disk. It maintains active 5-tuple conversations in memory and flushes finalized flows to `client/storage/network_telemetry/<YYYY-MM-DD>/flows.json` after an idle timeout (45s default).

3. **Downstream Dependencies Evaluated:**
   - `DeviceEnrichmentJob`: Reads in-memory snapshots from `PassiveProtocolListener` and `DHCPListener` -> writes `devices.json`.
   - `ActivityWindowAggregator`: Reads `flows.json` and `devices.json` -> writes `activity/<start>_<end>.json`.
   - `SyncManager`: Reads `activity/*.json` and `devices.json` -> sends delta payload to central server.
   - `flow_query.py`: Queries `flows.json` on-demand for API requests.
   - Central Server & MySQL: Persist device records and 15-minute activity window aggregates (`telemetry_activity_windows`). Raw packets are never uploaded to the server or stored in MySQL.

4. **Conclusion:**
   - **SAFE TO DELETE AFTER SUCCESSFUL PROCESSING: YES**
   - Raw packet files are write-only capture artifacts that are not required by any downstream features or APIs.

---

## Next Steps

Proceed to **Phase 1 — Implement Bounded Raw-File Retention** to implement automated, configurable, safe retention and pruning of old raw capture files.
