````md
# Endpoint Management Architecture — Action Framework + Physical Location + Center Visualization

## Overall Objective

Implement the next architectural layer of the endpoint management platform in four major phases:

1. Build a **unified Action Framework** shared by the server and Windows client.
2. Extend the **Client schema/data model** with physical location information.
3. Update the **first-registration flow** so an administrator assigns a physical location to a newly registered client.
4. Build the **center visualization UI** using the physical layout and client assignments.

The implementation should preserve all existing functionality and progressively migrate existing remote actions into the new framework.

---

# Phase 0 — Inspect Existing Architecture

Before making changes, inspect the complete existing implementation.

## Server

Identify:

- Client model/schema.
- Client registration endpoints.
- Authentication/authorization.
- Existing command/action endpoints.
- Existing command queue mechanism.
- Existing server-to-client communication.
- Existing process-control commands.
- Screenshot command.
- Shutdown/restart commands if already implemented.
- Network isolation commands.
- Existing alert/event system.
- Existing frontend client-management screens.
- Existing database migration system.

## Client

Identify:

- Client entry point.
- Server communication module.
- Command polling/receiving mechanism.
- Existing remote command handlers.
- Process management.
- Screenshot implementation.
- Shutdown/restart implementation.
- Isolation implementation.
- Client configuration.
- Local persistence.
- Logging.

Do not rewrite working functionality before understanding how it currently works.

The goal is to create a common architecture around existing functionality, not to duplicate it.

---

# Phase 1 — Build the Action Framework

## Objective

Create one unified action system that supports both:

```text
Single target
````

and:

```text
Bulk targets
```

The framework must exist on both the **server** and the **client**.

Do not implement every action separately anymore.

The architecture should become:

```text
                    Server
                      |
                Action Framework
                      |
          +-----------+-----------+
          |                       |
     Single Target           Bulk Target
          |                       |
          +-----------+-----------+
                      |
                 Command/Action
                      |
                      v
              Windows Client
                      |
                Action Handler
                      |
          +-----------+-----------+
          |           |           |
      Shutdown    Screenshot   Restart
      Process     Diagnostics   ...
```

---

# Phase 1.1 — Define Action Types

Create a centralized action type definition.

Examples:

```text
SHUTDOWN
RESTART
SCREENSHOT
KILL_PROCESS
START_PROCESS
ISOLATE_DEVICE
COLLECT_DIAGNOSTICS
REFRESH_HEALTH
```

Keep this extensible.

Do not scatter action strings throughout the codebase.

Use a single enum/constants definition on the server and an equivalent validated representation on the client.

---

# Phase 1.2 — Define Action States

Create standardized action states.

Recommended:

```text
PENDING
DISPATCHED
ACKNOWLEDGED
RUNNING
SUCCESS
PARTIAL_SUCCESS
FAILED
EXPIRED
CANCELLED
```

Single-target actions normally end in:

```text
SUCCESS
FAILED
```

Bulk actions can become:

```text
PARTIAL_SUCCESS
```

when some clients succeed and others fail.

---

# Phase 1.3 — Server Action Model

Create a persistent `Action` model/table.

Suggested fields:

```text
id
action_id
action_type
requested_by
created_at
started_at
completed_at
expires_at
status
parameters
result
error
```

Also store the target information.

Do not store a bulk action only as one target ID.

Use a relationship such as:

```text
Action
   |
   +-- ActionTarget
         |
         +-- client A
         +-- client B
         +-- client C
```

---

# Phase 1.4 — ActionTarget Model

Create an `ActionTarget` model/table.

Suggested fields:

```text
id
action_id
client_id
status
sent_at
acknowledged_at
started_at
completed_at
result
error
```

This allows the server to represent:

```text
Bulk Shutdown

