# Floor 1 — 2D Client Positioning Migration Plan

## Objective

Replace the current 3D digital-twin visualization and its 3D positioning logic with a **2D Floor 1 positioning system**.

For this phase, the application must:

1. Remove the current 3D building/model visualization from the device-location workflow.
2. Consider **only Floor 1**.
3. Represent Floor 1 using a **2D coordinate system**.
4. Use the known client PCs physically located on Floor 1 as the spatial reference points.
5. Estimate the position of discovered devices **relative to those known Floor-1 clients**.
6. Display the resulting device positions on a 2D representation of Floor 1.
7. Preserve the real spatial relationship between the two sides of the floor, especially the approximately **4–5 meter gap between the two aisles**.
8. Do not introduce unnecessary labels such as "Aisle 1", "Aisle 2", etc. The visualization should primarily communicate **where devices are located**.

---

# 1. Remove the 3D model from this workflow

Find the existing components, services, hooks, and data flow responsible for:

* loading the 3D building model;
* rendering the building in Three.js / React Three Fiber / other 3D technology;
* positioning devices using `(x, y, z)` coordinates;
* displaying devices inside the 3D model;
* requiring the user to navigate to a 3D view to see device locations.

Do not necessarily delete the old implementation immediately.

Instead:

### First phase

Decouple it from the active device-positioning workflow.

The application should no longer require the 3D model to:

* calculate a device's location;
* determine whether a device belongs to Floor 1;
* display device positions.

If the existing 3D implementation may be useful later for other floors, keep it isolated behind a separate module/component rather than deleting all related code blindly.

The active location workflow should become:

```text
Network discovery
       ↓
Discovered clients
       ↓
Floor 1 filtering
       ↓
2D positioning engine
       ↓
2D Floor 1 coordinate
       ↓
2D visualization
```

---

# 2. Redefine the spatial model

Stop representing the active position as:

```text
x, y, z
```

For Floor 1 use only:

```text
x, y
```

with:

```text
floor = 1
```

The floor should therefore have a 2D coordinate system:

```text
                    Y
                    ↑
                    │
                    │
                    │
                    │
                    │
                    └────────────────────→ X
```

There must be no active `z` coordinate in the Floor 1 positioning calculation.

A device location should conceptually become:

```json
{
  "floor": 1,
  "x": 12.4,
  "y": 7.8,
  "confidence": 0.82
}
```

Optionally include:

```json
{
  "referenceClients": [
    "client-id-1",
    "client-id-2",
    "client-id-3"
  ]
}
```

to record which known clients contributed to the estimation.

---

# 3. Define Floor 1 as a fixed 2D spatial reference

The physical Floor 1 layout must be encoded as a **2D coordinate map**.

The important geometry is:

* Formation Room 1 at the upper-left.
* Formation Room 2 at the upper-right.
* Stairs on the left side.
* One Table 2 on the left side.
* One Table 1 on the right side.
* One Table 2 on the right side.
* The two sides/aisles face each other.
* There is approximately **4–5 meters of physical space between the two sides**.

The application does not need to display the names of these areas.

Their purpose is to establish the geometry and reference coordinates.

Conceptually:

```text
                         FLOOR 1

       LEFT SIDE                              RIGHT SIDE


       ┌──────────┐                          ┌──────────┐
       │  STAIRS  │                          │ TABLE 1  │
       └──────────┘                          └──────────┘


       ┌──────────┐                          ┌──────────┐
       │ TABLE 2  │                          │ TABLE 2  │
       │ ● ●      │                          │ ● ●      │
       │ ● ●      │                          │ ● ●      │
       │ ● ●      │                          │ ● ●      │
       │ ● ●      │                          │ ● ●      │
       └──────────┘                          └──────────┘

                  ← approximately 4–5 meters →
```

The exact coordinates should be centralized in one configuration/data structure rather than scattered throughout frontend components.

---

# 4. Use the known Floor-1 clients as spatial reference points

This is the most important architectural change.

The known PCs/clients on Floor 1 should become the **reference points** for positioning discovered devices.

Do not assume that a newly discovered device is itself one of these reference points.

There are two categories:

### Reference clients

Known physical clients whose positions are already associated with Floor 1.

Example:

```text
Reference Client A → Table 2 → physical position
Reference Client B → Table 2 → physical position
Reference Client C → Table 1 → physical position
...
```

### Target/discovered devices

Devices discovered by the network discovery system whose location needs to be estimated.

Example:

```text
Unknown Device X
       ↓
measurements relative to known Floor-1 clients
       ↓
estimated (x, y)
```

The positioning system should therefore be based on:

```text
Known Floor-1 client positions
             +
Network/RSSI/proximity observations
             ↓
      Estimated 2D position
```

---

# 5. Establish coordinates for every known Floor-1 client

Every known Floor-1 client should have a stable 2D coordinate.

