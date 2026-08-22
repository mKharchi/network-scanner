# API Implementation Plan --- Network Monitoring Console

## 1. Objective

Implement the backend API required by the existing desktop Graphical
Interface (GUI).

The GUI has already been implemented in `server/gui` and currently
contains:

-   Dashboard
-   Clients
-   Client Details
-   Latest Network Scan
-   Scan History
-   Network Device Details
-   DHCP Activity
-   Alerts
-   Activity Logs
-   Settings & Policies

The frontend already has a typed API client (`client.ts`) and data-layer
hooks.

The goal is to connect that GUI to the real server functionality through
a clean, versioned API.

------------------------------------------------------------------------

# 2. Critical Rules

## Rule 1 --- Inspect Before Changing

Before implementing anything:

-   Inspect the complete server architecture.
-   Inspect the existing database/models.
-   Inspect the socket protocol.
-   Inspect the existing client registration flow.
-   Inspect network-neighbour collection.
-   Inspect DHCP collection/listening.
-   Inspect alerts.
-   Inspect activity logs.
-   Inspect existing configuration/settings.
-   Inspect the entire GUI API client and its types.

Do not assume the architecture.

Do not create duplicate functionality that already exists.

## Rule 2 --- The Existing GUI Is the API Consumer

The existing GUI is already implemented.

Treat its API client and data contracts as the starting point for the
API contract.

Inspect:

``` text
server/gui
```

and locate `client.ts` and all related API types/hooks.

For every API call determine:

-   HTTP method
-   URL
-   path parameters
-   query parameters
-   request body
-   expected response
-   error behavior
-   pagination/filtering requirements

Do not redesign the GUI simply because an endpoint is inconvenient to
implement.

If a frontend contract is demonstrably wrong, document the issue before
changing it.

## Rule 3 --- Do Not Replace the Existing Socket Architecture

The project already uses sockets for communication between:

``` text
Client Agent
      ↕
   Server
```

The REST API is primarily for:

``` text
Desktop GUI
      ↕
   Server
```

Do not replace the existing client/server socket communication with REST
unless explicitly required.

Expected architecture:

``` text
                    ┌─────────────────┐
                    │   Desktop GUI   │
                    └────────┬────────┘
                             │ HTTP API
                             ▼
                    ┌─────────────────┐
                    │     Server      │
                    │                 │
                    │ REST API        │
                    │ Client Manager  │
                    │ DHCP Listener   │
                    │ Network Scanner │
                    │ Alert Engine    │
                    └────────┬────────┘
                             │
                 ┌───────────┴───────────┐
                 ▼                       ▼
          ┌─────────────┐         ┌─────────────┐
          │ Client Agent│         │  Database   │
          └─────────────┘         └─────────────┘
```

------------------------------------------------------------------------

# Phase 1 --- Backend Architecture Audit

## Step 1. Inspect the repository

Before writing code, inspect:

-   server entry point
-   server package/module structure
-   configuration
-   database configuration
-   database models
-   migrations
-   socket server
-   client registration
-   command handling
-   activity logs
-   alerts
-   network-neighbour collector
-   DHCP listener
-   background tasks
-   existing tests

Also inspect the complete GUI under:

``` text
server/gui
```

to understand exactly what the frontend expects.

## Step 2. Identify the existing persistence layer

Determine:

-   database engine
-   ORM, if any
-   existing models
-   existing repositories/services
-   migration system
-   transaction handling

Do not introduce another database unless the architecture explicitly
requires it.

The API should use the existing persistence layer.

## Step 3. Identify existing domain entities

Find whether the project already has equivalents for:

``` text
Client
Device
NetworkDevice
NetworkScan
NetworkDeviceObservation
DHCPActivity
Alert
ActivityLog
Setting
Policy
```

If an equivalent already exists, reuse it.

Do not create duplicate models such as `ApiClient` when `Client` already
represents the same entity.

------------------------------------------------------------------------

# Phase 2 --- Frontend API Contract Audit

## Step 4. Inspect `client.ts`

Create an internal mapping of every API call.

