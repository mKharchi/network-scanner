# Client Localization Validation Mode — Implementation Plan

## 1. Objective

Add a temporary validation feature that allows the platform to locate real registered client PCs using the existing location system.

The purpose is **not** to redesign localization yet.

The purpose is to determine whether:

1. The center layout stores locations correctly.
2. The server interprets those locations correctly.
3. Clients are assigned the expected locations.
4. The coordinates used by the frontend and backend are consistent.
5. The visual representation corresponds to the real physical position of the client.

The feature should make discrepancies visible instead of trying to automatically correct them.

---

# 2. Main Concept

The system should expose the complete localization chain:

```text
CLIENT
  │
  │ MAC / client ID
  ▼
SERVER
  │
  │ assigned location
  ▼
LOCATION RECORD
  │
  │ coordinates
  ▼
SERVER COORDINATE SYSTEM
  │
  ▼
CENTER LAYOUT
  │
  ▼
VISUALIZED CLIENT
```

For every client, the system should be able to answer:

```text
Client:
    PC-TRAINING-04

MAC:
    XX:XX:XX:XX:XX:XX

Server location:
    Floor 2
    Training Room 1
    Seat 4

Server coordinates:
    X = ?
    Y = ?
    Z = ?

Displayed position:
    X = ?
    Y = ?
    Z = ?

Localization confidence:
    ?

Last update:
    ?
```

---

# 3. Why This Feature Is Needed

There are potentially two different coordinate systems.

For example, the center layout may define:

```text
Room 1
    x = 100
    y = 200
```

while the server may interpret those values as:

```text
x = 100 meters
y = 200 meters
```

or the frontend may transform them into:

```text
x = 10
y = 20
```

Another possibility is that:

```text
Frontend:
    X → horizontal
    Y → vertical

Server:
    X → horizontal
    Y → depth
    Z → vertical
```

There may also be:

* different origins
* different axes
* different scales
* different units
* different floor offsets
* inverted axes
* coordinate normalization
* room-local vs building-global coordinates

Therefore, the first objective is to expose the raw values at every stage.

---

# 4. Validation Dashboard

Create a dedicated development page:

```text
Client Localization
```

The page should show all currently connected clients.

Example:

```text
┌─────────────────────────────────────────────────────┐
│ CLIENT LOCALIZATION TEST                            │
├─────────────────────────────────────────────────────┤
│                                                     │
│ PC-ROOM1-01                                         │
│ MAC: AA:BB:CC:DD:EE:FF                              │
│                                                     │
│ Location                                            │
│ Floor 2 → Training Room 1 → Seat 4                 │
│                                                     │
│ Server Coordinates                                  │
│ X: 42.5                                             │
│ Y: 17.2                                             │
│ Z: 0                                                │
│                                                     │
│ Rendered Coordinates                                │
│ X: 425                                             │
│ Y: 172                                             │
│ Z: 0                                                │
│                                                     │
│ Status: ● ONLINE                                    │
│                                                     │
│ [Locate] [Highlight] [Inspect]                      │
└─────────────────────────────────────────────────────┘
```

This page is primarily a debugging/validation tool.

---

# 5. Client Selection

The administrator should be able to select a specific client.

Example:

```text
Select client:

PC-TRAINING-01
PC-TRAINING-02
PC-TRAINING-03
PC-TRAINING-04
```

After selection, the system should highlight the client's position on the center layout.

---

# 6. Locate Button

Add:

```text
[ Locate Client ]
```

When clicked:

```text
Client
   ↓
retrieve location
   ↓
retrieve coordinates
   ↓
convert coordinates
   ↓
highlight location
```

The selected client should visually stand out.

For example:

```text
                    FLOOR 2

┌─────────────────────────────────────────┐
│                                         │
│       TRAINING ROOM 1                   │
│                                         │
│    ○ PC1     ○ PC2     ● PC3            │
│                             ↑           │
│                       TEST CLIENT       │
│                                         │
└─────────────────────────────────────────┘
```

---

# 7. Raw vs Rendered Coordinates

This is one of the most important parts.

Do **not** only display the final coordinates.

Display both:

### Backend coordinates

```text
Backend:
X = 42.5
Y = 17.2
Z = 0
```

### Frontend/rendered coordinates

```text
Renderer:
X = 425
Y = 172
Z = 0
```

If they differ, show the transformation.

Example:

```text
Backend
(42.5, 17.2)

       ↓ ×10

Renderer
(425, 172)
```

This immediately reveals scaling problems.

---

# 8. Coordinate Transformation Debugging

