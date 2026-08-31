# Multi-Floor Three.js Spatial Visualization Implementation Plan

## 1. Objective

Extend the existing **Floor 1 Three.js visualization** to support the remaining floors:

* Floor 1 — already implemented and remains the reference scene.
* Floor 2 — two formation rooms, no PCs.
* Floor 0 — no PCs and no formation rooms.

The final system must use **one Three.js visualization framework with multiple floor-specific scenes**.

The user selects the floor using a control **outside the Three.js canvas**.

When the selected floor changes:

1. The active floor state changes.
2. The appropriate Three.js floor scene is loaded.
3. Devices are filtered using their `z` value.
4. Only devices belonging to the selected floor are rendered.
5. Their `x/y` coordinates determine their position inside the scene.

The old full-building 3D Digital Twin should no longer be part of this workflow.

---

# 2. Important architectural distinction

Three.js is still the rendering engine.

We are NOT removing Three.js.

We are removing the concept of the **old 3D building model**.

The new architecture is:

```text
                    Spatial Visualization
                            │
                          Three.js
                            │
             ┌──────────────┼──────────────┐
             │              │              │
          Floor 0        Floor 1        Floor 2
           Scene          Scene          Scene
             │              │              │
            X/Y            X/Y            X/Y
             │              │              │
          Devices       Reference PCs    Devices
                        + Devices
```

`z` is NOT a Three.js vertical coordinate.

It is only the floor identifier:

```text
z = 0 → Floor 0
z = 1 → Floor 1
z = 2 → Floor 2
```

Within every floor:

```text
x = horizontal position
y = vertical/depth position
```

---

# 3. Preserve the existing Floor 1 implementation

Do not rebuild Floor 1.

First inspect the existing Floor 1 Three.js implementation and identify:

* scene initialization;
* camera;
* renderer;
* controls;
* table geometry;
* PC/reference-client geometry;
* device markers;
* device labels;
* coordinate transformation;
* device selection behavior;
* animation/update loop;
* cleanup/disposal logic.

Extract reusable functionality where appropriate.

The goal is:

```text
Existing Floor 1
      ↓
Reusable Three.js spatial framework
      ↓
Floor-specific scene configurations
```

Do not duplicate the entire Floor 1 component to create Floor 2 and Floor 0.

---

# 4. Create a generic floor-scene architecture

Refactor the visualization into a generic structure.

Conceptually:

```text
SpatialVisualization
│
├── FloorSelector
│
└── ThreeSpatialScene
      │
      ├── Floor0Scene
      ├── Floor1Scene
      └── Floor2Scene
```

The Three.js infrastructure should be shared:

```text
ThreeSpatialScene
 ├── renderer
 ├── camera
 ├── controls
 ├── lighting/background
 ├── device rendering
 ├── labels
 ├── selection
 └── animation/update loop
```

The physical geometry should be floor-specific.

---

# 5. Centralize floor configuration

Create one configuration describing the available floors.

For example:

```javascript
const FLOOR_CONFIG = {
    0: {
        id: 0,
        name: "Floor 0",
        sceneType: "floor-0",
        objects: []
    },

    1: {
        id: 1,
        name: "Floor 1",
        sceneType: "floor-1",
        objects: ["tables", "referenceClients"]
    },

    2: {
        id: 2,
        name: "Floor 2",
        sceneType: "floor-2",
        objects: ["formationRooms"]
    }
};
```

Use the project's existing naming conventions.

Do not spread checks such as:

```javascript
if (floor === 1)
if (floor === 2)
if (floor === 0)
```

throughout unrelated components.

---

# 6. Define the floor coordinate model

All floors use the same conceptual coordinate system:

```text
                    Y
                    ↑
                    │
                    │
                    │
                    │
                    └────────────────→ X
```

Device data:

```json
{
    "x": 7.4,
    "y": 5.8,
    "z": 2
}
```

means:

```text
Floor 2
position = (7.4, 5.8)
```

Do not convert `z` into a Three.js vertical position.

Instead:

```javascript
floor = device.z
position = {
    x: device.x,
    y: device.y
}
```

The Three.js scene may technically use:

```javascript
new THREE.Vector3(x, 0, y)
```

