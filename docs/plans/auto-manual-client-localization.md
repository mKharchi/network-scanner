Absolutely. Copy the following directly into `04-hybrid-client-location-assignment.md`:

````md
# Hybrid Client Location Assignment — Implementation Plan

## 1. Purpose

Introduce a hybrid client-location assignment workflow that combines:

- automatic client localization when the existing system can calculate a reliable location;
- manual assignment when automatic localization cannot determine a location;
- immediate visualization of assigned clients on the center layout;
- confirmed client locations as spatial reference points for future localization improvements.

The desired workflow is:

```text
Client registers/connects
        ↓
Automatic localization attempt
        ↓
 ┌───────────────┴───────────────┐
 │                               │
Success                         Failure
 │                               │
 ▼                               ▼
AUTO assignment              MANUAL queue
 │                               │
 └───────────────┬───────────────┘
                 ▼
       Confirmed client location
                 ↓
        Center layout updates
                 ↓
       Client becomes visible
       spatial reference point
````

---

## 2. Why This Feature Is Needed

The current localization mechanism appears to use the existing location system, while the relationship between the center layout's coordinate system and the server's interpretation of those coordinates still needs validation.

Instead of blocking the project until automatic localization is perfect, this feature allows both mechanisms to coexist.

The platform should be able to say:

> "I calculated this client's location."

or:

> "I could not calculate it, so an administrator needs to place the client manually."

This creates a practical calibration workflow.

---

## 3. Main Principle

Automatic localization and manual assignment should use the **same location model**.

Do not create separate location systems.

```text
                 Location Model
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
       Automatic resolver    Manual selector
             │                   │
             └─────────┬─────────┘
                       ▼
                Client Location
                       │
                       ▼
                 Center Layout
```

Both methods must eventually produce the same client → location relationship.

---

## 4. Assignment States

Every client should have an explicit location assignment state.

Recommended initial model:

```text
UNASSIGNED
AUTO
MANUAL
```

Optionally extend this with:

```text
PENDING
ASSIGNED
CONFIRMED
```

Recommended fields:

```text
assignment_method:
    AUTO
    MANUAL

assignment_status:
    PENDING
    ASSIGNED
    CONFIRMED
```

---

## 5. Client Location Model

Extend the existing client/location relationship rather than creating an unrelated system.

Suggested fields:

```text
ClientLocation
- id
- client_id
- location_id
- assignment_method
- assignment_status
- confidence
- assigned_at
- assigned_by
- last_calculated_at
- source
- metadata
```

Where:

```text
assignment_method:
    AUTO
    MANUAL
```

and:

```text
source:
    localization_engine
    administrator
```

For automatic assignments, preserve the evidence used to calculate the position.

For manual assignments, preserve the administrator and timestamp.

---

## 6. Automatic Localization Workflow

When a client connects:

```text
Client detected
      ↓
Identify client
      ↓
Find existing location assignment
      ↓
If none:
      ↓
Run localization
      ↓
Evaluate result
```

The resolver should return a structured result.

Example:

```json
{
    "success": true,
    "location_id": 42,
    "confidence": 0.91,
    "source": "automatic",
    "evidence": [
        "sensor_match",
        "network_observation"
    ]
}
```

If localization fails:

```json
{
    "success": false,
    "location_id": null,
    "confidence": 0,
    "source": "automatic",
    "reason": "insufficient_evidence"
}
```

---

## 7. Automatic Assignment Threshold

Do not automatically assign every calculated result.

Define a minimum confidence threshold.

Example:

```text
confidence >= 0.80
    → automatic assignment

confidence < 0.80
    → manual assignment
```

The exact threshold should be configurable.

For the first implementation, use a conservative threshold.

The important distinction is:

```text
calculated
```

versus:

```text
reliable enough to assign automatically
```

---

## 8. Manual Fallback

If automatic localization fails or confidence is below the threshold:

```text
Client
  ↓
UNASSIGNED
  ↓
Manual Assignment Queue
```

The administrator should see:

```text
Unassigned Clients

┌───────────────────────────────────────┐
│ PC-TRAINING-07                       │
│ MAC: XX:XX:XX:XX:XX:XX                │
│ Reason: insufficient localization     │
│                                       │
│ [Assign Location]                     │
└───────────────────────────────────────┘
```

---

## 9. Manual Assignment Interface

Clicking:

```text
[Assign Location]
```

opens the center layout.

The administrator should be able to:

1. select a floor;
2. select a room;
3. select a zone;
4. select a seat/location;
5. confirm the assignment.

The layout should show already assigned clients.

Example:

```text
FLOOR 2

