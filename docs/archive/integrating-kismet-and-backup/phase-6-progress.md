# Phase 6 Progress — Connect Kismet Investigation to Alerts

## Phase Objective
Automatically connect a suspicious alert generated in the network monitoring system to the relevant Kismet observation window (`ALERT_KISMET_LOOKBACK_MINUTES=15`). When an alert is detected or viewed by an analyst, resolve the associated suspect device MAC address, calculate the lookback time window centered on the alert detection time, provide structured investigation metadata via REST API, and enable one-click navigation from the Alert detail view directly into the Kismet investigation interface.

---

## Status
- **Status:** COMPLETED
- **Date:** 2026-09-05
- **Key Modules Implemented:**
  - [`server/server_components/api_service.py`](file:///home/adonis/network-scanner/server/server_components/api_service.py) (`_extract_suspect_mac`, `get_alert_detail` enrichment, `get_alert_wireless_investigation`)
  - [`server/api_server.py`](file:///home/adonis/network-scanner/server/api_server.py) (`GET /api/v1/alerts/{alert_id}/wireless-investigation`)
  - [`server/gui/src/api/client.ts`](file:///home/adonis/network-scanner/server/gui/src/api/client.ts) (`getAlertWirelessInvestigation`, `AlertInvestigationRef`)
  - [`server/gui/src/pages/Alerts.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/Alerts.tsx) (Investigate Wireless Activity action button with 15m lookback)
  - [`server/tests/test_kismet_investigation_service.py`](file:///home/adonis/network-scanner/server/tests/test_kismet_investigation_service.py) (Alert investigation unit tests)

---

## Accomplishments & Verification

1. **Suspect MAC & Time-Window Resolution:**
   - Designed `_extract_suspect_mac` in `api_service.py` to resolve MACs from linked client records or alert text headers/descriptions via regex matching.
   - Configurable lookback duration via `ALERT_KISMET_LOOKBACK_MINUTES` environment variable (default: `15` minutes).
   - Computes exact UTC investigation window `[detected_at - lookback_minutes, detected_at]`.

2. **Backend Services & REST Endpoints:**
   - Enriched `get_alert_detail()` to return a structured `kismet_investigation` reference:
     - `suspect_mac`: Formatted MAC address (e.g., `AA:BB:CC:DD:EE:01`).
     - `lookback_minutes`: Configured lookback window in minutes (15).
     - `start_time` & `end_time`: ISO-8601 UTC timestamps.
     - `investigation_url`: Deep-link path to device investigation UI.
   - Added `get_alert_wireless_investigation()` and exposed `GET /api/v1/alerts/{alert_id}/wireless-investigation` to execute targeted Kismet queries directly from an alert ID.

3. **Frontend Alert UI Integration:**
   - In [`server/gui/src/pages/Alerts.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/Alerts.tsx), added an interactive action button on the alert detail panel:
     `📡 Investigate Wireless Activity (Kismet · 15m Lookback) →`
   - Deep-links directly to `/network/devices/{suspect_mac}?tab=investigation&lookback=15m&start={start_time}&end={end_time}`.

4. **Testing & Build Verification:**
   - Frontend built cleanly (`npm run build` in `server/gui`) with zero type errors.
   - Unit tests added in `server/tests/test_kismet_investigation_service.py` covering:
     - Suspect MAC extraction from client records and alert titles.
     - Lookback window calculation.
     - 404 handling for invalid alert IDs.
   - All server and client unit tests pass 100%.

---

## Next Steps
Proceed to **Phase 7 — Multi-Sensor Coverage Architecture** and **Phase 8 — Continuous Processing / ML Evaluation** to complete the rollout plan deliverables.