Create a single explicit transformation function.

Conceptually:

```text
server coordinates
        ↓
coordinate transformer
        ↓
visual coordinates
```

Do not allow different parts of the application to independently manipulate coordinates.

The transformation should be centralized.

Example:

```text
toRenderCoordinates(location)
```

The output should be:

```json
{
    "x": 425,
    "y": 172,
    "z": 0
}
```

---

# 9. Coordinate Metadata

Every location should expose its coordinate metadata.

Example:

```json
{
    "location_id": 42,
    "name": "Training Room 1",
    "floor": 2,

    "coordinates": {
        "x": 42.5,
        "y": 17.2,
        "z": 0
    },

    "coordinate_system": "center-layout-v1",
    "unit": "relative",
    "origin": "floor-2-origin"
}
```

If these fields do not currently exist, initially add them only to the debugging response rather than redesigning the database.

---

# 10. Client-to-Location Mapping

Verify exactly how the server currently determines:

```text
Client
    ↓
Location
```

Document the actual mechanism.

For example:

```text
Client MAC
    ↓
client.location_id
    ↓
Location
```

or:

```text
Client
    ↓
network observation
    ↓
location resolver
    ↓
Location
```

Do not change this mechanism yet.

The goal is to understand what the existing implementation is doing.

---

# 11. Real-World Validation Test

This is the most important part.

Take several physical PCs whose locations are known.

For example:

```text
PC A → Training Room 1 → Seat 1
PC B → Training Room 1 → Seat 4
PC C → Training Room 2 → Seat 2
PC D → Training Room 2 → Seat 6
```

Record the actual physical position.

Then connect each PC and inspect what the server reports.

Create a validation table:

| Client | Actual Location | Server Location | Rendered Location | Correct? |
| ------ | --------------- | --------------- | ----------------- | -------- |
| PC A   | Room 1 / Seat 1 | ?               | ?                 | ?        |
| PC B   | Room 1 / Seat 4 | ?               | ?                 | ?        |
| PC C   | Room 2 / Seat 2 | ?               | ?                 | ?        |
| PC D   | Room 2 / Seat 6 | ?               | ?                 | ?        |

Do not modify the localization algorithm until this test is complete.

---

# 12. Difference Visualization

If possible, display:

```text
Expected position
        +
        │
        │ distance/error
        │
        ▼
Actual rendered position
```

For example:

```text
Expected:
●

Rendered:
        ×
```

And calculate:

```text
error_x
error_y
error_z
```

For example:

```text
X error: +12
Y error: -8
Z error: 0

Total positional error: 14.4 units
```

This will tell us whether the problem is:

* constant offset
* scaling
* axis inversion
* rotation
* wrong location
* wrong floor
* wrong coordinate conversion

---

# 13. Detect Common Coordinate Problems

The validation feature should help identify these automatically.

## A. Constant offset

If every client is shifted by approximately the same amount:

```text
Expected: 100
Rendered: 120

Expected: 200
Rendered: 220
```

Likely:

```text
origin mismatch
```

---

## B. Scaling error

If:

```text
Expected: 10
Rendered: 100
```

and:

```text
Expected: 20
Rendered: 200
```

Likely:

```text
scale mismatch
```

---

## C. Axis inversion

If movement along X appears as movement along Y:

```text
Expected:
X changes

Rendered:
Y changes
```

Likely:

```text
axis mapping problem
```

---

## D. Axis inversion sign

If:

```text
Expected:
X = +20

Rendered:
X = -20
```

Likely:

```text
axis direction is inverted
```

---

## E. Rotation

If the whole layout appears rotated:

```text
Expected:
Room A → left

Rendered:
Room A → top
```

Likely:

```text
coordinate rotation
```

---

## F. Wrong hierarchy

If a client is in:

```text
Floor 2 → Room 1 → Seat 4
```

but appears in:

```text
Floor 1 → Room 4
```

the problem is not coordinate transformation.

It is likely:

```text
location association
```

---

# 14. Backend Debug Endpoint

Create a development endpoint such as:

```text
GET /api/debug/clients/{id}/localization
```

Return the entire chain.

Example:

```json
{
    "client": {
        "id": 12,
        "hostname": "PC-TRAINING-04",
        "mac": "AA:BB:CC:DD:EE:FF"
    },

    "location": {
        "id": 42,
        "name": "Seat 4",
        "room": "Training Room 1",
        "floor": 2
    },

    "server_coordinates": {
        "x": 42.5,
        "y": 17.2,
        "z": 0
    },

    "coordinate_system": {
        "name": "center-layout-v1",
        "unit": "relative"
    },

    "render_coordinates": {
        "x": 425,
        "y": 172,
        "z": 0
    },

    "last_updated": "..."
}
```