or an equivalent mapping because Three.js is inherently 3D.

That is acceptable.

The important rule is that **the application's spatial model remains 2D**.

---

# 7. Keep physical scale consistent

The world coordinates should represent physical distances.

Do not store screen pixels.

Do not arbitrarily compress the Floor 1 geometry.

The existing Floor 1 model has an approximately **4–5 meter gap between the two sides/aisles**.

Preserve that relationship in the Three.js world coordinates.

For example:

```text
Left-side objects
      │
      │
      │  ~4–5 meters
      │
Right-side objects
```

The Three.js camera may zoom in/out, but the underlying coordinates should remain physically meaningful.

This is important because future positioning calculations will depend on these coordinates.

---

# 8. Floor 2 scene

Create a dedicated Floor 2 scene using the same visual language as Floor 1.

Floor 2 contains:

* Formation Room 1.
* Formation Room 2.
* No PCs.
* No reference clients.
* No tables unless they are confirmed to physically exist.

The formation rooms should be positioned in the **same relative locations as the formation rooms on Floor 1**.

Conceptually:

```text
┌──────────────────┐              ┌──────────────────┐
│                  │              │                  │
│ FORMATION ROOM 1 │              │ FORMATION ROOM 2 │
│                  │              │                  │
└──────────────────┘              └──────────────────┘
```

Do not create fake PC/reference markers.

Do not use Floor 1 PC positions as Floor 2 reference clients.

The rooms are only spatial geometry.

---

# 9. Floor 0 scene

Create a dedicated Floor 0 scene.

Floor 0 contains:

* no PCs;
* no reference clients;
* no formation rooms.

Therefore the scene should be minimal.

It should provide:

* the same coordinate system;
* the same camera behavior;
* the same visual framework;
* the ability to display device markers;
* optional floor boundary/grid/background if consistent with the existing design.

Do not invent physical objects.

Conceptually:

```text
┌──────────────────────────────────────────┐
│                                          │
│              Device ●                    │
│                                          │
│                         ● Device         │
│                                          │
└──────────────────────────────────────────┘
```

---

# 10. Floor selector

Create a floor selector **outside the Three.js visualization**.

Do not put the selector inside the scene.

For example:

```text
Spatial View

[ Floor 0 ] [ Floor 1 ] [ Floor 2 ]

┌──────────────────────────────────────────┐
│                                          │
│              Three.js Scene              │
│                                          │
└──────────────────────────────────────────┘
```

Floor 1 should be selected by default.

The selector should have one shared state:

```javascript
const [selectedFloor, setSelectedFloor] = useState(1);
```

---

# 11. Scene switching

When:

```javascript
setSelectedFloor(2)
```

the Three.js visualization must transition from:

```text
Floor1Scene
```

to:

```text
Floor2Scene
```

Do not render all floors simultaneously.

The active scene should correspond to the selected floor.

Conceptually:

```text
selectedFloor
      │
      ├── 0 → Floor0Scene
      ├── 1 → Floor1Scene
      └── 2 → Floor2Scene
```

Before loading the new scene:

* remove floor-specific objects from the current scene;
* dispose geometries/materials/textures where appropriate;
* clear old device markers;
* clear old labels;
* create the new floor geometry;
* render devices belonging to the selected floor.

Avoid memory leaks when switching repeatedly.

---

# 12. Filter devices using Z

The device data already contains `z`.

Use it directly.

```javascript
const visibleDevices = devices.filter(
    device => device.z === selectedFloor
);
```

Therefore:

```text
selectedFloor = 0
      ↓
z === 0
```

```text
selectedFloor = 1
      ↓
z === 1
```

```text
selectedFloor = 2
      ↓
z === 2
```

Do not maintain a second independent floor assignment unless absolutely necessary.

`z` is the source of truth for floor membership.

---

# 13. Device coordinates

Once devices have been filtered by floor:

```javascript
visibleDevices.forEach(device => {
    const x = device.x;
    const y = device.y;

    // Map to Three.js's horizontal plane.
});
```

Use the same coordinate transformation already established by Floor 1.

Do not create separate coordinate conventions for each floor.

The same `(x,y)` meaning should apply everywhere.

---