For example:

```text
Reference Client       X        Y
-----------------------------------
Floor1-PC-01          2.0      8.0
Floor1-PC-02          2.0      7.0
Floor1-PC-03          2.0      6.0
Floor1-PC-04          2.0      5.0

Floor1-PC-05          3.0      8.0
Floor1-PC-06          3.0      7.0
...
```

These are examples only.

Do not hardcode these example values as real positions.

Create a proper configuration/database representation for the actual coordinates.

The coordinates should represent the physical geometry of the floor rather than arbitrary screen pixels.

---

# 6. Preserve the physical 4–5 meter separation

The distance between the two sides is important.

Do not compress the two sides together simply because the visualization has limited screen space.

The underlying coordinate system should preserve the approximate physical relationship:

```text
Left-side reference clients
            │
            │
            │
       4–5 meters
            │
            │
            │
Right-side reference clients
```

The renderer can scale the coordinate system to fit the screen, but the **underlying coordinates must remain proportional**.

For example, if the real-world model says:

```text
left side = x 0–3 m
gap       = approximately 4–5 m
right side = x 8–11 m
```

the renderer should scale these values rather than manually moving objects closer together.

This allows future distance calculations to remain meaningful.

---

# 7. Positioning algorithm

Replace any 3D positioning calculation with a 2D positioning pipeline.

The conceptual calculation should be:

```text
Known client A → (x1, y1)
Known client B → (x2, y2)
Known client C → (x3, y3)
Known client D → (x4, y4)
              +
       observations/RSSI
              ↓
       2D estimation
              ↓
        (x, y)
```

If RSSI is available, use the existing RSSI/proximity information to estimate relative distance.

A basic distance approximation can be:

```text
d = 10 ^ ((RSSI_reference - RSSI) / (10 × n))
```

where:

* `RSSI` = observed signal strength;
* `RSSI_reference` = calibrated signal strength at a reference distance;
* `n` = environment/path-loss coefficient.

Then use multiple known Floor-1 clients to estimate the target position.

For example:

```text
Reference A ───────┐
                   │
Reference B ───────┼──→ 2D position estimate
                   │
Reference C ───────┘
```

If the existing application already contains an RSSI-based positioning algorithm, adapt it rather than implementing a second competing algorithm.

The critical change is that its output must be:

```text
(x, y)
```

instead of:

```text
(x, y, z)
```

---

# 8. Floor-1 filtering must happen before positioning

Do not allow clients from other floors to influence the Floor 1 position calculation.

The pipeline should explicitly filter:

```text
All known/reference clients
          ↓
       floor = 1
          ↓
Floor-1 reference clients
          ↓
2D positioning
```

Likewise, the visualization should only receive:

```text
devices WHERE floor = 1
```

This is important because simply hiding Floor 2 visually is not sufficient.

A Floor 2 client must not accidentally become a positioning reference for a Floor 1 device.

---

# 9. Handle insufficient reference points

The positioning engine must not fabricate a precise location when there is insufficient information.

For example:

```text
0 reference clients
    ↓
No position

1 reference client
    ↓
Approximate proximity only

2 reference clients
    ↓
Limited 2D estimation

3+ reference clients
    ↓
Better 2D estimation
```

The exact mathematical requirements should follow the existing positioning implementation.

Every estimated location should also have a confidence value.

Example:

```json
{
  "x": 7.42,
  "y": 5.81,
  "floor": 1,
  "confidence": 0.78
}
```

The UI can visually distinguish high-confidence and low-confidence positions.

---

# 10. Build a 2D Floor 1 renderer

Create a dedicated component for the new visualization.

For example:

```text
Floor1Map
    ├── FloorBoundary
    ├── ReferenceClientMarkers
    ├── DiscoveredDeviceMarkers
    └── OptionalTableGeometry
```

The map should not be a generic architectural drawing.

It should primarily be a **device positioning interface**.

The user should immediately be able to answer:

> "Where are the detected devices?"

---

# 11. Tables should be spatial anchors

The tables should be represented because they provide meaningful physical reference geometry.

Each table should have:

```text
position
width
height
orientation
```

and each physical PC position can have:

```text
x
y
client_id
```

Conceptually:

```text
Table
 ├── PC position 1
 ├── PC position 2
 ├── PC position 3
 ├── PC position 4
 ├── PC position 5
 ├── PC position 6
 ├── PC position 7
 └── PC position 8
```

The eight PC positions correspond to:

```text
4 PCs on one side
+
4 PCs on the opposite side
```

Do not treat the table as one single point.

The individual known clients should retain their own coordinates.

---

# 12. Device markers

A discovered device should appear at its estimated 2D location.

Example:

```text
        Reference PCs

        ●       ●
        ●   ◉   ●
        ●       ●
```

Where:

* `●` = known/reference client;
* `◉` = discovered device being positioned.