PC-A → SUCCESS
PC-B → SUCCESS
PC-C → FAILED
PC-D → OFFLINE
```

while the parent action becomes:

```text
PARTIAL_SUCCESS
```

---

# Phase 1.5 — Action Parameters

Actions should support structured parameters.

For example:

```json
{
  "action_type": "SHUTDOWN",
  "parameters": {
    "delay_seconds": 10,
    "reason": "Administrative maintenance"
  }
}
```

Screenshot:

```json
{
  "action_type": "SCREENSHOT",
  "parameters": {
    "format": "png"
  }
}
```

Kill process:

```json
{
  "action_type": "KILL_PROCESS",
  "parameters": {
    "process_name": "discord.exe"
  }
}
```

Do not hardcode action-specific parameters into the generic Action model.

Use a flexible validated `parameters` object.

---

# Phase 1.6 — Action API

Implement a unified server API.

Possible structure:

```text
POST   /api/actions/
GET    /api/actions/
GET    /api/actions/{id}/
POST   /api/actions/{id}/cancel/
GET    /api/actions/{id}/targets/
```

The API should support:

### Single target

```json
{
  "action_type": "RESTART",
  "targets": ["client-a"]
}
```

### Multiple targets

```json
{
  "action_type": "RESTART",
  "targets": [
    "client-a",
    "client-b",
    "client-c"
  ]
}
```

Do not create separate server APIs for every action such as:

```text
/shutdown-client
/restart-client
/screenshot-client
```

unless an existing endpoint must be preserved temporarily for backwards compatibility.

The Action Framework should become the standard mechanism.

---

# Phase 1.7 — Action Authorization

Before creating an action:

```text
authenticated user?
        ↓
authorized for requested action?
        ↓
authorized for targeted clients?
        ↓
create action
```

Examples:

* Read-only user → cannot shutdown.
* Operator → may restart/screenshot.
* Administrator → may perform privileged actions.

Reuse the existing authorization system.

---

# Phase 1.8 — Client Action Framework

Create a corresponding client-side framework.

Conceptually:

```text
Client
 |
 +-- ActionManager
       |
       +-- ShutdownHandler
       +-- RestartHandler
       +-- ScreenshotHandler
       +-- KillProcessHandler
       +-- StartProcessHandler
       +-- IsolationHandler
       +-- DiagnosticsHandler
       +-- HealthRefreshHandler
```

The client must not contain one large `if/elif` block handling every command.

Instead:

```python
handlers = {
    "SHUTDOWN": ShutdownHandler(),
    "RESTART": RestartHandler(),
    "SCREENSHOT": ScreenshotHandler(),
    ...
}
```

The `ActionManager`:

1. validates the action;
2. checks expiration;
3. prevents duplicate execution;
4. selects the handler;
5. executes the action;
6. returns a standardized result.

---

# Phase 1.9 — Standard Client Action Result

Every action handler must return the same type of result.

Example:

```json
{
  "action_id": "...",
  "status": "SUCCESS",
  "started_at": "...",
  "completed_at": "...",
  "result": {
    "message": "Shutdown command issued successfully"
  },
  "error": null
}
```

Failure:

```json
{
  "action_id": "...",
  "status": "FAILED",
  "result": null,
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "..."
  }
}
```

This makes server processing consistent.

---

# Phase 1.10 — Action Idempotency

Every action must have a unique `action_id`.

If the same command is delivered twice:

```text
action_id = ABC123
```

the client must not execute it twice.

Expected behavior:

```text
First delivery:
execute

Second delivery:
return previous result
```

This is especially important for:

* shutdown;
* restart;
* isolation;
* screenshot;
* process operations.

---

# Phase 1.11 — Migrate Existing Actions

Once the framework is working, migrate existing functionality.

Priority:

```text
1. Screenshot
2. Shutdown
3. Restart
4. Kill Process
5. Start Process
6. Isolation
7. Collect Diagnostics
8. Refresh Health
```

Do not delete old endpoints until the new framework has been tested.

If backwards compatibility is required, temporarily make old endpoints internally create framework Actions.

---

# Phase 1.12 — Bulk Action Execution

For:

```text
POST /api/actions/
```

with multiple targets:

```text
targets = [A, B, C, D]
```

the server should:

1. Create one parent `Action`.
2. Create one `ActionTarget` per client.
3. Dispatch independently.
4. Track each result.
5. Aggregate the final result.

Example:

```text
Parent Action:
BULK_RESTART
Status:
PARTIAL_SUCCESS