For each call document:

  GUI feature     Method   Endpoint                   Request   Response
  --------------- -------- -------------------------- --------- ----------------
  Dashboard       GET      actual frontend endpoint   none      dashboard data
  Clients         GET      actual frontend endpoint   filters   client list
  Client detail   GET      actual frontend endpoint   ID        client
  Latest scan     GET      actual frontend endpoint   none      scan
  Scan history    GET      actual frontend endpoint   filters   scans
  Device detail   GET      actual frontend endpoint   ID        device
  DHCP            GET      actual frontend endpoint   filters   DHCP events
  Alerts          GET      actual frontend endpoint   filters   alerts
  Activity logs   GET      actual frontend endpoint   filters   logs
  Settings        GET      actual frontend endpoint   none      settings
  Policies        GET      actual frontend endpoint   none      policies

The exact endpoints must be extracted from the code rather than assumed
from this example.

## Step 5. Produce an API contract document

Create:

``` text
server/docs/API_CONTRACT.md
```

Document:

-   endpoint
-   method
-   authentication
-   request
-   response
-   status codes
-   filtering
-   sorting
-   pagination
-   errors

This document becomes the reference for backend/frontend integration.

------------------------------------------------------------------------

# Phase 3 --- Define the API Structure

## Step 6. Use API versioning

Prefer:

``` text
/api/v1/
```

All GUI endpoints should live under this prefix unless the existing
architecture already has an equivalent versioning convention.

Potential resources include:

``` text
/api/v1/dashboard
/api/v1/clients
/api/v1/network/devices
/api/v1/network/scans
/api/v1/dhcp/activity
/api/v1/alerts
/api/v1/activity-logs
/api/v1/settings
/api/v1/policies
```

Do not create multiple competing API prefixes.

------------------------------------------------------------------------

# Phase 4 --- Implement Read APIs First

The first objective is to make the existing GUI display real server
data.

Do not start with mutations.

Recommended order:

1.  Dashboard
2.  Clients
3.  Network devices
4.  Network scans
5.  DHCP activity
6.  Alerts
7.  Activity logs
8.  Settings
9.  Policies

------------------------------------------------------------------------

# Phase 5 --- Dashboard API

Implement the endpoint expected by the existing dashboard.

Expose only information the GUI actually needs.

Potential information includes:

``` text
total clients
online clients
offline clients
managed devices
unmanaged devices
latest scan
latest scan time
recent alerts
```

Do not duplicate expensive queries unnecessarily.

If aggregation is required, use efficient database queries rather than
loading all records into application memory.

------------------------------------------------------------------------

# Phase 6 --- Client APIs

Implement the endpoints required by:

``` text
Clients.tsx
ClientDetail.tsx
```

Support only the capabilities the GUI actually requests:

-   client list
-   online/offline filtering
-   search
-   sorting if required
-   client detail
-   connection history
-   activity-log references

Reuse the existing client identity and registration model.

Do not create another client identity system.

------------------------------------------------------------------------

# Phase 7 --- Network Device APIs

The network-monitoring system discovers unmanaged devices through
client-side neighbour collection.

The data flow is:

``` text
Client
   │
   │ ARP / neighbour table
   │
   ├── IP
   ├── MAC
   ├── vendor
   ├── hostname
   └── DHCP-derived information
        │
        ▼
     Server
        │
        ▼
 Network Device
        │
        ▼
 Observation History
```

Implement APIs for:

``` text
current network devices
device details
device observations
managed/unmanaged classification
```

## Device identity rule

Do not use IP address as the permanent identity.

Prefer MAC address because DHCP can change IP addresses.

Remember that modern devices can use MAC randomization.

Therefore MAC is the best available local identity, but not an absolute
physical-device identity.

------------------------------------------------------------------------

# Phase 8 --- Network Scan APIs

Implement the APIs required by:

``` text
LatestScan.tsx
ScanHistory.tsx
```

Support:

-   latest scan
-   scan history
-   scan details
-   scan status
-   devices discovered during a scan
-   managed/unmanaged filtering

If the server already stores scan information, expose it rather than
implementing a second scanner.

------------------------------------------------------------------------

# Phase 9 --- DHCP Activity API

The project now has passive DHCP collection from clients.

The API should expose the collected DHCP activity.

Potential fields include:

``` text
timestamp
reporter client
MAC
requested IP
hostname
DHCP message type
vendor class
client identifier
```

The exact response must match the frontend's existing contract.

Do not expose raw packet data unless the GUI actually needs it.

------------------------------------------------------------------------

# Phase 10 --- Alerts API

Reuse the existing alert system.

Do not create a second alert model or alert engine.

Expose the capabilities required by the GUI, such as:

``` text
list alerts
filter by severity
filter by status
filter by type
view alert details
```

