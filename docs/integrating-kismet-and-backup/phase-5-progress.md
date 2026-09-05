# Phase 5 Progress — Add Device Investigation UI

## Phase Objective
Allow security analysts and network administrators to investigate a device directly from the existing device-detail page in the Tauri/React GUI application. The interface provides time-windowed queries (`15m`, `30m`, `1h`, `4h`, `24h`, custom), noise filtering controls, RF signal strength summaries, active 802.11 channel distribution, 802.11 frame subtype breakdowns, and a detailed chronological observation timeline with search, role filtering, and CSV/JSON export capabilities.

---

## Status
- **Status:** COMPLETED
- **Date:** 2026-09-05
- **Key Modules Implemented:**
  - [`server/gui/src/components/WirelessInvestigationPanel.tsx`](file:///home/adonis/network-scanner/server/gui/src/components/WirelessInvestigationPanel.tsx) (`WirelessInvestigationPanel`)
  - [`server/gui/src/pages/DeviceDetail.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/DeviceDetail.tsx) (`DeviceDetailPage` tab navigation & URL deep-linking)
  - [`server/gui/src/api/client.ts`](file:///home/adonis/network-scanner/server/gui/src/api/client.ts) (`getDeviceWirelessObservations`, `getWifiSensors`, TypeScript types)

---

## Accomplishments & Verification

1. **Investigation Panel Component:**
   - Built [`server/gui/src/components/WirelessInvestigationPanel.tsx`](file:///home/adonis/network-scanner/server/gui/src/components/WirelessInvestigationPanel.tsx).
   - Time window presets: Last 15 Minutes (Default), Last 30 Minutes, Last 1 Hour, Last 4 Hours, Last 24 Hours, and Custom Start/End UTC datetime inputs.
   - Limit selector: 100, 250, 500, 1000 frames.
   - Noise filtering toggle: Controls omission/inclusion of 802.11 ACK/CTS frames.
   - Summary stat cards: Total matched observation frames, average RSSI (with Excellent/Good/Fair/Weak quality badges), RSSI range (min/max), active channels (2.4 GHz & 5 GHz bands), and noise filtering status.
   - Interactive frame subtype breakdown chips: One-click filtering by frame subtype (e.g. `QoS Data`, `Probe Request`, `Beacon`).
   - Client-side filtering: Real-time search across MACs, frame types, sensors, and channels, plus role dropdown selector (`ALL`, `SOURCE`, `TRANSMITTER`, `DESTINATION`).
   - Export tools: One-click CSV and JSON export of queried wireless observations.

2. **Device Detail Page Integration:**
   - Updated [`server/gui/src/pages/DeviceDetail.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/DeviceDetail.tsx) with clean tab navigation:
     - `Overview & Identity` (with quick CTA to launch 15m investigation)
     - `Network Intelligence & Telemetry` (TLS/SNI, DNS, JA3, ASN destinations, traffic profiles)
     - `📡 Kismet Wireless Investigation` (renders `WirelessInvestigationPanel`)
   - Supports search parameters (`?tab=investigation&lookback=15m&start=...&end=...`) to allow instant deep linking from alerts or external links.

3. **Compilation & Build Verification:**
   - Built frontend with `tsc && vite build` (`npm run build` in `server/gui`).
   - Succeeded with 0 TypeScript/compilation errors.

---

## Next Steps
Proceed to **Phase 6 — Connect Kismet Investigation to Alerts** to wire suspicious alert events to automatic 15-minute lookback investigation windows.
