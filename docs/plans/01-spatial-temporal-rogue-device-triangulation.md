# Spatial-Temporal Rogue Device Triangulation — Implementation Plan

## 1. Purpose

Transform passive network discovery from a system that answers **"What device appeared?"** into a system that can answer:

- What device is it?
- Is it known or rogue?
- Where is it probably located?
- When did it appear?
- Which observations support that conclusion?
- How confident is the location?

The feature correlates passive DHCP/ARP discovery with the platform's existing physical map of rooms, zones, and seats. The research proposes using RSSI, switch-port proximity through LLDP/CDP, and managed agents acting as sensors to estimate a device's physical position.

This feature is the foundation for the later 3D/AR visualization.

---

## 2. Implementation Order

This feature should be implemented first.

### Dependency chain

```text
Physical location model
        ↓
Sensor registration
        ↓
Passive network observations
        ↓
Device identity correlation
        ↓
Spatial inference
        ↓
Temporal tracking
        ↓
Rogue-device confidence
        ↓
API + dashboard
```

Do not begin triangulation until the platform can reliably represent locations.

---

## 3. Scope

### In scope

- Rooms, zones, seats, and coordinates
- Network observation ingestion
- Device identity correlation
- Sensor registration
- RSSI observations where available
- LLDP/CDP observations where available
- Temporal observation history
- Probable location calculation
- Confidence scoring
- Rogue-device detection
- Location history
- REST APIs
- Dashboard visualization
- Audit trail

### Initially out of scope

- Camera-based localization
- GPS
- Automatic physical intervention
- Autonomous blocking
- AI/LLM-based localization
- AR visualization

Those can consume this feature later.

---

## 4. Core Data Model

Introduce a spatial layer without destroying the existing device model.

### Location

```text
Location
- id
- name
- type: building | floor | room | zone | seat
- parent_id
- x
- y
- z
- metadata
```

A hierarchy should allow:

```text
Building
 └── Floor
      └── Room
           └── Zone
                └── Seat
```

### Sensor

```text
Sensor
- id
- device_id
- type: endpoint | access_point | switch | collector
- location_id
- x
- y
- z
- capabilities
- last_seen
- status
```

### Device observation

```text
DeviceObservation
- id
- device_id
- mac_address
- ip_address
- sensor_id
- observation_type
- timestamp
- rssi
- switch_port
- raw_data
```

### Device location estimate

```text
DeviceLocationEstimate
- id
- device_id
- location_id
- x
- y
- z
- confidence
- method
- calculated_at
```

### Location history

```text
DeviceLocationEvent
- id
- device_id
- previous_location_id
- new_location_id
- confidence
- timestamp
- reason
```

---

## 5. Identity Correlation

The same physical device can appear through multiple observations.

Create a correlation pipeline:

```text
MAC
 ↓
Known asset lookup
 ↓
DHCP identity
 ↓
IP correlation
 ↓
Vendor / hostname
 ↓
Existing client registration
 ↓
Spatial observations
```

The MAC address remains the primary network identity where appropriate.

Do not assume that an IP address represents a permanent device identity.

---

## 6. Sensor Architecture

Sensors should be first-class objects.

A sensor can be:

- an installed client
- a Wi-Fi observation point
- a switch
- a network collector
- another infrastructure device capable of providing proximity information

Each observation should identify its source.

Example:

```json
{
  "device": "AA:BB:CC:DD:EE:FF",
  "sensor": "room-2-agent-04",
  "rssi": -48,
  "timestamp": "2026-08-26T10:00:00Z"
}
```

---

## 7. Location Estimation

Implement localization progressively.

### Phase 1 — deterministic proximity

If a device is directly associated with a known switch port:

```text
device → switch → port → room
```

Use that as a high-confidence location.

### Phase 2 — nearest sensor

For sensors with coordinates:

```text
nearest sensor → probable zone
```

### Phase 3 — RSSI weighted estimation

Convert RSSI observations into relative proximity.

Do not initially claim centimeter-level accuracy.

Use:

```text
weight = f(RSSI)
estimated_position =
    Σ(sensor_position × weight) / Σ(weight)
```

The implementation should expose the uncertainty rather than hiding it.

### Phase 4 — multi-observation smoothing

Use observations across a time window to avoid jumping between seats because of one noisy measurement.

Example:

```text
Window: 30–60 seconds

Observation 1 → Seat 4
Observation 2 → Seat 4
Observation 3 → Seat 5
Observation 4 → Seat 4

Result → Seat 4
Confidence → high
```

---

## 8. Temporal Intelligence

Location must be time-aware.

Store:

```text
first_seen
last_seen
location_at_time
movement_events
observation_count
```

This allows queries such as:

- Where did this device first appear?
- Where is it now?
- Did it move?
- When did it move?
- Which devices appeared in this room during the last hour?

A device moving through the building should generate a location event rather than overwrite its history.

---