Targets:
A → SUCCESS
B → SUCCESS
C → FAILED
D → OFFLINE
```

---

# Phase 1.13 — Action UI Preparation

Do not build the full UI yet.

First make sure the frontend can consume:

```text
Action
ActionTarget
status
result
error
```

Later, the same system will support actions filtered by physical location.

---

# Phase 2 — Extend Client Physical Location

After the Action Framework is stable, add the physical location model.

The center should be represented hierarchically.

Do not store only:

```text
floor
aisle
row
spot
```

as independent fields directly on the Client.

Model the physical structure.

---

# Phase 2.1 — Physical Structure

Conceptually:

```text
Center
│
├── Floor 0
│
├── Floor 1
│   ├── Formation Room 1
│   ├── Formation Room 2
│   ├── Aisle 1
│   │   ├── Table 1
│   │   └── Table 2
│   │
│   └── Aisle 2
│       ├── Table 1
│       └── Table 2
│
└── Floor 2
    ├── Formation Room 1
    ├── Formation Room 2
    ├── Aisle 1
    │   ├── Table 1
    │   └── Table 2
    │
    └── Aisle 2
        ├── Table 1
        └── Table 2
```

The exact structure should reflect the actual center.

---

# Phase 2.2 — Location Model

Create a `Location` entity.

Suggested fields:

```text
id
floor
zone_type
zone_name
aisle
table
row
position
label
```

Example:

```json
{
  "floor": 1,
  "zone_type": "training",
  "aisle": 1,
  "table": 2,
  "row": 1,
  "position": 3,
  "label": "F1-A1-T2-R1-P3"
}
```

For conference rooms:

```json
{
  "floor": 1,
  "zone_type": "conference_room",
  "zone_name": "Formation Room 1",
  "label": "F1-RM1"
}
```

---

# Phase 2.3 — Client Location Relationship

Add:

```text
Client
   |
   +-- location_id
```

The client has exactly one current physical location.

Keep the location separate from the Client core identity.

---

# Phase 2.4 — Location History

Create a `ClientLocationHistory` model.

Fields:

```text
id
client_id
location_id
assigned_at
unassigned_at
assigned_by
```

When a client moves:

```text
old location history → closed
new location → assigned
```

Do not erase the old location.

This can later be used to identify physical moves.

---

# Phase 2.5 — API

Add APIs for:

```text
GET    /api/locations/
GET    /api/locations/{id}/
GET    /api/locations/{id}/clients/
PATCH  /api/clients/{id}/location/
GET    /api/clients/{id}/location-history/
```

The location assignment should be restricted to authorized administrators.

---

# Phase 3 — Update First Registration Flow

Now integrate the location assignment into the existing first-registration flow.

The intended flow:

```text
New Client
    |
    v
Client registration
    |
    v
Server creates/registers client
    |
    v
Client appears as:
"Location not assigned"
    |
    v
Administrator assigns physical location
    |
    v
Location saved
    |
    v
Client becomes fully registered
```

---

# Phase 3.1 — Do Not Guess the Location

The client should not try to determine its physical location automatically.

For the first version:

```text
Administrator chooses:
Floor
Aisle
Table
Row
Position
```

This becomes the authoritative physical location.

---

# Phase 3.2 — Registration UI

After a new client registers, show a location assignment screen.

Example:

```text
New Client

Hostname:
DESKTOP-ABC123

MAC:
AA:BB:CC:DD:EE:FF

Location:

Floor
[ 1 ]

Zone
[ Training ]

Aisle
[ 2 ]

Table
[ 1 ]

Row
[ 2 ]

Position
[ 4 ]

[ Assign Location ]
```

The available choices should depend on the selected structure.

---

# Phase 3.3 — Prevent Duplicate Physical Positions

Unless your center intentionally allows multiple PCs at one position, enforce uniqueness.

For example:

```text
F1 / A1 / T1 / R1 / P1
```

cannot simultaneously belong to:

```text
Client A
Client B
```

The server must validate this.

Return a clear error:

```text
"This physical position is already assigned to DESKTOP-ABC."
```

---

# Phase 3.4 — Send Location Back to Client

After assignment:

```text
Server
   |
   | location configuration
   v
