# Phase 0 — Kismet deployment and implementation baseline

> **Superseded:** This record belongs to the abandoned client/sensor query design. Use `phase-0-server-architecture.md` and `phase-1.md` through `phase-10.md` for the active server-side Kismet sensor plan.

**Status:** SUPERSEDED — client/sensor prerequisite no longer applies.

**Started:** 2026-09-06

## Objective

Verify the Option A prerequisite before changing the client/server TCP implementation: a supported Kismet sensor must be installed, running, capturing real traffic, persisting historical observations, and have a documented ownership/data-access boundary.

## Documentation reviewed

All design records in `option-a-client-server` were reviewed, including the prerequisite gate, client/server integration, protocol, storage, API/UI, error-handling, testing, implementation order, checklist, and file-change matrix.

## Evidence collected

### Existing pilot evidence

`docs/integrating-kismet-and-backup/KISMET_SENSOR_PILOT.md` records a successful standalone Linux pilot. It demonstrates that a dedicated Linux sensor model is feasible, but it does not prove deployment for the managed client fleet or define the client/sensor data-access boundary.

### Available development environment

- The workspace is running on Windows.
- `kismet` and `kismet_server` are not executable from the current environment.
- No running `kismet`, `kismet_server`, or `kismet_cap_linux_wifi` process was found.
- No `.kismet` capture database exists in this repository.

### Repository baseline

- `client/app/kismet_listener.py` polls the newest `.kismet` SQLite database below a presumed local directory. It does not install, launch, supervise, or health-check Kismet.
- `client/app/client.py` creates and starts `KismetListener`, but has no `GET_KISMET_OBSERVATIONS` command handler.
- `server/server_components/kismet_service.py` still looks for server-visible Kismet databases, including fixed server and repository paths. This is incompatible with Option A's remote-sensor ownership model.
- `server/server_components/server_lib.py` already provides the required framed TCP transport, sole post-registration reader, per-client response queues, send locks, timeouts, and disconnect sentinel. Its current response matcher uses the command name only, so the Option A request-ID correlation rule is not yet implemented.
- Existing Kismet tests are synthetic SQLite tests. They are useful for later unit coverage but do not satisfy the operational Kismet gate.

## Gate assessment

| Required condition | Result | Evidence / gap |
| --- | --- | --- |
| Supported Kismet installation and recorded version | Blocked | No local executable; no target sensor evidence for this implementation run. |
| Documented startup mechanism and stable process | Blocked | No running process or service evidence. |
| Compatible capture source and permissions | Blocked | No target capture adapter/interface or permission evidence. |
| Controlled real capture with required fields | Blocked | Pilot exists, but target deployment has not been verified. |
| Verified persistence path/schema/rotation/retention | Blocked | Pilot `.kismet` assumptions cannot be applied to an unverified target environment. |
| Query component access to the real source | Blocked | Linux sensor versus Windows client placement/boundary remains undecided. |
| Kismet API role documented | Blocked | Health/live/history API decision has not been made for the target deployment. |
| Device-to-capture-owner mapping | Blocked | No authoritative mapping from investigated device to connected sensor/client is defined. |

## Decision

Do **not** modify TCP, client dispatch, query behavior, server routing, API handling, UI code, or SQL during this phase. The Option A design explicitly prohibits beginning that work before the prerequisite gate passes.

The recommended next deployment model remains the documented Model B: an independently managed Linux Kismet sensor, with an explicitly defined query component and secure access to the sensor's historical source. Implementing Model A (the Windows-oriented client starts Kismet) requires a separate feasibility decision and is not authorized by the current design.

## Next phase entry criteria

Create `phase-1.md` only after the following target-deployment evidence is available:

1. Target sensor OS, Kismet/capture version, installation source, configuration path, process owner, and startup mechanism.
2. Capture adapter/interface, monitor-mode capability, permissions, and controlled-capture results.
3. Actual persistence/API contract: source location, schema, rotation, retention, and safe concurrent-read behavior.
4. Explicit Linux-sensor versus Windows-client ownership, query-component location, secure source-access path, and device-to-sensor/client mapping.
5. A decision on whether the Kismet API serves health, live data, history, both, or neither.

## Scope control

No application source files were changed in Phase 0. Existing untracked workspace items were not modified.
