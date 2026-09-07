# Operator GUI

## Technology and runtime

The console is a React/TypeScript application built with Vite and packaged
through Tauri for desktop use. The source is under `server/gui/`; the API
client centralizes REST calls and typed response contracts in
`server/gui/src/api/client.ts`.

Development commands:

```bash
cd server/gui
npm install
npm run dev
```

The release/Tauri workflow is documented in `server/gui/README.md` and the
package scripts.

## Navigation and pages

| Area | Routes/pages | Function |
| --- | --- | --- |
| Overview | `/`, `Dashboard.tsx` | KPIs, online clients, alerts, scans, live health |
| Client fleet | `/clients`, `/clients/:clientId` | Inventory, telemetry, remote commands, history, updates |
| Network inventory | `/network/devices`, `DeviceDetail.tsx` | Devices, observations, classifications, wireless investigation |
| Discovery | `/network/latest`, `/network/history` | Current and historical merged scans |
| DHCP | API-backed from network views | Daily passive DHCP activity |
| Security | `/alerts`, `/rogue-devices` | Alert triage and rogue-device review |
| Spatial | `/locations`, `/spatial`, `/digital-twin`, `/client-localization` | Assignment, floor maps, digital twin, localization |
| Activity | `/activity`, `/activity/:logId` | Client activity log review |
| Settings | `/settings` | Working hours, forbidden processes, resource protection, sensor settings |

`AppShell.tsx` defines the primary navigation. `App.tsx` defines route
matching and compatibility redirects.

## Data behavior

Pages load REST resources through the typed API client, show explicit loading
and error states, and use the SSE event stream for live invalidation. The
`useRealTimeEvents` hook and toast system surface connection, action, alert,
health, scan, and policy changes without losing the current page state.

## Update/deployment UI

`DeployPackagePanel.tsx` handles file/package deployment. `UpdateClientPanel.tsx`
builds/uploads packages and starts single or bulk `UPDATE_CLIENT` actions.
`ClientDetail.tsx` shows per-target progress/results and preserves links to
logs, screenshots, actions, location, and wireless investigation.

## Design system

Reusable controls live under `components/`; tokens and component styles live
under `styles/`. The UI uses shared buttons, cards, data tables, badges,
dialogs, number inputs, state indicators, and toast patterns instead of
page-specific one-off controls.