This endpoint is extremely useful while debugging.

---

# 15. Frontend Debug Overlay

Add an optional developer overlay.

```text
┌──────────────────────────────────┐
│ LOCATION DEBUG                   │
├──────────────────────────────────┤
│ Client: PC-TRAINING-04           │
│                                  │
│ Location ID: 42                  │
│ Room: Training Room 1            │
│ Seat: 4                          │
│                                  │
│ SERVER                           │
│ X: 42.5                          │
│ Y: 17.2                          │
│ Z: 0                             │
│                                  │
│ RENDERER                         │
│ X: 425                           │
│ Y: 172                           │
│ Z: 0                             │
│                                  │
│ Transform: ×10                   │
└──────────────────────────────────┘
```

Allow it to be disabled in production.

---

# 16. Implementation Phases

## Phase 1 — Understand the Existing Flow

* [ ] Identify the current client location field.
* [ ] Identify how the server assigns a location.
* [ ] Identify the location API.
* [ ] Identify how the frontend retrieves locations.
* [ ] Identify how the frontend converts location coordinates.
* [ ] Identify the center layout coordinate system.
* [ ] Identify units.
* [ ] Identify origin.
* [ ] Identify axis orientation.

Do not change behavior yet.

---

## Phase 2 — Expose the Data

* [ ] Add client localization debug endpoint.
* [ ] Return client identity.
* [ ] Return assigned location.
* [ ] Return raw coordinates.
* [ ] Return coordinate metadata.
* [ ] Return rendered coordinates if conversion happens server-side.
* [ ] Add timestamps.

---

## Phase 3 — Build the Validation UI

* [ ] Create Client Localization page.
* [ ] List connected clients.
* [ ] Add client search.
* [ ] Add Locate button.
* [ ] Highlight selected client.
* [ ] Add coordinate inspector.
* [ ] Add debug overlay.

---

## Phase 4 — Test Real Clients

Use at least:

```text
PC 1
PC 2
PC 3
PC 4
PC 5
```

Prefer clients in different:

* rooms
* seats
* floors
* zones

For each client:

1. Record its physical location.
2. Connect/register the client.
3. Wait for the server to recognize it.
4. Click Locate.
5. Record the server location.
6. Record the rendered location.
7. Compare with reality.

---

## Phase 5 — Diagnose

Classify the result.

### Case 1

```text
Server location = correct
Rendered location = correct
```

Localization works.

### Case 2

```text
Server location = correct
Rendered location = wrong
```

Frontend coordinate transformation is wrong.

### Case 3

```text
Server location = wrong
Rendered location = consistent with server
```

Location association/resolution is wrong.

### Case 4

```text
Server coordinates = wrong
Location name = correct
```

Coordinate data in the location model is wrong.

### Case 5

```text
Different clients have different errors
```

Likely:

* incorrect individual coordinates
* incorrect seat mapping
* hierarchy problem

### Case 6

```text
All clients have approximately the same error
```

Likely:

* origin
* scale
* rotation
* coordinate transformation

---

# 17. Important Rule

Do not immediately "fix" individual clients.

If five clients are all shifted by:

```text
+50 X
-20 Y
```

do not modify five locations.

Investigate the coordinate transformation first.

The goal is to identify the systemic problem.

---

# 18. Success Criteria

The validation feature is successful when you can select any connected client and see:

```text
CLIENT
    ↓
LOCATION
    ↓
RAW SERVER COORDINATES
    ↓
TRANSFORMATION
    ↓
RENDERED COORDINATES
    ↓
PHYSICAL POSITION
```

and determine exactly where a discrepancy occurs.

---

# 19. What Comes After

Only after validating this feature should you proceed with the larger:

```text
Spatial-Temporal Rogue Device Triangulation
```

The architecture then becomes:

```text
Existing client localization
            ↓
Validation
            ↓
Correct coordinate model
            ↓
Reliable physical client positions
            ↓
Spatial-temporal observations
            ↓
Rogue device localization
            ↓
3D digital twin
            ↓
AR visualization
```

This validation stage is therefore not wasted work.

It becomes the **calibration layer** for the entire spatial intelligence system.

---

# 20. Final Goal

The immediate goal is intentionally simple:

> **"Show me where the server thinks this real client is, and show me exactly how it arrived at that position."**

Once that works reliably, the more advanced localization features can be built on top of a coordinate system that has actually been validated against the physical center.