# 14. Floor 1 positioning

Floor 1 remains the only floor with known PC reference clients.

Its positioning architecture remains:

```text
Known Floor-1 clients
        │
        ▼
Reference coordinates
        │
        +
        │
RSSI/proximity observations
        │
        ▼
2D position estimate
        │
        ▼
       X/Y
```

The `z` value is then:

```text
z = 1
```

Do not change the existing Floor 1 positioning algorithm unless necessary to integrate it with the new multi-floor architecture.

---

# 15. Floor 2 positioning

There are no PCs on Floor 2.

Therefore:

```text
Floor 2
   │
   └── No PC reference clients
```

Do not invent reference points.

If the backend already provides valid `(x,y,z)` coordinates for a Floor 2 device, render those coordinates.

If it does not have a valid position:

```text
position = unknown
```

rather than fabricating a location.

If future positioning references are added to Floor 2, they can be integrated later without changing the scene architecture.

---

# 16. Floor 0 positioning

Same principle.

Floor 0 has:

* no PCs;
* no formation rooms;
* no current reference clients.

Therefore only render a device at `(x,y)` if that position is actually available.

Otherwise mark it as unpositioned.

Do not place devices at `(0,0)` just because coordinates are missing.

---

# 17. Device labels

Keep the existing Three.js device-label implementation if one already exists.

Labels should be associated with the corresponding device marker.

Conceptually:

```text
Device
 ├── Marker
 └── Label
```

The label should not be treated as part of the floor geometry.

This makes it possible to independently control label visibility.

---

# 18. Device-list selection

Create shared selection state:

```javascript
const [selectedDeviceId, setSelectedDeviceId] = useState(null);
```

The device list and Three.js scene must use this same state.

Architecture:

```text
              selectedDeviceId
                    │
             ┌──────┴──────┐
             ▼             ▼
        Device List     Three.js
                         Scene
```

When the user clicks a device in the list:

```text
Device List
    ↓
setSelectedDeviceId(device.id)
    ↓
Three.js updates
```

---

# 19. Label focus behavior

When:

```text
selectedDeviceId = null
```

all device labels can remain visible according to the current Floor 1 behavior.

When a device is selected:

```text
selectedDeviceId = device-X
```

then:

```text
Device X
    marker → visible
    label  → visible

All other devices
    marker → visible
    label  → hidden
```

Do NOT hide the other device markers.

The purpose is to focus the user's attention while preserving spatial context.

---

# 20. Selected device highlight

The selected device should have a stronger visual state.

For example:

```text
Normal:
●

Selected:
◉
```

Use the existing project's visual language rather than introducing an unrelated design.

The selected label should remain visible even when the camera moves or zooms.

---

# 21. Selection + floor switching

Handle this case:

```text
User selects Device A on Floor 1
            ↓
User switches to Floor 2
            ↓
Device A has z = 1
```

The selected device is no longer visible.

Recommended behavior:

```text
if selectedDevice.z !== selectedFloor:
    selectedDeviceId = null
```

This avoids keeping a hidden device selected.

If the selected device belongs to the new floor, retain the selection.

---

# 22. Optional automatic floor navigation from device selection

If the application design supports it, clicking a device from the global device list could automatically switch to that device's floor.

For example:

```text
Click Device X
      │
      ▼
device.z = 2
      │
      ▼
selectedFloor = 2
      │
      ▼
Floor 2 scene loads
      │
      ▼
Device X highlighted
      │
      ▼
Only Device X label visible
```

This would make the device list and spatial view feel like one integrated system.

If the device list is intentionally scoped to the current floor, then keep the simpler behavior of only selecting devices already visible on the active floor.

Choose the behavior that matches the existing application architecture.

---

# 23. Camera behavior

Each floor should have a sensible initial camera framing.

When switching floors:

```text
Floor 1 → camera framing for Floor 1
Floor 2 → camera framing for Floor 2
Floor 0 → camera framing for Floor 0
```

Do not carry an extreme zoom/pan state from one floor to another if it causes the new floor to appear off-screen.

Prefer a reusable:

```text
fitSceneToViewport()
```

or equivalent helper.

The user should immediately see the selected floor after switching.

---

