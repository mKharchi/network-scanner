# Multi-Sensor Wireless Coverage Architecture

## 1. Executive Summary

Following the successful single-sensor pilot (Phase 2), MAC correlation proof of concept (Phase 3), backend investigation service (Phase 4), and UI integration (Phases 5 & 6), this document defines the multi-sensor expansion architecture for comprehensive RF monitoring across the training facility.

A single 802.11 monitor-mode radio provides localized RF visibility (~25–30% of total building devices depending on physical partitions, attenuation, and band allocation). Full facility observability requires distributed passive sensor nodes coordinated with the central network monitoring server.

---

## 2. Distributed Sensor Topology

```text
                                CENTRAL MANAGEMENT SERVER
                           (FastAPI / REST API / SQLite / MySQL)
                                          │
                  ┌───────────────────────┼───────────────────────┐
                  ▼                       ▼                       ▼
          SENSOR NODE 1           SENSOR NODE 2           SENSOR NODE 3
       (Main Lab / Ground)      (East Wing / Server)    (West Wing / Class)
       - wlp0s20f3mon (2.4G)    - wlan1mon (2.4G)       - wlan1mon (2.4G)
       - wlan1mon (5G)          - wlan2mon (5G)         - wlan2mon (5G)
                  │                       │                       │
                  └───────────────┬───────┴───────────────────────┘
                                  ▼
                   SHARED CAPTURE REPOSITORY / STORAGE
                   - /storage/kismet/sensor-1/
                   - /storage/kismet/sensor-2/
                   - /storage/kismet/sensor-3/
```

---

## 3. Sensor Node Specification & Configuration

### 3.1 Hardware & Radio Profile per Node
- **Primary Interface (Management):** Wired Ethernet or dedicated Wi-Fi client connection for control plane and data transfer.
- **Capture Interface 1 (2.4 GHz ISM Band):** Dedicated USB or PCIe monitor adapter locked or hopping across channels 1, 6, 11 (20 MHz width).
- **Capture Interface 2 (5 GHz UNII Band):** Dedicated 802.11ac/ax monitor adapter hopping across UNII-1 (36–48), UNII-2 (52–64), and UNII-3 (149–165).

### 3.2 Sensor Registration & Identity Model
Each remote sensor instance reports its hardware UUID, interface, operational status, and capture path:

```json
{
  "sensor_id": "sensor-ground-lab-01",
  "name": "Ground Floor Main Laboratory",
  "hostname": "kismet-sensor-g1",
  "location": {
    "floor": 1,
    "zone": "Main Laboratory",
    "x_meters": 14.5,
    "y_meters": 8.2
  },
  "interfaces": [
    { "name": "wlan1mon", "band": "2.4GHz", "channels": [1, 6, 11], "driver": "iwlwifi" },
    { "name": "wlan2mon", "band": "5GHz", "channels": [36, 40, 44, 48, 149, 153, 157, 161], "driver": "ath9k_htc" }
  ],
  "status": "ONLINE",
  "last_heartbeat": "2026-09-05T15:25:00Z"
}
```

---

## 4. Multi-Sensor Data Ingestion & Central Service Discovery

The backend `KismetInvestigationService` is configured with multi-directory discovery via `KISMET_CAPTURE_DIRS`:

```bash
KISMET_CAPTURE_DIRS="/storage/kismet/sensor-g1,/storage/kismet/sensor-e2,/storage/kismet/sensor-w1,/home/adonis/kismet"
```

When querying device observations:
1. The backend searches across all active database files from all configured sensor directories.
2. Observations are tagged with `sensor` and `datasource` identifiers.
3. Signal RSSI readings from multiple sensors observing the same packet or MAC are preserved, enabling comparative RF analysis across physical zones.

---

## 5. Coverage Gap Analysis & Validation Protocol

To assess physical and spectrum coverage:
1. **BSSID Visibility Check:** Verify that all facility Access Point BSSIDs are continuously observed with RSSI > -75 dBm on at least one sensor node.
2. **Channel Dwell Time Optimization:** Balance channel hopping intervals (250 ms default) with packet capture rates to minimize missing probe requests.
3. **Known Inventory Correlation:** Run periodic MAC correlation audits (`python3 scripts/correlate_kismet_devices.py`) targeting all 314 known devices. Target coverage metric: **> 85% of active wireless devices**.

---

## 6. Relationship with 3D Spatial Digital Twin & Localization

With multiple sensors recording simultaneous RSSI values for a given device MAC:
- Multi-lateration algorithms can estimate device physical coordinates $(x, y, z)$.
- Observations feed into the existing 3D Spatial Digital Twin (`/spatial`) for real-time visual localization of rogue or unmanaged wireless transmitters.