## 9. Rogue Device Detection

A device becomes suspicious when identity and expected context disagree.

Example:

```text
New MAC
+
Not registered
+
Appears inside restricted room
+
Persists for 3 minutes
=
High-risk rogue candidate
```

Create a scoring model.

Example:

```text
rogue_score =
    unknown_identity_score
  + restricted_zone_score
  + persistence_score
  + unusual_movement_score
  + network_behavior_score
```

Keep the scoring explainable.

The UI should be able to say:

> Rogue candidate: 87%
>
> Reasons:
> - Unknown MAC
> - First seen in restricted zone
> - Persisted for 8 minutes
> - Communicating with 4 internal devices

---

## 10. API Design

Suggested endpoints:

```text
GET    /api/locations
GET    /api/locations/{id}
POST   /api/locations

GET    /api/sensors
POST   /api/sensors
PATCH  /api/sensors/{id}

GET    /api/devices/{id}/location
GET    /api/devices/{id}/location-history

GET    /api/rogue-devices
GET    /api/rogue-devices/{id}

GET    /api/spatial/events
```

For live updates, use the platform's existing real-time mechanism if available.

---

## 11. Dashboard

Add a spatial security view.

Each device should expose:

- current location
- confidence
- first seen
- last seen
- movement history
- sensor evidence
- rogue score

Example:

```text
UNKNOWN DEVICE

MAC: AA:BB:CC:DD:EE:FF
IP: 192.168.1.42

Probable location:
Floor 2 → Training Room 1 → Zone B → Seat 4

Confidence: 91%

Evidence:
✓ Sensor A
✓ Sensor B
✓ DHCP observation
✓ Switch proximity

First seen: 10:04
Last seen: 10:17
```

---

## 12. Implementation Phases

### Phase 1 — Spatial database

- [ ] Create Location model
- [ ] Create hierarchical locations
- [ ] Add coordinates
- [ ] Add location APIs
- [ ] Import existing physical map
- [ ] Validate coordinates

### Phase 2 — Sensor model

- [ ] Create Sensor model
- [ ] Associate sensors with locations
- [ ] Add capabilities
- [ ] Add health status
- [ ] Register existing clients as sensors where appropriate

### Phase 3 — Observation pipeline

- [ ] Normalize DHCP observations
- [ ] Normalize ARP observations
- [ ] Store observation timestamps
- [ ] Associate observations with sensors
- [ ] Preserve raw evidence

### Phase 4 — Spatial inference

- [ ] Implement switch-port localization
- [ ] Implement nearest-sensor localization
- [ ] Implement RSSI weighting
- [ ] Implement multi-sensor estimation
- [ ] Add confidence calculation

### Phase 5 — Temporal engine

- [ ] Store location history
- [ ] Detect movement
- [ ] Smooth noisy observations
- [ ] Create location events

### Phase 6 — Rogue detection

- [ ] Identify unknown devices
- [ ] Calculate rogue score
- [ ] Detect restricted-zone presence
- [ ] Correlate persistence and movement
- [ ] Generate alerts

### Phase 7 — UI

- [ ] Spatial device list
- [ ] Location details
- [ ] Rogue-device panel
- [ ] Movement timeline
- [ ] Confidence/evidence display

---

## 13. Testing

### Unit tests

- RSSI weighting
- coordinate calculation
- confidence calculation
- movement detection
- rogue scoring
- observation correlation

### Integration tests

```text
DHCP event
 → device correlation
 → location estimation
 → database
 → API
 → dashboard
```

### Simulation tests

Generate synthetic sensors and devices.

Example:

```text
Sensor A = (0,0)
Sensor B = (10,0)
Sensor C = (5,10)

Device observations:
A = -42
B = -60
C = -55
```

Verify that the estimated position moves toward Sensor A.

---

## 14. Security Requirements

- Authenticate observation sources.
- Validate MAC/IP data.
- Prevent arbitrary clients from submitting fake location evidence.
- Log changes to spatial configuration.
- Treat sensor compromise as a security event.
- Never allow location confidence to be interpreted as absolute physical certainty.
- Preserve evidence used to produce an alert.

---

## 15. Definition of Done

The feature is complete when:

- The platform knows the physical hierarchy automatically.
- Sensors have physical positions.
- Passive observations are associated with sensors.
- Unknown devices receive probable locations.
- Location confidence is calculated.
- Device movement is recorded.
- Rogue devices can be identified with explainable evidence.
- APIs expose current and historical location.
- The UI displays location and confidence.
- Automated tests cover the inference pipeline.

---

## 16. Foundation for Next Feature

The most important output is not the rogue alert.

It is the normalized spatial dataset:

```text
Device
 ├── identity
 ├── network state
 ├── physical coordinates
 ├── location hierarchy
 ├── confidence
 ├── sensors
 └── temporal history
```

The 3D/AR system should consume this dataset rather than create a second spatial model.