# 24. Keep the Three.js experience consistent

All three scenes should share:

* camera behavior;
* zoom;
* pan/orbit behavior;
* rendering quality;
* background;
* device marker style;
* label style;
* selection behavior;
* interaction conventions.

Only the physical floor geometry should differ.

This makes the system feel like **one visualization**, not three unrelated pages.

---

# 25. Remove the old Digital Twin navigation

Search the current application for the previous Digital Twin / building-level visualization entry point.

The new spatial visualization should replace that workflow.

Do not leave the user with:

```text
Digital Twin
     ↓
3D building
     ↓
choose floor
```

Instead:

```text
Spatial Visualization
     ↓
[ Floor 0 ] [ Floor 1 ] [ Floor 2 ]
     ↓
Three.js floor scene
```

The floor selector belongs to the application UI, not inside the scene.

---

# 26. API/data compatibility

Before changing backend structures, inspect how the existing system currently returns:

* `x`;
* `y`;
* `z`;
* device identity;
* positioning confidence;
* timestamps.

Do not create duplicate location systems.

If the current API already returns the required coordinates, adapt the frontend.

If the backend currently interprets `z` as something else, refactor it carefully so that:

```text
z = floor identifier
```

is consistent everywhere.

---

# 27. Database/reference-client handling

Floor 1 reference clients should retain their fixed coordinates.

Conceptually:

```text
reference_client
    ├── client_id
    ├── floor = 1
    ├── x
    └── y
```

Do not create reference clients for Floor 2 or Floor 0.

The system should be able to distinguish:

```text
Reference client
```

from:

```text
Discovered device
```

even though both can appear visually as markers.

---

# 28. Empty and unknown states

Each floor must gracefully support:

### No devices

```text
Floor 2

No devices detected
```

### Devices but no position

```text
3 devices detected
1 positioned
2 position unavailable
```

### No reference clients

For Floor 2/0, do not display an error merely because there are no PC reference clients.

That is expected by design.

---

# 29. Performance and Three.js cleanup

Because the scene changes dynamically, pay special attention to cleanup.

When changing floors:

1. Remove floor-specific meshes.
2. Remove device markers.
3. Remove labels.
4. Remove event listeners associated with disposed objects.
5. Dispose geometries.
6. Dispose materials.
7. Dispose textures where applicable.
8. Keep the shared renderer/canvas when possible.
9. Reuse the Three.js rendering infrastructure rather than recreating it unnecessarily.

Avoid creating a new WebGL renderer every time the user changes floors.

Prefer:

```text
One renderer
One visualization lifecycle
Multiple floor scenes
```

rather than:

```text
new renderer → Floor 1
new renderer → Floor 2
new renderer → Floor 0
```

---

# 30. Recommended final component architecture

Target something conceptually like:

```text
SpatialPage
│
├── FloorSelector
│
├── SpatialLayout
│   │
│   ├── DeviceList
│   │
│   └── SpatialCanvas
│        │
│        └── ThreeSpatialRenderer
│             │
│             ├── Floor0Scene
│             ├── Floor1Scene
│             └── Floor2Scene
│
└── Shared Spatial State
      ├── selectedFloor
      └── selectedDeviceId
```

Data flow:

```text
Backend
   │
   ▼
Devices
(x, y, z)
   │
   ▼
Spatial State
   │
   ├───────────────┐
   ▼               ▼
Floor filtering   Device list
   │
   ▼
Three.js scene
   │
   ▼
Device markers
   │
   ▼
Selected device
   │
   ▼
Focused label
```

---

# 31. Implementation sequence

Implement in this order.

## Phase 1 — Audit existing Floor 1

1. Locate the current Floor 1 Three.js implementation.
2. Identify its scene lifecycle.
3. Identify device marker rendering.
4. Identify label rendering.
5. Identify camera setup.
6. Identify coordinate conversion.
7. Identify device selection.
8. Identify how `z` is currently used.

Do not modify anything until these dependencies are understood.

---

## Phase 2 — Extract shared Three.js infrastructure

9. Separate generic Three.js functionality from Floor 1-specific geometry.
10. Create a reusable spatial renderer.
11. Keep one renderer/canvas.
12. Keep shared camera/control logic.
13. Keep shared device marker logic.
14. Keep shared label logic.