┌─────────────────────────────────────────────┐
│                                             │
│              TRAINING ROOM 1               │
│                                             │
│   ● PC-01        ● PC-02        ○ Seat 3   │
│                                             │
│   ● PC-04        ○ Seat 5        ○ Seat 6   │
│                                             │
│              ○ = available                 │
│              ● = assigned                  │
└─────────────────────────────────────────────┘
```

---

## 10. Reference Client Visualization

Already assigned clients should be displayed prominently.

For example:

```text
PC-01 → Seat 1
PC-02 → Seat 2
PC-04 → Seat 4
```

When assigning another client, the administrator can visually understand the physical arrangement.

This is the main calibration benefit of the feature.

---

## 11. Automatic Assignment Visualization

Automatically localized clients should look different from manually assigned clients.

For example:

```text
AUTO
● PC-01

MANUAL
◆ PC-02
```

Do not rely only on color.

The UI should communicate:

```text
PC-01
AUTO
Confidence: 92%
```

versus:

```text
PC-02
MANUAL
Assigned by: Admin
```

---

## 12. Confirming an Automatic Assignment

Automatic assignments should initially be considered calculated rather than permanently trusted.

The administrator should have:

```text
PC-01

Automatically detected:
Training Room 1 → Seat 4

Confidence: 93%

[Confirm]
[Move]
```

If the administrator moves it:

```text
AUTO
  ↓
MANUAL
```

The manual assignment becomes authoritative.

---

## 13. Manual Assignment as a Spatial Reference

Once an administrator manually assigns a client:

```text
Client
  ↓
MANUAL location
  ↓
CONFIRMED physical reference
```

This information should be available to the localization system.

Example:

```text
PC-01
Location: Seat 4
Method: MANUAL
Confirmed: YES
```

This creates a known spatial reference for future calibration.

---

## 14. Important Distinction

Do not confuse:

```text
Client location
```

with:

```text
Localization sensor
```

A manually assigned client can become a useful spatial reference without necessarily having the hardware/network capability required to measure RSSI.

Keep these concepts separate:

```text
Location assignment
        ≠
Sensor capability
```

---

## 15. Recalculation

Add an explicit action:

```text
[Recalculate Location]
```

Example:

```text
PC-01

Current:
Room 1 / Seat 4

New calculation:
Room 1 / Seat 5

Confidence:
87%

[Accept]
[Keep Current]
```

Do not silently move confirmed manual locations.

A manually confirmed location should require explicit administrator action before replacement.

---

## 16. Location Priority

Define clear precedence rules.

Recommended:

```text
MANUAL + CONFIRMED
        ↓
highest priority

AUTO + CONFIRMED
        ↓
high priority

AUTO + ASSIGNED
        ↓
normal priority

UNASSIGNED
        ↓
no location
```

Automatic recalculation must not overwrite a manually confirmed location.

---

## 17. Backend Services

Separate responsibilities.

Suggested services:

```text
ClientLocationService
LocalizationService
LocationAssignmentService
LocationConfirmationService
```

### LocalizationService

Responsible for:

```text
calculate(client)
```

Returns:

```text
location
confidence
evidence
```

### LocationAssignmentService

Responsible for:

```text
assign_auto(client, result)
assign_manual(client, location, user)
```

### LocationConfirmationService

Responsible for:

```text
confirm(client_location)
move(client_location)
```

This keeps automatic localization independent from manual administration.

---

## 18. API Design

Suggested endpoints:

```text
GET  /api/clients/unassigned
GET  /api/clients/{id}/location

POST /api/clients/{id}/location/auto
POST /api/clients/{id}/location/manual

POST /api/clients/{id}/location/confirm
POST /api/clients/{id}/location/recalculate

