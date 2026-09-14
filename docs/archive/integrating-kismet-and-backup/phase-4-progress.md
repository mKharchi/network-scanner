# Phase 4 Progress — Build the Kismet Investigation Service

## Phase Objective

Expose Kismet wireless observations through the central application's backend REST APIs without copying complete raw packet captures into MySQL. The user/analyst selects a device (or provides device identifier/MAC), and the backend queries relevant Kismet databases, handles 802.11 frame and address parsing, applies lookback/time-window filtering, performs noise filtering, and returns structured observation timelines with signal, channel, and frame metadata.

---

## Status

- **Status:** COMPLETED
- **Date:** 2026-09-05
- **Key Modules Implemented:**
  - [`server/server_components/kismet_service.py`](file:///home/adonis/network-scanner/server/server_components/kismet_service.py) (`KismetInvestigationService`)
  - [`server/server_components/api_service.py`](file:///home/adonis/network-scanner/server/server_components/api_service.py) (`get_device_wireless_observations`, `list_wifi_sensors`)
  - [`server/api_server.py`](file:///home/adonis/network-scanner/server/api_server.py) (`GET /api/v1/devices/{device_id}/wireless-observations`, `GET /api/v1/devices/{device_id}/network-observations`, `GET /api/v1/sensors/wifi`)
  - [`server/tests/test_kismet_investigation_service.py`](file:///home/adonis/network-scanner/server/tests/test_kismet_investigation_service.py)

---

## Accomplishments & Verification

1. **Investigation Service Architecture:**
   - Designed and built `KismetInvestigationService` in [`server/server_components/kismet_service.py`](file:///home/adonis/network-scanner/server/server_components/kismet_service.py).
   - Dynamically discovers `.kismet` sqlite capture databases across configured sensor paths (`KISMET_CAPTURE_DIR`, `/home/adonis/kismet`, `/home/adonis`).
   - Parses IEEE 802.11 frame control bytes with automatic Radiotap header length offset detection (DLT 127).
   - Determines 802.11 frame categories: Management (Beacon, Probe Request/Response, Assoc), Data (Data, QoS Data, Null, QoS Null), and Control (ACK, CTS, RTS, Block Ack).
   - Extracts device role relative to the frame: `source`, `destination`, `transmitter`, `receiver`, or `bssid`.
   - Normalizes signal RSSI (dBm), channel, frequency (MHz), frame size, and timestamps.
   - Intelligent noise filtering: Omits high-frequency non-identifying control frames (ACK, CTS, Block Ack) by default unless `include_noise=True`.

2. **REST API Endpoints:**
   - `GET /api/v1/devices/{device_id}/wireless-observations`:
     - Resolves device by ID, MAC, or IP from network scanner storage.
     - Supports query parameters: `lookback` (e.g., `15m`, `30m`, `1h`, `24h`), `start` (ISO timestamp), `end` (ISO timestamp), `include_noise` (bool), and `limit` (int).
     - Returns summary metrics: total observations, first/last seen timestamps, average/min/max RSSI, active channels, and structured frame timeline.
   - `GET /api/v1/devices/{device_id}/network-observations`: Compatible alias endpoint matching the plan specification.
   - `GET /api/v1/sensors/wifi`: Returns registered/discovered Wi-Fi sensor nodes, capture paths, active databases, total packets, and time spans.

3. **Testing & Verification:**
   - Comprehensive test suite created in [`server/tests/test_kismet_investigation_service.py`](file:///home/adonis/network-scanner/server/tests/test_kismet_investigation_service.py).
   - Validated:
     - Synthetic .kismet database queries and frame parsing.
     - Device ID resolution and MAC matching.
     - Time lookback window filtering (`lookback=15m`, custom start/end).
     - Noise filtering behavior (`include_noise=false` vs `include_noise=true`).
     - Sensor discovery and status reporting.
     - REST API route integration.
   - All server tests pass with 100% success rate.

---

## Next Steps

Proceed to **Phase 5 — Add Device Investigation UI**:

- Build the investigation view/tab in the Tauri / React frontend (`server/gui`).
- Add time range selectors (`15m`, `30m`, `1h`, `24h`, custom), summary cards (packet counts, RSSI metrics, channel distribution), and searchable/filterable observation timeline tables.