Existing alert types may include:

``` text
UNMANAGED_DEVICE_DETECTED
UNMANAGED_DEVICE_OUTSIDE_HOURS
```

along with existing process/activity alerts.

------------------------------------------------------------------------

# Phase 11 --- Activity Logs API

The existing client activity logs are separate from network-presence
monitoring.

Keep the distinction:

``` text
Activity Logs
"What did this managed computer do?"

Network Monitoring
"Which computers were present on the network?"
```

Do not merge these concepts.

The GUI currently displays activity records and JSON event streams.

Expose the existing log references/data according to the frontend
contract.

If logs are currently stored as files and the server keeps references to
those files, preserve that design.

Do not introduce a large database log table solely for the GUI.

------------------------------------------------------------------------

# Phase 12 --- Settings & Policies API

Implement APIs required by the existing Settings page.

At minimum inspect and expose:

``` text
working-hours configuration
forbidden-process policies
```

Use the project's existing configuration/persistence mechanism.

Do not hard-code settings in the API.

------------------------------------------------------------------------

# Phase 13 --- Mutation APIs

Once all read APIs work, implement mutations required by the GUI.

Examples:

``` text
POST /network/scans
PUT/PATCH /settings
PUT/PATCH /policies
```

Only implement mutations that the existing GUI actually requires.

------------------------------------------------------------------------

# Phase 14 --- Manual Network Scan

If the GUI has a "scan now" action, expose a controlled endpoint.

Example:

``` http
POST /api/v1/network/scans
```

The server should invoke the existing scanner.

Do not accept arbitrary shell commands.

Never create an API such as:

``` json
{
    "command": "nmap ..."
}
```

The API must expose predefined server operations.

------------------------------------------------------------------------

# Phase 15 --- Authentication & Authorization

Inspect the existing authentication system before implementing API
security.

Determine:

-   who can access the GUI
-   whether the GUI runs locally
-   whether authentication already exists
-   whether API tokens/session authentication exist

Apply the project's existing security model.

At minimum, protect administrative operations such as:

``` text
start scan
change settings
change policies
```

Do not introduce a second authentication system without a strong reason.

------------------------------------------------------------------------

# Phase 16 --- Serialization / DTO Layer

Do not expose raw ORM/database objects directly.

Use explicit response schemas/DTOs/serializers appropriate to the
project's architecture.

Example:

``` json
{
    "id": 42,
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "ip_address": "172.16.0.102",
    "hostname": "DESKTOP-DJP05CM",
    "vendor": "Microsoft",
    "os": "Windows",
    "managed": false,
    "first_seen": "2026-08-15T08:00:00+01:00",
    "last_seen": "2026-08-15T10:10:00+01:00",
    "currently_online": true
}
```

Use the exact field names expected by the frontend contract.

Do not expose internal database implementation details.

------------------------------------------------------------------------

# Phase 17 --- Filtering, Sorting & Pagination

Inspect what the GUI actually requests.

Only implement features that are needed.

Potential filters include:

``` text
online
offline
managed
unmanaged
severity
status
date range
search
reporter
```

If datasets can become large, use server-side pagination.

Do not load thousands of records into the GUI unnecessarily.

------------------------------------------------------------------------

# Phase 18 --- Error Contract

Create a consistent API error format.

Example:

``` json
{
    "error": {
        "code": "NETWORK_SCAN_FAILED",
        "message": "The network scan could not be completed."
    }
}
```

Use appropriate HTTP status codes:

``` text
400 Bad Request
401 Unauthorized
403 Forbidden
404 Not Found
409 Conflict
422 Unprocessable Entity
500 Internal Server Error
503 Service Unavailable
```

Do not expose stack traces to the GUI.

Log detailed technical errors on the server instead.

------------------------------------------------------------------------

# Phase 19 --- API Documentation

If the backend already has OpenAPI/Swagger support, extend it.

Otherwise, use the project's existing documentation mechanism.

Document:

-   available endpoints
-   request formats
-   response formats
-   authentication
-   error responses

Keep documentation synchronized with implementation.

------------------------------------------------------------------------

# Phase 20 --- Testing Strategy

Implement tests alongside each endpoint.

## Dashboard

-   [ ] returns 200
-   [ ] correct counts
-   [ ] handles empty database

## Clients

-   [ ] list clients
-   [ ] filtering
-   [ ] searching
-   [ ] client detail
-   [ ] unknown client returns 404

