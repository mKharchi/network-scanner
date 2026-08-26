# AR-Enhanced 3D Topology Visualization — Implementation Plan

## 1. Purpose

Transform the platform's network dashboard into a spatial digital twin where operators can understand the network through the physical environment.

The system should combine:

```text
Physical space
+
Network topology
+
Device state
+
Threat intelligence
+
Real-time telemetry
```

The research proposes a 3D digital twin that maps network assets to physical coordinates and allows operators to visualize traffic, threats, and device status in the physical environment.

This feature should be built after Spatial-Temporal Rogue Device Triangulation.

---

## 2. Dependency

```text
Spatial model
      ↓
Device coordinates
      ↓
Topology graph
      ↓
3D digital twin
      ↓
Real-time state
      ↓
Threat overlays
      ↓
AR mode
```

Do not begin with AR.

First build a reliable browser-based 3D digital twin. AR becomes an additional presentation mode.

---

## 3. Scope

### In scope

- 3D building/floor/room model
- Device positioning
- Network topology
- Device state
- Network links
- Threat overlays
- Traffic visualization
- Spatial search
- Time-based replay
- 3D dashboard
- AR-ready scene representation

### Initially out of scope

- Full indoor navigation
- Computer-vision-based object recognition
- Automatic physical control
- VR hardware
- Highly realistic architectural rendering

The goal is operational clarity, not architectural simulation.

---

## 4. Architecture

```text
                    Backend
                       │
          ┌────────────┼────────────┐
          │            │            │
       Devices      Locations    Events
          │            │            │
          └────────────┼────────────┘
                       │
                  Spatial API
                       │
                       ▼
              3D Scene Manager
                 │           │
                 ▼           ▼
            3D Browser      AR Layer
```

The 3D renderer should consume normalized JSON rather than directly querying database tables.

---

## 5. Spatial Scene Model

Represent the physical environment using a scene graph.

```text
Building
 └── Floor
      ├── Room
      │    ├── Zone
      │    │    ├── Seat
      │    │    └── Device
      │    └── Device
      └── Infrastructure
           ├── Switch
           ├── AP
           └── Sensor
```

Each object should have:

```text
id
type
position
rotation
scale
parent
metadata
```

---

## 6. Device Representation

Every network asset becomes a spatial object.

Example:

```json
{
  "id": "device-42",
  "type": "workstation",
  "position": {
    "x": 4.2,
    "y": 0.9,
    "z": 6.7
  },
  "status": "online",
  "risk": "high",
  "location_confidence": 0.91
}
```

Use simple visual representations initially.

For example:

```text
Workstation → cube
Server      → rack
Switch      → network node
AP          → wireless node
Unknown     → warning marker
```

Avoid spending development time on realistic models before the operational interactions work.

---

## 7. Network Topology

Separate physical topology from logical topology.

### Physical

```text
Device → Port → Switch → Rack
```

### Logical

```text
Device → IP → Service → Remote Device
```

The UI should allow switching between:

```text
Physical view
Logical view
Threat view
Traffic view
```

---

## 8. Topology Graph

Create graph edges such as:

```text
device → switch
switch → switch
device → device
device → gateway
```

Each edge can contain:

```text
source
target
type
status
traffic_rate
latency
risk
last_updated
```

The renderer should update only changed nodes/edges rather than rebuilding the entire scene.

---

## 9. Device State Visualization

Use state-driven visual behavior.

Possible states:

```text
ONLINE
OFFLINE
UNKNOWN
DEGRADED
SUSPICIOUS
ROGUE
ISOLATED
```

The visualization should make state obvious without depending exclusively on color.

Use:

- icon shape
- animation
- labels
- badges
- size
- pulse/ring effects

This improves accessibility and makes the visualization usable in screenshots and reports.

---

## 10. Threat Visualization

A threat should exist spatially.

Example:

```text
Rogue device
     ↓
Floor 2
     ↓
Training Room 1
     ↓
Seat 4
```

The 3D view can show:

```text
[ROGUE DEVICE]
      │
      ├── attempted connection → PC 12
      ├── attempted connection → PC 14
      └── DHCP activity
```

The operator should be able to select a threat and see the underlying evidence.

---

## 11. Traffic Visualization

Represent important flows as animated paths.

Example:

```text
PC A ───────────────→ Server
       suspicious
```

Do not render every packet.

Aggregate traffic into meaningful flows:

```text
source
destination
protocol
bytes
packets
rate
risk
time window
```

This prevents the scene from becoming unreadable.

---

## 12. Time Replay

Because the first feature stores temporal information, the 3D environment should support:

```text
Now
←──── timeline ────→
```

The operator could select:

```text
10:00
10:05
10:10
10:15
```

and see:

- devices appearing
- devices moving
- threats emerging
- topology changes
- isolation events

This is especially valuable for incident investigation.

---

## 13. API

Suggested endpoints:

```text
GET /api/spatial/scene
GET /api/spatial/topology
GET /api/spatial/devices
GET /api/spatial/events

GET /api/spatial/replay?from=...&to=...

GET /api/spatial/devices/{id}
GET /api/spatial/threats
```

A scene response should be optimized for rendering.

Example:

```json
{
  "version": 1,
  "timestamp": "...",
  "nodes": [],
  "edges": [],
  "events": []
}
```

---

## 14. Frontend Architecture

Separate the visualization from normal React UI.

Recommended structure:

```text
SpatialDashboard
 ├── Scene
 │    ├── Building
 │    ├── Rooms
 │    ├── Devices
 │    ├── Infrastructure
 │    └── NetworkLinks
 │
 ├── Controls
 │    ├── Floor selector
 │    ├── View selector
 │    ├── Time control
 │    └── Filters
 │
 └── Inspector
      ├── Device details
      ├── Network details
      ├── Threat evidence
      └── Location confidence
```

The 3D engine should not contain business logic.

---

## 15. AR Architecture

AR should consume exactly the same scene representation.

```text
                 Spatial Scene JSON
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
          3D Browser              AR
```

This prevents the project from developing two incompatible visualization systems.

The AR layer should eventually support:

- floor recognition
- spatial anchors
- device markers
- threat markers
- directional indicators
- topology paths
- device inspection

---

## 16. AR Safety and Accuracy

Physical coordinates are estimates.

Never present estimated coordinates as exact physical truth.

Display:

```text
Probable location
Confidence: 91%
```

rather than:

```text
Device physically confirmed at Seat 4
```

AR should preserve the uncertainty generated by the triangulation engine.

---

## 17. Implementation Phases

### Phase 1 — Scene API

- [ ] Create scene DTO
- [ ] Add nodes
- [ ] Add edges
- [ ] Add positions
- [ ] Add device metadata
- [ ] Add scene versioning

### Phase 2 — Browser 3D prototype

- [ ] Render floor
- [ ] Render rooms
- [ ] Render seats
- [ ] Render devices
- [ ] Add camera controls
- [ ] Add selection

### Phase 3 — Network topology

- [ ] Render physical links
- [ ] Render logical links
- [ ] Add topology filters
- [ ] Add infrastructure nodes
- [ ] Add flow aggregation

### Phase 4 — Security visualization

- [ ] Add threat markers
- [ ] Add rogue-device visualization
- [ ] Add evidence panel
- [ ] Add risk filters
- [ ] Add isolation state

### Phase 5 — Temporal replay

- [ ] Add timeline
- [ ] Load historical scenes
- [ ] Animate device movement
- [ ] Replay threat events
- [ ] Replay topology changes

### Phase 6 — AR prototype

- [ ] Define spatial anchors
- [ ] Reuse scene coordinates
- [ ] Render device markers
- [ ] Render threat markers
- [ ] Add object inspection
- [ ] Test alignment accuracy

---

## 18. Performance Requirements

A 3D visualization can become expensive quickly.

Use:

- instancing for repeated objects
- level-of-detail
- frustum culling
- event aggregation
- throttled telemetry updates
- incremental scene updates
- lazy loading by floor/room

Do not stream every raw telemetry event to the renderer.

---

## 19. Testing

### Scene tests

- Correct coordinates
- Correct parent-child relationships
- Correct topology edges
- Missing-device handling

### Interaction tests

- Select device
- Filter room
- Filter threat
- Change floor
- Replay time

### Performance tests

Test with progressively larger scenes:

```text
50 devices
100 devices
250 devices
500 devices
1000 devices
```

Measure:

- initial load
- frame rate
- memory
- update latency

### Spatial accuracy tests

Compare rendered device positions against known test positions.

---

## 20. Definition of Done

The feature is complete when:

- A physical floor can be rendered in 3D.
- Rooms and seats have spatial coordinates.
- Devices appear at their estimated locations.
- Network topology is visible.
- Threats are spatially represented.
- Device inspection exposes evidence.
- Historical events can be replayed.
- The scene updates without full reload.
- The architecture can feed an AR renderer.
- AR preserves location confidence.

---

## 21. Relationship to the Autonomous Agent

This visualization becomes the operator's window into autonomous behavior.

For example:

```text
ROGUE DEVICE DETECTED
        ↓
Location identified
        ↓
3D scene highlights device
        ↓
Edge agent evaluates threat
        ↓
Agent isolates device/process
        ↓
3D scene changes to ISOLATED
        ↓
Operator sees action + evidence
```

This creates a closed operational loop between physical context, detection, and response.
