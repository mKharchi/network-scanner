# Implementation Plan: Clients & 2D Locations GUI Alignment and Merge

## Goal Description
Resolve the GUI routing discrepancy where client locations were erroneously routed to the 3D Digital Twin (`/digital-twin`) instead of the 2D Locations floor view (`/locations`). Establish an intuitive visual assignment and reassignment workflow from the Client Details page, and merge the 2D floor visualizer with the Clients table into a single, unified operations dashboard.

---

## Current State Analysis

### 1. File Identification & Roles
| Page / Component | File Path | Current Status & Issue |
|---|---|---|
| **Client Details** | [`pages/ClientDetail.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/ClientDetail.tsx) | Line 672 hardcoded to `navigate('/digital-twin?client=' + c.id)`. Lacks an explicit "Reassign location" action. |
| **Clients Table** | [`pages/Clients.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/Clients.tsx) | Line 302 (`startManualAssignment`) and line 317 hardcoded to `/digital-twin`. |
| **Locations (2D Floor Map)** | [`pages/Locations.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/Locations.tsx) | Already contains full 2D interactive layout, table/seat grid, assignment banner (`searchParams.get("assign")`), and `api.assignClientLocation()`. Currently isolated on `/locations` route and absent from main top-bar navigation. |
| **Shell & Router** | [`components/AppShell.tsx`](file:///home/adonis/network-scanner/server/gui/src/components/AppShell.tsx), [`App.tsx`](file:///home/adonis/network-scanner/server/gui/src/App.tsx) | Top nav has "Spatial Map" (`/digital-twin`) and "Clients" (`/clients`), but `/locations` is hidden. |

### 2. Assignment Workflow
1. Admin clicks "Assign location" or "Reassign location" in Client Details.
2. System navigates to Locations view in assignment mode (`?assign=<clientId>&floor=<floor>`).
3. Admin clicks an empty seat on the 2D floor map.
4. Confirmation prompt appears and confirms assignment via `api.assignClientLocation()`.
5. Seat updates to assigned status and admin can easily view the client or return to details.

---

## Execution Phases

### Phase 1: Client Detail & Clients Redirection Fix
1. **ClientDetail.tsx**:
   - For assigned clients: Show location label, "View on floor map" (`/locations?floor=<f>&selected=<id>`), and "Reassign location" (`/locations?assign=<id>&floor=<f>`).
   - For unassigned clients: Show "Location unassigned" and primary button "Assign location" (`/locations?assign=<id>`).
2. **Clients.tsx**:
   - Fix `startManualAssignment` and auto-locate toast actions to point to `/locations`.
3. **Locations.tsx**:
   - Handle `floor`, `selected`, and `assign` query parameters cleanly with direct seat focusing and an assignment banner.

### Phase 2: Merging 2D Locations Floor Map with Clients Page
1. Embed the interactive 2D floor layout above the Clients data table.
2. Provide floor tabs, quick status/aisle/table filters, seat inspection drawer, and assignment queue.
3. Provide bidirectional synchronization: selecting a client in the table scrolls/highlights the seat on the map, and clicking a seat highlights the corresponding client in the table.
4. Keep routes cleanly aligned.

---

## Verification
- Automated type check: `npx tsc --noEmit` in `server/gui`.
- End-to-end verification of the redirect and assignment flow.