## Network devices

-   [ ] list devices
-   [ ] managed filtering
-   [ ] unmanaged filtering
-   [ ] device detail
-   [ ] observation history

## Scans

-   [ ] latest scan
-   [ ] scan history
-   [ ] scan detail
-   [ ] empty scan history
-   [ ] failed scan

## DHCP

-   [ ] list activity
-   [ ] filtering
-   [ ] empty result

## Alerts

-   [ ] list alerts
-   [ ] severity filtering
-   [ ] status filtering
-   [ ] alert detail

## Activity logs

-   [ ] list records
-   [ ] date filtering
-   [ ] log references
-   [ ] empty result

## Settings

-   [ ] retrieve settings
-   [ ] update settings
-   [ ] validation

## Security

-   [ ] unauthorized access rejected
-   [ ] authorized access succeeds
-   [ ] unauthorized mutation rejected

------------------------------------------------------------------------

# Phase 21 --- Frontend Integration Test

After implementing the APIs, run the GUI against the real server.

Do not use mocked API responses for final integration.

Verify each page.

### Dashboard

``` text
GUI → API → Database → GUI
```

### Clients

``` text
GUI → /clients → real clients
```

### Network Scan

``` text
Client agents
      ↓
Server
      ↓
Database
      ↓
GUI
```

### DHCP

``` text
Client DHCP listener
      ↓
Server
      ↓
Database
      ↓
GUI
```

### Alerts

``` text
Detection
   ↓
Alert engine
   ↓
Database
   ↓
GUI
```

------------------------------------------------------------------------

# Phase 22 --- API Performance

After functionality works, inspect performance.

Look for:

-   N+1 queries
-   repeated database queries
-   unnecessary records
-   expensive dashboard aggregation
-   unbounded activity-log queries
-   unbounded DHCP history
-   large scan responses

Add appropriate indexes based on actual query patterns.

Likely candidates include:

``` text
MAC address
IP address
timestamp
first_seen
last_seen
managed status
alert severity
alert status
scan ID
device ID
```

Do not add indexes blindly.

------------------------------------------------------------------------

# Phase 23 --- API/GUI Data Contract Verification

Before considering the API complete, verify every frontend API call.

Create a checklist from `client.ts`.

For every API function:

``` text
[ ] endpoint exists
[ ] method matches
[ ] request matches
[ ] response matches
[ ] null values handled
[ ] error response handled
[ ] authentication works
```

There should be no frontend endpoint pointing to a nonexistent backend
route.

------------------------------------------------------------------------

# Phase 24 --- Expected Architecture

The final architecture should look approximately like:

``` text
                         ┌───────────────────────┐
                         │     Desktop GUI       │
                         │                       │
                         │ Dashboard             │
                         │ Clients               │
                         │ Network Devices       │
                         │ Scans                 │
                         │ DHCP                  │
                         │ Alerts                │
                         │ Activity Logs         │
                         │ Settings              │
                         └───────────┬───────────┘
                                     │
                                  REST API
                                /api/v1/*
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │        Server         │
                         │                       │
                         │ API / Controllers     │
                         │ Services              │
                         │ Domain Logic          │
                         │ Client Manager        │
                         │ Network Monitoring    │
                         │ Alert Engine          │
                         └───────┬───────┬───────┘
                                 │       │
                         Socket  │       │ Database
                                 │       │
                                 ▼       ▼
                         ┌──────────┐  ┌──────────┐
                         │ Clients  │  │ Database │
                         │ Agents   │  │          │
                         └──────────┘  └──────────┘
```

------------------------------------------------------------------------

# Phase 25 --- Implementation Order

The IDE AI must implement the project incrementally.

## Milestone 1 --- Audit

-   [ ] Inspect backend
-   [ ] Inspect database
-   [ ] Inspect existing services
-   [ ] Inspect socket protocol
-   [ ] Inspect GUI API client
-   [ ] Extract API requirements
-   [ ] Identify reusable existing functionality
-   [ ] Identify missing backend functionality

**Do not modify implementation code yet except documentation if
necessary.**

------------------------------------------------------------------------

## Milestone 2 --- Contract

-   [ ] Produce `API_CONTRACT.md`
-   [ ] Map every frontend API call
-   [ ] Define request/response schemas
-   [ ] Define status/error behavior
-   [ ] Resolve contract inconsistencies

