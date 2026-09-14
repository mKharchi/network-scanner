# Spatial Localization and Digital Twin

## Model

The spatial subsystem maps clients and network devices to configured physical
locations. It supports manual assignment, automatic assignment proposals,
confirmation/history, reference sensors, floor geometry, physical neighbours,
and Three.js visualization.

## Server implementation

| Concern | Modules |
| --- | --- |
| Location hierarchy/layout | `center_layout.py`, `physical_layout.py`, `location_repository.py` |
| Manual/automatic assignment | `location_assignment.py`, `client_localization.py` |
| Calibration | `calibration.py` |
| Positioning/math | `spatial_engine.py`, `floor1_spatial.py` |
| Topology/neighbours | `physical_neighbors.py` |
| REST service | `api_service.py`, `api_server.py` |
| Persistence | `locations`, `client_location_history`, device estimate/event tables |

## Assignment lifecycle

1. A client may be assigned to a location manually or evaluated by the
   automatic assignment worker.
2. The server validates that an assignable location is not occupied by another
   active client.
3. Automatic proposals retain method/status metadata and require operator
   confirmation when policy requires it.
4. Assignment changes are written to history and emitted as events.

## Device localization

Reference clients/sensors provide known positions. Recent network observations
and RSSI/switch-port evidence are passed through the spatial engine. The result
contains coordinates, confidence, method, floor/elevation, and a location
match when one can be made. Stale or insufficient evidence must produce an
uncertain result rather than a fabricated precise location.

The floor scenes preserve the floor ID in `z` and apply configured geometry
and elevation gates. The current GUI includes floor selection, device markers,
reference sensors, topology edges, threat markers, replay/event views, and
location assignment controls.

## GUI implementation

`SpatialPage.tsx`, `DigitalTwin.tsx`, `Floor1Scene.tsx`,
`ThreeSpatialScene.tsx`, and the spatial utility/config files render the server
responses. The same API contracts also support the Locations and Client
Localization pages.

## Operational limitations

Spatial quality depends on calibration, correctly assigned reference clients,
fresh observations, and a stable physical layout. Changing floor geometry or
anchors requires a controlled calibration and verification cycle.