The marker should update when the estimated position changes.

Do not require the user to manually run a separate "re-evaluate positioning" workflow if the current architecture allows automatic updates.

The long-term UX should become:

```text
Client discovered
      ↓
Measurements collected
      ↓
Position calculated
      ↓
2D map automatically updated
```

rather than:

```text
Client discovered
      ↓
Go to another page
      ↓
Run evaluation
      ↓
Go to 3D model
      ↓
See device
```

---

# 13. Keep world coordinates separate from screen coordinates

Do not store browser pixel positions as device locations.

Use:

```text
World coordinates:
x = meters
y = meters
```

and convert them during rendering:

```text
world coordinates
       ↓
scale
       ↓
viewport coordinates
       ↓
screen pixels
```

This is essential because the application should preserve physical distances even if the browser window changes size.

---

# 14. Database changes

Inspect the existing location-related schema before modifying it.

If the current schema contains:

```text
x
y
z
floor
```

determine whether `z` is used elsewhere.

For the Floor 1 system, the active location representation should be:

```text
floor
x
y
confidence
timestamp
```

Reference clients should additionally have a stable spatial association:

```text
client_id
floor
x
y
```

Avoid duplicating coordinates in multiple unrelated tables.

Create one authoritative source for the physical position of known Floor-1 clients.

---

# 15. API changes

The backend should expose a clean Floor-1 positioning representation.

For example:

```text
GET /api/spatial/floor/1
```

could return:

```json
{
  "floor": 1,
  "references": [
    {
      "client_id": "...",
      "x": 2.4,
      "y": 7.2
    }
  ],
  "devices": [
    {
      "device_id": "...",
      "x": 7.4,
      "y": 5.8,
      "confidence": 0.82
    }
  ]
}
```

The exact endpoint should follow the project's existing API conventions rather than blindly creating this exact route.

---

# 16. Remove unnecessary 3D dependencies from the active path

After the new implementation works, verify that:

* device discovery does not require Three.js;
* positioning does not require 3D coordinates;
* Floor 1 device locations do not depend on the 3D model;
* the 2D map loads independently;
* the application can display device positions even if the 3D model is unavailable.

If the 3D model is not needed anywhere else, remove its related UI and dependencies only after confirming there are no remaining consumers.

---

# 17. Testing requirements

Test the system progressively.

### Test 1 — Floor filtering

Create/test devices associated with:

```text
Floor 1
Floor 2
```

Verify that only Floor 1 references participate in Floor 1 positioning.

### Test 2 — 2D output

Verify that every estimated Floor 1 position contains:

```text
x
y
floor = 1
```

and does not depend on `z`.

### Test 3 — Reference client positions

Verify that all known Floor-1 clients appear at their configured physical coordinates.

### Test 4 — Physical separation

Verify that the distance between the two sides of the floor remains approximately 4–5 meters in the world coordinate system.

### Test 5 — Device positioning

Use a known/test device near a known reference location and verify that the calculated position moves toward that reference.

### Test 6 — Multiple references

Verify that adding/removing reference clients changes the estimate appropriately.

### Test 7 — Insufficient references

Verify that the system reports low confidence or "position unavailable" instead of inventing an exact location.

### Test 8 — Responsive rendering

Resize the browser.

The physical geometry should remain proportional even though the screen coordinates change.

---

# 18. Final architecture

The resulting architecture should look like:

```text
                    NETWORK DISCOVERY
                           │
                           ▼
                    Discovered Devices
                           │
                           ▼
                  ┌──────────────────┐
                  │ Floor 1 Filter   │
                  └────────┬─────────┘
                           │
                           ▼
                  Floor-1 positioning
                           │
             ┌─────────────┴─────────────┐
             │                           │
     Known Floor-1 clients       Device observations
       (x, y coordinates)             RSSI/etc.
             │                           │
             └─────────────┬─────────────┘
                           ▼
                     2D Positioning
                           │
                           ▼
                       (x, y)
                           │
                           ▼
                  Confidence + timestamp
                           │
                           ▼
                     Floor1Map
                           │
             ┌─────────────┴─────────────┐
             │                           │
       Reference PC markers       Discovered devices
             │                           │
             └─────────────┬─────────────┘
                           ▼
                    2D visualization
```

## Important constraints

Do not:

* recreate the building as a 3D model;
* use `z` for Floor 1 positioning;
* use clients from other floors as references;
* collapse the two sides together visually;
* treat an entire table as one PC/reference point;
* hardcode browser pixel coordinates as physical coordinates;
* invent a precise location when the available measurements are insufficient;
* make the user manually navigate between separate pages to discover the resulting location.

The target is a **data-driven 2D Floor 1 spatial positioning system**, where the physical positions of known Floor-1 clients provide the reference framework and discovered devices are continuously/automatically estimated relative to those references.