GET  /api/locations/{id}/clients
GET  /api/locations/clients
```

The exact URL structure should follow the existing project's API conventions.

---

## 19. Automatic Assignment Response

Example:

```json
{
    "client_id": 12,
    "assignment": {
        "method": "auto",
        "status": "assigned"
    },
    "location": {
        "id": 42,
        "name": "Seat 4"
    },
    "confidence": 0.91,
    "evidence": [
        "sensor_match",
        "network_observation"
    ]
}
```

---

## 20. Manual Assignment Request

Example:

```json
{
    "location_id": 42
}
```

Response:

```json
{
    "client_id": 12,
    "assignment": {
        "method": "manual",
        "status": "assigned",
        "verified": true
    },
    "location": {
        "id": 42,
        "name": "Seat 4"
    }
}
```

The backend should record the authenticated administrator who performed the assignment.

---

## 21. Center Layout Integration

The center layout becomes the main visualization surface.

It should consume:

```text
Location
+
Assigned clients
+
Assignment metadata
```

Example:

```text
Location:
Training Room 1 / Seat 4

Client:
PC-TRAINING-04

Method:
AUTO

Confidence:
94%
```

This turns the layout into a live representation of the actual client deployment.

---

## 22. Client Movement

A client moving to another physical position should not automatically change its confirmed assignment unless the platform has enough evidence.

Example:

```text
PC-04
Current assignment:
Room 1 / Seat 4

New localization:
Room 1 / Seat 5

Confidence:
62%
```

Keep:

```text
Room 1 / Seat 4
```

until confidence is high enough or an administrator confirms the move.

This prevents visualization instability.

---

## 23. Real-Time Updates

When a client is assigned:

```text
Backend assignment
       ↓
event
       ↓
frontend
       ↓
center layout update
```

The administrator should not need to refresh the page.

If the project already uses WebSockets or another real-time mechanism, reuse it.

Possible event:

```json
{
    "type": "client.location.updated",
    "client_id": 12,
    "location_id": 42,
    "assignment_method": "manual"
}
```

---

## 24. Assignment Queue

Create a dedicated queue:

```text
Location Assignment

┌─────────────────────────────────────────────┐
│ Unassigned: 4                              │
├─────────────────────────────────────────────┤
│ PC-07     insufficient evidence     [Assign]│
│ PC-11     no location match         [Assign]│
│ PC-15     low confidence (42%)      [Assign]│
│ PC-18     localization unavailable  [Assign]│
└─────────────────────────────────────────────┘
```

---

## 25. Calibration Workflow

The intended operational workflow is:

### Step 1

Start the server.

### Step 2

Clients connect.

### Step 3

Server automatically localizes clients where possible.

### Step 4

Open the center layout.

### Step 5

Automatically localized clients appear.

### Step 6

Physically compare their positions with the center layout.

### Step 7

If an automatic location is correct:

```text
Confirm
```

### Step 8

If automatic localization is wrong:

```text
Move / manually assign
```

### Step 9

Assign remaining clients manually.

### Step 10

The center now provides a visual representation of the real client arrangement.

---

## 26. Calibration Dataset

Every confirmed assignment creates useful data.

Store:

```text
client
physical location
assignment method
confidence
timestamp
```

Over time:

```text
Client A → Room 1 / Seat 1
Client B → Room 1 / Seat 2
Client C → Room 1 / Seat 3
Client D → Room 2 / Seat 1
```

This becomes a verified spatial dataset.

It can later be used to evaluate and improve automatic localization.

---

## 27. Future Localization Improvement

Once enough clients are manually confirmed:

```text
Confirmed client locations
          ↓
Known spatial references
          ↓
Compare against localization observations
          ↓
Measure error
          ↓
Calibrate coordinate transformation
          ↓