---

## Phase 3 — Introduce floor state

15. Add `selectedFloor`.
16. Default it to `1`.
17. Create centralized floor configuration.
18. Ensure `z` is treated as the floor identifier.
19. Filter devices according to `selectedFloor`.

---

## Phase 4 — Convert Floor 1 into a floor scene

20. Move the existing Floor 1 geometry into `Floor1Scene`.
21. Preserve its current appearance.
22. Preserve the PC/reference-client positions.
23. Preserve the 4–5 meter spatial gap.
24. Verify all devices still render correctly.

---

## Phase 5 — Build Floor 2

25. Create `Floor2Scene`.
26. Reuse the Floor 1 coordinate orientation.
27. Add Formation Room 1.
28. Add Formation Room 2.
29. Place them in the same relative positions as Floor 1.
30. Do not add PCs.
31. Do not add fake reference clients.
32. Test devices where `z = 2`.

---

## Phase 6 — Build Floor 0

33. Create `Floor0Scene`.
34. Use the same coordinate orientation.
35. Add no formation rooms.
36. Add no PCs.
37. Add no fake reference clients.
38. Test devices where `z = 0`.

---

## Phase 7 — Add external floor selector

39. Add Floor 0 / Floor 1 / Floor 2 controls outside the canvas.
40. Make Floor 1 the initial selection.
41. Change `selectedFloor` when clicked.
42. Load the corresponding scene.
43. Filter devices by `z`.
44. Fit the camera to the new scene.

---

## Phase 8 — Device focus behavior

45. Create shared `selectedDeviceId`.
46. Connect the device list to it.
47. Keep all device markers visible.
48. Hide all non-selected labels.
49. Keep selected label visible.
50. Highlight selected marker.
51. Clear selection when switching to another floor where the device does not exist.

---

## Phase 9 — Remove old Digital Twin workflow

52. Remove the old floor-navigation behavior from the Digital Twin.
53. Remove unnecessary dependencies between spatial visualization and the old 3D building model.
54. Ensure the new Three.js floor scenes are the only active spatial visualization.
55. Keep old code only if it is needed elsewhere.

---

## Phase 10 — Test the complete workflow

Test:

```text
Floor 1
   ↓
Floor 2
   ↓
Floor 0
   ↓
Floor 1
```

Verify the scene changes correctly each time.

Then test:

```text
Device A: z = 1
Device B: z = 2
Device C: z = 0
```

Verify:

```text
Floor 1 → only A
Floor 2 → only B
Floor 0 → only C
```

Then test device selection:

```text
Click Device A
      ↓
A marker highlighted
A label visible
Other labels hidden
Other markers remain visible
```

Finally test:

```text
Select Device A
      ↓
Switch to Floor 2
      ↓
Selection cleared
```

---

# 32. Final target behavior

The final user experience should be:

```text
                    SPATIAL VIEW

          [ Floor 0 ] [ Floor 1 ] [ Floor 2 ]
                            │
                            ▼
                 ┌─────────────────────┐
                 │                     │
                 │    Three.js         │
                 │    2D Floor Scene   │
                 │                     │
                 │   ●       ●         │
                 │                     │
                 │          ◉ Device A │
                 │                     │
                 └─────────────────────┘
                            ▲
                            │
                      Device List
```

Floor switching changes the **scene**, not the coordinate semantics.

The coordinate semantics remain:

```text
X/Y → location inside the floor
Z   → floor identifier
```

The three floors therefore become:

```text
                Building
                   │
        ┌──────────┼──────────┐
        │          │          │
      Floor 2    Floor 1    Floor 0
        │          │          │
       2D         2D         2D
      scene      scene      scene
        │          │          │
      X/Y        X/Y        X/Y
        │          │          │
    devices     devices     devices
                   │
             reference PCs
```

The final system should feel like **one unified Three.js spatial interface with three selectable floor scenes**, rather than the old 3D building Digital Twin.

Most importantly, **do not rewrite the working Floor 1 implementation unnecessarily**. Treat it as the reference scene, extract its reusable rendering infrastructure, and build Floor 2 and Floor 0 on top of that architecture.
