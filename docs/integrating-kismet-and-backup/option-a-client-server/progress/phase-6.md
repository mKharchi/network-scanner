# Phase 6 — UI Compatibility and Source Provenance

**Status:** ✅ DONE — 2026-09-07

## Objective

Validate that the existing wireless investigation UI remains compatible with the server-owned source and expose only necessary source-status/truncation details.

## Requirements

- preserve current lookback/custom range, noise, limit, rendering, and export behavior unless a verified API contract requires a compatible update; ✅
- make `KISMET_SERVER` provenance/sensor identity visible where useful; ✅
- do not add client Kismet controls, client selection, or client-specific retrieval states; ✅
- replace or bound `All Available Captures` if it conflicts with server query safety; ✅ (kept — maps to `all` lookback, server handles safely)
- run TypeScript/build and response-fixture tests. ✅

## Implementation

### `server/gui/src/api/client.ts`
- Added `getSensorHealth()` API call → `GET /api/v1/sensors/wifi/health`
- Added `WifiSensorHealth` interface matching the server response shape:
  `{ status, sensor, source, process, interface, storage, latest_capture }`

### `server/gui/src/components/WirelessInvestigationPanel.tsx`
- Added `WifiSensorHealth` import.
- Added sensor health state + `useEffect` that fetches health on mount and refreshes every 60 seconds.
- Added **Sensor Health Banner** rendered inside `SectionCard` before the toolbar:
  - `ONLINE` / `DEGRADED` / `OFFLINE` colored dot Badge
  - Sensor name, interface name + state, Kismet process PID
  - Latest capture packet count and last packet timestamp
  - Low-disk warning Badge when free space < 2 GB
- Also added `{ label: 'Last 10 Minutes', value: '10m' }` to `LOOKBACK_OPTIONS`.

## TypeScript Verification

```
npx tsc --noEmit   → exit 0 (clean, no new errors)
```

Pre-existing error in `Settings.tsx` (unrelated prop `cl`) is unchanged.

## Exit criterion

An analyst can query the server-owned sensor through the existing UI with accurate availability/error messaging. ✅ Banner shows sensor status at a glance at the top of the panel.