**Stop and review before implementing the endpoints.**

------------------------------------------------------------------------

## Milestone 3 --- Read APIs

Implement:

-   [ ] Dashboard
-   [ ] Clients
-   [ ] Client details
-   [ ] Network devices
-   [ ] Device details
-   [ ] Latest scan
-   [ ] Scan history
-   [ ] DHCP activity
-   [ ] Alerts
-   [ ] Activity logs
-   [ ] Settings
-   [ ] Policies

------------------------------------------------------------------------

## Milestone 4 --- Mutations

Implement only required GUI actions:

-   [ ] Start network scan
-   [ ] Update settings
-   [ ] Update policies
-   [ ] Other required actions

------------------------------------------------------------------------

## Milestone 5 --- Security

-   [ ] Authentication
-   [ ] Authorization
-   [ ] Protected mutations
-   [ ] Input validation
-   [ ] Safe errors

------------------------------------------------------------------------

## Milestone 6 --- Testing

-   [ ] Unit tests
-   [ ] API integration tests
-   [ ] Authentication tests
-   [ ] Error tests
-   [ ] Empty-state tests
-   [ ] Real database tests

------------------------------------------------------------------------

## Milestone 7 --- GUI Integration

-   [ ] Run backend
-   [ ] Run GUI
-   [ ] Connect GUI to real API
-   [ ] Test every page
-   [ ] Test filters
-   [ ] Test detail views
-   [ ] Test scan action
-   [ ] Test settings
-   [ ] Fix contract mismatches

------------------------------------------------------------------------

## Milestone 8 --- Hardening

-   [ ] Performance review
-   [ ] Database indexes
-   [ ] Pagination
-   [ ] Logging
-   [ ] Error handling
-   [ ] API documentation
-   [ ] Remove temporary mocks
-   [ ] Remove debug output
-   [ ] Run complete test suite
-   [ ] Run frontend build

------------------------------------------------------------------------

# 26. Important Implementation Philosophy

The goal is **not** to build a generic REST API.

The goal is:

> Build the smallest clean API required to expose the server's existing
> network-monitoring functionality to the desktop GUI.

Prefer:

``` text
Existing functionality
        ↓
Existing domain logic
        ↓
API/service layer
        ↓
GUI
```

Avoid:

``` text
GUI requirement
      ↓
new duplicate backend logic
      ↓
duplicate database model
      ↓
duplicate service
```

Reuse wherever possible.

------------------------------------------------------------------------

# 27. Definition of Done

The API phase is complete when:

-   [ ] Every GUI API call has a real backend endpoint.
-   [ ] The endpoints use the existing server architecture.
-   [ ] No duplicate domain models were introduced unnecessarily.
-   [ ] Network devices discovered by clients are visible in the GUI.
-   [ ] DHCP activity is visible in the GUI.
-   [ ] Clients are visible in the GUI.
-   [ ] Scan history is visible.
-   [ ] Alerts are visible.
-   [ ] Activity logs are visible.
-   [ ] Settings and policies are functional.
-   [ ] Manual scanning works if required by the GUI.
-   [ ] Authentication/authorization is enforced.
-   [ ] API tests pass.
-   [ ] Frontend build passes.
-   [ ] GUI works against the real backend.
-   [ ] No production API depends on mock data.

------------------------------------------------------------------------

# 28. Final Instruction to the IDE AI

**Work incrementally.**

Do not implement the entire API in one pass.

Start with:

``` text
PHASE 1 — BACKEND AUDIT
```

Report:

1.  Existing backend architecture.
2.  Existing models.
3.  Existing network-monitoring functionality.
4.  Existing socket functionality.
5.  Existing alert functionality.
6.  Existing logging functionality.
7.  Existing DHCP functionality.
8.  Existing API functionality, if any.
9.  Every API endpoint currently expected by the GUI.
10. Which endpoints already exist.
11. Which endpoints are missing.
12. Which existing backend components can be reused.
13. Any architectural conflicts or ambiguities.

Then create/update:

``` text
server/docs/API_CONTRACT.md
```

**Do not start implementing endpoints until the audit and contract
mapping are complete.**

After the audit, proceed milestone by milestone.

After each milestone:

1.  Run the relevant tests.
2.  Verify the implementation.
3.  Report what changed.
4.  Report what remains.
5.  Do not silently redesign unrelated parts of the project.

The existing desktop GUI should remain stable while the backend API is
implemented.