Client
```

The client should receive:

```json
{
  "location": {
    "floor": 1,
    "aisle": 2,
    "table": 1,
    "row": 2,
    "position": 4,
    "label": "F1-A2-T1-R2-P4"
  }
}
```

The client may include this information in telemetry/health reports.

The server remains the source of truth.

---

# Phase 4 — Center Visualization

Only after the physical-location model and registration flow work should the visualization be implemented.

The visualization should represent the real structure of the center.

---

# Phase 4.1 — Floor Selector

Provide:

```text
[ Floor 1 ] [ Floor 2 ]
```

Floor 0 can be displayed but should show no PCs.

---

# Phase 4.2 — Floor Layout

For Floor 1:

```text
┌──────────────────┐
│ Formation Room 1 │
└──────────────────┘

┌──────────────────┐
│ Formation Room 2 │
└──────────────────┘

        AISLE 1
┌──────────────────────────────┐
│ TABLE 1                      │
│ R1  PC1 PC2 PC3 PC4          │
│ R2  PC1 PC2 PC3 PC4          │
│                              │
│ TABLE 2                      │
│ R1  PC1 PC2 PC3 PC4          │
│ R2  PC1 PC2 PC3 PC4          │
└──────────────────────────────┘

        AISLE 2
┌──────────────────────────────┐
│ TABLE 1                      │
│ R1  PC1 PC2 PC3 PC4          │
│ R2  PC1 PC2 PC3 PC4          │
│                              │
│ TABLE 2                      │
│ R1  PC1 PC2 PC3 PC4          │
│ R2  PC1 PC2 PC3 PC4          │
└──────────────────────────────┘
```

Use the actual geometry and proportions of the center as closely as practical.

---

# Phase 4.3 — Client State Visualization

Each PC position should show a client status.

Suggested states:

```text
GREEN   Healthy
YELLOW  Warning
RED     Critical
BLUE    Isolated
GRAY    Offline
WHITE   Empty
```

Do not hard-code raw colors deep inside components.

Use a centralized status → visual mapping.

---

# Phase 4.4 — Client Details

Clicking a PC should open a detail panel.

Show:

```text
Hostname
IP
MAC
OS
Vendor
Model

Location
Floor
Aisle
Table
Row
Position

Health
CPU
RAM
Disk
Network
Uptime

Security
Risk
Forbidden process alerts
Isolation state

Last Seen
Last Heartbeat
```

Actions should come from the new Action Framework:

```text
Screenshot
Restart
Shutdown
Collect Diagnostics
Refresh Health
Isolate
```

Do not create separate UI logic for each remote command.

---

# Phase 4.5 — Physical Neighbors

Once a client is selected:

```text
Client:
F1/A1/T2/R1/P3
```

calculate physical neighbors from the location hierarchy.

Possible neighbors:

```text
same row:
P2
P4

other row:
R2/P3

neighboring table:
T1/R1/P3
```

The exact neighbor definition should be centralized so the frontend does not independently guess it.

Prefer having the server provide:

```json
{
  "neighbors": [
    {
      "client_id": "...",
      "relationship": "same_row",
      "distance": 1
    }
  ]
}
```

---

# Phase 4.6 — Location Filtering

The visualization should eventually allow:

```text
Floor
Aisle
Table
Status
Health
Risk
OS
Device Type
```

Examples:

```text
Show all critical PCs on Floor 1.
Show all PCs in Aisle 2.
Show offline devices.
Show isolated devices.
```

This will later integrate naturally with the Bulk Action framework.

---

# Phase 4.7 — Bulk Actions From Visualization

After location visualization works:

```text
Select:
Floor 1 / Aisle 2

        ↓

24 clients

        ↓

Action:
[ Restart ]
[ Screenshot ]
[ Collect Diagnostics ]
[ Shutdown ]
```

The frontend should create one bulk `Action` with multiple targets.

The visualization should not execute commands itself.

---

# Phase 5 — Integration and Testing

After implementing all four phases, test the complete system.

---

## Action Framework Tests

### Single target

```text
Shutdown PC-A
→ one Action
→ one ActionTarget
→ success
```

### Bulk target

```text
Shutdown PC-A, PC-B, PC-C
→ one Action
→ three ActionTargets
```

### Partial failure

```text
A → success
B → failed
C → offline

Parent → PARTIAL_SUCCESS
```

### Duplicate command

Same `action_id` delivered twice:

```text
→ execute once
→ return previous result
```

---

## Location Tests

Test:

* Create location.
* Assign location.
* Change location.
* Prevent duplicate position.
* Retrieve current location.
* Retrieve location history.
* Send location to client.
* Client reports location in telemetry.

---

## Registration Tests

Test:

```text
New client
    ↓
