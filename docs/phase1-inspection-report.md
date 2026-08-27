# Phase 1 — Inspect Existing Localization

> Plan reference: [auto-manual-client-localization.md](file:///home/adonis/network-scanner/docs/plans/auto-manual-client-localization.md) §29, Phase 1

---

## ✅ Task checklist

| # | Task | Status |
|---|------|--------|
| 1 | Identify current client–location relationship | ✅ Done |
| 2 | Identify automatic localization function | ✅ Done |
| 3 | Identify location model | ✅ Done |
| 4 | Identify center layout data | ✅ Done |
| 5 | Identify coordinate representation | ✅ Done |
| 6 | Identify current assignment API | ✅ Done |
| 7 | Identify current visualization component | ✅ Done |

---

## 1. Client–Location Relationship

**Table:** [`clients`](file:///home/adonis/network-scanner/server/scripts.sql#L28-L49) (in [`scripts.sql`](file:///home/adonis/network-scanner/server/scripts.sql))

```
clients.location_id  →  locations.id   (nullable FK, ON DELETE SET NULL)
```

- The relationship is **a single direct FK** on the `clients` table.
- No `assignment_method`, `assignment_status`, `confidence`, or `assigned_by` columns exist on `clients` yet.
- History is kept in [`client_location_history`](file:///home/adonis/network-scanner/server/scripts.sql#L51-L62):
  - `client_id`, `location_id`, `assigned_at`, `unassigned_at`, `assigned_by` — but **no method or confidence** field.

> [!NOTE]
> There is already an audit trail table. Phase 2 should extend it rather than replace it.

---

## 2. Automatic Localization Function

There is **no automatic client-localization function** — the existing localization works for **network devices** (rogue / unmanaged), not for managed clients.

The relevant spatial functions in [`spatial_engine.py`](file:///home/adonis/network-scanner/server/server_components/spatial_engine.py):

| Function | Purpose |
|----------|---------|
| [`triangulate_position(sensor_readings)`](file:///home/adonis/network-scanner/server/server_components/spatial_engine.py#L65-L204) | RSSI/switch-port multilateration → `{x, y, z, confidence, method}` |
| [`find_closest_location(x, y, z, locations)`](file:///home/adonis/network-scanner/server/server_components/spatial_engine.py#L207-L253) | Map estimated coordinates to nearest `locations` row |
| [`get_device_location(mac)`](file:///home/adonis/network-scanner/server/server_components/spatial_engine.py#L1067-L1162) | Return stored estimate from `device_location_estimates` for a **network device** |
| [`sync_client_sensors()`](file:///home/adonis/network-scanner/server/server_components/spatial_engine.py#L369-L435) | Promote already-assigned clients into the `sensors` table as reference points |

The confidence scale produced by `triangulate_position`:
- Switch-port / direct → **0.95**
- Multi-sensor (≥3) → **0.75–0.93**
- Single-sensor RSSI ≥ −50 → **0.70**
- Single-sensor RSSI ≥ −70 → **0.55**
- Fallback → **0.45**

> [!IMPORTANT]
> There is no function that runs automatic localization specifically for a **managed client** when it connects. The infrastructure (triangulation math + closest-location matching) already exists and can be reused. A new wrapper that accepts a `client_id`, collects its sensor observations, calls `triangulate_position`, calls `find_closest_location`, and applies a confidence threshold is what Phase 3 needs to build.

---

## 3. Location Model

**Table:** [`locations`](file:///home/adonis/network-scanner/server/scripts.sql#L1-L26)

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT PK | |
| `floor` | INT | |
| `zone_type` | VARCHAR(64) | e.g. `formation_room`, `pc_position` |
| `zone_name` | VARCHAR(255) | nullable |
| `aisle` | INT | nullable |
| `table_no` | INT | nullable |
| `row_no` | INT | nullable |
| `position` | INT | nullable |
| `label` | VARCHAR(255) | **unique** — human-readable ID |
| `location_type` | VARCHAR(32) | `pc_position` (assignable), `floor`, `aisle`, etc. |
| `parent_id` | INT FK | self-referential hierarchy |
| `x, y, z` | DOUBLE | relative coordinates in "center-layout-v1" system |
| `is_restricted` | BOOLEAN | formation-room flag → affects rogue scoring |
| `metadata` | TEXT | JSON blob |

Assignable location type is defined in [`center_layout.py`](file:///home/adonis/network-scanner/server/server_components/center_layout.py#L20):
```python
ASSIGNABLE_LOCATION_TYPES = {LOCATION_TYPE_PC_POSITION}   # "pc_position"
```

The `location_type` column is the canonical gating field — only `pc_position` rows accept client assignments.

---

## 4. Center Layout Data

Layout is generated/seeded by [`center_layout.py`](file:///home/adonis/network-scanner/server/server_components/center_layout.py) and served via:

```
GET /api/locations/layout?floor=<n>
```

handled in [`api_server.py:155-158`](file:///home/adonis/network-scanner/server/api_server.py#L155-L158), backed by [`api_service.get_location_layout(floor)`](file:///home/adonis/network-scanner/server/server_components/api_service.py#L207-L240).

The response is a nested structure consumed by the frontend:

```
LocationLayout
├── rooms: ClientLocation[]          ← zone_type = formation_room
│   └── each room has:
│       ├── location: ClientLocation (optional)
│       └── stations: ClientLocation[]   ← pc_position rows
```

Each `ClientLocation` in the response already carries:
- `client_id` (if a client is assigned)
- `client_state` (`ONLINE | OFFLINE | ISOLATED`)
- `x, y, z` coordinates
- `health` object

> [!NOTE]
> The layout response already joins client data per seat. Phase 5 visualization changes will extend these joined fields with `assignment_method` and `confidence`, which will need to be added to both the `clients` table and the layout JOIN query.

---

## 5. Coordinate Representation

System name: **`center-layout-v1`** (defined in [`api_service.py:818`](file:///home/adonis/network-scanner/server/server_components/api_service.py#L818))

| Axis | Meaning |
|------|---------|
| X | Layout horizontal |
| Y | Layout depth |
| Z | Floor elevation |

- Units: `"relative"` (no real-world metric unit — layout-grid units)
- Floor height constant: **3.0 units**
- Origin: `"floor-{n}-origin"` per floor

Coordinates live in `locations.x / y / z` (set during seeding). Clients inherit their location's coordinates; they do not carry their own coordinate columns.

The 3D renderer is [`DigitalTwin.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/DigitalTwin.tsx). Final screen pixel positions depend on camera yaw, pitch, zoom, and pan (isometric projection).

---

## 6. Current Assignment API

### Endpoint
```
PUT /api/clients/{client_id}/location
Body: { "location_id": <int> }
```
Handled by [`api_server.py:918-945`](file:///home/adonis/network-scanner/server/api_server.py#L918-L945).

### Service function
[`api_service.assign_client_location(client_id, location_id, assigned_by)`](file:///home/adonis/network-scanner/server/server_components/api_service.py#L362-L407)

**What it does today:**
1. Validates client exists.
2. Validates `location_id` exists and is `pc_position`.
3. Checks no other client already occupies the seat.
4. Updates `clients.location_id`.
5. Closes the previous `client_location_history` row (`unassigned_at = NOW()`).
6. Inserts a new `client_location_history` row.
7. Fires a `UPDATE_LOCATION` action to notify the client agent.

**What it does NOT track:**
- Assignment method (`AUTO` vs `MANUAL`)
- Assignment status (`PENDING / ASSIGNED / CONFIRMED`)
- Confidence score
- Localization evidence / reason

### Supporting read endpoints
| Endpoint | Service function |
|----------|-----------------|
| `GET /api/clients/{id}/location` | `get_client_location()` |
| `GET /api/clients/{id}/location-history` | `get_client_location_history()` |
| `GET /api/locations` | `list_locations(assignable_only=)` |
| `GET /api/locations/{id}` | `get_location()` |
| `GET /api/locations/{id}/clients` | `get_location_clients()` |
| `GET /api/locations/layout?floor=` | `get_location_layout()` |

No `GET /api/clients/unassigned` endpoint exists yet.

---

## 7. Current Visualization Component

### Primary: [`Locations.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/Locations.tsx)
- Floor selector → room grid → table/aisle → seat (pc_position) cells
- Clicking a seat shows a side panel with client identity, status badge, and action buttons (screenshot, quarantine, etc.)
- Assignment is done from **[`ClientDetail.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/ClientDetail.tsx)** — *not* from the layout view
- Layout shows `●` (assigned) vs `○` (empty) states via CSS, but **no differentiation between AUTO and MANUAL** assignments

### Debug: [`ClientLocalization.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/ClientLocalization.tsx)
- Validation-only view for the `client → location → coordinate → renderer` chain
- Calls `GET /api/v1/debug/clients/{id}/localization`
- Shows raw `server_coordinates`, coordinate system metadata, and renderer transformation info
- Has **"Locate in 3D Twin"** and **"Highlight"** buttons that navigate to `DigitalTwin.tsx`
- Does **not** support assignment or confirmation actions

### 3D: [`DigitalTwin.tsx`](file:///home/adonis/network-scanner/server/gui/src/pages/DigitalTwin.tsx)
- Full isometric 3D scene rendering clients at their `x, y, z` coordinates
- 66 KB — largest frontend file

---

## Summary of Gaps for Next Phases

| Gap | Needed in Phase |
|-----|----------------|
| No `assignment_method` / `assignment_status` / `confidence` on `clients` or `client_location_history` | Phase 2 |
| No automatic localization function for managed clients on connect | Phase 3 |
| No confidence threshold gating | Phase 3 |
| No "unassigned client queue" (`GET /api/clients/unassigned`) | Phase 4 |
| No "Assign Location" flow from the layout view | Phase 4 |
| Layout shows no method/confidence distinction | Phase 5 |
| No confirm/move actions on auto-assignments | Phase 6 |
| No `client.location.updated` SSE event | Phase 7 |

> [!NOTE]
> The plan says **do not rewrite the existing localization system**. Everything above is additive: new columns, a new wrapper function, new endpoints, and new UI cards layered onto the existing infrastructure.