Improve localization
```

Do not introduce machine learning yet.

First collect trustworthy calibration data.

---

## 28. Database Requirements

First inspect the existing models.

Do not create duplicate `Location`, `Client`, `Room`, or `Seat` models if they already exist.

Possible migration:

```text
client.location_id
client.location_assignment_method
client.location_confidence
client.location_verified
client.location_assigned_at
client.location_assigned_by
```

Alternatively, if location history is already important, use a dedicated:

```text
ClientLocationAssignment
```

model.

The final choice should follow the existing architecture.

---

## 29. Implementation Phases

### Phase 1 — Inspect Existing Localization

* [x] Identify current client-location relationship.
* [x] Identify automatic localization function.
* [x] Identify location model.
* [x] Identify center layout data.
* [x] Identify coordinate representation.
* [x] Identify current assignment API.
* [x] Identify current visualization component.

**Do not rewrite the existing localization system.**

### Phase 2 — Assignment Model

* [x] Add assignment method.
* [x] Add assignment status.
* [x] Add confidence.
* [x] Add verification state.
* [x] Add assignment timestamp.
* [x] Add assigning administrator.
* [x] Preserve localization evidence where available.

### Phase 3 — Automatic Assignment

* [x] Run localization when a client becomes eligible.
* [x] Apply confidence threshold.
* [x] Assign automatically when confidence is sufficient.
* [x] Send low-confidence clients to the manual queue.
* [x] Store the reason when automatic assignment fails.

### Phase 4 — Manual Assignment

* [x] Create unassigned-client queue.
* [x] Add Assign button.
* [x] Open center layout.
* [x] Select location.
* [x] Confirm assignment.
* [x] Record administrator and timestamp.

### Phase 5 — Center Visualization

* [x] Display assigned clients.
* [x] Display automatically assigned clients differently.
* [x] Display manually assigned clients.
* [x] Show client identity.
* [x] Show confidence.
* [x] Show assignment method.
* [x] Add client selection.
* [x] Add location inspection.

### Phase 6 — Confirmation

* [x] Allow automatic assignments to be confirmed.
* [x] Allow automatic assignments to be corrected.
* [x] Prevent automatic recalculation from silently overriding manual confirmation.
* [x] Record changes through the existing client-location history audit trail.

### Phase 7 — Real-Time Updates

* [x] Emit client-location update events.
* [x] Update center layout without refresh.
* [x] Update assignment queue.
* [x] Update client details.

### Phase 8 — Calibration

* [x] Select physically known clients through confirmed automatic assignments.
* [x] Compare automatic location with actual location.
* [x] Confirm correct results.
* [x] Manually correct incorrect results through the existing assignment flow.
* [x] Record coordinate errors.
* [x] Identify systematic transformation problems.

---

## 30. Testing

### Unit Tests

Test:

* confidence threshold;
* automatic assignment;
* manual assignment;
* confirmation;
* reassignment;
* assignment precedence;
* unauthorized assignment;
* recalculation behavior.

### Integration Test

Test:

```text
Client connects
      ↓
Localization runs
      ↓
Successful result
      ↓
AUTO assignment
      ↓
Center layout receives update
```

Then:

```text
Client connects
      ↓
Localization fails
      ↓
UNASSIGNED
      ↓
Manual assignment
      ↓
Center layout receives update
```

### Override Test

Verify:

```text
MANUAL assignment
      ↓
automatic recalculation
      ↓
manual location remains unchanged
```

This is essential.

---

## 31. Security

Only authorized administrators should be able to manually assign or move clients.

Every manual change should be auditable:

```text
Client:
PC-07

Old:
Unassigned

New:
Training Room 2 / Seat 4

Changed by:
Administrator

Timestamp:
...
```

Do not allow arbitrary clients to submit their own location.

The client may provide evidence for localization, but the server remains authoritative for assignment.

---

## 32. Definition of Done

The feature is complete when:

* A connecting client triggers automatic localization.
* A sufficiently confident result is automatically assigned.
* Failed/low-confidence localization creates an unassigned client.
* Administrators can manually assign that client from the center layout.
* Assigned clients are immediately visible on the layout.
* Automatic and manual assignments are distinguishable.
* Manual assignments are protected from silent automatic overwrites.
* Administrators can confirm or correct automatic assignments.
* Assignment history is auditable.
* Confirmed clients can be identified as spatial references.
* The system can be used to visually calibrate the center layout.

---

## 33. Final Architecture

```text
                     CLIENT
                        │
                        ▼
                 Client Detection
                        │
                        ▼
              Automatic Localization
                        │
             ┌──────────┴──────────┐
             │                     │
        Confidence OK         Confidence low
             │                     │
             ▼                     ▼
       AUTO ASSIGNED           UNASSIGNED
             │                     │
             │               Manual Assignment
             │                     │
             └──────────┬──────────┘
                        ▼
               CONFIRMED LOCATION
                        │
                        ▼
                CENTER LAYOUT
                        │
          ┌─────────────┴─────────────┐
          ▼                           ▼
    Client visualization        Spatial reference
                                      │
                                      ▼
                           Future localization
                              calibration
```

The key idea is that **automatic localization is no longer a single point of failure**. It becomes the first attempt, while manual placement guarantees that every client can eventually be represented correctly.

The result is a progressively calibrated spatial map of the real center.```