Register
    ↓
No location
    ↓
Admin assigns
    ↓
Location saved
    ↓
Client receives location
```

Also test:

```text
New client attempts invalid location
→ server rejects
```

and:

```text
Location already occupied
→ server rejects
```

---

## Visualization Tests

Verify:

* Floor selector.
* Correct center structure.
* Correct PC placement.
* Empty positions.
* Health colors.
* Offline devices.
* Critical devices.
* Isolated devices.
* Client detail panel.
* Physical neighbors.
* Location filtering.
* Actions from selected clients.

---

# Final Architecture

The final system should look like:

```text
                         CENTRAL SERVER
                               |
          +--------------------+--------------------+
          |                                         |
    Action Framework                           Location
          |                                         |
    +-----+------+                            +-----+------+
    |            |                            |            |
Single       Bulk Targets                 Structure    Assignment
    |            |                            |            |
    +-----+------+                            +-----+------+
          |                                         |
          v                                         v
     Client Agent                              Client Model
          |                                         |
          +----------------+------------------------+
                           |
                           v
                  Center Visualization
                           |
              +------------+------------+
              |            |            |
           Health       Security      Actions
              |            |            |
             CPU        Alerts       Restart
             RAM        Risk         Shutdown
            Disk        Process      Screenshot
           Network      Isolation    Diagnostics
```

---

# Recommended Implementation Order

Do not implement all features simultaneously.

## Milestone 1 — Action Framework

* [ ] Inspect existing commands.
* [ ] Create server Action model.
* [ ] Create ActionTarget model.
* [ ] Add action types.
* [ ] Add action states.
* [ ] Add action API.
* [ ] Add authorization.
* [ ] Create client ActionManager.
* [ ] Create client action handlers.
* [ ] Standardize action results.
* [ ] Add idempotency.
* [ ] Migrate existing actions.
* [ ] Implement single-target actions.
* [ ] Implement bulk-target actions.
* [ ] Test thoroughly.

## Milestone 2 — Client Location

* [ ] Create Location model.
* [ ] Create physical hierarchy.
* [ ] Create Client → Location relationship.
* [ ] Create location history.
* [ ] Add location APIs.
* [ ] Add validation.
* [ ] Prevent duplicate occupied positions.

## Milestone 3 — First Registration

* [ ] Update registration response/data.
* [ ] Show newly registered client as location-unassigned.
* [ ] Add administrator location assignment flow.
* [ ] Validate location availability.
* [ ] Save location.
* [ ] Send assigned location to client.
* [ ] Store location locally.
* [ ] Include location in client telemetry.

## Milestone 4 — Visualization

* [ ] Build floor selector.
* [ ] Build Floor 1 layout.
* [ ] Build Floor 2 layout.
* [ ] Represent conference rooms.
* [ ] Represent aisles.
* [ ] Represent tables.
* [ ] Represent rows.
* [ ] Represent PC positions.
* [ ] Show client state.
* [ ] Show empty positions.
* [ ] Add device details.
* [ ] Add physical neighbors.
* [ ] Add filters.
* [ ] Connect actions to Action Framework.
* [ ] Test full visualization.

## Future Milestone

Only after the visualization is stable:

```text
Location
   ↓
Physical neighbors
   ↓
Location-aware alerts
   ↓
Location-based bulk actions
   ↓
ARP/BSSID-based unknown-device location estimation
   ↓
Physical incident visualization
```

# Important Architectural Principles

1. **The Action Framework is the only standard mechanism for remote actions.**

2. **Single-target and bulk-target actions share the same Action model.**

3. **The server is the source of truth for client physical location.**

4. **Physical structure is hierarchical; do not reduce it to four unrelated integers.**

5. **Client location assignment is administrator-controlled in the first version.**

6. **The frontend visualization consumes server location data; it should not independently calculate the physical layout.**

7. **Physical neighbors are derived centrally from the physical hierarchy.**

8. **Bulk actions use the Action Framework and never contain custom per-feature bulk logic.**

9. **Existing functionality must be migrated incrementally rather than rewritten unnecessarily.**

10. **Every milestone must remain independently testable before proceeding to the next one.**

```
```
